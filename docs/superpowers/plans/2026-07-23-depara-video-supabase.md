# De→para de vídeos no Supabase — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development para executar task a task. Steps usam checkbox (`- [ ]`). Idioma pt-BR. Branch nova a partir da `main` atualizada: `git checkout main && git pull && git checkout -b feat/depara-video-supabase`.

**Goal:** Fazer a data real de gravação aparecer nas coletas do VPS/web — publicando o de→para do Metabase numa tabela Supabase e fazendo o `sync_supabase` casar as datas de lá.

**Architecture:** Tabela `depara_video` (Supabase) + publicador local `sync_depara_supabase.py` (lê o gz, upsert em lotes) + `montar_payload` monta o de→para a partir do Supabase (só os IDs do snapshot). O gz local e o painel/Visualizador local ficam intactos. O publicador é isolado para troca futura por API.

**Tech Stack:** Python 3.12 (requests, gzip, sqlite3), unittest; Postgres/PostgREST (Supabase).

## Global Constraints
- pt-BR em tudo (código, comentários, commits). Sem dependência nova.
- Formato do gz (`saida\metabase_depara.json.gz`): `{video_id: {data, status, titulo, raiz, path, dur, n}}` — chave = `video_id_antigo`. ~283.762 registros.
- `montar_payload` deve manter o **shape** que `painel.dados_avaliacao` espera do depara: `{video_id: {"data": ..., ...}}` (o código usa `((depara or {}).get(vid) or {}).get("data")`).
- Reusar `sync_supabase._config`/`_headers` (service_role; env vars ou `supabase.json`). Escrita no Supabase só via service_role; RLS leitura `authenticated`.
- `video_id_antigo` vive em `blocos.video_id_antigo` (TEXT; vazio `''` quando o vídeo não tem ID antigo — filtrar esses).
- Fallback: se a `depara_video` estiver vazia/inacessível, o de→para volta vazio (comportamento atual "sem data") — nunca derrubar o sync.
- Verificação Python: `py -m unittest discover -s tests` (hoje 94 verdes). Schema/publicação real são passos manuais do Clovis (Supabase vivo).
- Spec: `docs\superpowers\specs\2026-07-23-depara-video-supabase-design.md`.

---

### Task 1: Schema `depara_video` (`supabase/schema_depara.sql`)

**Files:**
- Create: `supabase/schema_depara.sql`

- [ ] **Step 1: Escrever o schema (idempotente, padrão do schema_coleta.sql)**

```sql
-- De→para de vídeos do Metabase (question 19885): data real de gravação por
-- video_id_antigo, para a web/VPS casarem sem o cache gz local.
-- Idempotente. Aplicar no SQL editor do Supabase (Dashboard → SQL) → Run.

create table if not exists depara_video (
  video_id      text primary key,   -- = video_id_antigo (chave do gz)
  data          text,               -- data/hora de gravação (ISO, como no gz)
  status        text,
  titulo        text,
  raiz          text,               -- professor
  path          text,               -- árvore antiga
  dur           text,               -- "HH:MM:SS"
  n             int,
  atualizado_em timestamptz not null default now()
);

alter table depara_video enable row level security;

-- leitura autenticada; escrita só service_role (sem policy de escrita)
drop policy if exists "leitura autenticada" on depara_video;
create policy "leitura autenticada" on depara_video
  for select to authenticated using (true);

grant select on depara_video to authenticated;
```

- [ ] **Step 2: Commit** (o schema é aplicado no Supabase pelo Clovis — Task 5)

```bash
git add supabase/schema_depara.sql
git commit -m "feat(supabase): tabela depara_video (de→para de vídeos)"
```

---

### Task 2: Publicador `sync_depara_supabase.py`

**Files:**
- Create: `sync_depara_supabase.py`
- Test: `tests/test_sync_depara.py`

