# Coleta do Material Base — Plano de implementação (parte 1: local)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** permitir coletar o Material Base (MB) de um professor para o `conteudo.db` e
separar, no painel local, o universo "Cursos (LDI)" do universo "Material Base".

**Architecture:** o MB entra nas tabelas que já existem, com `extracoes.tipo`
(`'curso'`/`'mb'`) como discriminador. Uma função pura converte a árvore do MB no **mesmo
formato do `content_tree_cache`** de curso, de modo que `banco_conteudo.gravar_arvore` e
`coletor_ldi._baixar_lote` sejam reusados **sem alteração**. Toda consulta de agregação
passa a exigir `tipo` explícito.

**Tech Stack:** Python 3.12 (`requests`, `flask`), SQLite (WAL), `unittest`.

**Spec:** `docs/superpowers/specs/2026-08-03-coleta-material-base-design.md`

## Escopo desta parte

Esta é a **parte 1 (local)**: coleta, modelo e painel local. Ela entrega software
funcionando e testável sozinho — `py coletor_ldi.py --mb <id>` e o painel separando os dois
universos — sem migração no Supabase, sem deploy e **sem tocar o worker**.

A **parte 2 (web)** — `supabase/schema_mb.sql`, `snapshot_atual` com `distinct on (tipo,
chave)`, modo "professor" na `/coleta`, coluna `tipo` na `/admin` e o `git pull` do worker —
vira um plano próprio depois que a parte 1 for aceita com dados reais. O motivo de separar:
o risco nº 1 do spec (a contagem do MB pode não ser estável) só se resolve coletando de
verdade, e não faz sentido montar máquina de publicação em cima de um número não confirmado.

Por isso a Task 5 é obrigatória nesta parte: ela **impede** que uma extração de MB vaze para
o Supabase pelos caminhos que hoje pegam "a extração mais recente, seja ela qual for".

## Global Constraints

- Idioma do projeto: **pt-BR** em código, comentários, mensagens e UI.
- **Somente leitura** na API do LDI. Nenhum endpoint de escrita, em nenhuma hipótese.
- Migrações de schema no padrão do projeto: `ALTER TABLE ... ADD COLUMN` sob `try/except`,
  **idempotentes**, sem recoleta e sem quebrar snapshot antigo.
- Snapshots antigos continuam válidos: `tipo` ausente vale como `'curso'`
  (`COALESCE(tipo,'curso')` em toda consulta).
- Testes com `py -m unittest discover -s tests`. A suíte hoje tem **158 testes verdes** —
  nenhum pode ficar vermelho.
- Commits em português, formato `<tipo>: <descrição>` (feat, fix, docs, test, refactor).
- Nada de `print` de depuração deixado para trás; as mensagens de progresso do coletor
  seguem o padrão `[n/4]` já existente.

## Fatos medidos contra a API real (03/08/2026) — não re-derivar

| Fato | Valor |
|---|---|
| Endpoint (singular) | `GET /bo/ldi/base-material/{id}` · plural dá 404 |
| Árvore inteira | `GET /bo/ldi/base-material/{id}/chapters?per_page=100` — 1 req, 366 KB, 1,1 s |
| MB de referência | `3e8e7c78-cdc4-4dc2-90ad-0dae39b827f5` = Direito Constitucional, 36 caps, ~646 itens |
| Capítulos ocultos | `hide_chapters` = 111 nesse MB; **nenhum vem na árvore** |
| Sub-capítulos | **não existem** (`parent_chapter_id` vazio em 100%) |
| Sub-itens | existem: 25 itens com filhos nesse MB |
| `path` do sub-item | **já é absoluto no capítulo** (`"14"` → `"14.1"`) — não reconstruir |
| `updated_at` | **não existe** em capítulo nem item do MB |
| `path` do capítulo | vem **vazio** — a ordem é a posição no array devolvido |
| `sort_chapter_ids` | **incompleto** (27 ids para 36 capítulos) — não usar como ordem |
| Busca de professor | `GET /bo/ldi/users?term=<uma palavra>` — ignora `per_page`, ~50 resultados |
| Lista de MBs | `GET /bo/ldi/base-material?page&per_page` — 387 MBs, `user_id=` filtra |

### ⚠ A armadilha que este plano existe para evitar

**O `type_count` de um item-pai já inclui os descendentes.** Medido: um item com
`question: 149` tem 7 filhos que somam exatamente **149**, e `GET /bo/ldi/blocks` do pai
devolve **0 questões** (1 bloco). Achatar pai e filhos guardando o `type_count` de cada um
**dobraria** todas as contagens do capítulo, em silêncio e para sempre.

Regra correta, implementada na Task 1:
**contagem própria do nó = `type_count` do nó − Σ `type_count` dos filhos diretos** (por
chave, mínimo 0). Vale recursivamente.

## File Structure

| Arquivo | Responsabilidade | Task |
|---|---|---|
| `parse_blocos.py` | + `arvore_do_mb()` — árvore do MB → curso sintético no formato do `content_tree_cache` | 1 |
| `banco_conteudo.py` | + colunas de MB em `extracoes`; `iniciar_extracao()` aceita os metadados | 2 |
| `coletor_ldi.py` | + camada de API do MB (4 funções) | 3 |
| `coletor_ldi.py` | + `coletar_mb()` e as flags `--mb` / `--mb-professor` | 4 |
| `regras_qualidade.py`, `sync_supabase.py`, `exclusao_coleta.py` | guardas de universo | 5 |
| `painel.py` | `tipo` explícito em toda agregação; `?universo=` nas rotas | 6 |
| `painel.py` | + `cobertura_mb()` | 7 |
| `painel.html`, `avaliacao.html` | seletor de universo | 8 |
| `tests/test_parse_arvore_mb.py` | testes da Task 1 | 1 |
| `tests/test_banco_extracao_mb.py` | testes da Task 2 | 2 |
| `tests/test_coletor_mb.py` | testes das Tasks 3 e 4 | 3, 4 |
| `tests/test_guardas_universo.py` | testes da Task 5 | 5 |
| `tests/test_painel_universo.py` | testes das Tasks 6 e 7 | 6, 7 |

---

### Task 1: Árvore do MB → curso sintético (função pura)

**Files:**
- Modify: `parse_blocos.py` (acrescentar ao final, antes de `meta_do_bloco`)
- Test: `tests/test_parse_arvore_mb.py` (criar)

**Interfaces:**
- Consumes: `parse_blocos.contagens_da_aula` (já existe — lê `block_type_count` e
  `simple_block_type_count` no **topo** do item).
- Produces: `parse_blocos.arvore_do_mb(detalhe, capitulos, professor_nome="") -> dict`.
  Devolve um curso sintético no formato aceito por `banco_conteudo.gravar_arvore`:
  `{"id", "name", "published", "created_at", "authors_name", "content_tree_cache": [...]}`.
  Cada capítulo: `{"chapter_id", "name", "order_index", "chapter_version", "published_at",
  "items": [...]}`. Cada item (já achatado, sub-itens inclusos):
  `{"item_id", "name", "title", "path", "updated_at", "block_type_count",
  "simple_block_type_count"}`.

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/test_parse_arvore_mb.py`:

```python
# -*- coding: utf-8 -*-
"""Árvore do Material Base -> curso sintético (formato do content_tree_cache)."""
import unittest

import parse_blocos

# Fragmento fiel ao payload real de GET /bo/ldi/base-material/{id}/chapters
# (o item-pai "14" tem 149 questões que são a SOMA dos filhos — ver plano).
DETALHE = {
    "id": "mb-1", "name": "Direito Constitucional ",
    "main_classification_id": "cls-1", "user_id": "prof-1",
    "hide_chapters": ["h1", "h2", "h3"],
}
CAPITULOS = [
    {"id": "cap-a", "parent_chapter_id": "", "path": "", "name": "Teoria Geral",
     "title": "", "is_draft": False,
     "type_count": {"block_type_count": {}, "simple_block_type_count": {}},
     "items": [
         {"id": "it-1", "parent_chapter_id": "cap-a", "path": "1",
          "name": "1.1 Constitucionalismo", "title": "Constitucionalismo",
          "is_draft": False,
          "type_count": {"block_type_count": {"question": 11, "tiptap": 10,
                                              "videoMyDocuments": 4, "pdfMyDocuments": 2},
                         "simple_block_type_count": {"question": 3}},
          "items": []},
         {"id": "it-2", "parent_chapter_id": "cap-a", "path": "14",
          "name": "9.14 Questões (Hora de Praticar)", "title": "Questões",
          "is_draft": False,
          "type_count": {"block_type_count": {"question": 149, "tiptap": 3},
                         "simple_block_type_count": {"question": 46}},
          "items": [
              {"id": "it-2a", "parent_chapter_id": "cap-a", "path": "14.1",
               "name": "9.14.1 Comentadas Cebraspe", "title": "Comentadas",
               "is_draft": False,
               "type_count": {"block_type_count": {"question": 69, "tiptap": 1},
                              "simple_block_type_count": {"question": 12}},
               "items": []},
              {"id": "it-2b", "parent_chapter_id": "cap-a", "path": "14.2",
               "name": "9.14.2 Comentadas FGV", "title": "Comentadas FGV",
               "is_draft": False,
               "type_count": {"block_type_count": {"question": 80, "tiptap": 2},
                              "simple_block_type_count": {"question": 34}},
               "items": []},
          ]},
     ]},
    {"id": "cap-b", "parent_chapter_id": "", "path": "", "name": "Direitos Fundamentais",
     "title": "", "is_draft": False,
     "type_count": {"block_type_count": {}, "simple_block_type_count": {}},
     "items": []},
]


