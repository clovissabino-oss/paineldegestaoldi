# Coletor de Conteúdo + Base SQLite — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Coletor que varre TODOS os blocos (questões, textos, PDFs, vídeos...) dos cursos de um concurso no BO e grava snapshots de metadados em `saida\conteudo.db` (SQLite), retomável e sem tocar no fluxo de vídeos atual.

**Architecture:** 3 arquivos novos — `parse_blocos.py` (funções puras: payload da API → metadados), `banco_conteudo.py` (schema + escrita/leitura SQLite) e `coletor_ldi.py` (CLI que orquestra, importando `extrator_ldi` para sessão/cookie/config, como o `visualizador.py` já faz). Cada aula gravada é uma transação → retomada segura via `--continuar`.

**Tech Stack:** Python 3.12, stdlib (`sqlite3`, `unittest`, `argparse`, `concurrent.futures`) + `requests` (já usado). Sem dependência nova.

## Global Constraints

- Idioma pt-BR em código, mensagens, docs (convenção do projeto).
- `extrator_ldi.py` **não muda em nada**.
- Somente GETs à API; banco em `saida\conteudo.db`, modo WAL.
- Datas locais, nunca UTC (`datetime.now().isoformat(timespec="seconds")`).
- ID antigo de vídeo SEMPRE via `extrator_ldi.id_sistema_antigo()` (armadilha do ponto de milhar).
- Rodar testes: `py -m unittest discover -s tests -v` (na raiz do projeto).
- Spec: `docs/superpowers/specs/2026-07-05-painel-conteudo-fundacao-design.md`.

---

### Task 1: `parse_blocos.py` — parse puro de blocos e contagens

**Files:**
- Create: `parse_blocos.py`
- Test: `tests/test_parse_blocos.py`

**Interfaces:**
- Consumes: `extrator_ldi.id_sistema_antigo(res)`, `extrator_ldi.segundos(dur)`, `extrator_ldi._RX_UUID`, `extrator_ldi.TIPOS_VIDEO`.
- Produces (Tasks 2 e 3 dependem):
  - `contagens_da_aula(item: dict) -> dict` — chaves `qtd_videos, qtd_questoes, qtd_textos, qtd_pdfs, qtd_casts, qtd_outros` (ints).
  - `meta_do_bloco(bloco: dict) -> dict` — chaves fixas: `bloco_id, tipo, ordem, ativo, rascunho, titulo, questao_id, resposta_tipo, tem_solucao, tem_video_solucao, video_id_antigo, duracao_seg, tamanho_texto, meta` (`meta` é dict; demais são str/int/None).
  - `autores_do_curso(curso: dict) -> str`.

- [ ] **Step 1: Escrever os testes que falham** — `tests/test_parse_blocos.py` (payloads reais capturados da sondagem de 05/07/2026, enxugados):

```python
# -*- coding: utf-8 -*-
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import parse_blocos

BLOCO_QUESTION = {
    "id": "83dcc1f5-9541-4a41-85a5-5658e06b2c99", "type": "question",
    "order_index": 8, "is_active": True, "is_draft": False,
    "data": {
        "value": "58532862",
        "resolved": {
            "id": "58532862", "slug": "Com-escrituraca1991e48272",
            "answer_type": "TRUE_OR_FALSE",
            "alternatives": [{"id": "a"}, {"id": "b"}],
            "topics": [{"name": "Escrituração"}],
            "exams": [{"name": "CESPE 2020"}],
            "solution": {"brief": "Certo, pois...", "complete": "<p>...</p>"},
            "has_video_solution": False, "solution_video_url": "",
        },
    },
}

BLOCO_VIDEO = {
    "id": "b1", "type": "videoMyDocuments", "order_index": 2,
    "is_active": True, "is_draft": False,
    "data": {"title": "Aula 01", "resolved": {
        "id": "v-uuid", "name": "Contabilidade - 248487",
        "original_name": "videosintra248.487.mp4",
        "intra_video_id": "", "video_duration": "01:06:53.80",
        "file_size": 123456, "created_at": "2024-10-11T18:36:34Z",
    }},
}

BLOCO_TIPTAP = {
    "id": "37b868af", "type": "tiptap", "order_index": 7,
    "is_active": True, "is_draft": False, "content_length": 1830,
    "data": {"type": "doc", "block_content_length": 0, "content": []},
}

BLOCO_PDF = {
    "id": "p1", "type": "pdfMyDocuments", "order_index": 3,
    "is_active": True, "is_draft": True,
    "data": {"title": "Baixar Slide - Parte 01",
             "value": "a87dff46-1e7d-4193-b19f-1257f52a539a",
             "resolved": {"id": "a87dff46", "created_at": "2024-10-11T18:36:34Z"}},
}


class TestContagens(unittest.TestCase):
    def test_soma_por_familia_e_outros(self):
        item = {"block_type_count": {"videoMyDocuments": 2, "youtube": 1,
                                     "cast": 3, "question": 10, "tiptap": 5,
                                     "pdfMyDocuments": 1, "notebook": 1}}
        c = parse_blocos.contagens_da_aula(item)
        self.assertEqual(c, {"qtd_videos": 3, "qtd_questoes": 10, "qtd_textos": 5,
                             "qtd_pdfs": 1, "qtd_casts": 3, "qtd_outros": 1})

    def test_mescla_simple_e_normal_e_vazio(self):
        item = {"simple_block_type_count": {"question": 4},
                "block_type_count": {"question": 7}}
        self.assertEqual(parse_blocos.contagens_da_aula(item)["qtd_questoes"], 7)
        self.assertEqual(parse_blocos.contagens_da_aula({})["qtd_videos"], 0)


class TestMetaDoBloco(unittest.TestCase):
    def test_question(self):
        m = parse_blocos.meta_do_bloco(BLOCO_QUESTION)
        self.assertEqual(m["tipo"], "question")
        self.assertEqual(m["questao_id"], "58532862")
        self.assertEqual(m["resposta_tipo"], "TRUE_OR_FALSE")
        self.assertEqual(m["tem_solucao"], 1)
        self.assertEqual(m["tem_video_solucao"], 0)
        self.assertEqual(m["meta"]["topicos"], ["Escrituração"])
        self.assertEqual(m["meta"]["provas"], ["CESPE 2020"])
        self.assertEqual(m["meta"]["qtd_alternativas"], 2)

    def test_video_id_antigo_com_ponto_de_milhar(self):
        m = parse_blocos.meta_do_bloco(BLOCO_VIDEO)
        self.assertEqual(m["video_id_antigo"], "248487")   # armadilha resolvida
        self.assertEqual(m["duracao_seg"], 4014)
        self.assertEqual(m["titulo"], "Aula 01")

    def test_tiptap_tamanho(self):
        m = parse_blocos.meta_do_bloco(BLOCO_TIPTAP)
        self.assertEqual(m["tamanho_texto"], 1830)

    def test_pdf_e_rascunho(self):
        m = parse_blocos.meta_do_bloco(BLOCO_PDF)
        self.assertEqual(m["rascunho"], 1)
        self.assertEqual(m["titulo"], "Baixar Slide - Parte 01")
        self.assertEqual(m["meta"]["media_id"], "a87dff46")

    def test_tipo_desconhecido_nao_estoura(self):
        m = parse_blocos.meta_do_bloco({"id": "x", "type": "notebook"})
        self.assertEqual(m["tipo"], "notebook")
        self.assertEqual(m["meta"], {})


class TestAutores(unittest.TestCase):
    def test_prefere_authors_name_e_filtra_uuid(self):
        self.assertEqual(parse_blocos.autores_do_curso(
            {"authors_name": "Fulano | Beltrano"}), "Fulano | Beltrano")
        self.assertEqual(parse_blocos.autores_do_curso(
            {"authors": [{"name": "Fulano"},
                         {"name": "83dcc1f5-9541-4a41-85a5-5658e06b2c99"}]}), "Fulano")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar e ver falhar** — `py -m unittest tests.test_parse_blocos -v` → `ModuleNotFoundError: No module named 'parse_blocos'`.

- [ ] **Step 3: Implementar `parse_blocos.py`:**

```python
# -*- coding: utf-8 -*-
"""Funções puras: payload da API do BO -> metadados p/ o banco de conteúdo.

É a camada com maior risco quando a API mudar — por isso é pura e testada
com payloads reais (tests/test_parse_blocos.py).
"""
import extrator_ldi

