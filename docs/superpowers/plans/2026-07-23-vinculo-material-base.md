# Vínculo com o Material Base (por item) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development para executar task a task. Steps usam checkbox (`- [ ]`). Idioma pt-BR. Branch nova a partir da `main` atualizada: `git checkout main && git pull && git checkout -b feat/vinculo-material-base`.

**Goal:** Mostrar no Painel de Conteúdo quantos itens de cada curso estão vinculados ao Material Base do professor (KPI na visão geral, achado de auditoria e coluna por aula na avaliação).

**Architecture:** Passo novo na coleta (`chapters/{id}/items` por capítulo → grava `vinculado_mb` por item no `conteudo.db`); agregação em `painel.py` (reusada pelo `sync_supabase.py`); render nas telas `painel.html`/`avaliacao.html` (raiz + cópias `web/telas/`).

**Tech Stack:** Python 3.12 (requests, sqlite3, flask), unittest; HTML/JS vanilla nas telas.

## Global Constraints
- pt-BR em tudo (código, comentários, UI, commits).
- Terminologia LDI de exibição: Curso → **Aula** (capítulo) → **Item** (tópico) → **Bloco**. Contar por **item**.
- Fonte confiável do flag: `GET /bo/ldi/chapters/{chapter_id}/items` → `data[]`, cada item com `has_base_material` (bool). **NÃO** usar o `has_base_material` de capítulo (subnotifica).
- Números de aceite reais: **Amparo 68/75**, **DMAE 319/345**. Cursos de teste: Amparo `e93d81a4-9b73-4474-b885-136a3e2aef0a`, DMAE `d8970f8c-732d-4bc6-8bf3-bf9d53a9f314`.
- `vinculado_mb` é INTEGER 0/1, NULL = desconhecido (snapshot antigo). Nas telas, desconhecido = "—", nunca conta como não-vinculado.
- Migração de coluna idempotente (padrão `try/except sqlite3.OperationalError` já em `banco_conteudo.abrir`).
- Telas da raiz mudam **e** as cópias em `web/telas/` recebem as mesmas mudanças (byte-idênticas fora das edições web-only).
- service_role/cookie nunca no cliente; nada disso é tocado aqui.
- Verificação Python: `py -m unittest discover -s tests` (hoje 79 verdes). Sem dependência nova.

---

### Task 1: Coluna `vinculado_mb` + escrita no banco

**Files:**
- Modify: `banco_conteudo.py` (migração idempotente em `abrir()`; nova função `gravar_vinculo_mb`)
- Test: `tests/test_banco_vinculo_mb.py` (novo)

**Interfaces:**
- Produces: `banco_conteudo.gravar_vinculo_mb(con, extracao_id, vinculo)` onde `vinculo` é `dict[item_id -> bool]`; grava `vinculado_mb` (1/0) na tabela `aulas` por `(extracao_id, item_id)`.

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/test_banco_vinculo_mb.py`:

```python
import os, tempfile, unittest
import banco_conteudo