class TestArvoreDoMB(unittest.TestCase):
    def setUp(self):
        self.curso = parse_blocos.arvore_do_mb(DETALHE, CAPITULOS, professor_nome="Profa Fulana")

    def test_curso_sintetico_usa_o_id_do_mb_e_a_disciplina_sem_sujeira(self):
        self.assertEqual(self.curso["id"], "mb-1")
        self.assertEqual(self.curso["name"], "Direito Constitucional")  # sem espaço à direita
        self.assertEqual(self.curso["authors_name"], "Profa Fulana")

    def test_capitulos_saem_na_ordem_do_array_com_order_index_crescente(self):
        caps = self.curso["content_tree_cache"]
        self.assertEqual([c["chapter_id"] for c in caps], ["cap-a", "cap-b"])
        self.assertEqual([c["order_index"] for c in caps], [0, 1])

    def test_sub_itens_viram_itens_do_mesmo_capitulo_preservando_o_path(self):
        itens = self.curso["content_tree_cache"][0]["items"]
        self.assertEqual([i["item_id"] for i in itens], ["it-1", "it-2", "it-2a", "it-2b"])
        self.assertEqual([i["path"] for i in itens], ["1", "14", "14.1", "14.2"])

    def test_item_pai_nao_soma_de_novo_as_questoes_dos_filhos(self):
        """O type_count do pai JÁ inclui os descendentes (medido na API: 149 = 69+80).
        Guardar o pai com 149 dobraria o capítulo."""
        por_id = {i["item_id"]: i for i in self.curso["content_tree_cache"][0]["items"]}
        self.assertEqual(por_id["it-2"]["block_type_count"].get("question", 0), 0)
        self.assertEqual(por_id["it-2"]["block_type_count"].get("tiptap", 0), 0)  # 3 - (1+2)
        self.assertEqual(por_id["it-2a"]["block_type_count"]["question"], 69)
        self.assertEqual(por_id["it-2b"]["block_type_count"]["question"], 80)

    def test_o_capitulo_soma_exatamente_o_que_a_api_disse_do_pai(self):
        itens = self.curso["content_tree_cache"][0]["items"]
        total = sum(i["block_type_count"].get("question", 0) for i in itens)
        self.assertEqual(total, 11 + 149)  # it-1 + o galho do it-2 inteiro, sem duplicar

    def test_item_sem_filhos_mantem_a_contagem_intacta(self):
        it1 = self.curso["content_tree_cache"][0]["items"][0]
        self.assertEqual(it1["block_type_count"],
                         {"question": 11, "tiptap": 10, "videoMyDocuments": 4,
                          "pdfMyDocuments": 2})
        self.assertEqual(it1["simple_block_type_count"], {"question": 3})

    def test_contagens_da_aula_le_o_formato_produzido(self):
        """O contrato com gravar_arvore: as contagens ficam no TOPO do item."""
        it1 = self.curso["content_tree_cache"][0]["items"][0]
        c = parse_blocos.contagens_da_aula(it1)
        self.assertEqual(c["qtd_questoes"], 11)
        self.assertEqual(c["qtd_videos"], 4)
        self.assertEqual(c["qtd_pdfs"], 2)

    def test_capitulo_sem_itens_nao_quebra(self):
        self.assertEqual(self.curso["content_tree_cache"][1]["items"], [])

    def test_updated_at_ausente_vira_string_vazia(self):
        it1 = self.curso["content_tree_cache"][0]["items"][0]
        self.assertEqual(it1["updated_at"], "")

    def test_subtracao_nunca_fica_negativa(self):
        detalhe = {"id": "mb-x", "name": "X", "user_id": "u"}
        caps = [{"id": "c", "name": "C", "items": [
            {"id": "p", "path": "1", "name": "P",
             "type_count": {"block_type_count": {"question": 2}},
             "items": [{"id": "f", "path": "1.1", "name": "F",
                        "type_count": {"block_type_count": {"question": 9}},
                        "items": []}]}]}]
        curso = parse_blocos.arvore_do_mb(detalhe, caps)
        pai = curso["content_tree_cache"][0]["items"][0]
        self.assertEqual(pai["block_type_count"].get("question", 0), 0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `py -m unittest tests.test_parse_arvore_mb -v`
Expected: FAIL — `AttributeError: module 'parse_blocos' has no attribute 'arvore_do_mb'`

- [ ] **Step 3: Implementar**

Acrescentar em `parse_blocos.py`, logo depois de `contagens_da_aula`:

```python
def _menos(total, filhos):
    """Contagem PRÓPRIA de um nó: o que a API atribui a ele menos o que já é dos filhos.
    O type_count do LDI é cumulativo (medido: pai com 149 questões = soma dos 7 filhos),
    então achatar sem descontar dobraria o capítulo."""
    proprio = {}
    for chave, n in (total or {}).items():
        resto = (n or 0) - sum((f.get(chave) or 0) for f in filhos)
        if resto > 0:
            proprio[chave] = resto
    return proprio


def _achatar_itens(nos, saida):
    """Item -> aula, com os sub-itens virando aulas irmãs (o path do LDI já é absoluto
    dentro do capítulo: '14' -> '14.1'). Devolve saida, na ordem pai, filhos."""
    for no in (nos or []):
        if not isinstance(no, dict) or not no.get("id"):
            continue
        filhos = [f for f in (no.get("items") or []) if isinstance(f, dict)]
        tc = no.get("type_count") or {}
        saida.append({
            "item_id": no["id"],
            "name": no.get("name") or no.get("title") or "",
            "title": no.get("title") or "",
            "path": no.get("path") or "",
            "updated_at": "",  # o MB não devolve updated_at
            "block_type_count": _menos(
                tc.get("block_type_count"),
                [(f.get("type_count") or {}).get("block_type_count") or {} for f in filhos]),
            "simple_block_type_count": _menos(
                tc.get("simple_block_type_count"),
                [(f.get("type_count") or {}).get("simple_block_type_count") or {}
                 for f in filhos]),
        })
        _achatar_itens(filhos, saida)
    return saida


def arvore_do_mb(detalhe, capitulos, professor_nome=""):
    """Material Base -> curso sintético no formato do content_tree_cache, para que
    banco_conteudo.gravar_arvore seja reusado sem alteração.

    detalhe   = data de GET /bo/ldi/base-material/{id}
    capitulos = data de GET /bo/ldi/base-material/{id}/chapters?per_page=100
    """
    caps = []
    for ordem, cap in enumerate(capitulos or []):
        if not isinstance(cap, dict) or not cap.get("id"):
            continue
        caps.append({
            "chapter_id": cap["id"],
            "name": cap.get("name") or cap.get("title") or "",
            "order_index": ordem,   # o path do capítulo vem vazio; a ordem é a do array
            "chapter_version": "",
            "published_at": "",
            "items": _achatar_itens(cap.get("items"), []),
        })
    return {
        "id": detalhe.get("id", ""),
        "name": (detalhe.get("name") or "").strip(),
        "published": False,
        "created_at": detalhe.get("created_at", ""),
        "authors_name": professor_nome or "",
        "content_tree_cache": caps,
    }
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `py -m unittest tests.test_parse_arvore_mb -v`
Expected: PASS (10 testes)

- [ ] **Step 5: Rodar a suíte inteira**

Run: `py -m unittest discover -s tests`
Expected: OK — 158 + 10 testes

- [ ] **Step 6: Commit**

```bash
git add parse_blocos.py tests/test_parse_arvore_mb.py
git commit -m "feat(parse): arvore_do_mb converte o Material Base em curso sintetico"
```

---

### Task 2: Metadados de MB na tabela de extrações

**Files:**
- Modify: `banco_conteudo.py:13-19` (DDL de `extracoes`) e `banco_conteudo.py:96-102`
  (`iniciar_extracao`); a função `abrir` roda as migrações
- Test: `tests/test_banco_extracao_mb.py` (criar)

**Interfaces:**
- Consumes: nada de tasks anteriores.
- Produces: `banco_conteudo.iniciar_extracao(con, termo, vertical, tipo="curso",
  professor_id="", professor_nome="", disciplina="", classificacao_id="",
  capitulos_ocultos=0) -> int`. Colunas novas em `extracoes`: `tipo` (TEXT, default
  `'curso'`), `professor_id`, `professor_nome`, `disciplina`, `classificacao_id` (TEXT,
  default `''`), `capitulos_ocultos` (INTEGER, default 0).

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/test_banco_extracao_mb.py`:

```python
# -*- coding: utf-8 -*-
"""Colunas de Material Base em extracoes + migração idempotente."""
import os
import tempfile
import unittest

import banco_conteudo

_COLS_MB = ("tipo", "professor_id", "professor_nome", "disciplina",
            "classificacao_id", "capitulos_ocultos")


class TestExtracaoMB(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.caminho = os.path.join(self.dir, "t.db")
        self.con = banco_conteudo.abrir(self.caminho)

    def tearDown(self):
        self.con.close()

    def _cols(self):
        return {r[1] for r in self.con.execute("PRAGMA table_info(extracoes)")}

    def test_colunas_novas_existem(self):
        self.assertTrue(set(_COLS_MB) <= self._cols())

    def test_extracao_de_curso_continua_com_a_assinatura_antiga(self):
        eid = banco_conteudo.iniciar_extracao(self.con, "BACEN", "concursos")
        r = self.con.execute("SELECT tipo, termo FROM extracoes WHERE id=?", (eid,)).fetchone()
        self.assertEqual(r["tipo"], "curso")
        self.assertEqual(r["termo"], "BACEN")

    def test_extracao_de_mb_grava_os_metadados(self):
        eid = banco_conteudo.iniciar_extracao(
            self.con, "MB · Profa Fulana · Direito Constitucional", "concursos",
            tipo="mb", professor_id="prof-1", professor_nome="Profa Fulana",
            disciplina="Direito Constitucional", classificacao_id="cls-1",
            capitulos_ocultos=111)
        r = self.con.execute("SELECT * FROM extracoes WHERE id=?", (eid,)).fetchone()
        self.assertEqual(r["tipo"], "mb")
        self.assertEqual(r["professor_id"], "prof-1")
        self.assertEqual(r["professor_nome"], "Profa Fulana")
        self.assertEqual(r["disciplina"], "Direito Constitucional")
        self.assertEqual(r["classificacao_id"], "cls-1")
        self.assertEqual(r["capitulos_ocultos"], 111)

    def test_migracao_e_idempotente(self):
        """Abrir de novo o mesmo banco não pode estourar nem perder dado."""
        eid = banco_conteudo.iniciar_extracao(self.con, "PRF", "concursos")
        self.con.close()
        con2 = banco_conteudo.abrir(self.caminho)
        try:
            self.assertTrue(set(_COLS_MB) <= {r[1] for r in con2.execute(
                "PRAGMA table_info(extracoes)")})
            self.assertEqual(con2.execute(
                "SELECT termo FROM extracoes WHERE id=?", (eid,)).fetchone()[0], "PRF")
        finally:
            con2.close()
            self.con = banco_conteudo.abrir(self.caminho)

    def test_linha_antiga_sem_tipo_vale_como_curso(self):
        """Snapshot pré-migração: o default preenche 'curso' — nada de NULL solto."""
        eid = banco_conteudo.iniciar_extracao(self.con, "Antigo", "concursos")
        tipo = self.con.execute(
            "SELECT COALESCE(tipo,'curso') FROM extracoes WHERE id=?", (eid,)).fetchone()[0]
        self.assertEqual(tipo, "curso")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `py -m unittest tests.test_banco_extracao_mb -v`
Expected: FAIL — `test_colunas_novas_existem` e `test_extracao_de_mb_grava_os_metadados`
(`TypeError: iniciar_extracao() got an unexpected keyword argument 'tipo'`)

- [ ] **Step 3: Implementar a migração**

Em `banco_conteudo.py`, localizar a função `abrir` (linha ~76) e acrescentar as migrações
junto das que já existem (o padrão do projeto é `try/except` por coluna). Se ainda não
houver bloco de migração em `abrir`, criar este, logo após o `executescript(_SCHEMA)`:

```python
    for coluna, ddl in (
        ("tipo", "TEXT NOT NULL DEFAULT 'curso'"),
        ("professor_id", "TEXT DEFAULT ''"),
        ("professor_nome", "TEXT DEFAULT ''"),
        ("disciplina", "TEXT DEFAULT ''"),
        ("classificacao_id", "TEXT DEFAULT ''"),
        ("capitulos_ocultos", "INTEGER DEFAULT 0"),
    ):
        try:  # migração idempotente (padrão do projeto)
            con.execute(f"ALTER TABLE extracoes ADD COLUMN {coluna} {ddl}")
        except Exception:
            pass
```

- [ ] **Step 4: Implementar `iniciar_extracao`**

Substituir `banco_conteudo.iniciar_extracao` por:

```python
def iniciar_extracao(con, termo, vertical, tipo="curso", professor_id="",
                     professor_nome="", disciplina="", classificacao_id="",
                     capitulos_ocultos=0):
    """Abre um snapshot. tipo='mb' identifica coleta de Material Base de professor —
    os demais campos só se aplicam a ela e ficam vazios num curso."""
    with con:
        cur = con.execute(
            "INSERT INTO extracoes(termo, vertical, iniciada_em, tipo, professor_id, "
            "professor_nome, disciplina, classificacao_id, capitulos_ocultos) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (termo, vertical, _agora(), tipo, professor_id, professor_nome,
             disciplina, classificacao_id, int(capitulos_ocultos or 0)))
    return cur.lastrowid