# famílias de contagem (chaves do block_type_count da árvore)
_VIDEOS = ("videoMyDocuments", "youtube")
_MAPA = {"question": "qtd_questoes", "tiptap": "qtd_textos",
         "pdfMyDocuments": "qtd_pdfs", "cast": "qtd_casts"}


def contagens_da_aula(item):
    btc = {**(item.get("simple_block_type_count") or {}),
           **(item.get("block_type_count") or {})}
    c = {"qtd_videos": 0, "qtd_questoes": 0, "qtd_textos": 0,
         "qtd_pdfs": 0, "qtd_casts": 0, "qtd_outros": 0}
    for tipo, n in btc.items():
        n = n or 0
        if tipo in _VIDEOS:
            c["qtd_videos"] += n
        elif tipo in _MAPA:
            c[_MAPA[tipo]] += n
        else:
            c["qtd_outros"] += n
    return c


def autores_do_curso(curso):
    if curso.get("authors_name"):
        return str(curso["authors_name"])
    nomes = []
    for a in (curso.get("authors") or []):
        n = a.get("name") if isinstance(a, dict) else str(a)
        if n and not extrator_ldi._RX_UUID.match(str(n)):
            nomes.append(str(n))
    return " | ".join(nomes)


def meta_do_bloco(bloco):
    d = bloco.get("data") or {}
    res = d.get("resolved") or ((bloco.get("simple_data") or {}).get("resolved") or {})
    tipo = bloco.get("type") or ""
    linha = {
        "bloco_id": bloco.get("id", ""),
        "tipo": tipo,
        "ordem": bloco.get("order_index"),
        "ativo": 1 if bloco.get("is_active") else 0,
        "rascunho": 1 if bloco.get("is_draft") else 0,
        "titulo": d.get("title") or res.get("name") or res.get("title") or "",
        "questao_id": "", "resposta_tipo": "",
        "tem_solucao": None, "tem_video_solucao": None,
        "video_id_antigo": "", "duracao_seg": None, "tamanho_texto": None,
        "meta": {},
    }
    if tipo == "question":
        sol = res.get("solution") or {}
        linha["questao_id"] = str(res.get("id") or d.get("value") or "")
        linha["resposta_tipo"] = res.get("answer_type", "")
        linha["tem_solucao"] = 1 if (sol.get("brief") or sol.get("complete")) else 0
        linha["tem_video_solucao"] = 1 if res.get("has_video_solution") else 0
        linha["meta"] = {
            "slug": res.get("slug", ""),
            "topicos": [t.get("name") for t in (res.get("topics") or [])
                        if isinstance(t, dict) and t.get("name")],
            "provas": [e.get("name") for e in (res.get("exams") or [])
                       if isinstance(e, dict) and e.get("name")],
            "qtd_alternativas": len(res.get("alternatives") or []),
        }
    elif tipo in extrator_ldi.TIPOS_VIDEO:
        dur = res.get("video_duration") or res.get("duration") or ""
        seg = extrator_ldi.segundos(dur)
        linha["video_id_antigo"] = extrator_ldi.id_sistema_antigo(res)
        linha["duracao_seg"] = seg if seg != "" else None
        linha["meta"] = {
            "video_id": res.get("id", ""),
            "nome_original": res.get("original_name", ""),
            "intra_video_id": res.get("intra_video_id", ""),
            "tamanho_bytes": res.get("file_size", ""),
            "criado_em": res.get("created_at", ""),
        }
    elif tipo == "tiptap":
        linha["tamanho_texto"] = (bloco.get("content_length")
                                  or d.get("block_content_length") or 0)
    elif tipo == "pdfMyDocuments":
        linha["meta"] = {"media_id": res.get("id", "") or d.get("value", ""),
                         "criado_em": res.get("created_at", "")}
    return linha
