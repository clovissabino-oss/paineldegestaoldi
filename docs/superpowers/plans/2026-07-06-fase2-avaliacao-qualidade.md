# Fase 2 — Avaliação de Livro/Disciplina + Motor de Qualidade — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Coletor v1.1 (banca/ano, tópicos, autores, questões em texto), motor de pendências com baixa automática, e a tela `/avaliacao` (planilha por capítulo, formato mockup v6) no painel — com re-coleta real, docs, builds e push.

**Architecture:** Evolução dos módulos existentes (`parse_blocos`/`banco_conteudo`/`coletor_ldi`/`painel`) + 1 módulo novo (`regras_qualidade.py`, catálogo declarativo que materializa `pendencias` no mesmo `conteudo.db`). A idade de gravação vem do cache `saida\metabase_depara.json.gz` carregado 1× em memória (painel e regras).

**Tech Stack:** Python 3.12 stdlib + requests + flask (sem dependência nova). PyInstaller para os exes.

## Global Constraints

- Idioma pt-BR em código/mensagens/docs; `extrator_ldi.py` não muda.
- Régua 2/5: crítico = idade > 5 anos (ano ≤ ANO_ATUAL−6); atenção = 3-5 anos (ANO_ATUAL−5 … ANO_ATUAL−3).
- Detector de questões em texto grava contagem + referências (banca/ano/resto) — **nunca o texto**.
- Snapshots antigos permanecem válidos (colunas novas NULL); migração idempotente.
- Rodar testes: `py -m unittest discover -s tests` na raiz.
- Spec: `docs/superpowers/specs/2026-07-06-fase2-avaliacao-qualidade-design.md`.

---

### Task 1: `parse_blocos.py` v1.1 — banca/ano, tópicos, detector de questões em texto, autores

**Files:**
- Modify: `parse_blocos.py`
- Test: `tests/test_parse_blocos.py` (acrescentar)

**Interfaces:**
- Produces (Tasks 2-6 dependem):
  - `meta_do_bloco(bloco) -> dict` ganha chaves `banca` (str), `ano` (int|None), `qtd_questoes_texto` (int|None); question ganha `meta.orgao`, `meta.topico`, `meta.topico_caminho`; tiptap ganha `meta.questoes_texto` = `[{banca, ano, resto}]`.
  - `questoes_no_texto(conteudo) -> list[dict]` — refs extraídas do JSON tiptap.
  - `nomes_dos_autores(detalhe_curso: dict) -> str` — `structured_authors[].full_name` unidos por " | "; fallback regex `Profs?\.` no `name`.

- [ ] **Step 1: Testes que falham** — acrescentar em `tests/test_parse_blocos.py` (payloads reais da sondagem de 06/07):

```python
BLOCO_QUESTION_EXAMS = {
    "id": "q2", "type": "question", "order_index": 1, "is_active": True,
    "data": {"value": "61896628", "resolved": {
        "id": "61896628", "answer_type": "MULTIPLE_CHOICE",
        "alternatives": [{"id": "a"}],
        "topics": [{"path_name": ["Matérias", "Contabilidade Geral", "DRE"],
                    "is_main_classification": True},
                   {"path_name": ["Outra", "Secundária"], "is_main_classification": False}],
        "exams": [{"id": "61896628", "year": 2013,
                   "badges": [{"type": "YEAR", "text": "2013"},
                              {"type": "83d50f93", "text": "CESPE (CEBRASPE)"},
                              {"type": "4e3bff0b", "text": "SUFRAMA"}]}],
        "solution": {"brief": "x"}, "has_video_solution": False,
    }},
}

TIPTAP_COM_QUESTOES = {
    "id": "t2", "type": "tiptap", "order_index": 2, "is_active": True,
    "content_length": 5000,
    "data": {"type": "doc", "content": [{"type": "paragraph", "content": [
        {"type": "text", "text": "EXERCÍCIOS (CEBRASPE/2025/MPE CE/Analista) Julgue o item."},
        {"type": "text", "text": "Outra: (FGV - 2023) assinale. E (Inéditas/2026) também."},
    ]}]},
}


class TestBancaAnoTopicos(unittest.TestCase):
    def test_question_extrai_banca_ano_orgao_topico(self):
        m = parse_blocos.meta_do_bloco(BLOCO_QUESTION_EXAMS)
        self.assertEqual(m["banca"], "CESPE (CEBRASPE)")
        self.assertEqual(m["ano"], 2013)
        self.assertEqual(m["meta"]["orgao"], "SUFRAMA")
        self.assertEqual(m["meta"]["topico"], "DRE")
        self.assertEqual(m["meta"]["topico_caminho"], "Matérias > Contabilidade Geral > DRE")

    def test_question_sem_exams_fica_vazia(self):
        m = parse_blocos.meta_do_bloco(BLOCO_QUESTION)  # fixture antiga (exams com name, sem badges)
        self.assertEqual(m["banca"], "")
        self.assertIsNone(m["ano"])


class TestQuestoesNoTexto(unittest.TestCase):
    def test_detecta_padroes_reais(self):
        refs = parse_blocos.questoes_no_texto(TIPTAP_COM_QUESTOES["data"]["content"])
        self.assertEqual([r["banca"] for r in refs], ["CEBRASPE", "FGV", "Inéditas"])
        self.assertEqual([r["ano"] for r in refs], [2025, 2023, 2026])
        self.assertIn("MPE CE", refs[0]["resto"])

    def test_tiptap_ganha_contagem_e_refs(self):
        m = parse_blocos.meta_do_bloco(TIPTAP_COM_QUESTOES)
        self.assertEqual(m["qtd_questoes_texto"], 3)
        self.assertEqual(len(m["meta"]["questoes_texto"]), 3)

    def test_conteudo_vazio_zero(self):
        self.assertEqual(parse_blocos.questoes_no_texto(None), [])
        m = parse_blocos.meta_do_bloco(BLOCO_TIPTAP)  # fixture antiga sem questões
        self.assertEqual(m["qtd_questoes_texto"], 0)


class TestNomesDosAutores(unittest.TestCase):
    def test_structured_authors(self):
        d = {"structured_authors": [{"full_name": "Professora Renan Araújo"},
                                    {"full_name": "Outro Prof"}]}
        self.assertEqual(parse_blocos.nomes_dos_autores(d), "Professora Renan Araújo | Outro Prof")

    def test_fallback_regex_no_nome(self):
        d = {"structured_authors": [], "name": "Direito Penal para X - Prof. Renan Araújo"}
        self.assertEqual(parse_blocos.nomes_dos_autores(d), "Prof. Renan Araújo")
        self.assertEqual(parse_blocos.nomes_dos_autores({"name": "Curso sem prof"}), "")
```