```

- [ ] **Step 5: Rodar e confirmar que passa**

Run: `py -m unittest tests.test_banco_extracao_mb -v`
Expected: PASS (5 testes)

- [ ] **Step 6: Rodar a suíte inteira**

Run: `py -m unittest discover -s tests`
Expected: OK

- [ ] **Step 7: Commit**

```bash
git add banco_conteudo.py tests/test_banco_extracao_mb.py
git commit -m "feat(banco): tipo e metadados de Material Base em extracoes"
```

---

### Task 3: Camada de API do Material Base

**Files:**
- Modify: `coletor_ldi.py` (acrescentar depois de `_completar_vinculo_mb`, linha ~150)
- Test: `tests/test_coletor_mb.py` (criar)

**Interfaces:**
- Consumes: `extrator_ldi.API`, `extrator_ldi.falha`, `coletor_ldi.CookieVencido`.
- Produces (todas em `coletor_ldi`):
  - `obter_mb(sessao, mb_id) -> dict` — o `data` de `/bo/ldi/base-material/{id}`
  - `capitulos_do_mb(sessao, mb_id) -> list` — o `data` de `.../chapters?per_page=100`
  - `mbs_do_professor(sessao, user_id) -> list`
  - `indice_de_mbs(sessao) -> list` — os 387 MBs (pagina de 100 em 100, para 5 páginas)
  - `buscar_professores_com_mb(sessao, termo) -> list` de
    `{"user_id", "nome", "email", "mbs": [{"id", "disciplina"}]}`
  - `extrair_id_mb(texto) -> str` — aceita UUID solto ou URL do admin

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/test_coletor_mb.py`:

```python
# -*- coding: utf-8 -*-
"""Camada de API do Material Base (sem rede: sessão dublê)."""
import unittest

import coletor_ldi


class _Resposta:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.ok = 200 <= status < 300
        self.text = str(payload)

    def json(self):
        return self._payload


class _Sessao:
    """Dublê: responde por trecho da URL e guarda as chamadas feitas."""

    def __init__(self, rotas):
        self.rotas = rotas
        self.chamadas = []

    def get(self, url, **kw):
        self.chamadas.append(url)
        for trecho, resp in self.rotas.items():
            if trecho in url:
                return resp(url) if callable(resp) else resp
        return _Resposta({"error": {"message": "nao mapeado"}}, 404)


class TestExtrairIdMB(unittest.TestCase):
    def test_aceita_url_do_admin_e_ignora_team_id(self):
        url = ("https://admin.estrategia.com/#/concursos/livros-digitais-interativos/"
               "base-material/edit?id=3e8e7c78-cdc4-4dc2-90ad-0dae39b827f5&team_id")
        self.assertEqual(coletor_ldi.extrair_id_mb(url),
                         "3e8e7c78-cdc4-4dc2-90ad-0dae39b827f5")

    def test_aceita_uuid_solto(self):
        self.assertEqual(coletor_ldi.extrair_id_mb("3E8E7C78-CDC4-4DC2-90AD-0DAE39B827F5"),
                         "3e8e7c78-cdc4-4dc2-90ad-0dae39b827f5")

    def test_texto_sem_id_levanta(self):
        with self.assertRaises(SystemExit):
            coletor_ldi.extrair_id_mb("Direito Constitucional")


class TestObterMB(unittest.TestCase):
    def test_detalhe_e_capitulos(self):
        s = _Sessao({
            "/chapters": _Resposta({"data": [{"id": "cap-a", "items": []}],
                                    "meta": {"total": 1}}),
            "/base-material/mb-1": _Resposta({"data": {"id": "mb-1", "name": "Penal"}}),
        })
        self.assertEqual(coletor_ldi.obter_mb(s, "mb-1")["name"], "Penal")
        caps = coletor_ldi.capitulos_do_mb(s, "mb-1")
        self.assertEqual(len(caps), 1)
        self.assertIn("per_page=100", s.chamadas[-1])

    def test_401_vira_cookie_vencido(self):
        s = _Sessao({"/base-material/": _Resposta({}, 401)})
        with self.assertRaises(coletor_ldi.CookieVencido):
            coletor_ldi.obter_mb(s, "mb-1")


class TestBuscaDeProfessor(unittest.TestCase):
    def _sessao(self):
        # A rota /base-material? atende o índice (1 página incompleta) — é dele que
        # sai quem é professor. `u-aluno` não tem MB e por isso some do resultado.
        return _Sessao({
            "/users?": _Resposta({"data": [
                {"id": "u-prof", "full_name": "Profa Nilza Ciciliati",
                 "email": "nilza@x.com"},
                {"id": "u-aluno", "full_name": "Joao Ciciliati", "email": "joao@x.com"},
            ]}),
            "/base-material?": _Resposta({"data": [
                {"id": "mb-1", "name": "Serviço Social ", "user_id": "u-prof"},
            ]}),
        })

    def test_so_devolve_quem_tem_material_base(self):
        """O diretório do LDI é de TODOS os usuários; sem este filtro a busca
        devolveria alunos homônimos."""
        achados = coletor_ldi.buscar_professores_com_mb(self._sessao(), "Ciciliati")
        self.assertEqual([a["nome"] for a in achados], ["Profa Nilza Ciciliati"])
        self.assertEqual(achados[0]["mbs"], [{"id": "mb-1", "disciplina": "Serviço Social"}])

    def test_termo_curto_e_recusado_antes_da_rede(self):
        s = _Sessao({})
        with self.assertRaises(SystemExit):
            coletor_ldi.buscar_professores_com_mb(s, "ab")
        self.assertEqual(s.chamadas, [])  # nada foi à rede


class TestIndiceDeMBs(unittest.TestCase):
    def test_pagina_ate_a_pagina_incompleta(self):
        paginas = {1: [{"id": f"m{i}", "user_id": "u", "name": "D"} for i in range(100)],
                   2: [{"id": "m100", "user_id": "u", "name": "D"}]}

        def responder(url):
            pag = int(url.split("page=")[1].split("&")[0])
            return _Resposta({"data": paginas.get(pag, [])})

        s = _Sessao({"/base-material?": responder})
        self.assertEqual(len(coletor_ldi.indice_de_mbs(s)), 101)
        self.assertEqual(len(s.chamadas), 2)  # parou na página incompleta


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `py -m unittest tests.test_coletor_mb -v`
Expected: FAIL — `AttributeError: module 'coletor_ldi' has no attribute 'extrair_id_mb'`

- [ ] **Step 3: Implementar**

Acrescentar em `coletor_ldi.py`, logo após `_completar_vinculo_mb`:

```python
# ── Material Base do professor (universo separado do LDI de curso) ──────────