```

- [ ] **Step 4: Rodar e ver passar** — `py -m unittest tests.test_parse_blocos -v` → OK (9 testes).

- [ ] **Step 5: Commit** — `git add parse_blocos.py tests/test_parse_blocos.py && git commit -m "feat: parse puro de blocos do BO (question/tiptap/pdf/video) + contagens por aula"`

---

### Task 2: `banco_conteudo.py` — schema e escrita/leitura SQLite

**Files:**
- Create: `banco_conteudo.py`
- Test: `tests/test_banco_conteudo.py`

**Interfaces:**
- Consumes: `parse_blocos.contagens_da_aula`, `parse_blocos.autores_do_curso`.
- Produces (Task 3 depende — assinaturas exatas):
  - `abrir(caminho: str) -> sqlite3.Connection` — cria pasta/schema se preciso, WAL, `row_factory=sqlite3.Row`.
  - `iniciar_extracao(con, termo: str, vertical: str) -> int` (id novo, status `em_andamento`).
  - `gravar_arvore(con, extracao_id: int, cursos: list[dict]) -> tuple[int, int]` — grava cursos/capítulos/aulas (com contagens); retorna `(n_cursos, n_aulas_unicas)`.
  - `aulas_pendentes(con, extracao_id: int) -> list[str]` — item_ids únicos ainda sem registro em `aulas_coletadas`.
  - `gravar_blocos_da_aula(con, extracao_id: int, item_id: str, blocos: list[dict]) -> None` — transação única; registra em `aulas_coletadas` mesmo com 0 blocos.
  - `extracao_em_andamento(con, termo: str) -> sqlite3.Row | None` — a mais recente.
  - `finalizar_extracao(con, extracao_id: int, erros: dict[str, str]) -> str` — grava totais + `erros_json`; retorna status (`parcial` se `erros` ou se restam pendentes, senão `completa`).

- [ ] **Step 1: Escrever os testes que falham** — `tests/test_banco_conteudo.py`:

```python
# -*- coding: utf-8 -*-
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import banco_conteudo

CURSOS = [{
    "id": "c1", "name": "Curso A", "published": True,
    "created_at": "2024-01-01", "authors_name": "Prof X",
    "content_tree_cache": [{
        "chapter_id": "cap1", "name": "Cap 1", "order_index": 0,
        "items": [
            {"item_id": "i1", "name": "Aula 1", "path": "1",
             "block_type_count": {"question": 2, "tiptap": 1}},
            {"item_id": "i2", "name": "Aula 2", "path": "2",
             "block_type_count": {"videoMyDocuments": 1}},
        ],
    }],
}, {
    "id": "c2", "name": "Curso B", "published": False,
    "content_tree_cache": [{
        "chapter_id": "cap2", "name": "Cap 1", "order_index": 0,
        "items": [{"item_id": "i1", "name": "Aula 1", "path": "1",
                   "block_type_count": {"question": 2, "tiptap": 1}}],
    }],
}]

B1 = {"bloco_id": "b1", "tipo": "question", "ordem": 1, "ativo": 1, "rascunho": 0,
      "titulo": "", "questao_id": "111", "resposta_tipo": "TRUE_OR_FALSE",
      "tem_solucao": 1, "tem_video_solucao": 0, "video_id_antigo": "",
      "duracao_seg": None, "tamanho_texto": None, "meta": {"topicos": ["T"]}}