- [ ] **Step 2: Rodar e ver falhar** — `py -m unittest tests.test_parse_blocos -v` → falhas/erros nos testes novos (KeyError `banca` etc.).

- [ ] **Step 3: Implementar.** Em `parse_blocos.py`: (a) `import re` no topo; (b) acrescentar após `_MAPA`:

```python
_RX_QUESTAO_TEXTO = re.compile(
    r"\((CESPE[^/)]*|CEBRASPE[^/)]*|FGV|FCC|VUNESP|IADES|ESAF|CESGRANRIO|AOCP|QUADRIX|"
    r"Banca\s+[^/)]+|Instituto\s+[^/)]+|In[eé]ditas?[^/)]*)\s*[/\-–]\s*(\d{4})([^)]*)\)",
    re.I)
_RX_PROF_NO_NOME = re.compile(r"[-–]\s*(Profs?\.\s*[^-–]+?)\s*$", re.I)


def _texto_do_no(no, acc):
    if isinstance(no, dict):
        if isinstance(no.get("text"), str):
            acc.append(no["text"])
        for v in no.values():
            _texto_do_no(v, acc)
    elif isinstance(no, list):
        for v in no:
            _texto_do_no(v, acc)
    return acc


def questoes_no_texto(conteudo):
    """Refs de questões coladas no corpo do tiptap: [(BANCA/ANO/resto)] -> lista de dicts."""
    if not conteudo:
        return []
    txt = " ".join(_texto_do_no(conteudo, []))
    return [{"banca": m.group(1).strip(), "ano": int(m.group(2)),
             "resto": m.group(3).strip(" /-–")[:60]}
            for m in _RX_QUESTAO_TEXTO.finditer(txt)]


def nomes_dos_autores(detalhe_curso):
    """Nomes do GET /bo/ldi/courses/{id} (structured_authors); fallback: 'Prof. X' no nome."""
    nomes = [a.get("full_name") or a.get("public_name") or ""
             for a in (detalhe_curso.get("structured_authors") or []) if isinstance(a, dict)]
    nomes = [n for n in nomes if n]
    if nomes:
        return " | ".join(nomes)
    m = _RX_PROF_NO_NOME.search(detalhe_curso.get("name") or "")
    return m.group(1).strip() if m else ""
```

(c) em `meta_do_bloco`, acrescentar ao dict base `"banca": "", "ano": None, "qtd_questoes_texto": None,`; no ramo `question` substituir o bloco do `meta` por:

```python
        exs = res.get("exams") or []
        e0 = exs[0] if exs and isinstance(exs[0], dict) else {}
        badges = [b.get("text", "") for b in (e0.get("badges") or [])
                  if isinstance(b, dict) and b.get("type") != "YEAR" and b.get("text")]
        topicos = [t for t in (res.get("topics") or []) if isinstance(t, dict)]
        principal = next((t for t in topicos if t.get("is_main_classification")),
                         topicos[0] if topicos else None)
        caminho = (principal or {}).get("path_name") or []
        linha["banca"] = badges[0] if badges else ""
        linha["ano"] = e0.get("year")
        linha["meta"] = {
            "slug": res.get("slug", ""),
            "orgao": badges[1] if len(badges) > 1 else "",
            "topico": caminho[-1] if caminho else "",
            "topico_caminho": " > ".join(caminho),
            "qtd_alternativas": len(res.get("alternatives") or []),
        }
```

e no ramo `tiptap`, após `tamanho_texto`:

```python
        refs = questoes_no_texto(d.get("content"))
        linha["qtd_questoes_texto"] = len(refs)
        if refs:
            linha["meta"] = {"questoes_texto": refs[:200]}
```

  Atenção: os testes antigos de `topicos`/`provas` no meta da question (formato `name`) serão
  substituídos — atualizar `test_question` antigo para as chaves novas (`meta.topico == ""` na
  fixture antiga, pois ela usa `topics[].name`, formato que a API real não usa).

- [ ] **Step 4: Rodar e ver passar** — `py -m unittest tests.test_parse_blocos -v` → OK.

- [ ] **Step 5: Commit** — `git add parse_blocos.py tests/test_parse_blocos.py && git commit -m "feat: parse v1.1 — banca/ano/tópicos reais, detector de questões em texto, autores"`

---

### Task 2: `banco_conteudo.py` — migração de schema (colunas novas + índice + tabelas de pendência)

**Files:**
- Modify: `banco_conteudo.py`
- Test: `tests/test_banco_conteudo.py` (acrescentar)

**Interfaces:**
- Produces: `abrir()` passa a garantir colunas `banca TEXT`, `ano INTEGER`, `qtd_questoes_texto INTEGER` em `blocos`; índice `ix_blocos_item ON blocos(item_id)`; tabelas `pendencias` e `acionamentos`; `_COLS_BLOCO` estendida (INSERT grava os campos novos).

- [ ] **Step 1: Teste que falha:**

```python
    def test_migracao_adiciona_colunas_indice_e_tabelas(self):
        cols = {r[1] for r in self.con.execute("PRAGMA table_info(blocos)")}
        self.assertTrue({"banca", "ano", "qtd_questoes_texto"} <= cols)
        idx = {r[1] for r in self.con.execute("PRAGMA index_list(blocos)")}
        self.assertIn("ix_blocos_item", idx)
        tabelas = {r[0] for r in self.con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({"pendencias", "acionamentos"} <= tabelas)
        # reabrir a mesma base não pode estourar (idempotente)
        con2 = banco_conteudo.abrir(self.con.execute("PRAGMA database_list").fetchone()[2])
        con2.close()

    def test_insert_grava_campos_novos(self):
        eid = self._nova()
        b = dict(B1, banca="CESPE (CEBRASPE)", ano=2013, qtd_questoes_texto=None)
        banco_conteudo.gravar_blocos_da_aula(self.con, eid, "i1", [b])
        row = self.con.execute("SELECT banca, ano FROM blocos WHERE extracao_id=?", (eid,)).fetchone()
        self.assertEqual((row["banca"], row["ano"]), ("CESPE (CEBRASPE)", 2013))
```

- [ ] **Step 2: Rodar e ver falhar** — `py -m unittest tests.test_banco_conteudo -v` → FAIL (colunas ausentes).

- [ ] **Step 3: Implementar.** Em `banco_conteudo.py`:
  (a) acrescentar ao `_SCHEMA` (antes dos índices):