**Interfaces:**
- Produces: `linhas_do_gz(depara: dict) -> list[dict]` (transforma `{video_id: {campos}}` em linhas `{video_id, data, status, titulo, raiz, path, dur, n}` para upsert); `em_lotes(seq, tamanho) -> iterator[list]`; `publicar(gz_path=None, url=None, key=None) -> int` (lê o gz, upsert em lotes, devolve total publicado).

- [ ] **Step 1: Escrever os testes que falham**

Criar `tests/test_sync_depara.py`:

```python
import unittest
import sync_depara_supabase as sd


class TestLinhasDoGz(unittest.TestCase):
    def test_transforma_registro_completo(self):
        gz = {"37025": {"data": "2019-02-11T21:49:49", "status": "Disponível",
                        "titulo": "T", "raiz": "R", "path": "P", "dur": "00:20:33", "n": 3}}
        linhas = sd.linhas_do_gz(gz)
        self.assertEqual(len(linhas), 1)
        r = linhas[0]
        self.assertEqual(r["video_id"], "37025")
        self.assertEqual(r["data"], "2019-02-11T21:49:49")
        self.assertEqual(r["dur"], "00:20:33")
        self.assertEqual(r["n"], 3)

    def test_campos_ausentes_viram_none(self):
        gz = {"1": {"data": "2020-01-01T00:00:00"}}  # só data
        r = sd.linhas_do_gz(gz)[0]
        self.assertEqual(r["video_id"], "1")
        self.assertIsNone(r["titulo"])
        self.assertIsNone(r["n"])

    def test_gz_vazio(self):
        self.assertEqual(sd.linhas_do_gz({}), [])


class TestEmLotes(unittest.TestCase):
    def test_divide_em_lotes(self):
        got = list(sd.em_lotes(list(range(23)), 10))
        self.assertEqual([len(x) for x in got], [10, 10, 3])

    def test_vazio(self):
        self.assertEqual(list(sd.em_lotes([], 10)), [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `py -m unittest tests.test_sync_depara -v`
Expected: FAIL (`No module named 'sync_depara_supabase'`).

- [ ] **Step 3: Implementar**

Criar `sync_depara_supabase.py`:

```python
# -*- coding: utf-8 -*-
"""
============================================================
 SYNC DEPARA SUPABASE — publica o de→para de vídeos (Metabase)
 na tabela depara_video do Supabase, para a web/VPS casarem a
 data real de gravação sem o cache gz local.
 Roda no LOCAL (onde existe saida/metabase_depara.json.gz).
 Uso:  py sync_depara_supabase.py [--gz CAMINHO]
============================================================
"""
import argparse
import gzip
import json
import os
import sys

import requests

import sync_supabase  # reusa _config / _headers

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

LOTE = 5000
_CAMPOS = ("data", "status", "titulo", "raiz", "path", "dur", "n")


def gz_padrao():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "saida", "metabase_depara.json.gz")


def linhas_do_gz(depara):
    """Transforma {video_id: {campos}} nas linhas de upsert de depara_video."""
    linhas = []
    for vid, rec in (depara or {}).items():
        rec = rec or {}
        linha = {"video_id": str(vid)}
        for c in _CAMPOS:
            linha[c] = rec.get(c)
        linhas.append(linha)
    return linhas


def em_lotes(seq, tamanho):
    for i in range(0, len(seq), tamanho):
        yield seq[i:i + tamanho]


