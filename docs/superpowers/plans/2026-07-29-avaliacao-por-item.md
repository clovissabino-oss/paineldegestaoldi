# Avaliação por item + ordem real do curso — plano de implementação

> **Para workers agênticos:** SUB-SKILL OBRIGATÓRIA: use superpowers:subagent-driven-development
> (recomendado) ou superpowers:executing-plans para implementar tarefa a tarefa. Os passos usam
> checkbox (`- [ ]`) para acompanhamento.

**Goal:** Expandir a tela `/avaliacao` do capítulo para o item (expandir/recolher) e fazer
capítulos e itens saírem na ordem real do curso.

**Architecture:** A ordem é derivada na **leitura**, do campo `aulas.path` (`"13.1"` → `(13, 1)`),
porque `capitulos.ordem` é zero em toda a base. A agregação de `painel.py` passa a ser feita
**por item**, e o capítulo vira a soma dos seus itens — o pai bate com os filhos por construção.
A tela e o CSV consomem o mesmo payload nos dois níveis.

**Tech Stack:** Python 3.12 (stdlib + `requests`/`flask` já existentes), SQLite, `unittest`,
HTML/JS vanilla inline.

**Spec:** `docs/superpowers/specs/2026-07-29-avaliacao-por-item-e-ordem-design.md`

**Branch:** `feat/avaliacao-por-item` (já criada, já contém o commit do spec).

## Global Constraints

- Idioma do projeto: **pt-BR** em código, comentários, docs, UI e mensagens.
- **Sem dependências novas.** Só stdlib do Python e JS vanilla.
- Testes: `py -m unittest discover -s tests` — a suíte inteira precisa ficar verde ao fim de
  cada tarefa, não só o teste novo.
- CSV: separador `;`, BOM utf-8 (`"﻿"`), quebra `\r\n` — padrão já usado no arquivo.
- **Não** tocar em `extrator_ldi.py`, `visualizador.py`, `ui.html`, `estoque.html`,
  `coletor_ldi.py`, `banco_conteudo.py` nem em nenhum schema (SQLite ou Supabase).
- `sync_supabase.py` **não** é editado: ele reusa `painel.dados_avaliacao` e herda tudo.
- As chaves e tipos já existentes no payload de capítulo são preservados; as adições
  (`num`, `itens`) são aditivas.
- Commits em pt-BR, formato `<tipo>: <descrição>` (`feat`, `fix`, `test`, `docs`).

## Estrutura de arquivos

| Arquivo | Responsabilidade | Ação |
|---|---|---|
| `painel.py` | Ordem (`_chave_*`) e agregação por item (`_metricas_zeradas`/`_acumular`/`_somar`/`dados_avaliacao`) | Modificar |
| `tests/test_painel_ordem.py` | Ordenação: path, empate, capítulo sem item, path torto | Criar |
| `tests/test_painel_itens.py` | Pai = soma dos filhos; escopo por curso; itens no payload | Criar |
| `avaliacao.html` | Expandir/recolher, numeração, CSV com `nivel`/`num` | Modificar |
| `web/telas/avaliacao.html` | Mesmas mudanças de tela (cópia web) | Modificar |
| `PROXIMA-SESSAO.md` | Registro da sessão | Modificar |

---

### Task 1: Chave de ordem e ordenação dos capítulos

**Files:**
- Modify: `painel.py` (acrescenta funções de ordem antes de `dados_avaliacao`, linha ~123)
- Test: `tests/test_painel_ordem.py` (criar)

**Interfaces:**
- Consumes: nada de tarefas anteriores.
- Produces:
  - `_chave_path(path: str) -> tuple[int, ...]` — `"13.1"` → `(13, 1)`; `()` quando não há
    nenhum componente numérico.
  - `_chave_capitulo(paths: list[str], nome: str) -> tuple[int, tuple, str]`
  - `_chave_item(path: str, nome: str) -> tuple[int, tuple, str]`
  - `_num_capitulo(chave) -> str` — `"13"`
  - `_num_item(chave) -> str` — `"13.1"`
  - `dados_avaliacao` passa a devolver capítulos ordenados, cada um com a chave `num`.

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/test_painel_ordem.py`:

```python
# -*- coding: utf-8 -*-
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import banco_conteudo
import painel


def _semear(con, capitulos):
    """capitulos = [(capitulo_id, nome, [(item_id, nome_item, path), ...]), ...]"""
    con.execute("INSERT INTO extracoes(id, termo, vertical, iniciada_em, status) "
                "VALUES(1,'T','concursos','2026-07-29T00:00:00','completa')")
    con.execute("INSERT INTO cursos(extracao_id, curso_id, nome) VALUES(1,'cur1','Curso 1')")
    for cap_id, nome, itens in capitulos:
        con.execute("INSERT INTO capitulos(extracao_id, curso_id, capitulo_id, nome, ordem) "
                    "VALUES(1,'cur1',?,?,0)", (cap_id, nome))
        for item_id, nome_item, path in itens:
            con.execute("INSERT INTO aulas(extracao_id, curso_id, capitulo_id, item_id, "
                        "nome, path) VALUES(1,'cur1',?,?,?,?)",
                        (cap_id, item_id, nome_item, path))
    con.commit()


class TestChavePath(unittest.TestCase):
    def test_converte_para_tupla_de_inteiros(self):
        self.assertEqual(painel._chave_path("13.1"), (13, 1))

    def test_ordena_numericamente_e_nao_como_texto(self):
        # a armadilha: como texto, "10" viria antes de "2"
        self.assertLess(painel._chave_path("2"), painel._chave_path("10"))

    def test_path_vazio_ou_sem_numero_devolve_vazio(self):
        self.assertEqual(painel._chave_path(""), ())
        self.assertEqual(painel._chave_path(None), ())
        self.assertEqual(painel._chave_path("abc"), ())