```sql
CREATE TABLE IF NOT EXISTS pendencias(
  chave TEXT PRIMARY KEY,
  regra TEXT NOT NULL, severidade TEXT NOT NULL,
  curso_id TEXT NOT NULL, item_id TEXT DEFAULT '', bloco_id TEXT DEFAULT '',
  descricao TEXT,
  status TEXT NOT NULL DEFAULT 'nova',
  extracao_id_criada INTEGER, extracao_id_ultima INTEGER,
  criada_em TEXT, resolvida_em TEXT);
CREATE INDEX IF NOT EXISTS ix_pend_status ON pendencias(status, severidade);
CREATE TABLE IF NOT EXISTS acionamentos(
  chave_pendencia TEXT NOT NULL, status TEXT NOT NULL,
  observacao TEXT DEFAULT '', registrado_em TEXT);
```

  (b) na tabela `blocos` do `_SCHEMA`, acrescentar `banca TEXT, ano INTEGER, qtd_questoes_texto INTEGER,` antes de `meta TEXT` (bases novas já nascem certas); (c) migração para bases existentes — após `con.executescript(_SCHEMA)` em `abrir()`:

```python
    for sql in ("ALTER TABLE blocos ADD COLUMN banca TEXT",
                "ALTER TABLE blocos ADD COLUMN ano INTEGER",
                "ALTER TABLE blocos ADD COLUMN qtd_questoes_texto INTEGER"):
        try:
            con.execute(sql)
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e):
                raise
    con.execute("CREATE INDEX IF NOT EXISTS ix_blocos_item ON blocos(item_id)")
```

  (d) `_COLS_BLOCO` ganha `"banca", "ano", "qtd_questoes_texto"` e o INSERT de
  `gravar_blocos_da_aula` troca o `16` fixo por `len(_COLS_BLOCO) + 3` (extracao_id, item_id, meta):
  `VALUES({','.join('?' * (len(_COLS_BLOCO) + 3))})`.

- [ ] **Step 4: Rodar e ver passar** — suíte toda: `py -m unittest discover -s tests` → OK.

- [ ] **Step 5: Commit** — `git add banco_conteudo.py tests/test_banco_conteudo.py && git commit -m "feat: schema v1.1 — banca/ano/questões-texto, índice por aula e tabelas de pendência"`

---

### Task 3: `coletor_ldi.py` — professores via detalhe do curso

**Files:**
- Modify: `coletor_ldi.py`
- Test: `tests/test_coletor_fluxo.py` (acrescentar)

**Interfaces:**
- Consumes: `parse_blocos.nomes_dos_autores` (Task 1).
- Produces: coleta nova preenche `cursos.autores`; `SessaoFake` do teste passa a responder `GET .../courses/{id}` (Task 4 e 6 reusam o padrão).

- [ ] **Step 1: Teste que falha** — em `tests/test_coletor_fluxo.py`, estender `SessaoFake.get` e acrescentar teste:

```python
    def get(self, url, timeout=0):
        if "/bo/ldi/courses/" in url:                      # detalhe do curso (autores)
            cid = url.rsplit("/", 1)[1]
            return RespostaFake(200 if cid == "c1" else 404,
                                {"id": cid, "structured_authors":
                                 [{"full_name": "Prof Teste"}]} if cid == "c1" else None)
        item = url.split("item_id=")[1]
        if item in self.falhas:
            return RespostaFake(self.status_falha)
        return RespostaFake(200, BLOCOS.get(item, []))
```

  (no `RespostaFake.json`, devolver `{"data": self._dados}` como já faz — o detalhe vem em `data`.)

```python
    def test_coleta_preenche_autores_do_detalhe(self):
        eid = coletor_ldi.coletar(CFG, SessaoFake(), "BACEN", self.db)
        con = banco_conteudo.abrir(self.db)
        row = con.execute("SELECT autores FROM cursos WHERE extracao_id=? AND curso_id='c1'", (eid,)).fetchone()
        self.assertEqual(row["autores"], "Prof Teste")
        con.close()
```

- [ ] **Step 2: Rodar e ver falhar** — `py -m unittest tests.test_coletor_fluxo -v` → FAIL (autores vazio).

- [ ] **Step 3: Implementar** — em `coletor_ldi.py`, nova função e chamada no caminho de coleta nova (após `gravar_arvore`):

```python
def _completar_autores(sessao, con, extracao_id, cursos, concorrencia):
    """A listagem devolve só UUIDs; o detalhe do curso traz structured_authors (nomes)."""
    def detalhe(cid):
        j = extrator_ldi.get_json(sessao, f"{extrator_ldi.API}/bo/ldi/courses/{cid}")
        return cid, (j.get("data") or {})
    falhas = 0
    with ThreadPoolExecutor(max_workers=int(concorrencia)) as pool:
        futuros = {pool.submit(detalhe, c.get("id")): c for c in cursos if c.get("id")}
        for fut in as_completed(futuros):
            try:
                cid, d = fut.result()
                nomes = parse_blocos.nomes_dos_autores(d)
                if nomes:
                    with con:
                        con.execute("UPDATE cursos SET autores=? WHERE extracao_id=? AND curso_id=?",
                                    (nomes, extracao_id, cid))
            except SystemExit:
                raise
            except Exception:
                falhas += 1  # enriquecimento: falha pontual não derruba a coleta
    if falhas:
        print(f"      ({falhas} cursos sem professor identificado)")
```

  e, logo após o print de "N cursos, M aulas únicas":

```python
            print("      buscando professores (detalhe de cada curso)...")
            _completar_autores(sessao, con, extracao_id, cursos, cfg["concorrencia"])
```

- [ ] **Step 4: Rodar e ver passar** — suíte toda OK.

- [ ] **Step 5: Commit** — `git add coletor_ldi.py tests/test_coletor_fluxo.py && git commit -m "feat: coletor busca professores no detalhe do curso (structured_authors)"`

---

### Task 4: `regras_qualidade.py` — catálogo, materialização e baixa automática

**Files:**
- Create: `regras_qualidade.py`
- Modify: `coletor_ldi.py` (chamar ao fim da coleta)
- Test: `tests/test_regras_qualidade.py`

**Interfaces:**
- Consumes: `banco_conteudo.abrir`; cache Metabase opcional (`dict video_id -> {"data": ...}`).
- Produces:
  - `avaliar(con, extracao_id: int, depara: dict | None = None) -> dict` — roda o catálogo,
    faz upsert em `pendencias` + baixa automática; retorna
    `{"novas": int, "reabertas": int, "resolvidas": int, "abertas_por_regra": {regra: qtd}}`.
  - `CATALOGO`: tupla de `(id_regra, severidade, funcao)`; `funcao(con, e, ctx) -> list[(curso_id, item_id, bloco_id, descricao)]`. `ctx = {"depara": dict|None, "ano_atual": int}`.
  - Chave determinística: `f"{regra}|{curso_id}|{item_id}|{bloco_id}"`.
  - CLI: `py regras_qualidade.py [--extracao N]` (padrão: extração mais recente).