def publicar(gz_path=None, url=None, key=None):
    """Lê o gz e faz upsert em lotes em depara_video. Devolve o total publicado."""
    if url is None or key is None:
        url, key = sync_supabase._config()
    rest = f"{url}/rest/v1"
    gz_path = gz_path or gz_padrao()
    if not os.path.exists(gz_path):
        raise SystemExit(f"[depara] gz não encontrado: {gz_path}\n"
                         "       Rode antes: py depara_metabase.py --refresh (Warp + Metabase).")
    with gzip.open(gz_path, "rt", encoding="utf-8") as f:
        depara = json.load(f)
    linhas = linhas_do_gz(depara)
    # ping: falha na cara antes de escrever se a credencial estiver errada
    png = requests.get(f"{rest}/depara_video?select=video_id&limit=1",
                       headers=sync_supabase._headers(key), timeout=30)
    png.raise_for_status()
    total, lotes = 0, (len(linhas) + LOTE - 1) // LOTE
    for i, lote in enumerate(em_lotes(linhas, LOTE), 1):
        requests.post(f"{rest}/depara_video",
                      headers=sync_supabase._headers(key, "resolution=merge-duplicates"),
                      params={"on_conflict": "video_id"}, json=lote, timeout=120
                      ).raise_for_status()
        total += len(lote)
        print(f"[depara] lote {i}/{lotes} — {total}/{len(linhas)}")
    print(f"[depara] publicado: {total} vídeos em depara_video.")
    return total


def main():
    parser = argparse.ArgumentParser(description="Publica o de→para de vídeos no Supabase")
    parser.add_argument("--gz", help="caminho do metabase_depara.json.gz (padrão: saida/)")
    args = parser.parse_args()
    publicar(gz_path=args.gz)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Rodar e ver passar**

Run: `py -m unittest tests.test_sync_depara -v`
Expected: PASS (5 testes).

- [ ] **Step 5: Commit**

```bash
git add sync_depara_supabase.py tests/test_sync_depara.py
git commit -m "feat: publicador do de→para de vídeos no Supabase (sync_depara_supabase)"
```

---

### Task 3: `montar_payload` monta o de→para do Supabase

**Files:**
- Modify: `sync_supabase.py` (nova `depara_do_supabase`; `montar_payload` passa a usá-la)
- Test: `tests/test_sync_depara_consumo.py`

**Interfaces:**
- Consumes: tabela `depara_video` (via PostgREST).
- Produces: `sync_supabase.depara_do_supabase(rest, key, con, extracao_id) -> dict` — `{video_id: {"data":..., "dur":..., ...}}` (shape do gz). `montar_payload` usa esse dict no lugar de `painel._depara()`.

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/test_sync_depara_consumo.py` (mocka `requests.get` do PostgREST; usa uma base com blocos de vídeo):

```python
import os, tempfile, unittest
from unittest.mock import patch, MagicMock
import banco_conteudo
import sync_supabase


def _base_com_videos(caminho):
    con = banco_conteudo.abrir(caminho)
    con.execute("INSERT INTO extracoes(id, termo, vertical, iniciada_em, status) "
                "VALUES(1,'X','concursos','2026-07-23T00:00:00','completa')")
    con.execute("INSERT INTO aulas(extracao_id, curso_id, capitulo_id, item_id, nome) "
                "VALUES(1,'c1','cap1','i1','Aula')")
    # dois vídeos: um com id antigo, um sem (id vazio deve ser ignorado)
    con.execute("INSERT INTO blocos(extracao_id, item_id, bloco_id, tipo, video_id_antigo) "
                "VALUES(1,'i1','b1','videoMyDocuments','37025')")
    con.execute("INSERT INTO blocos(extracao_id, item_id, bloco_id, tipo, video_id_antigo) "
                "VALUES(1,'i1','b2','videoMyDocuments','')")
    con.commit()
    return con


