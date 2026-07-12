# Fundação de dados na nuvem (Supabase) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer os dados agregados do Painel de Conteúdo fluírem do `conteudo.db` (SQLite) para o Supabase (Postgres), prontos para o app web ler — sem tocar na coleta nem na agregação já validadas.

**Architecture:** Um script-ponte `sync_supabase.py` roda a agregação Python que já existe (`painel.dados_do_snapshot` / `painel.dados_avaliacao`) contra o snapshot mais recente do `conteudo.db` e faz upsert do resultado já mastigado em 3 tabelas do Supabase, via API REST (PostgREST). A parte pura (`montar_payload`) é testável com fixture; a parte de I/O (`enviar`) publica com visibilidade atômica (flag `pronto`).

**Tech Stack:** Python 3.12, `requests` (já no projeto — sem dependência nova), SQLite (`banco_conteudo.py`), Supabase (Postgres + PostgREST), `unittest`.

## Global Constraints

- **Idioma pt-BR** em código, comentários, prints e docs.
- **Sem dependência nova** — só `requests` + `flask` (já presentes). Nada de `supabase-py`.
- **Testes em `unittest`** (`py -m unittest discover -s tests`), não pytest.
- **Não regredir** o coletor nem a agregação: `sync_supabase.py` só LÊ o `conteudo.db` e REUSA `painel.py`; jamais altera a coleta.
- **Segredos nunca no git**: `SUPABASE_SERVICE_KEY` por env var (fallback `supabase.json`, gitignored). A service_role key ignora o RLS.
- **Datas de exibição = data local** (convenção do projeto, não UTC).
- **RLS**: leitura só para `authenticated`; escrita só via `service_role`.

---

### Task 1: Schema do Supabase (SQL versionado no repo)

**Files:**
- Create: `supabase/schema.sql`

**Interfaces:**
- Consumes: nada.
- Produces: as tabelas `snapshot`, `avaliacao_curso`, `pendencia_resumo` e a view `snapshot_atual` que a Task 3 (`enviar`) e o app web consomem.

- [ ] **Step 1: Escrever o arquivo de schema**

Create `supabase/schema.sql`:

```sql
-- Schema do app web (Painel de Conteúdo — leitura para o time).
-- Aplicar no SQL editor do Supabase (Dashboard → SQL) OU via `supabase db push`.
-- Idempotente: pode rodar de novo sem quebrar.

create table if not exists snapshot (
  id              bigserial primary key,
  termo           text        not null,
  extracao_local  int         not null,
  status          text,
  iniciada_em     timestamptz,
  resumo          jsonb,
  pronto          boolean     not null default false,
  sincronizado_em timestamptz not null default now(),
  unique (termo, extracao_local)
);

create table if not exists avaliacao_curso (
  snapshot_id bigint not null references snapshot(id) on delete cascade,
  curso_id    text   not null,
  curso_nome  text,
  autores     text,
  payload     jsonb,
  primary key (snapshot_id, curso_id)
);

create table if not exists pendencia_resumo (
  snapshot_id bigint not null references snapshot(id) on delete cascade,
  severidade  text   not null,
  regra       text   not null,
  abertas     int,
  primary key (snapshot_id, severidade, regra)
);

-- "o snapshot mais recente e 100% sincronizado de cada termo"
create or replace view snapshot_atual as
  select distinct on (termo) *
  from snapshot
  where pronto
  order by termo, extracao_local desc;

-- a view respeita o RLS das tabelas de baixo (não roda como dono)
alter view snapshot_atual set (security_invoker = on);

-- RLS: leitura só para autenticados; escrita só via service_role (ignora RLS)
alter table snapshot         enable row level security;
alter table avaliacao_curso  enable row level security;
alter table pendencia_resumo enable row level security;

drop policy if exists "leitura autenticada" on snapshot;
drop policy if exists "leitura autenticada" on avaliacao_curso;
drop policy if exists "leitura autenticada" on pendencia_resumo;

create policy "leitura autenticada" on snapshot
  for select to authenticated using (true);
create policy "leitura autenticada" on avaliacao_curso
  for select to authenticated using (true);
create policy "leitura autenticada" on pendencia_resumo
  for select to authenticated using (true);

grant select on snapshot, avaliacao_curso, pendencia_resumo to authenticated;
grant select on snapshot_atual to authenticated;
```

- [ ] **Step 2: Aplicar no Supabase e verificar (manual)**