_MIN_TERMO_PROFESSOR = 3


def extrair_id_mb(texto):
    """UUID do MB a partir de um UUID solto ou da URL do admin
    (…/base-material/edit?id=<uuid>&team_id). Pega SEMPRE o id=, nunca o team_id=."""
    tok = (texto or "").strip()
    m = re.search(rf"[?&]id=({_UUID})", tok)
    if m:
        return m.group(1).lower()
    if re.fullmatch(_UUID, tok):
        return tok.lower()
    raise extrator_ldi.falha(f"Não achei um ID de Material Base em: {tok[:60]}")


def _get_mb(sessao, caminho):
    r = sessao.get(f"{extrator_ldi.API}{caminho}", timeout=120)
    if r.status_code in (401, 403):
        raise CookieVencido(1)
    if not r.ok:
        raise extrator_ldi.falha(f"HTTP {r.status_code} em {caminho}")
    return r.json()


def obter_mb(sessao, mb_id):
    """Detalhe do Material Base: name (disciplina), user_id, hide_chapters."""
    return _get_mb(sessao, f"/bo/ldi/base-material/{mb_id}").get("data") or {}


def capitulos_do_mb(sessao, mb_id):
    """A árvore INTEIRA numa requisição (medido: 36 capítulos, 366 KB, 1,1 s)."""
    return _get_mb(sessao, f"/bo/ldi/base-material/{mb_id}/chapters?page=1&per_page=100"
                   ).get("data") or []


def mbs_do_professor(sessao, user_id):
    return _get_mb(sessao, f"/bo/ldi/base-material?page=1&per_page=100&user_id={user_id}"
                   ).get("data") or []


def indice_de_mbs(sessao):
    """Os ~387 MBs da base. Serve para saber QUEM é professor: o LDI não tem
    endpoint de professores, e a busca de usuários devolve alunos também."""
    todos, pagina = [], 1
    while pagina <= 10:  # trava de segurança; hoje são 4 páginas
        lote = _get_mb(sessao, f"/bo/ldi/base-material?page={pagina}&per_page=100"
                       ).get("data") or []
        todos += lote
        if len(lote) < 100:
            break
        pagina += 1
    return todos


def buscar_professores_com_mb(sessao, termo):
    """Busca no diretório do LDI e devolve SÓ quem tem Material Base.

    O `users?term=` varre todos os usuários (alunos inclusive), ignora per_page e
    devolve ~50 sem ranking — sozinho ele é inútil. Cruzar com o índice de MBs é o
    que transforma isso numa busca de professor.
    """
    termo = (termo or "").strip()
    if len(termo) < _MIN_TERMO_PROFESSOR:
        raise extrator_ldi.falha(
            f"Busque o professor com pelo menos {_MIN_TERMO_PROFESSOR} letras "
            "(tente só o sobrenome — a busca do LDI é de uma palavra só).")
    usuarios = _get_mb(sessao, f"/bo/ldi/users?page=1&per_page=50&term={termo}"
                       ).get("data") or []
    por_dono = {}
    for mb in indice_de_mbs(sessao):
        por_dono.setdefault(mb.get("user_id"), []).append(
            {"id": mb.get("id"), "disciplina": (mb.get("name") or "").strip()})
    achados = []
    for u in usuarios:
        mbs = por_dono.get(u.get("id"))
        if mbs:
            achados.append({"user_id": u.get("id"),
                            "nome": u.get("full_name") or u.get("id"),
                            "email": u.get("email") or "",
                            "mbs": sorted(mbs, key=lambda m: m["disciplina"])})
    return achados
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `py -m unittest tests.test_coletor_mb -v`
Expected: PASS (8 testes)

- [ ] **Step 5: Rodar a suíte inteira**

Run: `py -m unittest discover -s tests`
Expected: OK

- [ ] **Step 6: Commit**

```bash
git add coletor_ldi.py tests/test_coletor_mb.py
git commit -m "feat(coletor): camada de API do Material Base e busca de professor"
```

---

### Task 4: `coletar_mb()` e as flags do CLI

**Files:**
- Modify: `coletor_ldi.py` — nova função depois de `coletar` (linha ~292) e `main`
  (linha ~295); docstring do topo do arquivo (linha ~12)
- Test: `tests/test_coletor_mb.py` (acrescentar classe)

**Interfaces:**
- Consumes: `parse_blocos.arvore_do_mb` (Task 1), `banco_conteudo.iniciar_extracao` com
  `tipo="mb"` (Task 2), `coletor_ldi.obter_mb`/`capitulos_do_mb`/`buscar_professores_com_mb`
  (Task 3), e `_baixar_lote`/`banco_conteudo.gravar_arvore`/`finalizar_extracao`
  (já existem, **sem alteração**).
- Produces: `coletor_ldi.coletar_mb(cfg, sessao, mb_id, caminho_banco,
  professor_nome="", progresso=None) -> int` (o `extracao_id`).

- [ ] **Step 1: Escrever o teste que falha**

Acrescentar ao final de `tests/test_coletor_mb.py` (antes do `if __name__`):