class TestDeparaDoSupabase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.con = _base_com_videos(os.path.join(self.tmp, "c.db"))

    @patch("sync_supabase.requests.get")
    def test_monta_dict_shape_do_gz(self, mock_get):
        mock_get.return_value = MagicMock(
            raise_for_status=lambda: None,
            json=lambda: [{"video_id": "37025", "data": "2019-02-11T21:49:49",
                           "dur": "00:20:33", "status": "Disponível",
                           "titulo": "T", "raiz": "R", "path": "P", "n": 3}])
        depara = sync_supabase.depara_do_supabase("http://mock/rest/v1", "k", self.con, 1)
        self.assertIn("37025", depara)
        self.assertEqual(depara["37025"]["data"], "2019-02-11T21:49:49")
        # só o id não-vazio foi consultado
        chamada = mock_get.call_args
        self.assertIn("37025", str(chamada))
        self.assertNotIn("in.()", str(chamada))  # não consulta lista vazia

    @patch("sync_supabase.requests.get")
    def test_sem_ids_devolve_vazio(self, mock_get):
        con = banco_conteudo.abrir(os.path.join(self.tmp, "vazia.db"))
        con.execute("INSERT INTO extracoes(id, termo, vertical, iniciada_em, status) "
                    "VALUES(1,'X','c','2026-07-23T00:00:00','completa')")
        con.commit()
        depara = sync_supabase.depara_do_supabase("http://mock/rest/v1", "k", con, 1)
        self.assertEqual(depara, {})
        mock_get.assert_not_called()  # sem ids, nem consulta


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `py -m unittest tests.test_sync_depara_consumo -v`
Expected: FAIL (`has no attribute 'depara_do_supabase'`).

- [ ] **Step 3: Implementar**

Em `sync_supabase.py`, adicionar a função (antes de `montar_payload`):

```python
def depara_do_supabase(rest, key, con, extracao_id):
    """Monta o de→para {video_id: {data,...}} a partir da tabela depara_video,
    só para os video_id_antigo do snapshot. Shape idêntico ao gz (painel.dados_avaliacao
    usa .get(vid).get('data')). Devolve {} se não houver ids ou a tabela falhar."""
    ids = [r[0] for r in con.execute(
        "SELECT DISTINCT video_id_antigo FROM blocos "
        "WHERE extracao_id=? AND video_id_antigo IS NOT NULL AND video_id_antigo!=''",
        (extracao_id,))]
    if not ids:
        return {}
    depara = {}
    try:
        for lote in (ids[i:i + 500] for i in range(0, len(ids), 500)):
            lista = ",".join(lote)
            r = requests.get(f"{rest}/depara_video",
                             headers=_headers(key),
                             params={"video_id": f"in.({lista})", "select": "*"}, timeout=60)
            r.raise_for_status()
            for row in r.json():
                vid = row.get("video_id")
                if vid is not None:
                    depara[str(vid)] = row
    except Exception as e:  # de→para é enriquecimento: falha não derruba o sync
        print(f"[sync] de→para do Supabase falhou (segue sem data): {e}")
        return {}
    return depara
```

Em `montar_payload`, trocar a origem do depara. A assinatura de `montar_payload(con)` não muda; ela obtém `rest,key` via `_config` e usa a nova função:

```python
def montar_payload(con):
    """..."""
    ext = con.execute("SELECT * FROM extracoes ORDER BY id DESC LIMIT 1").fetchone()
    if ext is None:
        return None
    url, key = _config()
    depara = depara_do_supabase(f"{url}/rest/v1", key, con, ext["id"])
    cursos = con.execute(
        ...  # (inalterado)
```

(Só as 2 linhas `url, key = _config()` e `depara = depara_do_supabase(...)` entram no lugar de `depara = painel._depara()`. O resto de `montar_payload` fica igual.)

- [ ] **Step 4: Rodar e ver passar**

Run: `py -m unittest tests.test_sync_depara_consumo -v`
Expected: PASS (2 testes).

- [ ] **Step 5: Ajustar os testes existentes do sync (se preciso)**

Os testes de `tests/test_sync_supabase.py` chamam `montar_payload(con)` sem Supabase vivo. Agora `montar_payload` chama `_config()` (lê `supabase.json`/env) e `depara_do_supabase` (que faz `requests.get`). Rodar:

Run: `py -m unittest tests.test_sync_supabase -v`
- Se falhar por `_config` (sem supabase.json no ambiente de teste) ou por `requests.get` real: ajustar os testes para **mockar** `sync_supabase._config` (devolvendo `("http://mock","k")`) e `sync_supabase.requests.get` (devolvendo `[]`), de forma que `depara_do_supabase` retorne `{}` — a agregação segue idêntica (só sem datas). NÃO enfraquecer as asserções existentes; só isolar a dependência de rede nova. Se já passarem (porque há `supabase.json` local e a tabela responde vazio), não mexer.