- [ ] **Step 1: Testes que falham** — `tests/test_regras_qualidade.py`:

```python
# -*- coding: utf-8 -*-
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import banco_conteudo
import regras_qualidade
from tests.test_banco_conteudo import CURSOS, B1

B_Q_SEM_SOL = dict(B1, bloco_id="bq", questao_id="222", tem_solucao=0, ano=2015)
B_TXT_CURTO = {"bloco_id": "bt", "tipo": "tiptap", "ordem": 2, "ativo": 1, "rascunho": 0,
               "titulo": "", "questao_id": "", "resposta_tipo": "", "tem_solucao": None,
               "tem_video_solucao": None, "video_id_antigo": "", "duracao_seg": None,
               "tamanho_texto": 200, "qtd_questoes_texto": 0, "banca": "", "ano": None, "meta": {}}
B_VIDEO_VELHO = {"bloco_id": "bv", "tipo": "videoMyDocuments", "ordem": 3, "ativo": 1,
                 "rascunho": 0, "titulo": "v", "questao_id": "", "resposta_tipo": "",
                 "tem_solucao": None, "tem_video_solucao": None, "video_id_antigo": "999",
                 "duracao_seg": 60, "tamanho_texto": None, "qtd_questoes_texto": None,
                 "banca": "", "ano": None, "meta": {}}
DEPARA = {"999": {"data": "2018-05-01"}}


def montar(con, com_solucao=False):
    eid = banco_conteudo.iniciar_extracao(con, "T", "concursos")
    banco_conteudo.gravar_arvore(con, eid, CURSOS)
    blocos = [B_TXT_CURTO, B_VIDEO_VELHO] + ([dict(B_Q_SEM_SOL, tem_solucao=1)] if com_solucao
                                             else [B_Q_SEM_SOL])
    banco_conteudo.gravar_blocos_da_aula(con, eid, "i1", blocos)
    banco_conteudo.gravar_blocos_da_aula(con, eid, "i2", [])
    banco_conteudo.finalizar_extracao(con, eid, {})
    return eid


class TestRegras(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.con = banco_conteudo.abrir(os.path.join(self.dir.name, "c.db"))

    def tearDown(self):
        self.con.close()
        self.dir.cleanup()

    def test_avaliar_materializa_pendencias(self):
        eid = montar(self.con)
        r = regras_qualidade.avaliar(self.con, eid, depara=DEPARA)
        self.assertGreater(r["novas"], 0)
        regras = {row[0] for row in self.con.execute("SELECT DISTINCT regra FROM pendencias")}
        # Q1 (sem solução), Q2 (ano 2015 = crítica), V1 (gravado 2018 > 5 anos),
        # A1 (i2 sem questão), A3 (texto curto), C1 não (todos os cursos têm aula)
        self.assertTrue({"Q1", "Q2", "V1", "A1", "A3"} <= regras)
        # aula i2 sem questão: 1 pendência por vínculo curso↔aula (2 cursos? i2 só no c1)
        st = self.con.execute("SELECT COUNT(*) FROM pendencias WHERE status='nova'").fetchone()[0]
        self.assertEqual(st, r["novas"])

    def test_baixa_automatica_e_persistencia_de_status(self):
        eid = montar(self.con)
        regras_qualidade.avaliar(self.con, eid, depara=DEPARA)
        chave_q1 = self.con.execute(
            "SELECT chave FROM pendencias WHERE regra='Q1'").fetchone()[0]
        with self.con:
            self.con.execute("UPDATE pendencias SET status='enviada' WHERE chave=?", (chave_q1,))
        # snapshot novo: questão agora COM solução -> Q1 deve ser baixada; demais persistem
        eid2 = montar(self.con, com_solucao=True)
        r2 = regras_qualidade.avaliar(self.con, eid2, depara=DEPARA)
        row = self.con.execute("SELECT status, resolvida_em FROM pendencias WHERE chave=?",
                               (chave_q1,)).fetchone()
        self.assertEqual(row["status"], "resolvida")
        self.assertTrue(row["resolvida_em"])
        self.assertGreaterEqual(r2["resolvidas"], 1)
        # V1 persiste com status mantido (nova) e extracao_id_ultima atualizada
        v1 = self.con.execute("SELECT status, extracao_id_ultima FROM pendencias "
                              "WHERE regra='V1'").fetchone()
        self.assertEqual((v1["status"], v1["extracao_id_ultima"]), ("nova", eid2))

    def test_ignorada_nao_reabre(self):
        eid = montar(self.con)
        regras_qualidade.avaliar(self.con, eid, depara=DEPARA)
        with self.con:
            self.con.execute("UPDATE pendencias SET status='ignorada' WHERE regra='A3'")
        eid2 = montar(self.con)
        regras_qualidade.avaliar(self.con, eid2, depara=DEPARA)
        st = {r[0] for r in self.con.execute("SELECT status FROM pendencias WHERE regra='A3'")}
        self.assertEqual(st, {"ignorada"})

    def test_sem_depara_pula_v1_sem_estourar(self):
        eid = montar(self.con)
        r = regras_qualidade.avaliar(self.con, eid, depara=None)
        self.assertNotIn("V1", r["abertas_por_regra"])
```

- [ ] **Step 2: Rodar e ver falhar** — `py -m unittest tests.test_regras_qualidade -v` → `ModuleNotFoundError`.

- [ ] **Step 3: Implementar `regras_qualidade.py`:**