```python
import os
import tempfile

import banco_conteudo


class TestColetarMB(unittest.TestCase):
    """Coleta ponta a ponta com sessão dublê — prova o que grava no banco."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.caminho = os.path.join(self.dir, "t.db")
        self.cfg = {"vertical": "concursos", "concorrencia": 2}

    def _sessao(self):
        detalhe = {"id": "mb-1", "name": "Direito Constitucional ", "user_id": "u-prof",
                   "main_classification_id": "cls-1", "hide_chapters": ["h1", "h2"]}
        caps = [{"id": "cap-a", "name": "Teoria", "items": [
            {"id": "it-1", "path": "1", "name": "Item 1",
             "type_count": {"block_type_count": {"question": 2}}, "items": []},
        ]}]
        blocos = {"data": [
            {"id": "b1", "type": "question", "order": 1, "is_active": True},
            {"id": "b2", "type": "question", "order": 2, "is_active": True},
        ]}
        return _Sessao({
            "/chapters": _Resposta({"data": caps}),
            "/base-material/mb-1": _Resposta({"data": detalhe}),
            "/blocks?item_id=": _Resposta(blocos),
        })

    def test_grava_extracao_de_mb_com_metadados_e_blocos(self):
        eid = coletor_ldi.coletar_mb(self.cfg, self._sessao(), "mb-1", self.caminho,
                                     professor_nome="Profa Fulana")
        con = banco_conteudo.abrir(self.caminho)
        try:
            ext = con.execute("SELECT * FROM extracoes WHERE id=?", (eid,)).fetchone()
            self.assertEqual(ext["tipo"], "mb")
            self.assertEqual(ext["disciplina"], "Direito Constitucional")
            self.assertEqual(ext["professor_nome"], "Profa Fulana")
            self.assertEqual(ext["professor_id"], "u-prof")
            self.assertEqual(ext["capitulos_ocultos"], 2)
            self.assertEqual(ext["termo"], "MB · Profa Fulana · Direito Constitucional")
            self.assertEqual(con.execute(
                "SELECT COUNT(*) FROM blocos WHERE extracao_id=?", (eid,)).fetchone()[0], 2)
            self.assertEqual(con.execute(
                "SELECT curso_id, nome FROM cursos WHERE extracao_id=?",
                (eid,)).fetchone()[:2], ("mb-1", "Direito Constitucional"))
        finally:
            con.close()

    def test_todo_item_de_mb_nasce_vinculado_ao_mb(self):
        eid = coletor_ldi.coletar_mb(self.cfg, self._sessao(), "mb-1", self.caminho)
        con = banco_conteudo.abrir(self.caminho)
        try:
            self.assertEqual(con.execute(
                "SELECT vinculado_mb FROM aulas WHERE extracao_id=?", (eid,)).fetchone()[0], 1)
        finally:
            con.close()

    def test_nao_roda_regras_de_qualidade(self):
        """O motor dá baixa automática no snapshot seguinte; rodá-lo sobre um MB
        resolveria em massa pendências de curso que continuam abertas."""
        coletor_ldi.coletar_mb(self.cfg, self._sessao(), "mb-1", self.caminho)
        con = banco_conteudo.abrir(self.caminho)
        try:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM pendencias").fetchone()[0], 0)
        finally:
            con.close()

    def test_sem_professor_conhecido_usa_o_uuid_no_termo(self):
        eid = coletor_ldi.coletar_mb(self.cfg, self._sessao(), "mb-1", self.caminho)
        con = banco_conteudo.abrir(self.caminho)
        try:
            termo = con.execute("SELECT termo FROM extracoes WHERE id=?", (eid,)).fetchone()[0]
            self.assertIn("u-prof", termo)  # UUID visível, não "—"
        finally:
            con.close()
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `py -m unittest tests.test_coletor_mb.TestColetarMB -v`
Expected: FAIL — `AttributeError: module 'coletor_ldi' has no attribute 'coletar_mb'`

- [ ] **Step 3: Implementar `coletar_mb`**

Acrescentar em `coletor_ldi.py`, logo depois da função `coletar`:

```python
def coletar_mb(cfg, sessao, mb_id, caminho_banco, professor_nome="", progresso=None):
    """Coleta o Material Base de um professor (universo separado do LDI de curso).

    Do item para baixo é o mesmo caminho da coleta de curso (_baixar_lote); só a
    origem da árvore muda. NÃO roda regras de qualidade nem publica no Supabase —
    ver o spec 2026-08-03-coleta-material-base-design.md.
    """
    con = banco_conteudo.abrir(caminho_banco)
    try:
        print(f"[1/4] Lendo o Material Base {mb_id}...")
        detalhe = obter_mb(sessao, mb_id)
        if not detalhe.get("id"):
            raise extrator_ldi.falha(f"Material Base não encontrado: {mb_id}")
        disciplina = (detalhe.get("name") or "").strip()
        professor = professor_nome or detalhe.get("user_id") or "?"
        ocultos = len(detalhe.get("hide_chapters") or [])
        capitulos = capitulos_do_mb(sessao, mb_id)
        curso = parse_blocos.arvore_do_mb(detalhe, capitulos, professor_nome=professor_nome)

        extracao_id = banco_conteudo.iniciar_extracao(
            con, f"MB · {professor} · {disciplina}", cfg["vertical"], tipo="mb",
            professor_id=detalhe.get("user_id", ""), professor_nome=professor_nome,
            disciplina=disciplina,
            classificacao_id=detalhe.get("main_classification_id", ""),
            capitulos_ocultos=ocultos)
        _, n_aulas = banco_conteudo.gravar_arvore(con, extracao_id, [curso])
        with con:  # todo item de MB está, por definição, no Material Base
            con.execute("UPDATE aulas SET vinculado_mb=1 WHERE extracao_id=?", (extracao_id,))
        print(f"      {len(capitulos)} capítulos, {n_aulas} itens (snapshot #{extracao_id})"
              + (f" · {ocultos} capítulos ocultos pelo professor, fora desta coleta"
                 if ocultos else ""))

        pendentes = banco_conteudo.aulas_pendentes(con, extracao_id)
        print(f"[2/4] {len(pendentes)} itens a baixar")
        print(f"[3/4] Baixando blocos ({cfg['concorrencia']} por vez)...")
        erros = _baixar_lote(sessao, con, extracao_id, pendentes,
                             cfg["concorrencia"], None, progresso)
        if erros:
            print(f"      retry de {len(erros)} itens com falha...")
            erros = _baixar_lote(sessao, con, extracao_id, list(erros),
                                 cfg["concorrencia"], None, progresso)
        status = banco_conteudo.finalizar_extracao(con, extracao_id, erros)
        tot = con.execute("SELECT total_aulas, total_blocos FROM extracoes WHERE id=?",
                          (extracao_id,)).fetchone()
        print(f"[4/4] Coleta {status}: {tot[0]} itens, {tot[1]} blocos")
        print("      (Material Base não roda regras de qualidade nem publica na web)")
        return extracao_id
    finally:
        con.close()
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `py -m unittest tests.test_coletor_mb -v`
Expected: PASS (12 testes)

- [ ] **Step 5: Ligar no CLI**

Em `coletor_ldi.main()`, acrescentar os argumentos junto dos existentes:

```python
    parser.add_argument("--mb", help="coleta o Material Base de um professor "
                                     "(UUID ou URL do admin)")
    parser.add_argument("--mb-professor", dest="mb_professor",
                        help="busca o professor pelo nome e lista os Materiais Base dele")
```

E, no corpo de `main()`, **antes** do fluxo de coleta de curso (logo depois de montar
`cfg`, `cookie` e `sessao`), acrescentar:

```python
    if args.mb_professor:
        achados = buscar_professores_com_mb(sessao, args.mb_professor)
        if not achados:
            print(f'Nenhum professor com Material Base para "{args.mb_professor}".\n'
                  "Tente só o sobrenome — a busca do LDI é de uma palavra só.")
            return
        for a in achados:
            print(f"\n{a['nome']}  <{a['email']}>  ({a['user_id']})")
            for mb in a["mbs"]:
                print(f"   py coletor_ldi.py --mb {mb['id']}   # {mb['disciplina']}")
        return

    if args.mb:
        mb_id = extrair_id_mb(args.mb)
        nome = ""
        detalhe = obter_mb(sessao, mb_id)
        try:  # o nome do professor não vem no MB; resolve-se pelo diretório
            for a in buscar_professores_com_mb(sessao, (detalhe.get("name") or "")[:20]):
                if a["user_id"] == detalhe.get("user_id"):
                    nome = a["nome"]
                    break
        except Exception as e:  # o nome é enriquecimento: sem ele o UUID aparece
            print(f"      (não consegui resolver o nome do professor: {e} — "
                  "o UUID vai aparecer no lugar)")
        coletar_mb(cfg, sessao, mb_id, caminho, professor_nome=nome)
        return
```

> Nota para quem implementa: o nome da variável do caminho do banco em `main()` pode
> diferir de `caminho` — use o mesmo que a chamada de `coletar(...)` usa nesse arquivo.

- [ ] **Step 6: Atualizar a docstring do topo do arquivo**

Em `coletor_ldi.py`, no bloco de uso (linha ~12), acrescentar as duas linhas:

```
       --mb          coleta o Material Base de um professor (UUID ou URL do admin)
       --mb-professor  busca o professor pelo nome e lista os MBs dele
```

- [ ] **Step 7: Rodar a suíte inteira**

Run: `py -m unittest discover -s tests`
Expected: OK

- [ ] **Step 8: Commit**

```bash
git add coletor_ldi.py tests/test_coletor_mb.py
git commit -m "feat(coletor): coletar_mb e as flags --mb / --mb-professor"
```

---

### Task 5: Guardas de universo (o MB não pode vazar)

**Files:**
- Modify: `regras_qualidade.py:208`, `sync_supabase.py:62`, `exclusao_coleta.py` (a
  listagem do `--listar`)
- Test: `tests/test_guardas_universo.py` (criar)

**Interfaces:**
- Consumes: a coluna `extracoes.tipo` (Task 2).
- Produces: nenhuma função nova. Três consultas passam a filtrar
  `COALESCE(tipo,'curso')='curso'`; o `--listar` da exclusão ganha a coluna `tipo`.

**Por que esta task é obrigatória nesta parte:** `regras_qualidade.main`,
`sync_supabase.montar_payload` e a listagem da exclusão pegam hoje **a extração mais
recente, seja ela qual for**. Com um MB no banco, o `py sync_supabase.py` publicaria o MB
como se fosse curso — com a chave errada, que é exatamente a colisão silenciosa que o spec
manda evitar.

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/test_guardas_universo.py`:

```python
# -*- coding: utf-8 -*-
"""Uma extração de MB não pode ser confundida com curso pelos caminhos globais."""
import os
import tempfile
import unittest

import banco_conteudo
import sync_supabase


def _semear(caminho):
    """Um curso, e DEPOIS um MB (o MB é o id mais alto — é essa a armadilha)."""
    con = banco_conteudo.abrir(caminho)
    curso = banco_conteudo.iniciar_extracao(con, "BACEN", "concursos")
    banco_conteudo.gravar_arvore(con, curso, [{
        "id": "c-1", "name": "Direito Constitucional para BACEN", "published": True,
        "content_tree_cache": [{"chapter_id": "cap", "name": "Cap", "order_index": 0,
                                "items": [{"item_id": "it-1", "name": "Item", "path": "1",
                                           "block_type_count": {"question": 3}}]}]}])
    mb = banco_conteudo.iniciar_extracao(
        con, "MB · Profa Fulana · Direito Constitucional", "concursos", tipo="mb",
        professor_id="u-prof", professor_nome="Profa Fulana",
        disciplina="Direito Constitucional")
    banco_conteudo.gravar_arvore(con, mb, [{
        "id": "mb-1", "name": "Direito Constitucional", "published": False,
        "content_tree_cache": [{"chapter_id": "cap-mb", "name": "Cap MB", "order_index": 0,
                                "items": [{"item_id": "it-1", "name": "Item", "path": "1",
                                           "block_type_count": {"question": 3}}]}]}])
    return con, curso, mb