No projeto Supabase dedicado a este app: Dashboard → SQL Editor → colar o conteúdo de `supabase/schema.sql` → Run.
Depois, na aba **Table Editor**, confirmar que existem `snapshot`, `avaliacao_curso`, `pendencia_resumo` e a view `snapshot_atual`.
Expected: as 3 tabelas + 1 view aparecem; nenhuma tem linha ainda.

- [ ] **Step 3: Commit**

```bash
git add supabase/schema.sql
git commit -m "feat: schema Supabase do app web (3 tabelas + view + RLS)"
```

---

### Task 2: `montar_payload` — agregação pura para linhas de upsert

**Files:**
- Create: `sync_supabase.py`
- Test: `tests/test_sync_supabase.py`

**Interfaces:**
- Consumes: `painel.dados_do_snapshot(con)`, `painel.dados_avaliacao(con, curso_id, depara)`, `painel._depara()`, `banco_conteudo.abrir(caminho)`.
- Produces: `montar_payload(con) -> dict | None` com a forma
  `{"snapshot": {"termo","extracao_local","status","iniciada_em","resumo"},`
  ` "avaliacoes": [{"curso_id","curso_nome","autores","payload"}...],`
  ` "pendencias": [{"severidade","regra","abertas"}...]}`.
  Retorna `None` se a base não tem coletas.

- [ ] **Step 1: Escrever o teste que falha**

Create `tests/test_sync_supabase.py`:

```python
# -*- coding: utf-8 -*-
"""Testa a agregação pura do sync (montar_payload) contra um conteudo.db de fixture."""
import os
import tempfile
import unittest

import banco_conteudo
import painel
import sync_supabase


def _fixture(caminho):
    """Um snapshot mínimo: 1 curso, 1 capítulo, 1 aula, 1 questão, 1 vídeo, 1 pendência."""
    con = banco_conteudo.abrir(caminho)
    with con:
        con.execute("INSERT INTO extracoes(id,termo,vertical,iniciada_em,status) "
                    "VALUES(1,'TESTE','x','2026-07-06T10:00:00','completa')")
        con.execute("INSERT INTO cursos VALUES(1,'C1','Curso Um',1,'Prof A','')")
        con.execute("INSERT INTO capitulos VALUES(1,'C1','CAP1','Capitulo 1',0,'','')")
        con.execute("INSERT INTO aulas VALUES(1,'C1','CAP1','IT1','Aula 1','','',1,1,0,0,0,0)")
        con.execute("INSERT INTO aulas_coletadas VALUES(1,'IT1',2,'2026-07-06T10:05:00')")
        con.execute("INSERT INTO blocos(extracao_id,item_id,bloco_id,tipo,tem_solucao,"
                    "tem_video_solucao,banca,ano) "
                    "VALUES(1,'IT1','B1','question',1,0,'CESPE',2020)")
        con.execute("INSERT INTO blocos(extracao_id,item_id,bloco_id,tipo,"
                    "video_id_antigo,duracao_seg) "
                    "VALUES(1,'IT1','B2','videoMyDocuments','123',600)")
        con.execute("INSERT INTO pendencias(chave,regra,severidade,curso_id,status) "
                    "VALUES('k1','Q1','alta','C1','nova')")
    return con


class TestMontarPayload(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.con = _fixture(os.path.join(self.tmp, "conteudo.db"))

    def tearDown(self):
        self.con.close()

    def test_snapshot_reflete_a_extracao(self):
        rows = sync_supabase.montar_payload(self.con)
        self.assertEqual(rows["snapshot"]["termo"], "TESTE")
        self.assertEqual(rows["snapshot"]["extracao_local"], 1)
        self.assertEqual(rows["snapshot"]["status"], "completa")
        self.assertIsNotNone(rows["snapshot"]["resumo"])

    def test_uma_avaliacao_por_curso_com_aulas(self):
        rows = sync_supabase.montar_payload(self.con)
        self.assertEqual(len(rows["avaliacoes"]), 1)
        self.assertEqual(rows["avaliacoes"][0]["curso_id"], "C1")
        self.assertEqual(rows["avaliacoes"][0]["curso_nome"], "Curso Um")

    def test_paridade_com_painel(self):
        # o número na web tem que ser LITERALMENTE o do painel.py
        rows = sync_supabase.montar_payload(self.con)
        esperado = painel.dados_avaliacao(self.con, "C1", depara=painel._depara())
        self.assertEqual(rows["avaliacoes"][0]["payload"], esperado)

    def test_pendencias_abertas(self):
        rows = sync_supabase.montar_payload(self.con)
        self.assertIn({"severidade": "alta", "regra": "Q1", "abertas": 1},
                      rows["pendencias"])

    def test_base_vazia_devolve_none(self):
        con = banco_conteudo.abrir(os.path.join(self.tmp, "vazia.db"))
        try:
            self.assertIsNone(sync_supabase.montar_payload(con))
        finally:
            con.close()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar o teste e ver falhar**

Run: `py -m unittest tests.test_sync_supabase -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sync_supabase'`.