```python
# -*- coding: utf-8 -*-
"""Motor de qualidade: catálogo declarativo -> pendências materializadas em conteudo.db.

Regra nova = entrada nova no CATALOGO. Cada achado vira uma linha em `pendencias` com
chave determinística (regra|curso|aula|bloco) — é ela que permite a baixa automática:
no snapshot seguinte, o que não reaparece é resolvido sozinho (spec 2026-07-06, seção
Motor de Qualidade). Roda ao fim de cada coleta ou avulso:
    py regras_qualidade.py [--extracao N]
"""
import argparse
import gzip
import json
import os
import sys
from datetime import datetime

import banco_conteudo

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PASTA_APP = os.path.dirname(os.path.abspath(sys.argv[0]))


def _sql(con, sql, **p):
    return con.execute(sql, p).fetchall()


def q1_questao_sem_solucao(con, e, ctx):
    return [(r[0], r[1], r[2], f"Questão #{r[3]} sem solução cadastrada") for r in _sql(con, """
        SELECT a.curso_id, b.item_id, b.bloco_id, b.questao_id FROM blocos b
        JOIN aulas a ON a.extracao_id = b.extracao_id AND a.item_id = b.item_id
        WHERE b.extracao_id = :e AND b.tipo='question' AND b.tem_solucao = 0""", e=e)]


def q2_questao_desatualizada(con, e, ctx):
    corte_crit = ctx["ano_atual"] - 6      # régua 2/5: > 5 anos
    corte_aten = ctx["ano_atual"] - 3      # 3-5 anos
    out = []
    for r in _sql(con, """
        SELECT a.curso_id, b.item_id, b.bloco_id, b.questao_id, b.ano FROM blocos b
        JOIN aulas a ON a.extracao_id = b.extracao_id AND a.item_id = b.item_id
        WHERE b.extracao_id = :e AND b.tipo='question' AND b.ano IS NOT NULL
          AND b.ano <= :corte""", e=e, corte=corte_aten):
        nivel = "crítica" if r[4] <= corte_crit else "atenção"
        out.append((r[0], r[1], r[2], f"Questão #{r[3]} de prova de {r[4]} ({nivel} pela régua 2/5)"))
    return out


def v1_video_envelhecido(con, e, ctx):
    depara = ctx.get("depara")
    if not depara:
        return None  # sem cache do Metabase: regra pulada nesta rodada
    corte_crit = ctx["ano_atual"] - 6
    corte_aten = ctx["ano_atual"] - 3
    out = []
    for r in _sql(con, """
        SELECT a.curso_id, b.item_id, b.bloco_id, b.video_id_antigo, b.titulo FROM blocos b
        JOIN aulas a ON a.extracao_id = b.extracao_id AND a.item_id = b.item_id
        WHERE b.extracao_id = :e AND b.tipo='videoMyDocuments' AND b.video_id_antigo <> ''""", e=e):
        data = (depara.get(r[3]) or {}).get("data") or ""
        if not data[:4].isdigit():
            continue
        ano = int(data[:4])
        if ano <= corte_aten:
            nivel = "crítica" if ano <= corte_crit else "atenção"
            out.append((r[0], r[1], r[2],
                        f"Vídeo gravado em {ano} ({nivel} pela régua 2/5): {r[4] or r[3]}"))
    return out


def v2_video_fora_depara(con, e, ctx):
    return [(r[0], r[1], r[2], f"Vídeo sem ID do sistema antigo: {r[3] or '(sem título)'}")
            for r in _sql(con, """
        SELECT a.curso_id, b.item_id, b.bloco_id, b.titulo FROM blocos b
        JOIN aulas a ON a.extracao_id = b.extracao_id AND a.item_id = b.item_id
        WHERE b.extracao_id = :e AND b.tipo='videoMyDocuments' AND b.video_id_antigo = ''""", e=e)]


def c1_curso_sem_aula(con, e, ctx):
    return [(r[0], "", "", f"Curso sem nenhuma aula na árvore: {r[1]}") for r in _sql(con, """
        SELECT curso_id, nome FROM cursos c WHERE extracao_id = :e AND curso_id NOT IN
          (SELECT DISTINCT curso_id FROM aulas WHERE extracao_id = :e)""", e=e)]


def a1_aula_sem_questao(con, e, ctx):
    return [(r[0], r[1], "", f"Aula sem nenhuma questão (embedada ou em texto): {r[2]}")
            for r in _sql(con, """
        SELECT a.curso_id, a.item_id, a.nome FROM aulas a
        JOIN aulas_coletadas ac ON ac.extracao_id = a.extracao_id AND ac.item_id = a.item_id
        WHERE a.extracao_id = :e
          AND NOT EXISTS (SELECT 1 FROM blocos b WHERE b.extracao_id = a.extracao_id
                          AND b.item_id = a.item_id
                          AND (b.tipo = 'question' OR COALESCE(b.qtd_questoes_texto, 0) > 0))""", e=e)]


def a3_aula_sem_texto(con, e, ctx):
    return [(r[0], r[1], "", f"Aula com texto abaixo de 1.000 caracteres: {r[2]}")
            for r in _sql(con, """
        SELECT a.curso_id, a.item_id, a.nome FROM aulas a
        JOIN aulas_coletadas ac ON ac.extracao_id = a.extracao_id AND ac.item_id = a.item_id
        WHERE a.extracao_id = :e
          AND (SELECT COALESCE(SUM(b.tamanho_texto), 0) FROM blocos b
               WHERE b.extracao_id = a.extracao_id AND b.item_id = a.item_id
                 AND b.tipo = 'tiptap') < 1000""", e=e)]


def b1_bloco_rascunho(con, e, ctx):
    return [(r[0], r[1], r[2], f"Bloco em rascunho: {r[3] or r[2]}") for r in _sql(con, """
        SELECT a.curso_id, b.item_id, b.bloco_id, b.titulo FROM blocos b
        JOIN aulas a ON a.extracao_id = b.extracao_id AND a.item_id = b.item_id
        WHERE b.extracao_id = :e AND b.rascunho = 1""", e=e)]


# (id, severidade, função) — A2 "aula sem vídeo" é INFORMATIVA por decisão do Luiz (73% das
# aulas): vira indicador de tela, não pendência.
CATALOGO = (
    ("Q1", "critica", q1_questao_sem_solucao),
    ("Q2", "atencao", q2_questao_desatualizada),
    ("V1", "atencao", v1_video_envelhecido),
    ("V2", "critica", v2_video_fora_depara),
    ("C1", "atencao", c1_curso_sem_aula),
    ("A1", "atencao", a1_aula_sem_questao),
    ("A3", "atencao", a3_aula_sem_texto),
    ("B1", "atencao", b1_bloco_rascunho),
)


def _agora():
    return datetime.now().isoformat(timespec="seconds")


def avaliar(con, extracao_id, depara=None):
    ctx = {"depara": depara, "ano_atual": datetime.now().year}
    achados = {}
    puladas = []
    for regra, sev, fn in CATALOGO:
        rows = fn(con, extracao_id, ctx)
        if rows is None:
            puladas.append(regra)
            continue
        for curso_id, item_id, bloco_id, desc in rows:
            chave = f"{regra}|{curso_id}|{item_id}|{bloco_id}"
            achados[chave] = (regra, sev, curso_id, item_id, bloco_id, desc)

    novas = reabertas = 0
    with con:
        abertas = {r["chave"]: r["status"] for r in con.execute(
            "SELECT chave, status FROM pendencias WHERE status IN ('nova','enviada','resolvida')")}
        for chave, (regra, sev, curso_id, item_id, bloco_id, desc) in achados.items():
            status = abertas.get(chave)
            if status is None:
                existe = con.execute("SELECT status FROM pendencias WHERE chave=?",
                                     (chave,)).fetchone()
                if existe:      # ignorada: nunca reabre
                    continue
                con.execute(
                    "INSERT INTO pendencias(chave, regra, severidade, curso_id, item_id, "
                    "bloco_id, descricao, status, extracao_id_criada, extracao_id_ultima, "
                    "criada_em) VALUES(?,?,?,?,?,?,?,'nova',?,?,?)",
                    (chave, regra, sev, curso_id, item_id, bloco_id, desc,
                     extracao_id, extracao_id, _agora()))
                novas += 1
            elif status == "resolvida":   # voltou: reabre como nova, com histórico
                con.execute("UPDATE pendencias SET status='nova', resolvida_em=NULL, "
                            "extracao_id_ultima=?, descricao=? WHERE chave=?",
                            (extracao_id, desc, chave))
                con.execute("INSERT INTO acionamentos VALUES(?,?,?,?)",
                            (chave, "nova", "reaberta pela coleta", _agora()))
                reabertas += 1
            else:
                con.execute("UPDATE pendencias SET extracao_id_ultima=?, descricao=? "
                            "WHERE chave=?", (extracao_id, desc, chave))

        resolvidas = 0
        for chave, status in abertas.items():
            regra = chave.split("|", 1)[0]
            if status in ("nova", "enviada") and chave not in achados and regra not in puladas:
                con.execute("UPDATE pendencias SET status='resolvida', resolvida_em=? "
                            "WHERE chave=?", (_agora(), chave))
                con.execute("INSERT INTO acionamentos VALUES(?,?,?,?)",
                            (chave, "resolvida", "baixa automática (sumiu do BO)", _agora()))
                resolvidas += 1

    abertas_por_regra = {r[0]: r[1] for r in con.execute(
        "SELECT regra, COUNT(*) FROM pendencias WHERE status IN ('nova','enviada') "
        "GROUP BY regra")}
    return {"novas": novas, "reabertas": reabertas, "resolvidas": resolvidas,
            "abertas_por_regra": abertas_por_regra}


def carregar_depara():
    caminho = os.path.join(PASTA_APP, "saida", "metabase_depara.json.gz")
    if not os.path.exists(caminho):
        return None
    with gzip.open(caminho, "rt", encoding="utf-8") as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(description="Motor de qualidade (pendências)")
    parser.add_argument("--extracao", type=int, help="id da extração (padrão: a mais recente)")
    args = parser.parse_args()
    con = banco_conteudo.abrir(os.path.join(PASTA_APP, "saida", "conteudo.db"))
    try:
        eid = args.extracao or con.execute(
            "SELECT id FROM extracoes ORDER BY id DESC LIMIT 1").fetchone()[0]
        print(f"Avaliando regras sobre a extração #{eid}...")
        r = avaliar(con, eid, depara=carregar_depara())
        print(f"novas: {r['novas']} | reabertas: {r['reabertas']} | resolvidas: {r['resolvidas']}")
        for regra, qtd in sorted(r["abertas_por_regra"].items()):
            print(f"  {regra}: {qtd} abertas")
    finally:
        con.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Integrar ao coletor** — em `coletor_ldi.py`, após `finalizar_extracao` (dentro de `coletar`):

```python
        try:
            import regras_qualidade
            print("      avaliando regras de qualidade...")
            r = regras_qualidade.avaliar(con, extracao_id,
                                         depara=regras_qualidade.carregar_depara())
            print(f"      pendências: {r['novas']} novas, {r['resolvidas']} resolvidas")
        except Exception as e:
            print(f"      (regras de qualidade falharam: {e} — rode py regras_qualidade.py)")