class TestGuardasDeUniverso(unittest.TestCase):
    def setUp(self):
        self.caminho = os.path.join(tempfile.mkdtemp(), "t.db")
        self.con, self.curso, self.mb = _semear(self.caminho)

    def tearDown(self):
        self.con.close()

    def test_o_mb_e_mesmo_a_extracao_mais_recente(self):
        """Guarda do próprio teste: se isto falhar, os outros não provam nada."""
        maior = self.con.execute("SELECT MAX(id) FROM extracoes").fetchone()[0]
        self.assertEqual(maior, self.mb)

    def test_sync_publica_o_curso_e_nunca_o_mb(self):
        escolhida = sync_supabase.extracao_publicavel(self.con)
        self.assertEqual(escolhida["id"], self.curso)
        self.assertEqual(escolhida["termo"], "BACEN")

    def test_regras_de_qualidade_escolhem_a_ultima_coleta_de_curso(self):
        import regras_qualidade
        self.assertEqual(regras_qualidade.ultima_extracao_de_curso(self.con), self.curso)

    def test_sem_coleta_de_curso_o_sync_nao_publica_nada(self):
        con2 = banco_conteudo.abrir(os.path.join(tempfile.mkdtemp(), "so_mb.db"))
        try:
            banco_conteudo.iniciar_extracao(con2, "MB · X · Y", "concursos", tipo="mb")
            self.assertIsNone(sync_supabase.extracao_publicavel(con2))
        finally:
            con2.close()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `py -m unittest tests.test_guardas_universo -v`
Expected: FAIL — `AttributeError: module 'sync_supabase' has no attribute
'extracao_publicavel'`

- [ ] **Step 3: Implementar o guarda do sync**

Em `sync_supabase.py`, acrescentar antes de `montar_payload`:

```python
def extracao_publicavel(con):
    """A coleta mais recente que PODE ir para a web: só universo de curso.

    Material Base não é publicado (a chave da view snapshot_atual é por termo, e
    dois MBs da mesma disciplina colidiriam) — ver o spec do Material Base.
    """
    return con.execute(
        "SELECT * FROM extracoes WHERE COALESCE(tipo,'curso')='curso' "
        "ORDER BY id DESC LIMIT 1").fetchone()
```

E, em `montar_payload`, trocar a linha 62:

```python
    ext = con.execute("SELECT * FROM extracoes ORDER BY id DESC LIMIT 1").fetchone()
```

por:

```python
    ext = extracao_publicavel(con)
```

- [ ] **Step 4: Implementar o guarda das regras**

Em `regras_qualidade.py`, acrescentar antes de `main`:

```python
def ultima_extracao_de_curso(con):
    """Regra de qualidade só vale para o universo de curso: rodar sobre um Material
    Base daria baixa automática em pendências de curso que continuam abertas."""
    r = con.execute("SELECT id FROM extracoes WHERE COALESCE(tipo,'curso')='curso' "
                    "ORDER BY id DESC LIMIT 1").fetchone()
    return r[0] if r else None
```

E, na linha 208 de `main`, trocar

```python
            "SELECT id FROM extracoes ORDER BY id DESC LIMIT 1").fetchone()[0]
```

pelo uso de `ultima_extracao_de_curso(con)`, tratando `None` com a mensagem
`"Nenhuma coleta de curso na base — as regras de qualidade não se aplicam ao Material Base."`
e retornando sem erro.

- [ ] **Step 5: Rodar e confirmar que passa**

Run: `py -m unittest tests.test_guardas_universo -v`
Expected: PASS (4 testes)

- [ ] **Step 6: Mostrar o tipo no `--listar` da exclusão**

Sem isso, sete "Direito Constitucional" aparecem iguais na listagem e a confirmação por
digitar o termo — que é a trava de segurança da exclusão — vira roleta.

Em `exclusao_coleta.py:279-282`, acrescentar a coluna à consulta de `listar_extracoes`:

```python
    for r in con.execute(
            "SELECT e.id, e.termo, e.iniciada_em, e.status, e.total_cursos, "
            "       COALESCE(e.tipo,'curso') tipo, "
            "       (SELECT COUNT(*) FROM blocos b WHERE b.extracao_id = e.id) blocos "
            "FROM extracoes e ORDER BY e.id"):
```

e ao dict montado logo abaixo (linha ~285):

```python
            "id": r["id"], "termo": r["termo"], "tipo": r["tipo"],
```

Em `exclusao_coleta.py:344-348`, acrescentar a coluna na impressão:

```python
    print(f"  {'#':>3}  {'tipo':5}  {'termo':28}  {'quando':16}  "
          f"{'cursos':>6}  {'blocos':>7}  publicada?")
    for l in linhas:
        pub = {True: "sim", False: "não", None: "?"}[l["publicada"]]
        print(f"  {l['id']:>3}  {l['tipo']:5}  {l['termo'][:28]:28}  {l['iniciada_em']:16}  "
              f"{l['cursos']:>6}  {l['blocos']:>7}  {pub}")
```

- [ ] **Step 7: Conferir o `--listar` à mão**

Run: `py exclusao_coleta.py --listar`
Expected: a tabela sai com a coluna `tipo`, todas as coletas atuais como `curso`.

- [ ] **Step 8: Rodar a suíte inteira**

Run: `py -m unittest discover -s tests`
Expected: OK

- [ ] **Step 9: Commit**

```bash
git add sync_supabase.py regras_qualidade.py exclusao_coleta.py tests/test_guardas_universo.py
git commit -m "fix: Material Base nao vaza para sync, regras nem listagem de exclusao"
```

---

### Task 6: Separação dos universos no painel

**Files:**
- Modify: `painel.py:46` (`dados_do_snapshot`), `painel.py:289` (`index`),
  `painel.py:311` (`api_cursos`)
- Test: `tests/test_painel_universo.py` (criar)

**Interfaces:**
- Consumes: `extracoes.tipo` (Task 2).
- Produces:
  - `painel.dados_do_snapshot(con, tipo="curso") -> dict | None` (parâmetro novo, default
    preserva o comportamento de hoje)
  - `GET /?universo=mb` e `GET /api/cursos?universo=mb`
  - o dict devolvido ganha, dentro de `extracao`: `tipo`, `professor_nome`, `disciplina`,
    `capitulos_ocultos`

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/test_painel_universo.py`:

```python
# -*- coding: utf-8 -*-
"""O painel nunca mistura curso com Material Base."""
import os
import tempfile
import unittest

import banco_conteudo
import painel


def _semear(caminho):
    con = banco_conteudo.abrir(caminho)
    curso = banco_conteudo.iniciar_extracao(con, "BACEN", "concursos")
    banco_conteudo.gravar_arvore(con, curso, [{
        "id": "c-1", "name": "Constitucional para BACEN", "published": True,
        "content_tree_cache": [{"chapter_id": "cap", "name": "Cap", "order_index": 0,
                                "items": [{"item_id": "it-1", "name": "A", "path": "1",
                                           "block_type_count": {"question": 3}},
                                          {"item_id": "it-2", "name": "B", "path": "2",
                                           "block_type_count": {"question": 1}}]}]}])
    mb = banco_conteudo.iniciar_extracao(
        con, "MB · Profa Fulana · Direito Constitucional", "concursos", tipo="mb",
        professor_id="u-prof", professor_nome="Profa Fulana",
        disciplina="Direito Constitucional", capitulos_ocultos=111)
    banco_conteudo.gravar_arvore(con, mb, [{
        "id": "mb-1", "name": "Direito Constitucional", "published": False,
        "authors_name": "Profa Fulana",
        "content_tree_cache": [{"chapter_id": "cap-mb", "name": "Cap MB", "order_index": 0,
                                "items": [{"item_id": "it-1", "name": "A", "path": "1",
                                           "block_type_count": {"question": 3}},
                                          {"item_id": "it-9", "name": "Z", "path": "9",
                                           "block_type_count": {"question": 7}}]}]}])
    return con, curso, mb