- [ ] **Step 3: Implementar `montar_payload` (mínimo para passar)**

Create `sync_supabase.py`:

```python
# -*- coding: utf-8 -*-
"""
============================================================
 SYNC SUPABASE — publica o snapshot mais recente do conteudo.db
 no Supabase (Postgres) para o app web de leitura consumir.
 Só LÊ o conteudo.db e REUSA a agregação do painel.py — não
 toca na coleta. Spec: docs/superpowers/specs/2026-07-12-*.md

 Uso:  py sync_supabase.py [--termo BACEN]
============================================================
"""
import argparse
import os
import sys

import painel

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def montar_payload(con):
    """Monta as linhas de upsert a partir do snapshot mais recente do conteudo.db.

    Devolve None se a base ainda não tem coletas. A agregação é a MESMA do
    painel.py (garantia de paridade com a tela aprovada)."""
    ext = con.execute("SELECT * FROM extracoes ORDER BY id DESC LIMIT 1").fetchone()
    if ext is None:
        return None
    depara = painel._depara()
    cursos = con.execute(
        "SELECT c.curso_id, c.nome, c.autores FROM cursos c WHERE c.extracao_id=? "
        "AND EXISTS (SELECT 1 FROM aulas a WHERE a.extracao_id=c.extracao_id "
        "AND a.curso_id=c.curso_id) ORDER BY c.nome", (ext["id"],)).fetchall()
    avaliacoes = [{
        "curso_id": c["curso_id"],
        "curso_nome": c["nome"],
        "autores": c["autores"] or "",
        "payload": painel.dados_avaliacao(con, c["curso_id"], depara=depara),
    } for c in cursos]
    pend = con.execute(
        "SELECT severidade, regra, COUNT(*) FROM pendencias "
        "WHERE status IN ('nova','enviada') GROUP BY severidade, regra").fetchall()
    return {
        "snapshot": {
            "termo": ext["termo"], "extracao_local": ext["id"],
            "status": ext["status"], "iniciada_em": ext["iniciada_em"],
            "resumo": painel.dados_do_snapshot(con),
        },
        "avaliacoes": avaliacoes,
        "pendencias": [{"severidade": r[0], "regra": r[1], "abertas": r[2]} for r in pend],
    }
```

- [ ] **Step 4: Rodar o teste e ver passar**

Run: `py -m unittest tests.test_sync_supabase -v`
Expected: PASS (5 testes).

- [ ] **Step 5: Commit**

```bash
git add sync_supabase.py tests/test_sync_supabase.py
git commit -m "feat: montar_payload — agregação pura do sync (reusa painel.py)"
```

---

### Task 3: `enviar` + CLI — publicar no Supabase (PostgREST)

**Files:**
- Modify: `sync_supabase.py`

**Interfaces:**
- Consumes: `montar_payload(con)` (Task 2), `banco_conteudo.abrir`, `extrator_ldi.carregar_config`, `extrator_ldi.PASTA_APP`.
- Produces: `esta_configurado() -> bool`, `enviar(rows, url=None, key=None) -> int` (o snapshot_id no Supabase), e `main()` (CLI). Usados pela Task 4 (gancho no coletor).

- [ ] **Step 1: Implementar `esta_configurado`, `enviar` e `main`**

Add to `sync_supabase.py` (após `montar_payload`, e ajuste os imports do topo para incluir `json` e `requests`):

Troque o bloco de imports do topo por:
```python
import argparse
import json
import os
import sys

import requests

import painel
```