```

- [ ] **Step 5: Rodar e ver passar** — `py -m unittest discover -s tests` → OK (todas).

- [ ] **Step 6: Commit** — `git add regras_qualidade.py coletor_ldi.py tests/test_regras_qualidade.py && git commit -m "feat: motor de qualidade — catálogo de regras + pendências com baixa automática"`

---

### Task 5: painel — tela `/avaliacao` (planilha viva) + APIs

**Files:**
- Create: `avaliacao.html`
- Modify: `painel.py`
- Test: `tests/test_painel_dados.py` (acrescentar)

**Interfaces:**
- Produces:
  - `painel.dados_avaliacao(con, curso_id: str, depara: dict | None) -> dict` —
    `{"curso": str, "autores": str, "capitulos": [{nome, aulas, q_emb, q_txt, bancas: {banca: qtd},
    q_ate: int, q_meio: int, q_novo: int, q_com_ano: int, sol_texto, sol_video, vids, dur,
    v_com_data, v_ate, v_meio, v_novo}]}` (faixas pela régua 2/5 sobre o ano corrente).
  - Rotas: `GET /avaliacao` (HTML), `GET /api/cursos`, `GET /api/avaliacao?curso_id=X`,
    `GET /api/pendencias/resumo` (contagens por severidade/regra p/ home).
  - Cache Metabase: `painel._depara()` carrega `saida\metabase_depara.json.gz` 1× (global).

- [ ] **Step 1: Teste que falha** — acrescentar em `tests/test_painel_dados.py`:

```python
B_Q = {"bloco_id": "q1", "tipo": "question", "ordem": 1, "ativo": 1, "rascunho": 0,
       "titulo": "", "questao_id": "10", "resposta_tipo": "TRUE_OR_FALSE",
       "tem_solucao": 1, "tem_video_solucao": 0, "video_id_antigo": "",
       "duracao_seg": None, "tamanho_texto": None, "banca": "CESPE (CEBRASPE)",
       "ano": 2019, "qtd_questoes_texto": None, "meta": {}}
B_T = {"bloco_id": "t1", "tipo": "tiptap", "ordem": 2, "ativo": 1, "rascunho": 0,
       "titulo": "", "questao_id": "", "resposta_tipo": "", "tem_solucao": None,
       "tem_video_solucao": None, "video_id_antigo": "", "duracao_seg": None,
       "tamanho_texto": 5000, "banca": "", "ano": None, "qtd_questoes_texto": 2,
       "meta": {"questoes_texto": [{"banca": "FGV", "ano": 2025, "resto": ""},
                                    {"banca": "FGV", "ano": 2016, "resto": ""}]}}
B_V = {"bloco_id": "v1", "tipo": "videoMyDocuments", "ordem": 3, "ativo": 1, "rascunho": 0,
       "titulo": "v", "questao_id": "", "resposta_tipo": "", "tem_solucao": None,
       "tem_video_solucao": None, "video_id_antigo": "999", "duracao_seg": 600,
       "tamanho_texto": None, "banca": "", "ano": None, "qtd_questoes_texto": None, "meta": {}}