class TestUniversos(unittest.TestCase):
    def setUp(self):
        self.caminho = os.path.join(tempfile.mkdtemp(), "t.db")
        self.con, self.curso, self.mb = _semear(self.caminho)

    def tearDown(self):
        self.con.close()

    def test_default_continua_sendo_curso_mesmo_com_mb_mais_recente(self):
        """Sem o filtro de tipo, o painel abriria mostrando o MB como se fosse curso."""
        d = painel.dados_do_snapshot(self.con)
        self.assertEqual(d["extracao"]["id"], self.curso)
        self.assertEqual(d["extracao"]["termo"], "BACEN")
        self.assertEqual([c["nome"] for c in d["cursos"]], ["Constitucional para BACEN"])

    def test_universo_mb_traz_o_material_base(self):
        d = painel.dados_do_snapshot(self.con, tipo="mb")
        self.assertEqual(d["extracao"]["id"], self.mb)
        self.assertEqual(d["extracao"]["tipo"], "mb")
        self.assertEqual(d["extracao"]["professor_nome"], "Profa Fulana")
        self.assertEqual(d["extracao"]["disciplina"], "Direito Constitucional")
        self.assertEqual(d["extracao"]["capitulos_ocultos"], 111)

    def test_kpis_de_curso_ignoram_os_itens_do_mb(self):
        d = painel.dados_do_snapshot(self.con)
        self.assertEqual(d["kpis"]["aulas_unicas"], 2)  # não 3 (it-9 é só do MB)

    def test_sem_coleta_do_universo_devolve_none(self):
        con2 = banco_conteudo.abrir(os.path.join(tempfile.mkdtemp(), "so_curso.db"))
        try:
            banco_conteudo.iniciar_extracao(con2, "PRF", "concursos")
            self.assertIsNone(painel.dados_do_snapshot(con2, tipo="mb"))
        finally:
            con2.close()

    def test_api_cursos_respeita_o_universo(self):
        painel.app.config["TESTING"] = True
        painel.caminho_banco = lambda: self.caminho
        cli = painel.app.test_client()
        curso = cli.get("/api/cursos").get_json()["data"]
        mb = cli.get("/api/cursos?universo=mb").get_json()["data"]
        self.assertEqual([c["curso_id"] for c in curso], ["c-1"])
        self.assertEqual([c["curso_id"] for c in mb], ["mb-1"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `py -m unittest tests.test_painel_universo -v`
Expected: FAIL — `test_default_continua_sendo_curso_mesmo_com_mb_mais_recente` acusa o MB
(id maior) no lugar do curso

- [ ] **Step 3: Implementar em `painel.py`**

Trocar a assinatura e a primeira consulta de `dados_do_snapshot`:

```python
def dados_do_snapshot(con, tipo="curso"):
    """Agrega o snapshot mais recente DO UNIVERSO pedido ('curso' ou 'mb').

    O filtro por tipo não é decoração: sem ele, coletar um Material Base faria o
    painel de cursos passar a mostrar o MB, que é a coleta de id mais alto."""
    ext = con.execute(
        "SELECT * FROM extracoes WHERE COALESCE(tipo,'curso')=? "
        "ORDER BY id DESC LIMIT 1", (tipo,)).fetchone()
    if ext is None:
        return None
```

E, no dict devolvido, trocar a chave `"extracao"` por:

```python
        "extracao": {"id": e, "termo": ext["termo"], "iniciada_em": ext["iniciada_em"],
                     "status": ext["status"],
                     "erros": len(json.loads(ext["erros_json"] or "{}")),
                     "tipo": ext["tipo"] or "curso",
                     "professor_nome": ext["professor_nome"] or "",
                     "disciplina": ext["disciplina"] or "",
                     "capitulos_ocultos": ext["capitulos_ocultos"] or 0},
```

Em `index()`:

```python
@app.route("/")
def index():
    universo = "mb" if request.args.get("universo") == "mb" else "curso"
    con = banco_conteudo.abrir(caminho_banco())
    try:
        dados = dados_do_snapshot(con, tipo=universo)
    finally:
        con.close()
    if dados is None:
        vazio = ("Nenhum Material Base coletado ainda.</h1>"
                 "<p>Rode <code>py coletor_ldi.py --mb &lt;id do MB&gt;</code>"
                 if universo == "mb" else
                 "Sem coletas na base ainda.</h1>"
                 "<p>Rode <code>py coletor_ldi.py --termo SEU_CONCURSO</code>")
        return Response(f"<h1>{vazio} e recarregue esta página.</p>", mimetype="text/html")
```

Em `api_cursos()`, trocar a escolha da extração:

```python
@app.route("/api/cursos")
def api_cursos():
    universo = "mb" if request.args.get("universo") == "mb" else "curso"
    con = banco_conteudo.abrir(caminho_banco())
    try:
        r = con.execute("SELECT MAX(id) FROM extracoes "
                        "WHERE COALESCE(tipo,'curso')=?", (universo,)).fetchone()
        e = r[0] or 0
        rows = [dict(r) for r in con.execute(
            "SELECT c.curso_id, c.nome, c.autores FROM cursos c WHERE c.extracao_id=? "
            "AND EXISTS (SELECT 1 FROM aulas a WHERE a.extracao_id=c.extracao_id "
            "AND a.curso_id=c.curso_id) ORDER BY c.nome", (e,))]
    finally:
        con.close()
    return {"data": rows}
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `py -m unittest tests.test_painel_universo -v`
Expected: PASS (5 testes)

- [ ] **Step 5: Rodar a suíte inteira**

Run: `py -m unittest discover -s tests`
Expected: OK — em especial `test_painel_dados`, `test_painel_itens`, `test_painel_ordem`
e `test_painel_vinculo_mb` continuam verdes (o default `tipo="curso"` preserva tudo)

- [ ] **Step 6: Commit**

```bash
git add painel.py tests/test_painel_universo.py
git commit -m "feat(painel): universo explicito (curso x material base) em toda agregacao"
```

---

### Task 7: Cobertura do Material Base nos cursos

**Files:**
- Modify: `painel.py` (função nova depois de `dados_do_snapshot`) e a rota `index`
- Test: `tests/test_painel_universo.py` (acrescentar classe)

**Interfaces:**
- Consumes: `extracoes.tipo` (Task 2), `dados_do_snapshot` (Task 6).
- Produces: `painel.cobertura_mb(con, extracao_id) -> dict` com
  `{"itens_mb": int, "itens_em_curso": int, "cursos_comparados": int}`. Entra no dict de
  `dados_do_snapshot` sob a chave `"cobertura"` quando `tipo == "mb"` (e só então).

- [ ] **Step 1: Escrever o teste que falha**

Acrescentar em `tests/test_painel_universo.py` (antes do `if __name__`):

```python
class TestCoberturaMB(unittest.TestCase):
    """Quanto do acervo do professor chega de fato a um curso."""

    def setUp(self):
        self.caminho = os.path.join(tempfile.mkdtemp(), "t.db")
        self.con, self.curso, self.mb = _semear(self.caminho)

    def tearDown(self):
        self.con.close()

    def test_conta_so_os_itens_que_estao_em_curso(self):
        """O MB tem it-1 e it-9; o curso tem it-1 e it-2. Só it-1 é cobertura.
        Sem o filtro de tipo, o próprio MB entraria como 'curso' e daria 2 de 2."""
        c = painel.cobertura_mb(self.con, self.mb)
        self.assertEqual(c["itens_mb"], 2)
        self.assertEqual(c["itens_em_curso"], 1)
        self.assertEqual(c["cursos_comparados"], 1)

    def test_sem_curso_no_banco_a_cobertura_e_zero_e_diz_contra_quantos_comparou(self):
        con2 = banco_conteudo.abrir(os.path.join(tempfile.mkdtemp(), "so_mb.db"))
        try:
            mb = banco_conteudo.iniciar_extracao(con2, "MB · X · Y", "concursos", tipo="mb")
            banco_conteudo.gravar_arvore(con2, mb, [{
                "id": "mb-9", "name": "Y",
                "content_tree_cache": [{"chapter_id": "c", "name": "C", "order_index": 0,
                                        "items": [{"item_id": "z", "name": "Z", "path": "1",
                                                   "block_type_count": {}}]}]}])
            c = painel.cobertura_mb(con2, mb)
            self.assertEqual((c["itens_em_curso"], c["cursos_comparados"]), (0, 0))
        finally:
            con2.close()

    def test_curso_recoletado_conta_uma_vez_so(self):
        """Duas coletas do mesmo curso não podem inflar 'cursos_comparados'."""
        outra = banco_conteudo.iniciar_extracao(self.con, "BACEN", "concursos")
        banco_conteudo.gravar_arvore(self.con, outra, [{
            "id": "c-1", "name": "Constitucional para BACEN", "published": True,
            "content_tree_cache": [{"chapter_id": "cap", "name": "Cap", "order_index": 0,
                                    "items": [{"item_id": "it-1", "name": "A", "path": "1",
                                               "block_type_count": {}}]}]}])
        c = painel.cobertura_mb(self.con, self.mb)
        self.assertEqual(c["cursos_comparados"], 1)
        self.assertEqual(c["itens_em_curso"], 1)

    def test_o_dict_do_painel_traz_cobertura_so_no_universo_mb(self):
        self.assertIn("cobertura", painel.dados_do_snapshot(self.con, tipo="mb"))
        self.assertNotIn("cobertura", painel.dados_do_snapshot(self.con))
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `py -m unittest tests.test_painel_universo.TestCoberturaMB -v`
Expected: FAIL — `AttributeError: module 'painel' has no attribute 'cobertura_mb'`

- [ ] **Step 3: Implementar**

Acrescentar em `painel.py`, depois de `dados_do_snapshot`:

```python
def cobertura_mb(con, extracao_id):
    """Quanto do Material Base chega de fato a um curso.

    Compara contra a coleta MAIS RECENTE de cada curso do banco (universo 'curso').
    Devolve também quantos cursos entraram na comparação — sem isso o percentual
    mente: 35% contra um único concurso não é 35% do catálogo.
    """
    itens_mb = con.execute(
        "SELECT COUNT(DISTINCT item_id) FROM aulas WHERE extracao_id=?",
        (extracao_id,)).fetchone()[0] or 0
    ultimas = con.execute(
        "SELECT a.curso_id, MAX(a.extracao_id) FROM aulas a "
        "JOIN extracoes x ON x.id = a.extracao_id "
        "WHERE COALESCE(x.tipo,'curso')='curso' GROUP BY a.curso_id").fetchall()
    if not ultimas:
        return {"itens_mb": itens_mb, "itens_em_curso": 0, "cursos_comparados": 0}
    pares = [(cid, eid) for cid, eid in ultimas]
    marcas = " OR ".join(["(a.curso_id=? AND a.extracao_id=?)"] * len(pares))
    valores = [v for par in pares for v in par]
    em_curso = con.execute(
        "SELECT COUNT(*) FROM (SELECT DISTINCT item_id FROM aulas WHERE extracao_id=?) m "
        f"WHERE m.item_id IN (SELECT DISTINCT a.item_id FROM aulas a WHERE {marcas})",
        (extracao_id, *valores)).fetchone()[0] or 0
    return {"itens_mb": itens_mb, "itens_em_curso": em_curso,
            "cursos_comparados": len(pares)}
```

E, em `dados_do_snapshot`, logo antes do `return`, acrescentar a chave só no universo MB:

```python
    resultado = { ... }   # o dict que já existe
    if (ext["tipo"] or "curso") == "mb":
        resultado["cobertura"] = cobertura_mb(con, e)
    return resultado
```

> Nota para quem implementa: hoje `dados_do_snapshot` faz `return {...}` direto. Atribua o
> dict a `resultado` primeiro e devolva no fim — não mude nenhuma chave existente.

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `py -m unittest tests.test_painel_universo -v`
Expected: PASS (9 testes)

- [ ] **Step 5: Rodar a suíte inteira**

Run: `py -m unittest discover -s tests`
Expected: OK

- [ ] **Step 6: Commit**

```bash
git add painel.py tests/test_painel_universo.py
git commit -m "feat(painel): cobertura do Material Base nos cursos coletados"
```

---

### Task 8: Seletor de universo nas telas

**Files:**
- Modify: `painel.html:99-108` (cabeçalho) e `painel.html:141-150` (chips)
- Modify: `avaliacao.html:89` (seletor) e `avaliacao.html:155` (fetch de `/api/cursos`)
- Test: manual (as telas não têm suíte; a lógica que importa está coberta nas Tasks 6 e 7)

**Interfaces:**
- Consumes: `GET /?universo=mb` e `GET /api/cursos?universo=mb` (Task 6), e as chaves
  `extracao.tipo`, `extracao.professor_nome`, `extracao.disciplina`,
  `extracao.capitulos_ocultos`, `cobertura` (Tasks 6 e 7).
- Produces: nada consumido por outras tasks.

**Fora do escopo desta task:** as cópias `web/telas/{painel,avaliacao}.html`. Elas leem o
payload publicado no Supabase, que **nunca** conterá MB nesta parte (Task 5 garante). O
seletor entra nelas na parte 2, junto do resto da web — mexer agora criaria um botão que
leva a lugar nenhum.

- [ ] **Step 1: Trocar o link do topo do painel por um seletor de universo**

Em `painel.html`, substituir a linha 99-100:

```html
  <p class="eyebrow">Painel de Conteúdo · Inventário
    &nbsp;·&nbsp; <a href="/avaliacao" style="color:inherit">📋 Avaliação de disciplina</a></p>
```

por:

```html
  <p class="eyebrow">Painel de Conteúdo · Inventário
    &nbsp;·&nbsp; <a href="/avaliacao" style="color:inherit">📋 Avaliação de disciplina</a></p>
  <p class="eyebrow" id="universo"></p>
```

- [ ] **Step 2: Renderizar o seletor e o cabeçalho de MB**

Em `painel.html`, logo depois da linha `const K = D.kpis, X = D.achados, E = D.extracao;`,
acrescentar:

```js
  const ehMB = E.tipo === "mb";
  document.getElementById("universo").innerHTML =
    ["curso", "mb"].map(u => {
      const rotulo = u === "mb" ? "🎓 Material Base (professores)" : "📚 Cursos (LDI)";
      const atual = (u === "mb") === ehMB;
      return atual ? `<b>${rotulo}</b>`
                   : `<a href="/${u === "mb" ? "?universo=mb" : ""}" style="color:inherit">${rotulo}</a>`;
    }).join(" &nbsp;·&nbsp; ");
```

- [ ] **Step 3: Trocar título e chips quando o universo for MB**

Em `painel.html`, substituir o trecho que monta título e chips (linhas ~141-150) por:

```js
  const titulo = ehMB ? `${E.disciplina} — Material Base de ${E.professor_nome || "professor sem nome no diretório"}`
                      : `${E.termo} — inventário de conteúdo do BO`;
  document.getElementById("titulo").textContent = titulo;
  document.title = ehMB ? `Material Base — ${E.disciplina}` : `Painel de Conteúdo — ${E.termo}`;

  const dt = (E.iniciada_em || "").replace("T", " ").slice(0, 16);
  const chips = [
    `Snapshot <b>#${E.id}</b>`, `Coletado em <b>${dt}</b>`,
    ehMB ? `Disciplina <b>${E.disciplina}</b>` : `Termo <b>${E.termo}</b>`,
    `Status <b>${E.status}</b> · ${fmt(E.erros)} erro(s)`,
  ];
  if (ehMB && E.capitulos_ocultos) {
    chips.push(`<b>${fmt(E.capitulos_ocultos)}</b> capítulos ocultos pelo professor, fora desta coleta`);
  }
  if (ehMB && D.cobertura) {
    const c = D.cobertura;
    const pct = c.itens_mb ? Math.round(100 * c.itens_em_curso / c.itens_mb) : 0;
    chips.push(`Chega a algum curso: <b>${fmt(c.itens_em_curso)}</b> de ${fmt(c.itens_mb)} itens (${pct}%) · comparado com ${fmt(c.cursos_comparados)} curso(s) na base`);
  }
  document.getElementById("chips").innerHTML =
    chips.map(c => `<span class="chip">${c}</span>`).join("");
```

- [ ] **Step 4: Conferir o painel de curso à mão (não regrediu)**

Run: `py painel.py --sem-navegador` e abrir `http://127.0.0.1:8766`
Expected: a tela do BACEN aparece **exatamente como antes**, com a linha nova de universo no
topo e "📚 Cursos (LDI)" em negrito.

- [ ] **Step 5: Commit do painel**

```bash
git add painel.html
git commit -m "feat(painel): seletor de universo e cabecalho do Material Base"
```

- [ ] **Step 6: Seletor de universo na avaliação**

Em `avaliacao.html`, na linha 89, trocar

```html
      <select id="selCurso"><option value="">carregando...</option></select>
```

por

```html
      <select id="selUniverso">
        <option value="curso">📚 Cursos (LDI)</option>
        <option value="mb">🎓 Material Base</option>
      </select>
      <select id="selCurso"><option value="">carregando...</option></select>
```

- [ ] **Step 7: Levar o universo no fetch**

Em `avaliacao.html`, na linha ~155, trocar

```js
    const r = await fetch("/api/cursos");
```

por

```js
    const universo = document.getElementById("selUniverso").value;
    const r = await fetch("/api/cursos?universo=" + encodeURIComponent(universo));
```

e, logo depois da função que carrega os cursos, ligar a troca:

```js
  document.getElementById("selUniverso").addEventListener("change", carregarCursos);
```

> Nota para quem implementa: use o nome real da função que faz esse fetch neste arquivo
> (localize com `grep -n "api/cursos" avaliacao.html` e suba até o `async function`).

- [ ] **Step 8: Conferir a avaliação à mão**

Run: `py painel.py --sem-navegador` e abrir `http://127.0.0.1:8766/avaliacao`
Expected: com o universo em "Cursos", a lista é a de sempre; em "Material Base", a lista
fica vazia enquanto não houver MB coletado (e passa a listar o MB depois da coleta real).

- [ ] **Step 9: Commit**

```bash
git add avaliacao.html
git commit -m "feat(avaliacao): seletor de universo na planilha de avaliacao"
```

---

## Aceite final (só o Clovis pode fazer — exige cookie válido do LDI)

Depois das 8 tasks, com `cookie.txt` válido:

- [ ] **1. Coletar o MB de referência**

```powershell
py coletor_ldi.py --mb 3e8e7c78-cdc4-4dc2-90ad-0dae39b827f5
```

Esperado: **36 capítulos**, **~646–651 itens**, e a mensagem
"111 capítulos ocultos pelo professor, fora desta coleta".

- [ ] **2. Coletar o MESMO MB uma segunda vez e comparar os totais**

Este passo resolve o **risco nº 1 do spec**. Rodar de novo e comparar `total_aulas` e
`total_blocos` das duas extrações:

```powershell
py exclusao_coleta.py --listar
```

Se os números baterem, a paginação é estável e a diferença 646/651 era edição do professor.
**Se divergirem sem que o professor tenha mexido, a coleta está perdendo itens em silêncio —
parar e investigar antes da parte 2.**

- [ ] **3. Conferir a busca de professor**

```powershell
py coletor_ldi.py --mb-professor Ciciliati
```

Esperado: **um** professor (Profa Nilza Ciciliati) com o MB "Serviço Social".

```powershell
py coletor_ldi.py --mb-professor Fauth
```

Esperado: só quem tem MB — não os oito homônimos do diretório.

- [ ] **4. Conferir os dois universos no painel**

`py painel.py` → o universo "Cursos" mostra os números **idênticos** aos de antes; o
universo "Material Base" mostra o MB, os capítulos ocultos e a cobertura (esperado
**~225 itens** chegando a curso, comparado com os cursos do BACEN na base).

- [ ] **5. Conferir que a web não mudou nada**

Não rodar sync nenhum. Abrir o app web e confirmar que **nada** mudou — é o ponto da Task 5.

---

## O que NÃO está nesta parte (parte 2, plano próprio)

- `supabase/schema_mb.sql`: `tipo` e `chave` em `snapshot`; view `snapshot_atual` com
  `distinct on (tipo, chave)`.
- Modo "professor" na `/coleta` (busca, seleção múltipla, `tipo='mb'` na fila com alvo JSON).
- Coluna `tipo` na lista de exclusão da `/admin`.
- Seletor de universo nas cópias `web/telas/{painel,avaliacao}.html`.
- `git pull` + `systemctl restart worker-coleta` no VPS.