class TestOrdemDosCapitulos(unittest.TestCase):
    def _ordem(self, capitulos):
        with tempfile.TemporaryDirectory() as d:
            con = banco_conteudo.abrir(os.path.join(d, "c.db"))
            _semear(con, capitulos)
            dados = painel.dados_avaliacao(con, "cur1", depara={})
            con.close()
        return [c["nome"] for c in dados["capitulos"]]

    def test_ordena_pelo_path_das_aulas(self):
        # inseridos fora de ordem de proposito
        ordem = self._ordem([
            ("capC", "Terceiro", [("i5", "a", "3.1")]),
            ("capA", "Primeiro", [("i1", "a", "1.1"), ("i2", "b", "1.2")]),
            ("capB", "Segundo", [("i3", "a", "2.1")]),
        ])
        self.assertEqual(ordem, ["Primeiro", "Segundo", "Terceiro"])

    def test_capitulo_10_vem_depois_do_2(self):
        ordem = self._ordem([
            ("cap10", "Decimo", [("i10", "a", "10.1")]),
            ("cap2", "Segundo", [("i2", "a", "2.1")]),
        ])
        self.assertEqual(ordem, ["Segundo", "Decimo"])

    def test_capitulo_sem_item_usa_o_numero_do_nome(self):
        ordem = self._ordem([
            ("capC", "3. Terceiro", [("i3", "a", "3.1")]),
            ("capB", "2. Vazio sem aula", []),
            ("capA", "1. Primeiro", [("i1", "a", "1.1")]),
        ])
        self.assertEqual(ordem, ["1. Primeiro", "2. Vazio sem aula", "3. Terceiro"])

    def test_capitulo_sem_numero_nenhum_vai_para_o_fim_sem_sumir(self):
        ordem = self._ordem([
            ("capX", "Zebra sem numero", []),
            ("capA", "Primeiro", [("i1", "a", "1.1")]),
        ])
        self.assertEqual(ordem, ["Primeiro", "Zebra sem numero"])

    def test_path_torto_nao_derruba_a_agregacao(self):
        ordem = self._ordem([
            ("capA", "Com path", [("i1", "a", "1.1")]),
            ("capB", "Path torto", [("i2", "b", "xx.yy")]),
        ])
        self.assertEqual(sorted(ordem), ["Com path", "Path torto"])

    def test_capitulo_expoe_o_numero_para_exibicao(self):
        with tempfile.TemporaryDirectory() as d:
            con = banco_conteudo.abrir(os.path.join(d, "c.db"))
            _semear(con, [("capA", "Funcao Exponencial",
                           [("i1", "a", "13.1"), ("i2", "b", "13.2")])])
            dados = painel.dados_avaliacao(con, "cur1", depara={})
            con.close()
        self.assertEqual(dados["capitulos"][0]["num"], "13")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar o teste e confirmar que FALHA**

Run: `py -m unittest tests.test_painel_ordem -v`
Expected: FAIL — `AttributeError: module 'painel' has no attribute '_chave_path'`

- [ ] **Step 3: Implementar as funções de ordem**

Em `painel.py`, garantir `import re` no topo (junto dos imports já existentes) e inserir
**antes** de `def dados_avaliacao` (linha ~123):

```python
_RE_NUM_NOME = re.compile(r"^\s*(\d+)")


def _chave_path(path):
    """'13.1' -> (13, 1). Devolve () quando não há nenhum componente numérico.

    A ordem do LDI vem daqui: `capitulos.ordem` é zero em toda a base (a API manda
    order_index=0), então o path da aula é a única fonte real de posição — e ele é
    relativo ao curso (o mesmo item tem path diferente em cada pacote).
    """
    partes = [p.strip() for p in str(path or "").split(".") if p.strip() != ""]
    if not any(p.isdigit() for p in partes):
        return ()
    return tuple(int(p) if p.isdigit() else 0 for p in partes)


def _chave_capitulo(paths, nome):
    """Ordem do capítulo: menor path entre os itens; sem itens, o número do nome;
    sem nada disso, vai para o fim em ordem alfabética. Nunca lança."""
    nm = (nome or "").strip().lower()
    chaves = [k for k in (_chave_path(p) for p in paths) if k]
    if chaves:
        return (0, min(chaves), nm)
    achado = _RE_NUM_NOME.match(nome or "")
    if achado:
        return (0, (int(achado.group(1)),), nm)
    return (1, (), nm)


def _chave_item(path, nome):
    """Ordem do item dentro do capítulo; sem path utilizável, vai para o fim."""
    nm = (nome or "").strip().lower()
    k = _chave_path(path)
    return (0, k, nm) if k else (1, (), nm)


def _num_capitulo(chave):
    """Numeração exibida do capítulo: '13'."""
    return str(chave[1][0]) if chave[0] == 0 and chave[1] else ""


def _num_item(chave):
    """Numeração exibida do item: '13.1'."""
    return ".".join(str(x) for x in chave[1]) if chave[0] == 0 and chave[1] else ""
```

- [ ] **Step 4: Ordenar os capítulos em `dados_avaliacao`**

Em `painel.py`, dentro de `dados_avaliacao`, trocar o cabeçalho do laço. **Antes:**

```python
    for cap in con.execute("SELECT capitulo_id, nome FROM capitulos "
                           "WHERE extracao_id=? AND curso_id=? ORDER BY ordem", (e, curso_id)):
        itens = [r[0] for r in con.execute(
            "SELECT item_id FROM aulas WHERE extracao_id=? AND curso_id=? AND capitulo_id=?",
            (e, curso_id, cap["capitulo_id"]))]
```

**Depois** (o `ORDER BY ordem` sai — a coluna é zero em toda a base; passamos a ler o `path`):

```python
    for cap in con.execute("SELECT capitulo_id, nome FROM capitulos "
                           "WHERE extracao_id=? AND curso_id=?", (e, curso_id)):
        linhas = con.execute(
            "SELECT item_id, nome, path FROM aulas "
            "WHERE extracao_id=? AND curso_id=? AND capitulo_id=?",
            (e, curso_id, cap["capitulo_id"])).fetchall()
        itens = [r["item_id"] for r in linhas]
        chave_cap = _chave_capitulo([r["path"] for r in linhas], cap["nome"])
```

Ainda em `dados_avaliacao`, no dicionário `c` do capítulo, acrescentar duas chaves logo
depois de `"nome"` (as demais ficam como estão):

```python
        c = {"nome": cap["nome"], "num": _num_capitulo(chave_cap), "aulas": len(itens),
             "q_emb": 0, "q_txt": 0,
```

E guardar a chave para ordenar no fim (linha seguinte ao `caps.append(c)`):

```python
        c["_chave"] = chave_cap
```

Por fim, antes do `return`, ordenar e limpar a chave interna:

```python
    caps.sort(key=lambda c: c["_chave"])
    for c in caps:
        c.pop("_chave")
    return {"curso": curso["nome"], "autores": curso["autores"] or "", "capitulos": caps}
```

- [ ] **Step 5: Rodar os testes e confirmar que PASSAM**

Run: `py -m unittest tests.test_painel_ordem -v`
Expected: PASS (10 testes)

Run: `py -m unittest discover -s tests`
Expected: OK — a suíte inteira verde. `tests/test_painel_dados.py` e
`tests/test_painel_vinculo_mb.py` continuam passando (usam `path` `"1"`/`"2"` e nomes sem
número, então a ordem derivada bate com a antiga).

- [ ] **Step 6: Commit**

```bash
git add painel.py tests/test_painel_ordem.py
git commit -m "feat: ordena a avaliacao pela ordem real do curso (path da aula)

capitulos.ordem e zero em todos os 2.547 capitulos da base porque a API
devolve order_index=0. A ordem passa a ser derivada do path da aula, que
e relativo ao curso, e conserta retroativamente todos os snapshots."
```

---

### Task 2: Contagem de Material Base escopada pelo curso