Acrescente ao fim do arquivo:
```python
def _config():
    """URL + service_role key: env vars primeiro, fallback supabase.json (gitignored)."""
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if (not url or not key):
        caminho = os.path.join(os.path.dirname(os.path.abspath(__file__)), "supabase.json")
        if os.path.exists(caminho):
            with open(caminho, encoding="utf-8") as f:
                j = json.load(f)
            url = url or j.get("url")
            key = key or j.get("service_key")
    if not url or not key:
        raise SystemExit("[sync] Faltam SUPABASE_URL e SUPABASE_SERVICE_KEY "
                         "(ou um supabase.json com {url, service_key}).")
    return url.rstrip("/"), key


def esta_configurado():
    if os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_KEY"):
        return True
    return os.path.exists(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "supabase.json"))


def _headers(key, prefer=None):
    h = {"apikey": key, "Authorization": f"Bearer {key}",
         "Content-Type": "application/json"}
    if prefer:
        h["Prefer"] = prefer
    return h


def enviar(rows, url=None, key=None):
    """Upsert no Supabase com visibilidade atômica (pronto=false → filhos → pronto=true)."""
    if url is None or key is None:
        url, key = _config()
    rest = f"{url}/rest/v1"

    # ping: falha na cara ANTES de escrever se a credencial estiver errada
    png = requests.get(f"{rest}/snapshot?select=id&limit=1", headers=_headers(key), timeout=30)
    png.raise_for_status()

    # 1. upsert do snapshot (pronto=false), devolve o id
    corpo = {**rows["snapshot"], "pronto": False}
    r = requests.post(f"{rest}/snapshot", headers=_headers(
        key, "resolution=merge-duplicates,return=representation"),
        params={"on_conflict": "termo,extracao_local"}, json=corpo, timeout=60)
    r.raise_for_status()
    sid = r.json()[0]["id"]

    # 2. limpa filhos desse snapshot (re-run idempotente)
    for tab in ("avaliacao_curso", "pendencia_resumo"):
        d = requests.delete(f"{rest}/{tab}", headers=_headers(key),
                            params={"snapshot_id": f"eq.{sid}"}, timeout=60)
        d.raise_for_status()

    # 3. insere os filhos
    avals = [{"snapshot_id": sid, **a} for a in rows["avaliacoes"]]
    if avals:
        requests.post(f"{rest}/avaliacao_curso", headers=_headers(key),
                      json=avals, timeout=120).raise_for_status()
    pend = [{"snapshot_id": sid, **p} for p in rows["pendencias"]]
    if pend:
        requests.post(f"{rest}/pendencia_resumo", headers=_headers(key),
                      json=pend, timeout=60).raise_for_status()

    # 4. marca pronto=true → só agora a view snapshot_atual enxerga
    requests.patch(f"{rest}/snapshot", headers=_headers(key),
                   params={"id": f"eq.{sid}"}, json={"pronto": True},
                   timeout=60).raise_for_status()
    return sid


def main():
    import banco_conteudo
    import extrator_ldi
    parser = argparse.ArgumentParser(description="Publica o snapshot mais recente no Supabase")
    parser.add_argument("--termo", help="guarda: recusa se o snapshot mais recente não for deste termo")
    args = parser.parse_args()

    caminho = os.path.join(extrator_ldi.PASTA_APP,
                           extrator_ldi.carregar_config()["pasta_saida"], "conteudo.db")
    con = banco_conteudo.abrir(caminho)
    try:
        rows = montar_payload(con)
    finally:
        con.close()
    if rows is None:
        raise SystemExit("[sync] Base sem coletas — rode o coletor primeiro.")
    if args.termo and rows["snapshot"]["termo"] != args.termo:
        raise SystemExit(f"[sync] Snapshot mais recente é '{rows['snapshot']['termo']}', "
                         f"não '{args.termo}'. Colete '{args.termo}' antes.")
    sid = enviar(rows)
    print(f"[sync] snapshot {sid} publicado: {len(rows['avaliacoes'])} cursos, "
          f"{len(rows['pendencias'])} linhas de pendência.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Garantir que os testes da Task 2 continuam passando**

Run: `py -m unittest tests.test_sync_supabase -v`
Expected: PASS (5 testes) — `enviar`/`main` não são exercidos aqui (são I/O), mas o import do módulo não pode ter quebrado.

- [ ] **Step 3: Smoke test manual contra o Supabase**

Pré-requisito: schema da Task 1 aplicado; `supabase.json` criado na pasta do app com `{"url": "...", "service_key": "..."}` (a **service_role** key, do Dashboard → Settings → API), OU as env vars `SUPABASE_URL`/`SUPABASE_SERVICE_KEY` definidas. É preciso haver ao menos uma coleta no `conteudo.db` (ex.: BACEN).

Run: `py sync_supabase.py`
Expected: imprime `[sync] snapshot <n> publicado: <N> cursos, <M> linhas de pendência.`
Confirmar no Supabase (Table Editor): `snapshot` tem 1 linha com `pronto = true`; `avaliacao_curso` tem N linhas; `snapshot_atual` retorna a linha.

- [ ] **Step 4: Commit**

```bash
git add sync_supabase.py
git commit -m "feat: enviar — upsert do snapshot no Supabase via PostgREST (pronto atômico)"
```

---

### Task 4: Gancho no coletor + `.gitignore`

**Files:**
- Modify: `coletor_ldi.py:190-198` (após o bloco das regras de qualidade, dentro de `coletar`)
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `sync_supabase.esta_configurado()`, `sync_supabase.montar_payload(con)`, `sync_supabase.enviar(rows)` (Tasks 2-3).
- Produces: nada novo (efeito colateral: publica no fim da coleta se configurado).

- [ ] **Step 1: Adicionar `supabase.json` ao `.gitignore`**

Modify `.gitignore` — na seção "Segredos / credenciais", após a linha `*.cookie`, acrescentar:
```
supabase.json
```

- [ ] **Step 2: Ligar o sync ao fim da coleta (não-fatal)**

Modify `coletor_ldi.py`: logo APÓS o bloco `try/except` das regras de qualidade (que termina na linha `print(f"      (regras de qualidade falharam...`), e ANTES do `if com_videos and tarefas:`, inserir:

```python
        try:
            import sync_supabase
            if sync_supabase.esta_configurado():
                print("      publicando no Supabase...")
                rows = sync_supabase.montar_payload(con)
                if rows:
                    sid = sync_supabase.enviar(rows)
                    print(f"      Supabase: snapshot {sid} publicado.")
            else:
                print("      (Supabase não configurado — pulei o sync; "
                      "rode py sync_supabase.py quando quiser)")
        except Exception as e:  # publicação não pode derrubar a coleta já gravada
            print(f"      (sync com Supabase falhou: {e} — rode py sync_supabase.py)")
```

- [ ] **Step 3: Verificar que o coletor ainda importa e roda o `--help`**

Run: `py coletor_ldi.py --help`
Expected: mostra a ajuda sem erro de import (confirma que o gancho não quebrou o módulo).

- [ ] **Step 4: Rodar toda a suíte de testes**

Run: `py -m unittest discover -s tests`
Expected: todos os testes passam (os 38 anteriores + os 5 novos do sync).

- [ ] **Step 5: Commit**

```bash
git add .gitignore coletor_ldi.py
git commit -m "feat: coletor publica no Supabase ao fim da coleta (não-fatal) + gitignore"
```

---

## Self-Review

**Spec coverage:**
- Schema (3 tabelas + view + RLS `authenticated`) → Task 1. ✓
- `montar_payload` puro + paridade com `painel.py` → Task 2. ✓
- `enviar` via `requests`/PostgREST + segredos por env/`supabase.json` + `pronto` atômico + idempotência → Task 3. ✓
- Acionamento avulso (`py sync_supabase.py [--termo]`) e ao fim do coletor → Task 3 (`main`) + Task 4 (gancho). ✓
- Deleções resolvidas por `snapshot_id` novo → coberto pelo modelo (snapshot novo a cada coleta) + limpeza de filhos no re-run (Task 3, Step 1). ✓
- Erro "aborta claro" (ping antes de escrever; gancho não-fatal) → Task 3 + Task 4. ✓
- **Fora deste plano (Plano 2):** app Next.js/Vercel, Supabase Auth, port das telas, selo de frescor. Correto — é o outro subsistema.

**Placeholder scan:** sem TBD/TODO; todo passo tem código ou comando real. O único "manual" (Task 1 Step 2, Task 3 Step 3) é aplicação de SQL/smoke test que exige o Supabase — inerente, com passos e expected concretos.

**Type consistency:** `montar_payload` devolve `{snapshot, avaliacoes[], pendencias[]}` (Task 2) e `enviar` consome exatamente essas chaves (Task 3). `snapshot` tem `termo/extracao_local/status/iniciada_em/resumo`; a tabela `snapshot` (Task 1) tem essas colunas + `pronto`/`sincronizado_em` (default). `avaliacoes[]` tem `curso_id/curso_nome/autores/payload` = colunas de `avaliacao_curso`. `pendencias[]` tem `severidade/regra/abertas` = colunas de `pendencia_resumo`. Consistente. ✓

## Próximo plano (a escrever depois de verificar este)

**Plano 2 — App web no Vercel:** Next.js mínimo + Supabase Auth (magic-link, convite) + middleware de gate + port de `avaliacao.html`/`painel.html` (troca `fetch` → `supabase-js`, com o mesmo `{data}`) + selo "dados de DD/MM HH:MM" + estados vazios. Será escrito com edições exatas nas telas (exige leitura próxima do `avaliacao.html`/`painel.html`), idealmente após a fundação estar verificada no Supabase.