class TestBanco(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.con = banco_conteudo.abrir(os.path.join(self.dir.name, "x", "conteudo.db"))

    def tearDown(self):
        self.con.close()
        self.dir.cleanup()

    def _nova(self):
        eid = banco_conteudo.iniciar_extracao(self.con, "BACEN", "concursos")
        banco_conteudo.gravar_arvore(self.con, eid, CURSOS)
        return eid

    def test_arvore_grava_cursos_aulas_e_contagens(self):
        eid = self._nova()
        n = self.con.execute("SELECT COUNT(*) FROM cursos WHERE extracao_id=?", (eid,)).fetchone()[0]
        self.assertEqual(n, 2)
        # aula i1 vinculada a 2 cursos = 2 linhas em aulas, mas 1 pendente
        n = self.con.execute("SELECT COUNT(*) FROM aulas WHERE extracao_id=? AND item_id='i1'", (eid,)).fetchone()[0]
        self.assertEqual(n, 2)
        row = self.con.execute("SELECT qtd_questoes, qtd_textos FROM aulas "
                               "WHERE extracao_id=? AND item_id='i1' AND curso_id='c1'", (eid,)).fetchone()
        self.assertEqual((row[0], row[1]), (2, 1))
        self.assertEqual(sorted(banco_conteudo.aulas_pendentes(self.con, eid)), ["i1", "i2"])

    def test_gravar_blocos_tira_da_pendencia_mesmo_vazia(self):
        eid = self._nova()
        banco_conteudo.gravar_blocos_da_aula(self.con, eid, "i1", [B1])
        banco_conteudo.gravar_blocos_da_aula(self.con, eid, "i2", [])   # aula sem blocos
        self.assertEqual(banco_conteudo.aulas_pendentes(self.con, eid), [])
        row = self.con.execute("SELECT questao_id, meta FROM blocos WHERE extracao_id=? AND item_id='i1'", (eid,)).fetchone()
        self.assertEqual(row["questao_id"], "111")
        self.assertIn("topicos", row["meta"])

    def test_finalizar_completa_e_parcial(self):
        eid = self._nova()
        banco_conteudo.gravar_blocos_da_aula(self.con, eid, "i1", [B1])
        self.assertEqual(banco_conteudo.finalizar_extracao(self.con, eid, {"i2": "rede"}), "parcial")
        eid2 = banco_conteudo.iniciar_extracao(self.con, "BACEN", "concursos")
        banco_conteudo.gravar_arvore(self.con, eid2, CURSOS)
        banco_conteudo.gravar_blocos_da_aula(self.con, eid2, "i1", [B1])
        banco_conteudo.gravar_blocos_da_aula(self.con, eid2, "i2", [])
        self.assertEqual(banco_conteudo.finalizar_extracao(self.con, eid2, {}), "completa")
        row = self.con.execute("SELECT total_cursos, total_aulas, total_blocos, status FROM extracoes WHERE id=?", (eid2,)).fetchone()
        self.assertEqual((row[0], row[1], row[2], row[3]), (2, 2, 1, "completa"))

    def test_extracao_em_andamento_acha_a_mais_recente_do_termo(self):
        self.assertIsNone(banco_conteudo.extracao_em_andamento(self.con, "BACEN"))
        self._nova()
        eid2 = self._nova()
        achada = banco_conteudo.extracao_em_andamento(self.con, "BACEN")
        self.assertEqual(achada["id"], eid2)
        self.assertIsNone(banco_conteudo.extracao_em_andamento(self.con, "PF"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar e ver falhar** — `py -m unittest tests.test_banco_conteudo -v` → `ModuleNotFoundError`.

- [ ] **Step 3: Implementar `banco_conteudo.py`:**

```python
# -*- coding: utf-8 -*-
"""Base de conteúdo do BO (saida\\conteudo.db): schema + escrita/leitura.

Princípio: snapshot é a unidade — cada rodada do coletor grava suas linhas
com extracao_id; nada é sobrescrito (spec 2026-07-05, seção Modelo de dados).
"""
import json
import os
import sqlite3
from datetime import datetime

_SCHEMA = """
CREATE TABLE IF NOT EXISTS extracoes(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  termo TEXT NOT NULL, vertical TEXT NOT NULL,
  iniciada_em TEXT NOT NULL, concluida_em TEXT,
  status TEXT NOT NULL DEFAULT 'em_andamento',
  total_cursos INTEGER DEFAULT 0, total_aulas INTEGER DEFAULT 0,
  total_blocos INTEGER DEFAULT 0, erros_json TEXT DEFAULT '{}');
CREATE TABLE IF NOT EXISTS cursos(
  extracao_id INTEGER NOT NULL, curso_id TEXT NOT NULL,
  nome TEXT, publicado INTEGER, autores TEXT, criado_em_bo TEXT,
  PRIMARY KEY(extracao_id, curso_id));
CREATE TABLE IF NOT EXISTS capitulos(
  extracao_id INTEGER NOT NULL, curso_id TEXT NOT NULL, capitulo_id TEXT NOT NULL,
  nome TEXT, ordem INTEGER, versao TEXT, publicado_em TEXT,
  PRIMARY KEY(extracao_id, curso_id, capitulo_id));
CREATE TABLE IF NOT EXISTS aulas(
  extracao_id INTEGER NOT NULL, curso_id TEXT NOT NULL,
  capitulo_id TEXT NOT NULL, item_id TEXT NOT NULL,
  nome TEXT, path TEXT, atualizada_em TEXT,
  qtd_videos INTEGER DEFAULT 0, qtd_questoes INTEGER DEFAULT 0,
  qtd_textos INTEGER DEFAULT 0, qtd_pdfs INTEGER DEFAULT 0,
  qtd_casts INTEGER DEFAULT 0, qtd_outros INTEGER DEFAULT 0,
  PRIMARY KEY(extracao_id, curso_id, capitulo_id, item_id));
CREATE TABLE IF NOT EXISTS aulas_coletadas(
  extracao_id INTEGER NOT NULL, item_id TEXT NOT NULL,
  qtd_blocos INTEGER DEFAULT 0, coletada_em TEXT,
  PRIMARY KEY(extracao_id, item_id));
CREATE TABLE IF NOT EXISTS blocos(
  extracao_id INTEGER NOT NULL, item_id TEXT NOT NULL, bloco_id TEXT NOT NULL,
  tipo TEXT, ordem INTEGER, ativo INTEGER, rascunho INTEGER, titulo TEXT,
  questao_id TEXT, resposta_tipo TEXT, tem_solucao INTEGER, tem_video_solucao INTEGER,
  video_id_antigo TEXT, duracao_seg INTEGER, tamanho_texto INTEGER, meta TEXT,
  PRIMARY KEY(extracao_id, item_id, bloco_id));
CREATE INDEX IF NOT EXISTS ix_blocos_extracao ON blocos(extracao_id);
CREATE INDEX IF NOT EXISTS ix_blocos_tipo ON blocos(extracao_id, tipo);
CREATE INDEX IF NOT EXISTS ix_blocos_questao ON blocos(questao_id);
CREATE INDEX IF NOT EXISTS ix_blocos_vid_antigo ON blocos(video_id_antigo);
"""

_COLS_BLOCO = ("bloco_id", "tipo", "ordem", "ativo", "rascunho", "titulo",
               "questao_id", "resposta_tipo", "tem_solucao", "tem_video_solucao",
               "video_id_antigo", "duracao_seg", "tamanho_texto")


def _agora():
    return datetime.now().isoformat(timespec="seconds")  # data LOCAL (convenção)


def abrir(caminho):
    os.makedirs(os.path.dirname(os.path.abspath(caminho)), exist_ok=True)
    con = sqlite3.connect(caminho)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(_SCHEMA)
    return con


def iniciar_extracao(con, termo, vertical):
    with con:
        cur = con.execute(
            "INSERT INTO extracoes(termo, vertical, iniciada_em) VALUES(?,?,?)",
            (termo, vertical, _agora()))
    return cur.lastrowid


def gravar_arvore(con, extracao_id, cursos):
    import parse_blocos
    itens = set()
    with con:
        for c in cursos:
            con.execute(
                "INSERT OR REPLACE INTO cursos VALUES(?,?,?,?,?,?)",
                (extracao_id, c.get("id", ""), c.get("name", ""),
                 1 if c.get("published") else 0,
                 parse_blocos.autores_do_curso(c), c.get("created_at", "")))
            for cap in (c.get("content_tree_cache") or []):
                con.execute(
                    "INSERT OR REPLACE INTO capitulos VALUES(?,?,?,?,?,?,?)",
                    (extracao_id, c.get("id", ""), cap.get("chapter_id", ""),
                     cap.get("name", ""), cap.get("order_index"),
                     str(cap.get("chapter_version", "")), cap.get("published_at") or ""))
                for item in (cap.get("items") or []):
                    q = parse_blocos.contagens_da_aula(item)
                    con.execute(
                        "INSERT OR REPLACE INTO aulas VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (extracao_id, c.get("id", ""), cap.get("chapter_id", ""),
                         item.get("item_id", ""),
                         item.get("name") or item.get("title") or "",
                         item.get("path", ""), item.get("updated_at", ""),
                         q["qtd_videos"], q["qtd_questoes"], q["qtd_textos"],
                         q["qtd_pdfs"], q["qtd_casts"], q["qtd_outros"]))
                    itens.add(item.get("item_id", ""))
    return len(cursos), len(itens)


def aulas_pendentes(con, extracao_id):
    rows = con.execute(
        "SELECT DISTINCT a.item_id FROM aulas a "
        "LEFT JOIN aulas_coletadas ac "
        "  ON ac.extracao_id = a.extracao_id AND ac.item_id = a.item_id "
        "WHERE a.extracao_id = ? AND ac.item_id IS NULL", (extracao_id,))
    return [r[0] for r in rows]


def gravar_blocos_da_aula(con, extracao_id, item_id, blocos):
    with con:  # 1 aula = 1 transação (retomada segura)
        for b in blocos:
            con.execute(
                f"INSERT OR REPLACE INTO blocos(extracao_id, item_id, "
                f"{', '.join(_COLS_BLOCO)}, meta) VALUES({','.join('?' * 16)})",
                (extracao_id, item_id, *[b.get(c) for c in _COLS_BLOCO],
                 json.dumps(b.get("meta") or {}, ensure_ascii=False)))
        con.execute(
            "INSERT OR REPLACE INTO aulas_coletadas VALUES(?,?,?,?)",
            (extracao_id, item_id, len(blocos), _agora()))


def extracao_em_andamento(con, termo):
    return con.execute(
        "SELECT * FROM extracoes WHERE termo = ? AND status = 'em_andamento' "
        "ORDER BY id DESC LIMIT 1", (termo,)).fetchone()


def finalizar_extracao(con, extracao_id, erros):
    pendentes = aulas_pendentes(con, extracao_id)
    status = "parcial" if (erros or pendentes) else "completa"
    tot = con.execute(
        "SELECT (SELECT COUNT(*) FROM cursos WHERE extracao_id = :e),"
        "       (SELECT COUNT(*) FROM aulas_coletadas WHERE extracao_id = :e),"
        "       (SELECT COUNT(*) FROM blocos WHERE extracao_id = :e)",
        {"e": extracao_id}).fetchone()
    with con:
        con.execute(
            "UPDATE extracoes SET concluida_em=?, status=?, total_cursos=?, "
            "total_aulas=?, total_blocos=?, erros_json=? WHERE id=?",
            (_agora(), status, tot[0], tot[1], tot[2],
             json.dumps(erros, ensure_ascii=False), extracao_id))
    return status
```

- [ ] **Step 4: Rodar e ver passar** — `py -m unittest tests.test_banco_conteudo -v` → OK (4 testes). Rodar também a suíte toda: `py -m unittest discover -s tests -v`.

- [ ] **Step 5: Commit** — `git add banco_conteudo.py tests/test_banco_conteudo.py && git commit -m "feat: base SQLite de conteúdo (snapshots por extração, WAL, retomada por aula)"`

---

### Task 3: `coletor_ldi.py` — CLI e orquestração (com retomada)

**Files:**
- Create: `coletor_ldi.py`
- Test: `tests/test_coletor_fluxo.py`

**Interfaces:**
- Consumes: `extrator_ldi.{carregar_config, carregar_cookie, montar_sessao, listar_cursos, falha, API, PASTA_APP}`, `banco_conteudo.*` (Task 2), `parse_blocos.meta_do_bloco` (Task 1).
- Produces:
  - `baixar_blocos(sessao, item_id: str, tentativa: int = 1) -> list[dict]` — levanta `CookieVencido(SystemExit)` em 401/403; `RuntimeError` em falha definitiva de rede/HTTP (a aula é registrada como erro e a coleta segue).
  - `coletar(cfg: dict, sessao, termo: str, caminho_banco: str, continuar: bool = False, com_videos: bool = False) -> int` — devolve o `extracao_id`. (Task 4 estende `com_videos`.)
  - `class CookieVencido(SystemExit)`.

- [ ] **Step 1: Escrever os testes que falham** — `tests/test_coletor_fluxo.py` (sessão fake; sem rede):

```python
# -*- coding: utf-8 -*-
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import banco_conteudo
import coletor_ldi

CURSOS = [{
    "id": "c1", "name": "Curso A", "published": True,
    "content_tree_cache": [{
        "chapter_id": "cap1", "name": "Cap 1", "order_index": 0,
        "items": [
            {"item_id": "i1", "name": "Aula 1", "path": "1",
             "block_type_count": {"question": 1}},
            {"item_id": "i2", "name": "Aula 2", "path": "2",
             "block_type_count": {"tiptap": 1}},
        ],
    }],
}]

BLOCOS = {
    "i1": [{"id": "b1", "type": "question", "order_index": 1, "is_active": True,
            "data": {"value": "9", "resolved": {"id": "9", "answer_type": "MULTI",
                                                "solution": {"brief": "x"}}}}],
    "i2": [{"id": "b2", "type": "tiptap", "order_index": 1, "is_active": True,
            "content_length": 50, "data": {}}],
}


class RespostaFake:
    def __init__(self, status, dados=None):
        self.status_code, self._dados, self.ok = status, dados, status < 400
        self.text = ""

    def json(self):
        return {"data": self._dados}


class SessaoFake:
    """GET de /bo/ldi/blocks?item_id=X devolve BLOCOS[X]; falhas injetáveis."""
    def __init__(self, falhas=(), status_falha=404):
        self.falhas, self.status_falha = set(falhas), status_falha

    def get(self, url, timeout=0):
        item = url.split("item_id=")[1]
        if item in self.falhas:
            return RespostaFake(self.status_falha)
        return RespostaFake(200, BLOCOS.get(item, []))


CFG = {"vertical": "concursos", "filtro_local": "", "concorrencia": 2}


class TestColetar(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.dir.name, "conteudo.db")
        self._listar = coletor_ldi.extrator_ldi.listar_cursos
        coletor_ldi.extrator_ldi.listar_cursos = lambda s, t: CURSOS

    def tearDown(self):
        coletor_ldi.extrator_ldi.listar_cursos = self._listar
        self.dir.cleanup()

    def test_coleta_completa(self):
        eid = coletor_ldi.coletar(CFG, SessaoFake(), "BACEN", self.db)
        con = banco_conteudo.abrir(self.db)
        row = con.execute("SELECT status, total_blocos FROM extracoes WHERE id=?", (eid,)).fetchone()
        self.assertEqual((row[0], row[1]), ("completa", 2))
        con.close()

    def test_falha_de_aula_vira_parcial_e_continuar_completa(self):
        eid = coletor_ldi.coletar(CFG, SessaoFake(falhas={"i2"}), "BACEN", self.db)
        con = banco_conteudo.abrir(self.db)
        row = con.execute("SELECT status, erros_json FROM extracoes WHERE id=?", (eid,)).fetchone()
        self.assertEqual(row[0], "parcial")
        self.assertIn("i2", json.loads(row[1]))
        con.close()
        # snapshot volta a 'em_andamento'? Não: --continuar retoma PARCIAL ou EM_ANDAMENTO
        eid2 = coletor_ldi.coletar(CFG, SessaoFake(), "BACEN", self.db, continuar=True)
        self.assertEqual(eid2, eid)
        con = banco_conteudo.abrir(self.db)
        row = con.execute("SELECT status, total_blocos FROM extracoes WHERE id=?", (eid,)).fetchone()
        self.assertEqual((row[0], row[1]), ("completa", 2))
        con.close()

    def test_401_aborta_com_cookie_vencido(self):
        with self.assertRaises(coletor_ldi.CookieVencido):
            coletor_ldi.coletar(CFG, SessaoFake(falhas={"i1", "i2"}, status_falha=401),
                                "BACEN", self.db)

    def test_continuar_sem_coleta_aberta_falha_claro(self):
        with self.assertRaises(SystemExit):
            coletor_ldi.coletar(CFG, SessaoFake(), "BACEN", self.db, continuar=True)


if __name__ == "__main__":
    unittest.main()
```

  *Nota de design:* `--continuar` retoma snapshots `em_andamento` **ou** `parcial` (o teste acima fixa isso) — uma coleta que fechou `parcial` por falhas pontuais é retomável sem criar snapshot novo. `extracao_em_andamento()` do Task 2 ganha o filtro `status IN ('em_andamento','parcial')` — ajustar a função e o teste do Task 2 se necessário (renomear mentalmente para "retomável"; manter o nome da função para não inflar a mudança).

- [ ] **Step 2: Rodar e ver falhar** — `py -m unittest tests.test_coletor_fluxo -v` → `ModuleNotFoundError: No module named 'coletor_ldi'`.

- [ ] **Step 3: Implementar `coletor_ldi.py`:**

```python
# -*- coding: utf-8 -*-
"""
============================================================
 COLETOR LDI — Conteúdo completo por concurso (SOMENTE LEITURA)
 Varre TODOS os blocos (questões, textos, PDFs, vídeos...) dos
 cursos de um concurso e grava snapshots de METADADOS em
 saida\\conteudo.db (SQLite). O fluxo de vídeos (extrator_ldi)
 continua intacto — este script é a fundação do Painel de
 Conteúdo (spec docs/superpowers/specs/2026-07-05-*.md).

 Uso:  py coletor_ldi.py [--termo BACEN] [--continuar] [--com-videos] [--agendado]
============================================================
"""
import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

import banco_conteudo
import extrator_ldi
import parse_blocos

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


class CookieVencido(SystemExit):
    pass


def baixar_blocos(sessao, item_id, tentativa=1):
    url = f"{extrator_ldi.API}/bo/ldi/blocks?item_id={item_id}"
    try:
        r = sessao.get(url, timeout=60)
    except requests.RequestException as e:
        if tentativa < 4:
            time.sleep(0.7 * tentativa * tentativa)
            return baixar_blocos(sessao, item_id, tentativa + 1)
        raise RuntimeError(f"rede: {e}")
    if r.status_code in (401, 403):
        raise CookieVencido("\n[ERRO] A API respondeu 401/403 — o cookie venceu.\n"
                            "       Atualize o cookie.txt e rode com --continuar.")
    if r.status_code == 429 or r.status_code >= 500:
        if tentativa < 4:
            time.sleep(0.7 * tentativa * tentativa)
            return baixar_blocos(sessao, item_id, tentativa + 1)
        raise RuntimeError(f"HTTP {r.status_code}")
    if not r.ok:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:120]}")
    return r.json().get("data") or []


def _baixar_lote(sessao, con, extracao_id, pendentes, concorrencia):
    """Baixa e grava as aulas pendentes; devolve {item_id: erro} das que falharam."""
    erros, feitos = {}, 0
    with ThreadPoolExecutor(max_workers=int(concorrencia)) as pool:
        futuros = {pool.submit(baixar_blocos, sessao, i): i for i in pendentes}
        for fut in as_completed(futuros):
            item_id = futuros[fut]
            try:
                brutos = fut.result()
                metas = [parse_blocos.meta_do_bloco(b) for b in brutos]
                banco_conteudo.gravar_blocos_da_aula(con, extracao_id, item_id, metas)
            except SystemExit:
                raise
            except Exception as e:  # falha pontual: registra e segue
                erros[item_id] = str(e)
            feitos += 1
            if feitos % 100 == 0 or feitos == len(pendentes):
                print(f"      ...{feitos}/{len(pendentes)}")
    return erros


def coletar(cfg, sessao, termo, caminho_banco, continuar=False, com_videos=False):
    con = banco_conteudo.abrir(caminho_banco)
    try:
        if continuar:
            ext = banco_conteudo.extracao_em_andamento(con, termo)
            if ext is None:
                raise extrator_ldi.falha(
                    f"Nenhuma coleta retomável de \"{termo}\" na base.")
            extracao_id = ext["id"]
            print(f"[1/4] Retomando a coleta #{extracao_id} de \"{termo}\"...")
        else:
            print(f"[1/4] Buscando cursos com \"{termo}\"...")
            cursos = extrator_ldi.listar_cursos(sessao, termo)
            if cfg.get("filtro_local"):
                rx = re.compile(cfg["filtro_local"], re.I)
                cursos = [c for c in cursos if rx.search(c.get("name") or "")]
            if not cursos:
                raise extrator_ldi.falha("Nenhum curso encontrado — confira o termo.")
            extracao_id = banco_conteudo.iniciar_extracao(con, termo, cfg["vertical"])
            n_cursos, n_aulas = banco_conteudo.gravar_arvore(con, extracao_id, cursos)
            print(f"      {n_cursos} cursos, {n_aulas} aulas únicas (snapshot #{extracao_id})")

        pendentes = banco_conteudo.aulas_pendentes(con, extracao_id)
        print(f"[2/4] {len(pendentes)} aulas a baixar")
        print(f"[3/4] Baixando blocos ({cfg['concorrencia']} por vez)...")
        erros = _baixar_lote(sessao, con, extracao_id, pendentes, cfg["concorrencia"])
        if erros:  # 1 rodada de retry
            print(f"      retry de {len(erros)} aulas com falha...")
            erros = _baixar_lote(sessao, con, extracao_id, list(erros), cfg["concorrencia"])

        status = banco_conteudo.finalizar_extracao(con, extracao_id, erros)
        tot = con.execute("SELECT total_aulas, total_blocos FROM extracoes WHERE id=?",
                          (extracao_id,)).fetchone()
        print(f"[4/4] Coleta {status}: {tot[0]} aulas, {tot[1]} blocos"
              + (f" | {len(erros)} aulas com erro (retomável com --continuar)" if erros else ""))
        return extracao_id
    finally:
        con.close()


def main():
    parser = argparse.ArgumentParser(
        description="Coletor LDI — conteúdo completo por concurso (somente leitura)")
    parser.add_argument("--termo", help="termo de busca (sobrepõe o config.json)")
    parser.add_argument("--continuar", action="store_true",
                        help="retoma a coleta interrompida/parcial mais recente do termo")
    parser.add_argument("--com-videos", action="store_true",
                        help="além da base, emite o videos_*.json/csv clássico")
    parser.add_argument("--agendado", action="store_true", help="não pede ENTER no final")
    args = parser.parse_args()

    cfg = extrator_ldi.carregar_config()
    termo = args.termo or cfg["termo_busca"]
    if args.continuar and args.com_videos:
        raise extrator_ldi.falha("--com-videos não funciona com --continuar "
                                 "(rode uma coleta nova).")
    sessao = extrator_ldi.montar_sessao(cfg, extrator_ldi.carregar_cookie())
    caminho = os.path.join(extrator_ldi.PASTA_APP, cfg["pasta_saida"], "conteudo.db")

    print("=" * 60)
    print(f" COLETOR LDI  |  termo: {termo}  |  banco: {caminho}")
    print("=" * 60)
    coletar(cfg, sessao, termo, caminho,
            continuar=args.continuar, com_videos=args.com_videos)
    if not args.agendado:
        input("\nPressione ENTER para fechar...")


if __name__ == "__main__":
    try:
        main()
    except SystemExit as e:
        if e.code and "--agendado" not in sys.argv:
            input("\nPressione ENTER para fechar...")
        raise
```

- [ ] **Step 4: Ajustar `extracao_em_andamento` (Task 2) para retomar `parcial`** — em `banco_conteudo.py`, trocar o `WHERE` por `status IN ('em_andamento','parcial')`. Conferir que o teste do Task 2 continua passando (ele só usa `em_andamento`).

- [ ] **Step 5: Rodar e ver passar** — `py -m unittest tests.test_coletor_fluxo -v` → OK (4 testes); suíte toda: `py -m unittest discover -s tests -v` → OK.

- [ ] **Step 6: Commit** — `git add coletor_ldi.py tests/test_coletor_fluxo.py banco_conteudo.py && git commit -m "feat: coletor de conteúdo do BO — snapshots retomáveis em saida/conteudo.db"`

---

### Task 4: `--com-videos` — emitir o `videos_*.json/csv` clássico na mesma varredura

**Files:**
- Modify: `coletor_ldi.py` (função `coletar` e nova `_emitir_videos`)
- Test: `tests/test_coletor_fluxo.py` (novo teste)

**Interfaces:**
- Consumes: `extrator_ldi.linha(cfg, curso, cap, item, bloco, erro="")` (dict com as colunas do CSV clássico) e `extrator_ldi.TIPOS_VIDEO`.
- Produces: arquivos `saida\videos_<termo>_<data>.{json,csv}` no MESMO formato do extrator (compatível com VisualizadorLDI e depara_metabase).

- [ ] **Step 1: Escrever o teste que falha** — acrescentar em `tests/test_coletor_fluxo.py`:

```python
    def test_com_videos_emite_arquivo_classico(self):
        cfg = dict(CFG, pasta_saida=self.dir.name, incluir_url=False)
        eid = coletor_ldi.coletar(cfg, SessaoFake(), "BACEN", self.db, com_videos=True)
        import glob
        arquivos = glob.glob(os.path.join(self.dir.name, "videos_BACEN_*.json"))
        self.assertEqual(len(arquivos), 1)
        with open(arquivos[0], encoding="utf-8") as f:
            linhas = json.load(f)
        # i1 (sem vídeo) vira linha "aula sem bloco de video"; i2 idem (tiptap)
        self.assertTrue(all("curso_nome" in l and "video_id_antigo" in l for l in linhas))
```

  *Atenção:* o `_emitir_videos` grava na MESMA pasta `cfg["pasta_saida"]` interpretada a partir de `PASTA_APP` no `main()`, mas `coletar()` recebe o caminho já resolvido do banco — para o arquivo de vídeos, resolver a pasta como `os.path.dirname(caminho_banco)` (mantém teste e produção coerentes sem depender de `PASTA_APP`).

- [ ] **Step 2: Rodar e ver falhar** — `py -m unittest tests.test_coletor_fluxo.TestColetar.test_com_videos_emite_arquivo_classico -v` → FAIL (arquivo não gerado).

- [ ] **Step 3: Implementar.** Em `coletar()`: quando `com_videos=True`, acumular os blocos brutos de vídeo por aula durante o download (apenas os de `type in extrator_ldi.TIPOS_VIDEO` — memória pequena) e, após finalizar, montar as linhas com a MESMA estrutura do extrator. Mudanças:

  1. `_baixar_lote` ganha parâmetro opcional `videos_por_item=None`; após gravar no banco, se o dict foi passado: `videos_por_item[item_id] = [b for b in brutos if b.get("type") in extrator_ldi.TIPOS_VIDEO]`.
  2. Em `coletar()`, com `com_videos=True`, guardar também `tarefas = [(curso, cap, item), ...]` ao varrer a árvore (mesma iteração do `gravar_arvore` — repetir o loop leve sobre `cursos` em memória) e chamar no final:

```python
def _emitir_videos(cfg, termo, pasta, tarefas, videos_por_item):
    from datetime import date
    linhas = []
    for curso, cap, item in tarefas:
        achou = False
        for b in videos_por_item.get(item["item_id"], []):
            linhas.append(extrator_ldi.linha(cfg, curso, cap, item, b))
            achou = True
        if not achou:
            linhas.append(extrator_ldi.linha(cfg, curso, cap, item, None,
                                             "aula sem bloco de video na versao atual"))
    termo_arq = re.sub(r"[^\w\-]+", "_", termo)
    base = os.path.join(pasta, f"videos_{termo_arq}_{date.today():%Y-%m-%d}")
    with open(base + ".json", "w", encoding="utf-8") as f:
        json.dump(linhas, f, ensure_ascii=False, indent=1)
    import csv as _csv
    with open(base + ".csv", "w", newline="", encoding="utf-8-sig") as f:
        w = _csv.DictWriter(f, fieldnames=list(linhas[0].keys()),
                            delimiter=";", quoting=_csv.QUOTE_ALL)
        w.writeheader()
        w.writerows(linhas)
    print(f"      vídeos clássico: {base}.json/.csv")
```

  (`cfg` precisa de `incluir_url` — no `main()` já vem do `carregar_config()`; no teste é passado explícito.)

- [ ] **Step 4: Rodar e ver passar** — `py -m unittest tests.test_coletor_fluxo -v` → OK (5 testes); suíte toda OK.

- [ ] **Step 5: Commit** — `git add coletor_ldi.py tests/test_coletor_fluxo.py && git commit -m "feat: --com-videos emite o videos_*.json/csv clássico na mesma varredura"`

---

### Task 5: Verificação real (BACEN) + documentação

**Files:**
- Modify: `PROXIMA-SESSAO.md` (nova seção de sessão), `CLAUDE.md` (comando novo no ciclo)

**Interfaces:**
- Consumes: tudo acima; `cookie.txt` válido na pasta (expira 01/08/2026).
- Produces: base `saida\conteudo.db` populada com um snapshot real do BACEN; docs atualizados.

- [ ] **Step 1: Rodar a coleta real** — `py coletor_ldi.py --termo BACEN --agendado` (≈10,5 mil aulas; minutos, como o extrator). Esperado no console: `[4/4] Coleta completa: ~10545 aulas, ~185000 blocos` (ordem de grandeza do censo de 05/07).

- [ ] **Step 2: Conferir a base** — `py -c "import sqlite3; con=sqlite3.connect(r'saida\conteudo.db'); print(con.execute('SELECT termo,status,total_cursos,total_aulas,total_blocos FROM extracoes').fetchall()); print(con.execute('SELECT tipo,COUNT(*) FROM blocos GROUP BY tipo ORDER BY 2 DESC').fetchall())"` — distribuição por tipo deve bater com o censo (question ≈ 115 mil, tiptap ≈ 55 mil, videoMyDocuments ≈ 10 mil, pdf ≈ 3 mil).

- [ ] **Step 3: Testar `--continuar` inócuo** — rodar `py coletor_ldi.py --termo BACEN --continuar --agendado`; esperado: falha clara "Nenhuma coleta retomável" (a anterior fechou `completa`).

- [ ] **Step 4: Atualizar docs** — `PROXIMA-SESSAO.md`: seção "Sessão 5 (05/07): fundação do Painel de Conteúdo" (o que existe, como rodar, spec/plano, próxima fase = Painel Inventário). `CLAUDE.md`: acrescentar `py coletor_ldi.py [--termo X] [--continuar] [--com-videos]` na seção Comandos + 1 linha na Arquitetura + `saida\conteudo.db` na tabela de arquivos.

- [ ] **Step 5: Commit final** — `git add PROXIMA-SESSAO.md CLAUDE.md && git commit -m "docs: registra a fundação do Painel de Conteúdo (coletor + conteudo.db)"`

---

## Self-review (do plano)

- **Cobertura do spec:** schema 6 tabelas ✓ (extracoes/cursos/capitulos/aulas/aulas_coletadas/blocos — `aulas_coletadas` foi adição necessária para retomada com aulas de 0 blocos); CLI 4 flags ✓; 401 aborta ✓; falha pontual segue ✓; retry 1 rodada ✓; WAL ✓; parse puro testado com payloads reais ✓; `--com-videos` ✓; ID antigo via extrator ✓.
- **Sem placeholders:** todo step tem código/comando/saída esperada.
- **Consistência de tipos:** assinaturas de `banco_conteudo` e `parse_blocos` idênticas entre Interfaces e implementação; `extracao_em_andamento` ganha `parcial` no Task 3 Step 4 (documentado).