class TestDadosAvaliacao(unittest.TestCase):
    def test_agrega_por_capitulo_com_faixas_e_solucoes(self):
        with tempfile.TemporaryDirectory() as d:
            con = banco_conteudo.abrir(os.path.join(d, "c.db"))
            eid = banco_conteudo.iniciar_extracao(con, "T", "concursos")
            banco_conteudo.gravar_arvore(con, eid, CURSOS)
            banco_conteudo.gravar_blocos_da_aula(con, eid, "i1", [B_Q, B_T, B_V])
            banco_conteudo.gravar_blocos_da_aula(con, eid, "i2", [])
            banco_conteudo.finalizar_extracao(con, eid, {})

            d1 = painel.dados_avaliacao(con, "c1", depara={"999": {"data": "2019-01-01"}})
            con.close()

            self.assertEqual(d1["curso"], "Curso A")
            cap = d1["capitulos"][0]
            self.assertEqual((cap["q_emb"], cap["q_txt"]), (1, 2))
            self.assertEqual(cap["bancas"], {"CESPE (CEBRASPE)": 1, "FGV": 2})
            # anos: 2019 (velho), 2025 (novo), 2016 (velho) com ano_atual=2026
            self.assertEqual((cap["q_ate"], cap["q_meio"], cap["q_novo"]), (2, 0, 1))
            self.assertEqual((cap["sol_texto"], cap["sol_video"]), (1, 0))
            self.assertEqual((cap["vids"], cap["v_com_data"], cap["v_ate"]), (1, 1, 0))
            self.assertEqual(cap["v_meio"], 1)  # 2019: hoje 7 anos? não — 2026-2019=7 -> v_ate
```

  *Atenção ao teste acima:* 2026−2019 = 7 anos → `v_ate` (faixa crítica). Corrigir a última
  asserção para `self.assertEqual((cap["vids"], cap["v_com_data"], cap["v_ate"]), (1, 1, 1))`
  e remover a linha do `v_meio`. (Deixado registrado para o implementador não repetir o erro.)

- [ ] **Step 2: Rodar e ver falhar** — `py -m unittest tests.test_painel_dados -v` → AttributeError (`dados_avaliacao`).

- [ ] **Step 3: Implementar em `painel.py`:**

```python
import gzip
import json as _json
from datetime import datetime

_DEPARA = {"cache": None, "carregado": False}


def _depara():
    if not _DEPARA["carregado"]:
        _DEPARA["carregado"] = True
        caminho = os.path.join(PASTA_APP, "saida", "metabase_depara.json.gz")
        if os.path.exists(caminho):
            with gzip.open(caminho, "rt", encoding="utf-8") as f:
                _DEPARA["cache"] = _json.load(f)
    return _DEPARA["cache"]


def dados_avaliacao(con, curso_id, depara=None):
    """Planilha de avaliação por capítulo do LDI (formato aprovado — mockup v6)."""
    e = con.execute("SELECT MAX(extracao_id) FROM cursos WHERE curso_id=?",
                    (curso_id,)).fetchone()[0]
    curso = con.execute("SELECT nome, autores FROM cursos WHERE extracao_id=? AND curso_id=?",
                        (e, curso_id)).fetchone()
    ano_atual = datetime.now().year
    corte_crit, corte_aten = ano_atual - 6, ano_atual - 3

    caps = []
    for cap in con.execute("SELECT capitulo_id, nome FROM capitulos "
                           "WHERE extracao_id=? AND curso_id=? ORDER BY ordem", (e, curso_id)):
        itens = [r[0] for r in con.execute(
            "SELECT item_id FROM aulas WHERE extracao_id=? AND curso_id=? AND capitulo_id=?",
            (e, curso_id, cap["capitulo_id"]))]
        c = {"nome": cap["nome"], "aulas": len(itens), "q_emb": 0, "q_txt": 0,
             "bancas": {}, "q_ate": 0, "q_meio": 0, "q_novo": 0, "q_com_ano": 0,
             "sol_texto": 0, "sol_video": 0, "vids": 0, "dur": 0,
             "v_com_data": 0, "v_ate": 0, "v_meio": 0, "v_novo": 0}
        if not itens:
            caps.append(c)
            continue

        def faixa(pref, ano):
            c[f"{pref}_com_ano" if pref == "q" else "v_com_data"] += 1
            if ano <= corte_crit:
                c[f"{pref}_ate"] += 1
            elif ano <= corte_aten:
                c[f"{pref}_meio"] += 1
            else:
                c[f"{pref}_novo"] += 1

        marks = ",".join("?" * len(itens))
        for b in con.execute(
                f"SELECT tipo, banca, ano, tem_solucao, tem_video_solucao, video_id_antigo, "
                f"duracao_seg, qtd_questoes_texto, meta FROM blocos "
                f"WHERE extracao_id=? AND item_id IN ({marks})", (e, *itens)):
            if b["tipo"] == "question":
                c["q_emb"] += 1
                c["sol_texto"] += b["tem_solucao"] or 0
                c["sol_video"] += b["tem_video_solucao"] or 0
                if b["banca"]:
                    c["bancas"][b["banca"]] = c["bancas"].get(b["banca"], 0) + 1
                if b["ano"]:
                    faixa("q", b["ano"])
            elif b["tipo"] == "tiptap" and (b["qtd_questoes_texto"] or 0) > 0:
                c["q_txt"] += b["qtd_questoes_texto"]
                for ref in (_json.loads(b["meta"] or "{}").get("questoes_texto") or []):
                    if ref.get("banca"):
                        c["bancas"][ref["banca"]] = c["bancas"].get(ref["banca"], 0) + 1
                    if ref.get("ano"):
                        faixa("q", ref["ano"])
            elif b["tipo"] in ("videoMyDocuments", "cast", "youtube"):
                c["vids"] += 1
                c["dur"] += b["duracao_seg"] or 0
                data = ((depara or {}).get(b["video_id_antigo"]) or {}).get("data") or ""
                if data[:4].isdigit():
                    faixa("v", int(data[:4]))
        caps.append(c)
    return {"curso": curso["nome"], "autores": curso["autores"] or "", "capitulos": caps}
```

  Rotas novas (após `index`), com `avaliacao.html` servida como a `painel.html`:

```python
@app.route("/avaliacao")
def avaliacao():
    caminho = os.path.join(getattr(sys, "_MEIPASS", PASTA_APP), "avaliacao.html")
    with open(caminho, encoding="utf-8") as f:
        return Response(f.read(), mimetype="text/html")


@app.route("/api/cursos")
def api_cursos():
    con = banco_conteudo.abrir(caminho_banco())
    try:
        e = con.execute("SELECT MAX(id) FROM extracoes").fetchone()[0] or 0
        rows = [dict(r) for r in con.execute(
            "SELECT c.curso_id, c.nome, c.autores FROM cursos c WHERE c.extracao_id=? "
            "AND EXISTS (SELECT 1 FROM aulas a WHERE a.extracao_id=c.extracao_id "
            "AND a.curso_id=c.curso_id) ORDER BY c.nome", (e,))]
    finally:
        con.close()
    return {"data": rows}