**Files:**
- Modify: `painel.py` (`dados_avaliacao`, o bloco `row_mb` — linhas ~147-152 do original)
- Test: `tests/test_painel_itens.py` (criar; a classe de escopo)

**Interfaces:**
- Consumes: `_chave_capitulo`, `_num_capitulo` (Task 1) e o `SELECT ... FROM aulas` que já
  traz `item_id, nome, path`.
- Produces: `dados_avaliacao` com `itens_total`/`itens_mb` contando **uma linha por item do
  curso**; a query auxiliar de MB deixa de existir.

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/test_painel_itens.py`:

```python
# -*- coding: utf-8 -*-
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import banco_conteudo
import painel


class TestEscopoPorCurso(unittest.TestCase):
    """Item compartilhado entre pacotes conta uma vez em CADA curso, nunca duas no mesmo.

    No BACEN, 1.990 dos 3.612 itens vivem em mais de um curso: o mesmo
    'Atos Administrativos' aparece em 6 pacotes, com path 6.4, 5.4 e 1.4.
    """

    def _con(self, d):
        con = banco_conteudo.abrir(os.path.join(d, "c.db"))
        con.execute("INSERT INTO extracoes(id, termo, vertical, iniciada_em, status) "
                    "VALUES(1,'BACEN','concursos','2026-07-29T00:00:00','completa')")
        for cid, nome in (("cur1", "Analista"), ("cur2", "Tecnico")):
            con.execute("INSERT INTO cursos(extracao_id, curso_id, nome) VALUES(1,?,?)",
                        (cid, nome))
            con.execute("INSERT INTO capitulos(extracao_id, curso_id, capitulo_id, nome, ordem) "
                        "VALUES(1,?,'capA','Atos Administrativos',0)", (cid,))
        # MESMO item_id nos dois cursos, com path diferente em cada um
        con.execute("INSERT INTO aulas(extracao_id, curso_id, capitulo_id, item_id, nome, "
                    "path, vinculado_mb) VALUES(1,'cur1','capA','compartilhado','Atos','6.4',1)")
        con.execute("INSERT INTO aulas(extracao_id, curso_id, capitulo_id, item_id, nome, "
                    "path, vinculado_mb) VALUES(1,'cur2','capA','compartilhado','Atos','1.4',1)")
        con.commit()
        return con

    def test_item_compartilhado_conta_uma_vez_no_curso(self):
        with tempfile.TemporaryDirectory() as d:
            con = self._con(d)
            cap = painel.dados_avaliacao(con, "cur1", depara={})["capitulos"][0]
            con.close()
        self.assertEqual((cap["itens_mb"], cap["itens_total"]), (1, 1))

    def test_cada_curso_usa_o_proprio_path(self):
        with tempfile.TemporaryDirectory() as d:
            con = self._con(d)
            n1 = painel.dados_avaliacao(con, "cur1", depara={})["capitulos"][0]["num"]
            n2 = painel.dados_avaliacao(con, "cur2", depara={})["capitulos"][0]["num"]
            con.close()
        self.assertEqual((n1, n2), ("6", "1"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar o teste e confirmar que FALHA**

Run: `py -m unittest tests.test_painel_itens -v`
Expected: `test_item_compartilhado_conta_uma_vez_no_curso` FALHA com
`(2, 2) != (1, 1)` — a consulta atual não filtra por curso e conta o item uma vez por
pacote. (`test_cada_curso_usa_o_proprio_path` já passa, graças à Task 1.)

- [ ] **Step 3: Trazer o `vinculado_mb` junto com os itens do capítulo**

Em `painel.py`, `dados_avaliacao`, acrescentar a coluna à consulta da Task 1:

```python
        linhas = con.execute(
            "SELECT item_id, nome, path, vinculado_mb FROM aulas "
            "WHERE extracao_id=? AND curso_id=? AND capitulo_id=?",
            (e, curso_id, cap["capitulo_id"])).fetchall()
```

- [ ] **Step 4: Remover a consulta que vazava o filtro**

**Apagar** este bloco inteiro (o `marks_i`/`row_mb` e as duas atribuições):

```python
        marks_i = ",".join("?" * len(itens))
        row_mb = con.execute(
            f"SELECT COUNT(*), SUM(vinculado_mb) FROM aulas WHERE extracao_id=? "
            f"AND vinculado_mb IS NOT NULL AND item_id IN ({marks_i})",
            (e, *itens)).fetchone()
        c["itens_total"] = row_mb[0] or 0
        c["itens_mb"] = row_mb[1] or 0
```

**Substituir** por (contando só as linhas do curso e capítulo corrente):

```python
        conhecidos = [r["vinculado_mb"] for r in linhas if r["vinculado_mb"] is not None]
        c["itens_total"] = len(conhecidos)
        c["itens_mb"] = sum(1 for v in conhecidos if v)
```

⚠ Esse bloco fica **antes** do `if not itens: continue`, senão capítulo vazio pula a
contagem. Conferir a ordem das linhas ao editar.

- [ ] **Step 5: Rodar os testes e confirmar que PASSAM**

Run: `py -m unittest tests.test_painel_itens -v`
Expected: PASS (2 testes)

Run: `py -m unittest discover -s tests`
Expected: OK. Em especial `tests/test_painel_vinculo_mb.py::test_avaliacao_por_aula`
continua dando `(1, 2)` e `(1, 1)` — lá nenhum item é compartilhado.

- [ ] **Step 6: Commit**

```bash
git add painel.py tests/test_painel_itens.py
git commit -m "fix: contagem de Itens no MB escapava do filtro de curso

A consulta somava aulas por item_id sem filtrar curso/capitulo. Como
1.990 dos 3.612 itens do BACEN vivem em mais de um pacote, o item
compartilhado era contado uma vez por curso e inflava o capitulo.
Agora o vinculado_mb vem na mesma consulta que lista os itens do
capitulo, ja filtrada por curso."
```

---

### Task 3: Agregação por item

**Files:**
- Modify: `painel.py` (`dados_avaliacao` + três funções novas)
- Test: `tests/test_painel_itens.py` (acrescentar classe)

**Interfaces:**
- Consumes: `_chave_item`, `_num_item` (Task 1); o `linhas` com `vinculado_mb` (Task 2).
- Produces: cada capítulo do payload ganha `itens: list[dict]`, ordenada, em que cada item
  tem **as mesmas chaves do capítulo** (`nome`, `num`, `aulas`, `q_emb`, `q_txt`,
  `itens_mb`, `itens_total`, `bancas`, `q_ate`, `q_meio`, `q_novo`, `q_com_ano`,
  `sol_texto`, `sol_video`, `vids`, `dur`, `v_com_data`, `v_ate`, `v_meio`, `v_novo`) e
  `aulas == 1`. O item **não** tem a chave `itens`.
- Funções novas: `_metricas_zeradas(nome, num, aulas=1) -> dict`,
  `_acumular(m, bloco, depara, corte_crit, corte_aten) -> None`,
  `_somar(destino, origem) -> None`.

- [ ] **Step 1: Escrever o teste que falha**

Acrescentar a `tests/test_painel_itens.py`, antes do `if __name__`:

```python
B_Q_2019 = {"bloco_id": "q1", "tipo": "question", "ordem": 1, "ativo": 1, "rascunho": 0,
            "titulo": "", "questao_id": "10", "resposta_tipo": "TRUE_OR_FALSE",
            "tem_solucao": 1, "tem_video_solucao": 0, "video_id_antigo": "",
            "duracao_seg": None, "tamanho_texto": None, "banca": "CESPE (CEBRASPE)",
            "ano": 2019, "qtd_questoes_texto": None, "meta": {}}
B_Q_2025 = {**B_Q_2019, "bloco_id": "q2", "questao_id": "11", "banca": "FGV", "ano": 2025}
B_VIDEO = {"bloco_id": "v1", "tipo": "videoMyDocuments", "ordem": 2, "ativo": 1,
           "rascunho": 0, "titulo": "v", "questao_id": "", "resposta_tipo": "",
           "tem_solucao": None, "tem_video_solucao": None, "video_id_antigo": "999",
           "duracao_seg": 600, "tamanho_texto": None, "banca": "", "ano": None,
           "qtd_questoes_texto": None, "meta": {}}


class TestAgregacaoPorItem(unittest.TestCase):
    def _capitulo(self):
        d = tempfile.mkdtemp()
        con = banco_conteudo.abrir(os.path.join(d, "c.db"))
        con.execute("INSERT INTO extracoes(id, termo, vertical, iniciada_em, status) "
                    "VALUES(1,'T','concursos','2026-07-29T00:00:00','completa')")
        con.execute("INSERT INTO cursos(extracao_id, curso_id, nome) VALUES(1,'cur1','C')")
        con.execute("INSERT INTO capitulos(extracao_id, curso_id, capitulo_id, nome, ordem) "
                    "VALUES(1,'cur1','capA','Funcao Exponencial',0)")
        for item_id, nome, path, mb in (("i1", "Teoria", "13.1", 1),
                                        ("i2", "Questoes", "13.2", 0),
                                        ("i3", "Revisao", "13.3", None)):
            con.execute("INSERT INTO aulas(extracao_id, curso_id, capitulo_id, item_id, "
                        "nome, path, vinculado_mb) VALUES(1,'cur1','capA',?,?,?,?)",
                        (item_id, nome, path, mb))
        con.commit()
        banco_conteudo.gravar_blocos_da_aula(con, 1, "i1", [B_Q_2019, B_VIDEO])
        banco_conteudo.gravar_blocos_da_aula(con, 1, "i2", [B_Q_2025])
        banco_conteudo.gravar_blocos_da_aula(con, 1, "i3", [])
        cap = painel.dados_avaliacao(
            con, "cur1", depara={"999": {"data": "2019-05-01"}})["capitulos"][0]
        con.close()
        return cap

    def test_capitulo_traz_os_itens_ordenados_com_numeracao(self):
        cap = self._capitulo()
        self.assertEqual([i["num"] for i in cap["itens"]], ["13.1", "13.2", "13.3"])
        self.assertEqual([i["nome"] for i in cap["itens"]], ["Teoria", "Questoes", "Revisao"])

    def test_item_tem_as_mesmas_chaves_do_capitulo(self):
        cap = self._capitulo()
        esperadas = set(cap) - {"itens"}
        self.assertEqual(set(cap["itens"][0]), esperadas)
        self.assertEqual(cap["itens"][0]["aulas"], 1)

    def test_pai_e_a_soma_dos_filhos(self):
        cap = self._capitulo()
        contadores = ("q_emb", "q_txt", "itens_mb", "itens_total", "q_ate", "q_meio",
                      "q_novo", "q_com_ano", "sol_texto", "sol_video", "vids", "dur",
                      "v_com_data", "v_ate", "v_meio", "v_novo")
        for k in contadores:
            self.assertEqual(cap[k], sum(i[k] for i in cap["itens"]), f"divergiu em {k}")

    def test_mapa_de_bancas_do_pai_e_a_soma_dos_filhos(self):
        cap = self._capitulo()
        somado = {}
        for i in cap["itens"]:
            for b, n in i["bancas"].items():
                somado[b] = somado.get(b, 0) + n
        self.assertEqual(cap["bancas"], somado)
        self.assertEqual(cap["bancas"], {"CESPE (CEBRASPE)": 1, "FGV": 1})

    def test_metricas_ficam_no_item_certo(self):
        por_nome = {i["nome"]: i for i in self._capitulo()["itens"]}
        # i1: 1 questao 2019 (faixa critica) + 1 video gravado em 2019
        self.assertEqual((por_nome["Teoria"]["q_emb"], por_nome["Teoria"]["vids"]), (1, 1))
        self.assertEqual(por_nome["Teoria"]["dur"], 600)
        self.assertEqual(por_nome["Teoria"]["q_ate"], 1)
        # i2: 1 questao 2025 (faixa recente), sem video
        self.assertEqual((por_nome["Questoes"]["q_novo"], por_nome["Questoes"]["vids"]), (1, 0))
        # i3: sem bloco nenhum
        self.assertEqual((por_nome["Revisao"]["q_emb"], por_nome["Revisao"]["vids"]), (0, 0))

    def test_vinculo_mb_por_item(self):
        por_nome = {i["nome"]: i for i in self._capitulo()["itens"]}
        self.assertEqual((por_nome["Teoria"]["itens_mb"],
                          por_nome["Teoria"]["itens_total"]), (1, 1))
        self.assertEqual((por_nome["Questoes"]["itens_mb"],
                          por_nome["Questoes"]["itens_total"]), (0, 1))
        # NULL = desconhecido: nao entra no denominador
        self.assertEqual((por_nome["Revisao"]["itens_mb"],
                          por_nome["Revisao"]["itens_total"]), (0, 0))

    def test_capitulo_sem_item_tem_lista_vazia(self):
        with tempfile.TemporaryDirectory() as d:
            con = banco_conteudo.abrir(os.path.join(d, "c.db"))
            con.execute("INSERT INTO extracoes(id, termo, vertical, iniciada_em, status) "
                        "VALUES(1,'T','concursos','2026-07-29T00:00:00','completa')")
            con.execute("INSERT INTO cursos(extracao_id, curso_id, nome) VALUES(1,'cur1','C')")
            con.execute("INSERT INTO capitulos(extracao_id, curso_id, capitulo_id, nome, "
                        "ordem) VALUES(1,'cur1','vazio','24. Crimes',0)")
            con.commit()
            cap = painel.dados_avaliacao(con, "cur1", depara={})["capitulos"][0]
            con.close()
        self.assertEqual(cap["itens"], [])
        self.assertEqual(cap["aulas"], 0)
```

- [ ] **Step 2: Rodar o teste e confirmar que FALHA**

Run: `py -m unittest tests.test_painel_itens -v`
Expected: FAIL — `KeyError: 'itens'` nos testes novos (os 2 da Task 2 seguem passando).

- [ ] **Step 3: Criar as três funções de agregação**

Em `painel.py`, inserir **antes** de `def dados_avaliacao` (depois das funções de ordem):

```python
_CONTADORES = ("q_emb", "q_txt", "itens_mb", "itens_total", "q_ate", "q_meio", "q_novo",
               "q_com_ano", "sol_texto", "sol_video", "vids", "dur", "v_com_data",
               "v_ate", "v_meio", "v_novo")


def _metricas_zeradas(nome, num, aulas=1):
    """Linha da planilha de avaliação. Capítulo e item usam o MESMO formato — o item é
    uma linha com aulas=1, o que deixa tela e CSV desenharem os dois níveis igual."""
    m = {"nome": nome, "num": num, "aulas": aulas, "bancas": {}}
    m.update({k: 0 for k in _CONTADORES})
    return m


def _acumular(m, b, depara, corte_crit, corte_aten):
    """Aplica um bloco sobre uma linha de métricas."""
    def faixa(pref, ano):
        m["q_com_ano" if pref == "q" else "v_com_data"] += 1
        if ano <= corte_crit:
            m[f"{pref}_ate"] += 1
        elif ano <= corte_aten:
            m[f"{pref}_meio"] += 1
        else:
            m[f"{pref}_novo"] += 1

    if b["tipo"] == "question":
        m["q_emb"] += 1
        m["sol_texto"] += b["tem_solucao"] or 0
        m["sol_video"] += b["tem_video_solucao"] or 0
        if b["banca"]:
            m["bancas"][b["banca"]] = m["bancas"].get(b["banca"], 0) + 1
        if b["ano"]:
            faixa("q", b["ano"])
    elif b["tipo"] == "tiptap" and (b["qtd_questoes_texto"] or 0) > 0:
        m["q_txt"] += b["qtd_questoes_texto"]
        for ref in (json.loads(b["meta"] or "{}").get("questoes_texto") or []):
            if ref.get("banca"):
                m["bancas"][ref["banca"]] = m["bancas"].get(ref["banca"], 0) + 1
            if ref.get("ano"):
                faixa("q", ref["ano"])
    elif b["tipo"] in ("videoMyDocuments", "cast", "youtube"):
        m["vids"] += 1
        m["dur"] += b["duracao_seg"] or 0
        data = ((depara or {}).get(b["video_id_antigo"]) or {}).get("data") or ""
        if data[:4].isdigit():
            faixa("v", int(data[:4]))


def _somar(destino, origem):
    """Soma uma linha na outra: números somam, mapa de bancas mescla."""
    for k in _CONTADORES:
        destino[k] += origem[k]
    for banca, n in origem["bancas"].items():
        destino["bancas"][banca] = destino["bancas"].get(banca, 0) + n
```

- [ ] **Step 4: Reescrever o corpo do laço de `dados_avaliacao`**

Substituir **todo** o corpo do laço (do `linhas = con.execute(...)` até o fim do laço,
incluindo o `if not itens: continue`, o `def faixa` interno, o `marks` e o `for b in
con.execute(...)`) por:

```python
        linhas = con.execute(
            "SELECT item_id, nome, path, vinculado_mb FROM aulas "
            "WHERE extracao_id=? AND curso_id=? AND capitulo_id=?",
            (e, curso_id, cap["capitulo_id"])).fetchall()
        chave_cap = _chave_capitulo([r["path"] for r in linhas], cap["nome"])

        itens, por_id = [], {}
        for r in linhas:
            chave = _chave_item(r["path"], r["nome"])
            m = _metricas_zeradas(r["nome"] or "", _num_item(chave))
            m["_chave"] = chave
            if r["vinculado_mb"] is not None:
                m["itens_total"] = 1
                m["itens_mb"] = 1 if r["vinculado_mb"] else 0
            itens.append(m)
            por_id[r["item_id"]] = m

        if por_id:
            # UMA consulta por capítulo (como antes) — os baldes são separados aqui.
            marks = ",".join("?" * len(por_id))
            for b in con.execute(
                    f"SELECT item_id, tipo, banca, ano, tem_solucao, tem_video_solucao, "
                    f"video_id_antigo, duracao_seg, qtd_questoes_texto, meta FROM blocos "
                    f"WHERE extracao_id=? AND item_id IN ({marks})", (e, *por_id)):
                m = por_id.get(b["item_id"])
                if m is not None:
                    _acumular(m, b, depara, corte_crit, corte_aten)

        itens.sort(key=lambda m: m["_chave"])
        c = _metricas_zeradas(cap["nome"], _num_capitulo(chave_cap), aulas=len(itens))
        for m in itens:
            _somar(c, m)
        c["_chave"] = chave_cap
        c["itens"] = [{k: v for k, v in m.items() if k != "_chave"} for m in itens]
        caps.append(c)
```

⚠ O `c = {...}` literal com os contadores zerados e o `caps.append(c)` que ficavam **no
início** do laço somem — agora o capítulo só é montado depois de somar os itens.

- [ ] **Step 5: Rodar os testes e confirmar que PASSAM**

Run: `py -m unittest tests.test_painel_itens -v`
Expected: PASS (9 testes)

Run: `py -m unittest discover -s tests`
Expected: OK — a suíte inteira. `test_painel_dados.py::test_agrega_por_capitulo_com_faixas_e_solucoes`
é o guarda-costas aqui: os números do capítulo não podem mudar com a refatoração.

- [ ] **Step 6: Commit**

```bash
git add painel.py tests/test_painel_itens.py
git commit -m "feat: avaliacao agrega por item e o capitulo vira a soma dos itens

Cada capitulo do payload passa a trazer itens[], cada um com as mesmas
chaves da linha do capitulo. O pai e a soma dos filhos por construcao —
e a mesma conta, entao a tela nao tem como divergir. Mantida UMA consulta
de blocos por capitulo (nada de N+1)."
```

---

### Task 4: Expandir/recolher na tela

**Files:**
- Modify: `avaliacao.html` (CSS ~linha 54, barra ~linha 80, `render()` ~linhas 155-200,
  `carregarAvaliacao()` ~linha 128)

**Interfaces:**
- Consumes: `capitulo.num`, `capitulo.itens` (Task 3).
- Produces: `ABERTOS` (Set de índices), `linhaHtml(c, ehItem, idx, aberto)`, `alternar(i)`,
  `alternarTudo()`. A Task 6 replica exatamente estas mudanças na cópia web.

- [ ] **Step 1: Acrescentar o CSS**

Em `avaliacao.html`, depois da regra `.cap-nm small { ... }` (linha ~55):

```css
  .exp { background: none; border: 0; color: var(--ink-3); cursor: pointer; font: inherit;
         padding: 0 6px 0 0; }
  .exp:hover { color: var(--accent); }
  .exp.vazio-cap { visibility: hidden; }
  tr.item td { background: transparent; border-bottom: 1px dashed var(--border); }
  tr.item .cap-nm { font-weight: 400; padding-left: 30px; color: var(--ink-2); }
```

- [ ] **Step 2: Acrescentar o botão na barra**

Na `<div class="barra">`, antes do botão de CSV (linha ~80):

```html
    <button class="btn" id="btnExpandir" onclick="alternarTudo()">⊕ Expandir tudo</button>
```

- [ ] **Step 3: Escrever o estado e as funções de expansão**

Logo depois de `let D = null;` (linha ~116):

```js
  // índices dos capítulos abertos. Fica FORA do render porque a tabela é redesenhada
  // inteira ao trocar a banca-alvo — sem isso, trocar a banca fecharia tudo.
  const ABERTOS = new Set();

  function alternar(i) {
    ABERTOS.has(i) ? ABERTOS.delete(i) : ABERTOS.add(i);
    render();
  }

  function alternarTudo() {
    const comItens = D.capitulos.map((c, i) => [c, i]).filter(([c]) => (c.itens || []).length);
    if (ABERTOS.size >= comItens.length) ABERTOS.clear();
    else comItens.forEach(([, i]) => ABERTOS.add(i));
    render();
  }
```

- [ ] **Step 4: Extrair a linha e desenhar os dois níveis**

Em `render()`, substituir o bloco `document.getElementById("corpo").innerHTML = D.capitulos.map(c => { ... }).join("");`
(linhas ~160-184) por:

```js
    document.getElementById("corpo").innerHTML = D.capitulos.map((c, i) => {
      const aberto = ABERTOS.has(i);
      const html = [linhaHtml(c, false, i, aberto)];
      if (aberto) (c.itens || []).forEach(it => html.push(linhaHtml(it, true, i, false)));
      return html.join("");
    }).join("");

    const comItens = D.capitulos.filter(c => (c.itens || []).length).length;
    document.getElementById("btnExpandir").textContent =
      ABERTOS.size >= comItens && comItens ? "⊖ Recolher tudo" : "⊕ Expandir tudo";
```

E criar `linhaHtml` logo antes de `function render()` (linha ~155). O corpo das 7 células
seguintes é **idêntico** ao que estava no `map`; só a primeira célula muda:

```js
  function linhaHtml(c, ehItem, idx, aberto) {
    const totQ = c.q_emb + c.q_txt;
    const alvo = alvoDe(c);
    const banca = document.getElementById("selBanca").value;
    const bancasTxt = Object.entries(c.bancas).sort((x, y) => y[1] - x[1]).slice(0, 3)
      .map(([b, n]) => `${b.replace(" (CEBRASPE)", "")}: ${n}`).join("<br>") || "—";
    const nome = (c.nome || "").trim();
    const cel1 = ehItem
      ? `<td class="cap-nm">${c.num ? c.num + " " : ""}${nome}</td>`
      : `<td class="cap-nm"><button class="exp${(c.itens || []).length ? "" : " vazio-cap"}"
             onclick="alternar(${idx})">${aberto ? "▼" : "▶"}</button>${c.num ? c.num + ". " : ""}${nome}<small>${c.aulas} itens</small></td>`;
    return `<tr${ehItem ? ' class="item"' : ""}>
        ${cel1}
        <td class="num">${c.itens_total
            ? `<b style="color:${c.itens_mb === c.itens_total ? "var(--ok)" : "var(--warn)"}">${c.itens_mb}/${c.itens_total}</b>`
            : "—"}</td>
        <td class="num">${fmt(totQ)}<br><small style="color:var(--ink-3)">${c.q_emb} emb. + ${c.q_txt} texto</small></td>
        <td class="num">${totQ === 0 ? '<span class="vazio">—</span>' : banca
          ? `${alvo} / ${totQ - alvo}<br><b>${pc(alvo, totQ)}</b> banca-alvo`
          : `<small>${bancasTxt}</small>`}</td>
        <td>${faixaHtml(c.q_ate, c.q_meio, c.q_novo, c.q_com_ano)}
          ${c.q_com_ano ? `<div class="pct-leg">${c.q_com_ano} com prova identificada</div>` : ""}</td>
        <td class="sol">${c.q_emb === 0 ? '<span class="vazio">' + (c.q_txt ? "— (só em texto)" : "—") + "</span>" : `
          📝 <b>${c.sol_texto}</b> <span class="pct">(${pc(c.sol_texto, c.q_emb)})</span> ·
          🎬 <b>${c.sol_video}</b> <span class="pct">(${pc(c.sol_video, c.q_emb)})</span><br>
          <span class="pct">das ${c.q_emb} embedadas</span>`}</td>
        <td class="num">${c.vids} · ${dur(c.dur)}</td>
        <td>${faixaHtml(c.v_ate, c.v_meio, c.v_novo, c.v_com_data)}
          ${c.vids ? `<div class="pct-leg">${c.v_com_data} de ${c.vids} com data real</div>` : ""}</td>
      </tr>`;
  }
```

- [ ] **Step 5: Zerar o estado ao trocar de disciplina**

Em `carregarAvaliacao()`, logo depois de `D = (await r.json()).data;`:

```js
    ABERTOS.clear();
```

- [ ] **Step 6: Testar na mão**

```powershell
py painel.py --sem-navegador
```

Abrir `http://127.0.0.1:8766/avaliacao` e conferir:
1. A tabela abre **recolhida**, com os capítulos numerados (`1.`, `2.`, ... `13.`) e em
   ordem crescente — sem buracos nem embaralhamento.
2. `▶` abre um capítulo; os itens aparecem recuados, numerados (`13.1`, `13.2`), na ordem.
3. **Trocar a banca-alvo com um capítulo aberto não fecha o capítulo** (a regressão que o
   `ABERTOS` fora do render existe para evitar).
4. "⊕ Expandir tudo" abre todos e o rótulo vira "⊖ Recolher tudo"; clicar de novo recolhe.
5. Trocar de disciplina volta ao recolhido.
6. Capítulo sem item nenhum aparece na lista, sem seta clicável.
7. **Os KPIs do topo não mudam ao expandir** — eles somam capítulos, não itens. Anotar os
   números com tudo recolhido, expandir tudo e conferir que continuam idênticos.

Encerrar com Ctrl+C.

- [ ] **Step 7: Commit**

```bash
git add avaliacao.html
git commit -m "feat: expandir/recolher itens na tela de avaliacao

Linha de capitulo ganha seta e numeracao; os itens entram recuados com as
mesmas 8 colunas. O conjunto de abertos vive fora do render para trocar a
banca-alvo nao fechar o que o usuario abriu."
```

---

### Task 5: CSV com `nivel` e `num`

**Files:**
- Modify: `avaliacao.html` (`baixarCSV()`, linhas ~202-226)

**Interfaces:**
- Consumes: `capitulo.num`, `capitulo.itens` (Task 3).
- Produces: CSV com as colunas `nivel` e `num` na frente das 21 já existentes, uma linha por
  capítulo e uma por item, **sempre** — independente do que está expandido.

- [ ] **Step 1: Reescrever `baixarCSV`**

Substituir o corpo da função (da linha do `const linhas = [[...]]` até o `D.capitulos.forEach`
inclusive) por:

```js
    const linhas = [["nivel", "num", "capitulo", "aulas", "itens_no_mb", "questoes_total",
      "questoes_embedadas", "questoes_em_texto",
      "qtd_banca_alvo", "qtd_outras_bancas", "pct_banca_alvo",
      "pct_prova_faixa_critica", "pct_prova_faixa_media", "pct_prova_faixa_recente", "questoes_com_prova",
      "emb_com_solucao_texto", "emb_com_video_solucao",
      "videos", "tempo_videos", "videos_com_data",
      "pct_grav_faixa_critica", "pct_grav_faixa_media", "pct_grav_faixa_recente"]];
    // nas linhas de item, a coluna "capitulo" carrega o nome do item e "aulas" vale 1;
    // filtrar nivel=capitulo devolve exatamente o arquivo antigo.
    const push = (c, nivel) => {
      const totQ = c.q_emb + c.q_txt;
      const alvo = banca ? (c.bancas[banca] || 0) : "";
      linhas.push([nivel, c.num || "", (c.nome || "").trim(), c.aulas,
        c.itens_total ? `${c.itens_mb}/${c.itens_total}` : "—", totQ, c.q_emb, c.q_txt,
        alvo, banca ? totQ - alvo : "", banca ? pc(alvo, totQ) : "",
        pc(c.q_ate, c.q_com_ano), pc(c.q_meio, c.q_com_ano), pc(c.q_novo, c.q_com_ano), c.q_com_ano,
        c.sol_texto, c.sol_video, c.vids, dur(c.dur), c.v_com_data,
        pc(c.v_ate, c.v_com_data), pc(c.v_meio, c.v_com_data), pc(c.v_novo, c.v_com_data)]);
    };
    D.capitulos.forEach(c => {
      push(c, "capitulo");
      (c.itens || []).forEach(it => push(it, "item"));
    });
```

⚠ As linhas seguintes (`const csv = "﻿" + ...`, o `<a>` e o `click()`) **não mudam**.
A coluna `aulas` é nova no CSV — antes o cabeçalho tinha `capitulo, aulas, itens_no_mb`
mas o `forEach` empurrava `c.nome, c.aulas, ...`; a ordem continua a mesma, só ganhou
`nivel` e `num` na frente.

- [ ] **Step 2: Testar na mão**

```powershell
py painel.py --sem-navegador
```

Em `http://127.0.0.1:8766/avaliacao`, escolher uma disciplina e clicar **⬇ CSV (Excel)**.
Abrir o arquivo e conferir:
1. Primeiras colunas: `nivel;num;capitulo;aulas;...`
2. Cada `capitulo` é seguido pelos seus `item`, na ordem (`13`, `13.1`, `13.2`, `14`, ...).
3. Filtrar `nivel = capitulo` no Excel devolve exatamente as linhas de antes.
4. Acentos corretos ao abrir direto no Excel (BOM preservado).

Encerrar com Ctrl+C.

- [ ] **Step 3: Commit**

```bash
git add avaliacao.html
git commit -m "feat: CSV da avaliacao sai com itens e colunas nivel/num

Uma linha por capitulo e uma por item, sempre — independente do que esta
expandido. As colunas antigas mantem nome e ordem, entao planilhas ja
montadas nao quebram; filtrar nivel=capitulo devolve o arquivo de antes."
```

---

### Task 6: Replicar na cópia web

**Files:**
- Modify: `web/telas/avaliacao.html`

**Interfaces:**
- Consumes: as edições das Tasks 4 e 5 em `avaliacao.html`.
- Produces: cópia web com o mesmo comportamento, **sem perder** as 5 edições próprias dela.

**Contexto obrigatório:** `web/telas/avaliacao.html` é uma cópia da tela da raiz com edições
próprias que **não podem ser perdidas**: (1) banner de cookie no topo, (2) links Coleta/Admin/sair
no `eyebrow`, (3) selo de frescor `#frescor`, (4) seletor de concurso + `carregarConcursos()`,
(5) estado vazio em `carregarCursos()`, além das URLs de fetch com `&termo=` e o
`carregarConcursos()` no lugar de `carregarCursos()` no fim do script.

**Boa notícia:** `render()` e `baixarCSV()` são hoje **byte-idênticas** entre os dois arquivos
— todas as edições da cópia estão fora delas.

- [ ] **Step 1: Confirmar o ponto de partida**

```bash
git diff --no-index --stat avaliacao.html web/telas/avaliacao.html
```

Expected: as diferenças são só as 5 edições listadas acima (as mesmas de antes da Task 4).

- [ ] **Step 2: Aplicar as mesmas edições**

Repetir na cópia, **exatamente** como nas Tasks 4 e 5:
1. O bloco CSS do Step 1 da Task 4 (depois de `.cap-nm small`).
2. O botão `#btnExpandir` na `.barra`, antes do botão de CSV.
3. `ABERTOS`, `alternar`, `alternarTudo` depois de `let D = null;` — na cópia, **depois** de
   `let TERMO = "";`.
4. `linhaHtml` antes de `function render()` e o novo corpo do `render()`.
5. `ABERTOS.clear();` depois de `D = (await r.json()).data;` em `carregarAvaliacao`.
6. O novo `baixarCSV` da Task 5.

- [ ] **Step 3: Verificar que nada da cópia se perdeu**

```bash
git diff --no-index avaliacao.html web/telas/avaliacao.html
```

Expected: **as mesmas 5 diferenças de antes, nem uma a mais**. Nenhuma diferença dentro de
`render()`, `linhaHtml()` ou `baixarCSV()` — se aparecer alguma ali, a réplica saiu torta.

Conferir também que os 5 marcadores continuam presentes:

```bash
grep -c "banner-cookie\|/auth/sair\|id=\"frescor\"\|carregarConcursos\|sem dados" web/telas/avaliacao.html
```

Expected: 5 ou mais ocorrências.

- [ ] **Step 4: Build da web**

```powershell
cd web; npm run build
```

Expected: build limpo, sem erro. Voltar com `cd ..`.

- [ ] **Step 5: Commit**

```bash
git add web/telas/avaliacao.html
git commit -m "feat: replica expandir/recolher e CSV por item na tela web

As 5 edicoes proprias da copia (banner de cookie, links, selo de frescor,
seletor de concurso, estado vazio) foram preservadas."
```

---

### Task 7: Verificação com dados reais e documentação

**Files:**
- Create: `docs/superpowers/verificacao-2026-07-29-itens-mb.md` (relatório do antes/depois)
- Modify: `PROXIMA-SESSAO.md`

**Interfaces:**
- Consumes: tudo. É o portão de aceite antes do PR.

- [ ] **Step 1: Medir o antes/depois do "Itens no MB"**

Rodar o comparativo entre o número publicado hoje (consulta antiga) e o novo:

```powershell
py -c @"
import sqlite3, json, painel, banco_conteudo
con = banco_conteudo.abrir('saida/conteudo.db')
e = con.execute('SELECT MAX(id) FROM extracoes').fetchone()[0]
linhas = []
for c in con.execute('SELECT curso_id, nome FROM cursos WHERE extracao_id=?', (e,)):
    d = painel.dados_avaliacao(con, c['curso_id'], depara={})
    novo_t = sum(x['itens_total'] for x in d['capitulos'])
    novo_m = sum(x['itens_mb'] for x in d['capitulos'])
    # antigo: a consulta que nao filtrava por curso
    velho_t = velho_m = 0
    for cap in con.execute('SELECT capitulo_id FROM capitulos WHERE extracao_id=? AND curso_id=?', (e, c['curso_id'])):
        itens = [r[0] for r in con.execute('SELECT item_id FROM aulas WHERE extracao_id=? AND curso_id=? AND capitulo_id=?', (e, c['curso_id'], cap[0]))]
        if not itens: continue
        marks = ','.join('?' * len(itens))
        r = con.execute(f'SELECT COUNT(*), SUM(vinculado_mb) FROM aulas WHERE extracao_id=? AND vinculado_mb IS NOT NULL AND item_id IN ({marks})', (e, *itens)).fetchone()
        velho_t += r[0] or 0; velho_m += r[1] or 0
    if (velho_t, velho_m) != (novo_t, novo_m):
        linhas.append((c['nome'][:60], velho_m, velho_t, novo_m, novo_t))
print(f'cursos com diferenca: {len(linhas)}')
for l in linhas[:40]: print(f'{l[0]:60} {l[1]}/{l[2]} -> {l[3]}/{l[4]}')
"@
```

Salvar a saída em `docs/superpowers/verificacao-2026-07-29-itens-mb.md`, com uma frase
explicando que a diferença é a correção do vazamento de filtro, não regressão.

- [ ] **Step 2: Conferir os cursos de controle**

Os cursos **Amparo** e **DMAE** não têm item compartilhado — os números do aceite anterior
precisam sair **idênticos**:

Run: `py painel.py --sem-navegador` → `/avaliacao`, escolher cada um e somar a coluna
"Itens no MB".
Expected: **Amparo 68/75** e **DMAE 319/345**, inalterados. Se mudaram, parar: a correção
saiu errada.

- [ ] **Step 3: Conferir a ordem contra o LDI**

Abrir no admin do LDI um curso qualquer da base e comparar a sequência de capítulos com a
da tela.
Expected: mesma ordem, começando pelo capítulo 1 (tipicamente "Apresentação").

- [ ] **Step 4: Rodar a suíte inteira**

Run: `py -m unittest discover -s tests`
Expected: OK, sem falha nem erro.

- [ ] **Step 5: Atualizar o `PROXIMA-SESSAO.md`**

Acrescentar esta seção antes de `## 🔑 Coisas que a próxima sessão PRECISA saber`,
preenchendo `<...>` com o que foi medido nos Steps 1-3:

```markdown
## ✅ Sessão 10 (29/07): avaliação por item + ordem real do curso

A tela `/avaliacao` desce do capítulo ao **item** (expandir/recolher, botão "expandir tudo")
e sai na **ordem do curso**. Spec: `docs\superpowers\specs\2026-07-29-avaliacao-por-item-e-ordem-design.md`;
plano: `docs\superpowers\plans\2026-07-29-avaliacao-por-item.md`.

**Achado da ordem:** `capitulos.ordem` é **zero nos 2.547 capítulos** da base — a API devolve
`order_index=0` para todos, então o `ORDER BY ordem` do painel era um no-op. A ordem real vem
do **`path` da aula** (`13.1` = capítulo 13, item 1), que é **relativo ao curso** (o mesmo item
tem path `6.4` num pacote e `1.4` noutro). Derivada na leitura → conserta **retroativamente
todos os snapshots**, sem recoleta e sem migração.

**Correção junto:** a contagem de "Itens no MB" não filtrava por curso e contava o item
compartilhado uma vez por pacote (1.990 dos 3.612 itens do BACEN vivem em mais de um curso).
Antes/depois medido em `docs\superpowers\verificacao-2026-07-29-itens-mb.md`:
<N> cursos mudaram. Controles sem compartilhamento intactos: Amparo 68/75, DMAE 319/345.

**Também:** o capítulo virou a **soma dos seus itens** (pai não tem como divergir dos filhos);
o CSV ganhou as colunas `nivel` e `num` com uma linha por capítulo e uma por item.

**Sem mudança de schema** (SQLite ou Supabase) e **sem recoleta**. O worker do VPS não precisa
de `git pull` — nada em `coletor_ldi.py`/`worker_coleta.py` mudou.

**⚠ Falta:** push da branch `feat/avaliacao-por-item` + PR → `main` (login interativo do
Clovis; o merge deploya no Vercel) e o aceite na tela.
```

⚠ Trocar `<N>` pelo número real de cursos com diferença. Se os controles (Amparo/DMAE) tiverem
mudado, **não** commitar: a correção saiu errada e o Step 2 falhou.

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/verificacao-2026-07-29-itens-mb.md PROXIMA-SESSAO.md
git commit -m "docs: verificacao com dados reais da avaliacao por item"
```

- [ ] **Step 7: Entregar para o Clovis**

A branch fica local. Push e PR são dele (o merge na `main` deploya no Vercel). Deixar
pronto:

```
! git push -u origin feat/avaliacao-por-item
```

E lembrar: **nenhuma mudança de schema** (SQLite ou Supabase) e **nenhuma recoleta** é
necessária; os snapshots já publicados saem ordenados na próxima sincronização. O worker do
VPS não precisa de `git pull` para esta entrega — nada em `coletor_ldi.py` ou
`worker_coleta.py` mudou.

---

## Notas para quem executa

- **Não** rodar `--refresh` do Metabase nem `sync_depara_supabase.py`: nada aqui depende
  disso.
- O `saida/conteudo.db` tem 242 MB; abrir só leitura nas medições (`mode=ro`) quando não
  precisar da migração de schema.
- Se o painel servir código velho depois de editar o HTML, matar instâncias antigas de
  `python`/`PainelLDI` — a porta aceita bind duplo no Windows (armadilha conhecida; **não**
  tocar no python de `src\backend\app.py`, que é outro app).
- Se houver `PainelLDI.exe` empacotado, ele embute `painel.html`/`avaliacao.html`: rebuild
  com PyInstaller para o exe refletir a tela nova.