- [ ] **Step 6: Rodar a suíte inteira**

Run: `py -m unittest discover -s tests`
Expected: OK (94 + 5 + 2 novos; ajustes do Step 5 se necessários).

- [ ] **Step 7: Commit**

```bash
git add sync_supabase.py tests/test_sync_depara_consumo.py tests/test_sync_supabase.py
git commit -m "feat(sync): montar_payload casa a data do de→para via Supabase (depara_video)"
```

---

### Task 4: Docs (fluxo prático) + fecho

**Files:**
- Modify: `CLAUDE.md` (1 linha na seção do sync sobre `depara_video`); `PROXIMA-SESSAO.md` (o ritual periódico); `TUTORIAL.md` (passo a passo do refresh do de→para na nuvem); `deploy/README-vps.md` (nota: o VPS só consome, sem cache local).

- [ ] **Step 1: Documentar o fluxo prático**

Em `CLAUDE.md`, na descrição do `sync_supabase`, acrescentar que a data real de gravação na web vem da tabela `depara_video` (publicada por `sync_depara_supabase.py`), não do gz local.

Em `PROXIMA-SESSAO.md` e `TUTORIAL.md`, registrar o ritual periódico do Clovis:
```
1. Warp ativo + renovar cookie do Metabase (pasta da Limpeza)
2. py depara_metabase.py --refresh      (atualiza o gz local)
3. py sync_depara_supabase.py           (sobe o de→para pro Supabase)
```
E que o schema novo (`supabase/schema_depara.sql`) precisa ser aplicado 1× no Supabase
(Dashboard → SQL Editor → colar → Run) antes do primeiro `sync_depara_supabase.py`.

Em `deploy/README-vps.md`, uma linha: o VPS não precisa de nada para a data real — o
`montar_payload` já consome a `depara_video` do Supabase.

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md PROXIMA-SESSAO.md TUTORIAL.md deploy/README-vps.md
git commit -m "docs: fluxo do de→para de vídeos no Supabase (refresh periódico)"
```

- [ ] **Step 3: Passos manuais do Clovis (após o merge) — checklist, não é código**

1. Aplicar `supabase/schema_depara.sql` no Supabase (SQL Editor → Run).
2. Local: `py depara_metabase.py --refresh` (Warp + Metabase) → `py sync_depara_supabase.py`.
3. Re-sincronizar o snapshot atual (`py sync_supabase.py`) ou recoletar → conferir que a
   coluna "% por ano de gravação" do curso "Língua Portuguesa DMAE" deixa de ser 0 (os 123
   vídeos com ID antigo passam a casar). O VPS não precisa de `git pull` (o consumo já foi
   pro Supabase no merge, mas o worker precisa do código novo do `montar_payload`: **sim,
   precisa** `git pull` + restart no VPS para a nova `depara_do_supabase` valer nas coletas
   de lá).

## Self-Review (feita pelo autor do plano)
- **Cobertura do spec:** tabela (Task 1), publicador (Task 2), consumo no montar_payload (Task 3), docs/fluxo (Task 4). ✔
- **Shape preservado:** `depara_do_supabase` devolve `{video_id: row}` e `painel.dados_avaliacao` usa `.get(vid).get("data")` — `row` tem a chave `data`. ✔
- **Fallback:** sem ids → `{}`; erro de rede → `{}` + log, nunca derruba o sync. ✔
- **Nomes consistentes:** `depara_video` (tabela), `linhas_do_gz`/`em_lotes`/`publicar` (publicador), `depara_do_supabase` (consumo) — usados igual entre tasks. ✔
- **Sem placeholders:** todo step tem código/comando real. ✔
- **Nota de risco (Task 3 Step 5):** `montar_payload` ganhou dependência de `_config`/rede; os testes existentes podem precisar de mock — instrução explícita para isolar sem enfraquecer asserções.