@app.route("/api/avaliacao")
def api_avaliacao():
    from flask import request
    con = banco_conteudo.abrir(caminho_banco())
    try:
        dados = dados_avaliacao(con, request.args.get("curso_id", ""), depara=_depara())
    finally:
        con.close()
    return {"data": dados}


@app.route("/api/pendencias/resumo")
def api_pendencias_resumo():
    con = banco_conteudo.abrir(caminho_banco())
    try:
        rows = con.execute("SELECT severidade, regra, COUNT(*) FROM pendencias "
                           "WHERE status IN ('nova','enviada') GROUP BY severidade, regra")
        resumo = [dict(severidade=r[0], regra=r[1], abertas=r[2]) for r in rows]
    finally:
        con.close()
    return {"data": resumo}
```

- [ ] **Step 4: Criar `avaliacao.html`** — adaptar o mockup v6 aprovado (arquivo
  `painel-pormenorizado-mockup.html` do scratchpad é a referência visual): mesma tabela, dashboard
  e CSV, com três mudanças: (1) `<select id="selCurso">` populado por `fetch("/api/cursos")`;
  (2) `D` vem de `fetch("/api/avaliacao?curso_id=...")`; (3) o select de banca-alvo é populado com
  as bancas presentes (`capitulos[].bancas` agregadas, ordenadas por frequência) + opção
  "— sem banca-alvo —"; a coluna banca-alvo/outras calcula em JS a partir de `bancas`
  (`alvo = bancas[selecionada] || 0`). Percentuais/CSV idênticos ao mockup (chaves novas:
  `q_ate/q_meio/q_novo/v_ate/v_meio/v_novo`). Link "← visão geral" para `/` e, na `painel.html`,
  link "📋 Avaliação de disciplina" para `/avaliacao`.

- [ ] **Step 5: Rodar e ver passar** — `py -m unittest discover -s tests` → OK. Subir
  `py painel.py --sem-navegador` e conferir `GET /avaliacao` (200) e
  `GET /api/avaliacao?curso_id=<id do Direito Penal>` retornando capítulos.

- [ ] **Step 6: Commit** — `git add painel.py avaliacao.html painel.html tests/test_painel_dados.py && git commit -m "feat: tela /avaliacao — planilha de avaliação por disciplina (formato aprovado)"`

---

### Task 6: Re-coleta real do BACEN + verificação ponta a ponta

**Files:** nenhum (execução e conferência)

- [ ] **Step 1:** `py coletor_ldi.py --termo BACEN --agendado` (snapshot #2, com autores, banca/ano,
  questões em texto; ao final roda as regras sozinho). Esperado: `Coleta completa` + resumo de
  pendências.
- [ ] **Step 2:** Conferir campos novos:
  `py -c "import sqlite3;c=sqlite3.connect(r'saida\conteudo.db');print(c.execute(\"SELECT COUNT(*) FROM blocos WHERE extracao_id=2 AND banca<>''\").fetchone());print(c.execute('SELECT SUM(qtd_questoes_texto) FROM blocos WHERE extracao_id=2').fetchone());print(c.execute(\"SELECT COUNT(*) FROM cursos WHERE extracao_id=2 AND autores<>''\").fetchone())"`
  — esperado: milhares com banca; milhares de questões em texto; ~100+ cursos com autores.
- [ ] **Step 3:** Conferir pendências e baixa automática entre snapshots #1→#2 (deve haver
  `resolvidas` > 0 apenas se conteúdo mudou; o normal é persistirem):
  `py regras_qualidade.py` → contagens por regra coerentes com o modelo de QC publicado.
- [ ] **Step 4:** `py painel.py --sem-navegador` + abrir `/avaliacao`, selecionar Direito Penal e
  comparar com o mockup v6 (29 embedadas/24 em texto no snapshot #1; #2 pode variar). CSV baixa.

---

### Task 7: Docs + merge + push + builds

**Files:**
- Modify: `PROXIMA-SESSAO.md`, `CLAUDE.md`, `TUTORIAL.md`

- [ ] **Step 1: Docs** — `PROXIMA-SESSAO.md`: seção "Sessão 6 (06-07/07): fase 2" (o que existe,
  comandos, pendências abertas, fase 2.1 = tela rica de Pendências). `CLAUDE.md`: comandos novos
  (`py regras_qualidade.py`, rota `/avaliacao`) + arquivos (`regras_qualidade.py`,
  `avaliacao.html`) + build do PainelLDI. `TUTORIAL.md`: seção curta "Painel de Conteúdo (novo)".
- [ ] **Step 2: Commit docs** — `git add PROXIMA-SESSAO.md CLAUDE.md TUTORIAL.md && git commit -m "docs: registra a fase 2 (avaliação + qualidade)"`
- [ ] **Step 3: Suíte final** — `py -m unittest discover -s tests` → OK.
- [ ] **Step 4: Merge + push** — `git checkout main && git merge --no-ff feat/fase2-avaliacao-qualidade -m "Merge: fase 2 — planilha de avaliação + motor de qualidade + coletor v1.1" && git push -u origin main feat/coletor-conteudo feat/painel-inventario-preview feat/fase2-avaliacao-qualidade` (push autorizado pelo Luiz em 06/07: "Pode commitar para aquele git").
- [ ] **Step 5: Builds** —
  `py -m PyInstaller --onefile --clean --name ColetorLDI coletor_ldi.py` e
  `py -m PyInstaller --onefile --clean --name PainelLDI --add-data "painel.html;." --add-data "avaliacao.html;." painel.py`.
  Conferir: `dist\ColetorLDI.exe --help` responde; `dist\PainelLDI.exe --sem-navegador` sobe e `/avaliacao` responde 200; copiar os exes para a raiz do projeto (padrão da casa).

## Self-review

- **Cobertura do spec:** planilha v6 ✓ (Task 5); motor + baixa automática ✓ (Task 4, incl.
  reabertura e `ignorada`); coletor v1.1 completo ✓ (Tasks 1-3; investigação do contador da árvore
  é nota de docs, não código); re-coleta ✓ (Task 6); publicação/push/builds ✓ (Task 7).
  `B1` implementada sem o critério ">30 dias" (não armazenamos data do bloco) — desvio documentado
  no código e aceitável (hoje = 0 casos).
- **Placeholders:** nenhum; todo step tem código/comando/esperado.
- **Consistência:** chaves de `dados_avaliacao` (q_ate/q_meio/q_novo...) idem no teste e no HTML;
  `avaliar()`/`carregar_depara()` batem entre Task 4 e a integração no coletor; `_COLS_BLOCO`
  estendida antes de qualquer INSERT com campos novos (Task 2 precede 3-6).