class TestVinculoMB(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.db = os.path.join(self.dir, "c.db")

    def _semear_aula(self, con, e, item_id):
        con.execute(
            "INSERT OR REPLACE INTO aulas(extracao_id, curso_id, capitulo_id, item_id, nome) "
            "VALUES(?,?,?,?,?)", (e, "cur1", "cap1", item_id, "Item " + item_id))
        con.commit()

    def test_coluna_existe_e_default_null(self):
        con = banco_conteudo.abrir(self.db)
        self._semear_aula(con, 1, "i1")
        v = con.execute("SELECT vinculado_mb FROM aulas WHERE item_id='i1'").fetchone()[0]
        self.assertIsNone(v)  # desconhecido até a coleta gravar

    def test_gravar_vinculo_mb(self):
        con = banco_conteudo.abrir(self.db)
        for i in ("i1", "i2", "i3"):
            self._semear_aula(con, 1, i)
        banco_conteudo.gravar_vinculo_mb(con, 1, {"i1": True, "i2": False})
        got = {r[0]: r[1] for r in con.execute(
            "SELECT item_id, vinculado_mb FROM aulas WHERE extracao_id=1")}
        self.assertEqual(got["i1"], 1)
        self.assertEqual(got["i2"], 0)
        self.assertIsNone(got["i3"])  # não informado permanece NULL


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `py -m unittest tests.test_banco_vinculo_mb -v`
Expected: FAIL (`AttributeError: module 'banco_conteudo' has no attribute 'gravar_vinculo_mb'` e/ou coluna inexistente).

- [ ] **Step 3: Implementar**

⚠ **Correção descoberta na execução:** `gravar_arvore` usa `INSERT OR REPLACE INTO aulas VALUES(?,...)` **posicional** (13 placeholders) — a 14ª coluna quebra. Converter esse INSERT para colunas **nomeadas** (as 13 atuais), deixando `vinculado_mb` NULL no insert. Seguro porque `gravar_arvore` roda 1× por extração, antes de `_completar_vinculo_mb` (não há wipe).

Em `banco_conteudo.py`, dentro de `abrir()`, no bloco de migração idempotente (junto das `ALTER TABLE blocos ...`), acrescentar a linha do `aulas`:

```python
    for sql in ("ALTER TABLE blocos ADD COLUMN banca TEXT",
                "ALTER TABLE blocos ADD COLUMN ano INTEGER",
                "ALTER TABLE blocos ADD COLUMN qtd_questoes_texto INTEGER",
                "ALTER TABLE aulas ADD COLUMN vinculado_mb INTEGER"):
```

E adicionar a função (após `gravar_arvore`):

```python
def gravar_vinculo_mb(con, extracao_id, vinculo):
    """Grava vinculado_mb (1/0) por item na tabela aulas. `vinculo` = {item_id: bool}.
    Itens ausentes do dict permanecem NULL (desconhecido)."""
    with con:
        for item_id, tem in vinculo.items():
            con.execute(
                "UPDATE aulas SET vinculado_mb=? WHERE extracao_id=? AND item_id=?",
                (1 if tem else 0, extracao_id, item_id))
```

- [ ] **Step 4: Rodar e ver passar**

Run: `py -m unittest tests.test_banco_vinculo_mb -v`
Expected: PASS (2 testes).

- [ ] **Step 5: Commit**

```bash
git add banco_conteudo.py tests/test_banco_vinculo_mb.py
git commit -m "feat(banco): coluna vinculado_mb por item + gravar_vinculo_mb"
```

---

### Task 2: Parse do payload de itens (`has_base_material` → dict)

**Files:**
- Modify: `parse_blocos.py` (nova função pura `vinculo_mb_dos_itens`)
- Test: `tests/test_parse_vinculo_mb.py` (novo)

**Interfaces:**
- Produces: `parse_blocos.vinculo_mb_dos_itens(data_itens) -> dict[str, bool]` — recebe a lista `data` de `GET /bo/ldi/chapters/{id}/items`, devolve `{item_id: has_base_material}`. Ignora entradas sem `item_id`/`id`.

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/test_parse_vinculo_mb.py` (payload no formato real observado — item usa `id` como identificador de item na resposta de `/items`):

```python
import unittest
import parse_blocos


class TestVinculoMbDosItens(unittest.TestCase):
    def test_extrai_flag_por_item(self):
        data = [
            {"id": "i1", "has_base_material": True, "name": "A"},
            {"id": "i2", "has_base_material": False, "name": "B"},
        ]
        self.assertEqual(parse_blocos.vinculo_mb_dos_itens(data),
                         {"i1": True, "i2": False})

    def test_ausencia_de_flag_vira_false(self):
        data = [{"id": "i3", "name": "C"}]  # sem has_base_material
        self.assertEqual(parse_blocos.vinculo_mb_dos_itens(data), {"i3": False})

    def test_ignora_sem_id(self):
        data = [{"has_base_material": True}, {"id": "", "has_base_material": True}]
        self.assertEqual(parse_blocos.vinculo_mb_dos_itens(data), {})

    def test_lista_vazia(self):
        self.assertEqual(parse_blocos.vinculo_mb_dos_itens([]), {})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `py -m unittest tests.test_parse_vinculo_mb -v`
Expected: FAIL (`has no attribute 'vinculo_mb_dos_itens'`).

- [ ] **Step 3: Implementar**

Em `parse_blocos.py`, adicionar (perto de `contagens_da_aula`):

```python
def vinculo_mb_dos_itens(data_itens):
    """De GET /bo/ldi/chapters/{id}/items: {item_id: has_base_material(bool)}.
    O item usa 'id' (fallback 'item_id') como identificador; sem id, ignora."""
    out = {}
    for it in (data_itens or []):
        iid = it.get("id") or it.get("item_id")
        if iid:
            out[iid] = bool(it.get("has_base_material"))
    return out
```

- [ ] **Step 4: Rodar e ver passar**

Run: `py -m unittest tests.test_parse_vinculo_mb -v`
Expected: PASS (4 testes).

- [ ] **Step 5: Commit**

```bash
git add parse_blocos.py tests/test_parse_vinculo_mb.py
git commit -m "feat(parse): vinculo_mb_dos_itens (has_base_material por item)"
```

---

### Task 3: Passo de coleta `_completar_vinculo_mb`

**Files:**
- Modify: `coletor_ldi.py` (nova função `_completar_vinculo_mb`; chamada dentro de `coletar()` após `_completar_autores`)
- Test: `tests/test_coletor_vinculo_mb.py` (novo)

**Interfaces:**
- Consumes: `banco_conteudo.gravar_vinculo_mb` (Task 1), `parse_blocos.vinculo_mb_dos_itens` (Task 2).
- Produces: `coletor_ldi._completar_vinculo_mb(sessao, con, extracao_id, cursos, concorrencia)` — varre capítulos, chama `chapters/{id}/items`, grava o vínculo; 401/403 vira `CookieVencido`; falha pontual de capítulo é contada e ignorada.

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/test_coletor_vinculo_mb.py` (usa uma sessão fake; grava numa base temporária real):

```python
import os, tempfile, unittest
import banco_conteudo
import coletor_ldi
import extrator_ldi


class _Resp:
    def __init__(self, status, data=None):
        self.status_code = status
        self.ok = 200 <= status < 300
        self._data = data or []
    def json(self):
        return {"data": self._data}


class _Sessao:
    """Devolve itens por capitulo conforme o path chamado."""
    def __init__(self, por_cap, status=200):
        self.por_cap = por_cap
        self.status = status
    def get(self, url, timeout=60):
        if self.status != 200:
            return _Resp(self.status)
        ch = url.rstrip("/").split("/chapters/")[1].split("/")[0]
        return _Resp(200, self.por_cap.get(ch, []))


class TestCompletarVinculoMB(unittest.TestCase):
    def setUp(self):
        self.db = os.path.join(tempfile.mkdtemp(), "c.db")
        self.con = banco_conteudo.abrir(self.db)
        # árvore mínima: 1 curso, 2 capítulos, 3 itens
        for (cap, item) in [("capA", "i1"), ("capA", "i2"), ("capB", "i3")]:
            self.con.execute(
                "INSERT OR REPLACE INTO aulas(extracao_id, curso_id, capitulo_id, item_id, nome) "
                "VALUES(1,'cur1',?,?,?)", (cap, item, item))
        self.con.commit()
        self.cursos = [{"id": "cur1", "content_tree_cache": [
            {"chapter_id": "capA"}, {"chapter_id": "capB"}]}]

    def test_grava_vinculo_por_item(self):
        sess = _Sessao({
            "capA": [{"id": "i1", "has_base_material": True},
                     {"id": "i2", "has_base_material": False}],
            "capB": [{"id": "i3", "has_base_material": True}],
        })
        coletor_ldi._completar_vinculo_mb(sess, self.con, 1, self.cursos, 2)
        got = {r[0]: r[1] for r in self.con.execute(
            "SELECT item_id, vinculado_mb FROM aulas WHERE extracao_id=1")}
        self.assertEqual((got["i1"], got["i2"], got["i3"]), (1, 0, 1))

    def test_401_vira_cookie_vencido(self):
        sess = _Sessao({}, status=401)
        with self.assertRaises(coletor_ldi.CookieVencido):
            coletor_ldi._completar_vinculo_mb(sess, self.con, 1, self.cursos, 2)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `py -m unittest tests.test_coletor_vinculo_mb -v`
Expected: FAIL (`has no attribute '_completar_vinculo_mb'`).

- [ ] **Step 3: Implementar**

Em `coletor_ldi.py`, adicionar a função (logo após `_completar_autores`, reusando `ThreadPoolExecutor`/`as_completed` já importados no topo do arquivo):

```python
def _completar_vinculo_mb(sessao, con, extracao_id, cursos, concorrencia):
    """Vínculo com o Material Base por item (has_base_material) — vem só de
    GET /bo/ldi/chapters/{id}/items (o flag de capítulo subnotifica)."""
    caps = [cap.get("chapter_id") for c in cursos
            for cap in (c.get("content_tree_cache") or []) if cap.get("chapter_id")]

    def itens_do_cap(ch):
        r = sessao.get(f"{extrator_ldi.API}/bo/ldi/chapters/{ch}/items", timeout=60)
        if r.status_code in (401, 403):
            raise CookieVencido(1)
        if not r.ok:
            raise RuntimeError(f"HTTP {r.status_code}")
        return parse_blocos.vinculo_mb_dos_itens(r.json().get("data") or [])

    falhas = 0
    with ThreadPoolExecutor(max_workers=int(concorrencia)) as pool:
        futuros = {pool.submit(itens_do_cap, ch): ch for ch in caps}
        for fut in as_completed(futuros):
            try:
                vinc = fut.result()
                if vinc:
                    banco_conteudo.gravar_vinculo_mb(con, extracao_id, vinc)
            except CookieVencido:
                raise
            except Exception:  # enriquecimento: capítulo pontual falho não derruba
                falhas += 1
    if falhas:
        print(f"      ({falhas} capítulos sem vínculo de MB lido)")
```

Em `coletar()`, logo após a chamada de `_completar_autores(...)` (linha ~207), acrescentar:

```python
            print("      lendo vínculo com o Material Base (por item)...")
            _completar_vinculo_mb(sessao, con, extracao_id, cursos, cfg["concorrencia"])
```

Nota: `CookieVencido` e `parse_blocos` já estão disponíveis no módulo (import no topo; `CookieVencido = extrator_ldi.CookieVencido`).

- [ ] **Step 4: Rodar e ver passar**

Run: `py -m unittest tests.test_coletor_vinculo_mb -v`
Expected: PASS (2 testes).

- [ ] **Step 5: Commit**

```bash
git add coletor_ldi.py tests/test_coletor_vinculo_mb.py
git commit -m "feat(coletor): passo _completar_vinculo_mb (chapters/{id}/items)"
```

---

### Task 4: Agregação no `painel.py` (KPI, achado e coluna por aula)

**Files:**
- Modify: `painel.py` (`dados_do_snapshot`: kpis + achados; `dados_avaliacao`: por capítulo)
- Test: `tests/test_painel_vinculo_mb.py` (novo)

**Interfaces:**
- Consumes: coluna `aulas.vinculado_mb` (Task 1).
- Produces: em `dados_do_snapshot(con)["kpis"]` → `itens_mb`, `itens_total`; em `["achados"]` → `aulas_com_item_fora_mb`. Em cada capítulo de `dados_avaliacao(...)["capitulos"]` → `itens_mb`, `itens_total`.

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/test_painel_vinculo_mb.py`:

```python
import os, tempfile, unittest
import banco_conteudo
import painel


def _semear(con):
    con.execute("INSERT INTO extracoes(id, termo, vertical, iniciada_em, status) "
                "VALUES(1,'X','concursos','2026-07-23T00:00:00','completa')")
    con.execute("INSERT INTO cursos(extracao_id, curso_id, nome) VALUES(1,'cur1','Curso 1')")
    con.execute("INSERT INTO capitulos(extracao_id, curso_id, capitulo_id, nome, ordem) "
                "VALUES(1,'cur1','capA','Aula A',1)")
    con.execute("INSERT INTO capitulos(extracao_id, curso_id, capitulo_id, nome, ordem) "
                "VALUES(1,'cur1','capB','Aula B',2)")
    # capA: i1 vinculado, i2 fora  -> aula MISTA (conta como fora)
    # capB: i3 vinculado, i4 desconhecido(NULL)
    dados = [("capA", "i1", 1), ("capA", "i2", 0), ("capB", "i3", 1), ("capB", "i4", None)]
    for cap, item, v in dados:
        con.execute("INSERT INTO aulas(extracao_id, curso_id, capitulo_id, item_id, nome, vinculado_mb) "
                    "VALUES(1,'cur1',?,?,?,?)", (cap, item, item, v))
    con.commit()


class TestPainelVinculoMB(unittest.TestCase):
    def setUp(self):
        self.db = os.path.join(tempfile.mkdtemp(), "c.db")
        self.con = banco_conteudo.abrir(self.db)
        _semear(self.con)

    def test_kpi_itens_mb(self):
        d = painel.dados_do_snapshot(self.con)
        # conhecidos: i1,i2,i3 (i4 NULL não entra no total); vinculados: i1,i3
        self.assertEqual(d["kpis"]["itens_total"], 3)
        self.assertEqual(d["kpis"]["itens_mb"], 2)

    def test_achado_aulas_com_item_fora(self):
        d = painel.dados_do_snapshot(self.con)
        # só capA tem item conhecido fora do MB (i2=0); capB não tem 0
        self.assertEqual(d["achados"]["aulas_com_item_fora_mb"], 1)

    def test_avaliacao_por_aula(self):
        d = painel.dados_avaliacao(self.con, "cur1", depara={})
        por_nome = {c["nome"]: c for c in d["capitulos"]}
        self.assertEqual((por_nome["Aula A"]["itens_mb"], por_nome["Aula A"]["itens_total"]), (1, 2))
        self.assertEqual((por_nome["Aula B"]["itens_mb"], por_nome["Aula B"]["itens_total"]), (1, 1))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `py -m unittest tests.test_painel_vinculo_mb -v`
Expected: FAIL (`KeyError: 'itens_total'` etc.).

- [ ] **Step 3: Implementar**

Em `painel.py`, dentro de `dados_do_snapshot`, no dict `"kpis"` acrescentar duas chaves (o `vinculado_mb IS NOT NULL` garante que NULL não entra no total):

```python
            "itens_total": um("SELECT COUNT(*) FROM aulas WHERE extracao_id=? "
                              "AND vinculado_mb IS NOT NULL", e),
            "itens_mb": um("SELECT COUNT(*) FROM aulas WHERE extracao_id=? "
                           "AND vinculado_mb=1", e),
```

No dict `"achados"` acrescentar (conta aulas/capítulos com ≥1 item conhecido fora do MB):

```python
            "aulas_com_item_fora_mb": um(
                "SELECT COUNT(*) FROM (SELECT capitulo_id FROM aulas "
                "WHERE extracao_id=? AND vinculado_mb=0 GROUP BY curso_id, capitulo_id)", e),
```

Em `dados_avaliacao`, no dict `c = {...}` de cada capítulo, inicializar os campos:

```python
        c = {"nome": cap["nome"], "aulas": len(itens), "q_emb": 0, "q_txt": 0,
             "itens_mb": 0, "itens_total": 0,
             "bancas": {}, "q_ate": 0, "q_meio": 0, "q_novo": 0, "q_com_ano": 0,
             "sol_texto": 0, "sol_video": 0, "vids": 0, "dur": 0,
             "v_com_data": 0, "v_ate": 0, "v_meio": 0, "v_novo": 0}
        caps.append(c)
        if not itens:
            continue
        marks_i = ",".join("?" * len(itens))
        row_mb = con.execute(
            f"SELECT COUNT(*), SUM(vinculado_mb) FROM aulas WHERE extracao_id=? "
            f"AND vinculado_mb IS NOT NULL AND item_id IN ({marks_i})",
            (e, *itens)).fetchone()
        c["itens_total"] = row_mb[0] or 0
        c["itens_mb"] = row_mb[1] or 0
```

(inserir logo após `caps.append(c)` e o `if not itens: continue`).

- [ ] **Step 4: Rodar e ver passar**

Run: `py -m unittest tests.test_painel_vinculo_mb -v`
Expected: PASS (3 testes).

- [ ] **Step 5: Rodar a suíte inteira**

Run: `py -m unittest discover -s tests`
Expected: OK (todos verdes; hoje 79 + os novos).

- [ ] **Step 6: Commit**

```bash
git add painel.py tests/test_painel_vinculo_mb.py
git commit -m "feat(painel): KPI itens_mb + achado + coluna por aula (vínculo MB)"
```

---

### Task 5: Telas — KPI, achado e coluna (raiz + cópias web)

**Files:**
- Modify: `painel.html` e `web/telas/painel.html` (KPI + achado)
- Modify: `avaliacao.html` e `web/telas/avaliacao.html` (coluna por aula)

**Interfaces:**
- Consumes: `D.kpis.itens_mb`/`itens_total`, `D.achados.aulas_com_item_fora_mb`, `c.itens_mb`/`c.itens_total` (Task 4).

- [ ] **Step 1: painel.html — KPI novo**

Em `painel.html`, no array `kpis` (perto da linha 151, logo após o item de "itens únicos"), acrescentar um card. Usar guarda para snapshot antigo (total 0 → "—"):

```javascript
    { n: K.itens_total ? K.itens_mb : "—",
      l: "itens no Material Base",
      d: K.itens_total ? `de ${fmt(K.itens_total)} (${Math.round(K.itens_mb / K.itens_total * 100)}%)` : "sem dado neste snapshot" },
```

- [ ] **Step 2: painel.html — achado novo**

No array `achados` (perto da linha 173), acrescentar uma linha:

```javascript
    [X.aulas_com_item_fora_mb ? "warn" : "ok",
     `<b>${fmt(X.aulas_com_item_fora_mb)}</b> aulas com itens fora do Material Base`],
```

- [ ] **Step 3: Replicar em web/telas/painel.html**

Aplicar os Steps 1 e 2 idênticos em `web/telas/painel.html` (mesmos trechos; preservar as edições web-only de banner/links).

- [ ] **Step 4: avaliacao.html — coluna nova (thead + corpo)**

Em `avaliacao.html`, no `<thead>` (linha ~88), acrescentar a coluna após "Aula (LDI)":

```html
      <th>Aula (LDI)</th>
      <th>Itens no MB</th>
```

No render do corpo (`D.capitulos.map`, linha ~159), acrescentar a célula logo após a de `cap-nm` (linha ~165). Verde quando completo, amarelo quando incompleto, "—" quando desconhecido:

```javascript
        <td class="num">${c.itens_total
            ? `<b style="color:${c.itens_mb === c.itens_total ? "var(--ok)" : "var(--warn)"}">${c.itens_mb}/${c.itens_total}</b>`
            : "—"}</td>
```

E no CSV (`linhas`, ~202 e ~211) incluir a coluna: no cabeçalho após `"aulas"` adicionar `"itens_no_mb"`, e na linha do map após `c.aulas` adicionar `` `${c.itens_mb}/${c.itens_total}` ``.

- [ ] **Step 5: Replicar em web/telas/avaliacao.html**

Aplicar o Step 4 idêntico em `web/telas/avaliacao.html` (preservar edições web-only).

- [ ] **Step 6: Verificar paridade das cópias**

Run: `git diff --stat`
Expected: só `painel.html`, `web/telas/painel.html`, `avaliacao.html`, `web/telas/avaliacao.html` alterados. Conferir que as mudanças de conteúdo são idênticas entre raiz e cópia (diff manual dos trechos).

- [ ] **Step 7: Build web limpo**

Run (PowerShell): `cd web; npm run build`
Expected: compilado sem erro (as telas são estáticas, mas garante que nada quebrou o app).

- [ ] **Step 8: Commit**

```bash
git add painel.html avaliacao.html web/telas/painel.html web/telas/avaliacao.html
git commit -m "feat(ui): KPI/achado de vínculo MB na visão geral + coluna por aula"
```

---

### Task 6: Verificação real + docs

**Files:**
- Modify: `PROXIMA-SESSAO.md` (registrar a feature); `CLAUDE.md` (uma linha na seção de arquitetura sobre o vínculo MB)

- [ ] **Step 1: Coleta real de aceite (exige cookie válido no config_ldi)**

Rodar duas coletas por ID e conferir os números contra a sondagem. No PowerShell, da raiz:

```powershell
py coletor_ldi.py --ids "e93d81a4-9b73-4474-b885-136a3e2aef0a" --rotulo "TESTE Amparo MB"
py coletor_ldi.py --ids "d8970f8c-732d-4bc6-8bf3-bf9d53a9f314" --rotulo "TESTE DMAE MB"
```

Depois abrir `py painel.py --sem-navegador` e conferir via API local:

```powershell
# na visão geral do snapshot mais recente, itens_mb/itens_total
# aceite: Amparo 68/75 ; DMAE 319/345 (±, conforme edições recentes no admin)
```

Expected: KPI e coluna refletem ~68/75 (Amparo) e ~319/345 (DMAE); achado lista as aulas mistas. Registrar os números observados no commit.

- [ ] **Step 2: Atualizar docs**

Em `PROXIMA-SESSAO.md`, adicionar um parágrafo curto na seção da sessão atual (feature entregue, endpoint `chapters/{id}/items`, números de aceite). Em `CLAUDE.md`, uma linha na descrição do coletor citando o passo de vínculo MB e a coluna `aulas.vinculado_mb`.

- [ ] **Step 3: Commit**

```bash
git add PROXIMA-SESSAO.md CLAUDE.md
git commit -m "docs: registra o vínculo com o Material Base (por item)"
```

- [ ] **Step 4: Deixar pronto para o Clovis**

`git push` (a credencial costuma estar cacheada; se travar, deixar o comando pronto). Após o push, o worker no VPS precisa de `git pull` + `systemctl restart worker-coleta` para o passo novo valer nas coletas do VPS. PR → `main` (fluxo enxuto) ou merge direto se preferir.

## Self-Review (feita pelo autor do plano)
- **Cobertura do spec:** coleta (Tasks 1–3), agregação (Task 4), telas (Task 5), web via sync (automático — `sync_supabase` reusa `painel.py`, coberto pela Task 4), aceite/docs (Task 6). ✔
- **Denominador:** `itens_total` só conta `vinculado_mb IS NOT NULL` — NULL nunca vira "fora". Explícito nos testes das Tasks 1 e 4. ✔
- **Nomes consistentes:** `gravar_vinculo_mb`, `vinculo_mb_dos_itens`, `_completar_vinculo_mb`, chaves `itens_mb`/`itens_total`/`aulas_com_item_fora_mb` usadas igualzinho entre tasks e telas. ✔
- **Sem placeholders:** todo step tem código/comando real. ✔
