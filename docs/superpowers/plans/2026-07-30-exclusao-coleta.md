# Exclusão de uma coleta pelo admin — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O admin apaga uma coleta pela tela `/admin`; o worker do VPS remove o snapshot no Supabase e a extração no `conteudo.db`, numa transação só.

**Architecture:** O clique enfileira `coleta_pedido` com `tipo='excluir'` e um alvo **JSON** (worker antigo falha limpo). O worker roteia por tipo, apaga o Supabase primeiro e depois os 6 DELETEs numa transação com `extracoes` por último. Toda a lógica destrutiva mora em `exclusao_coleta.py`, com funções puras e sem HTTP.

**Tech Stack:** Python 3.12 (`unittest`, `sqlite3`, `requests`), Next.js 15 / React 19 / TypeScript (App Router, server actions), Supabase (PostgREST).

**Spec:** `docs/superpowers/specs/2026-07-30-exclusao-coleta-design.md`

## Global Constraints

- **Idioma pt-BR** em código, comentários, docs e UI (nomes de função, variáveis e mensagens).
- **Suíte atual: 119 testes verdes.** Nenhum pode ficar vermelho — rodar `py -m unittest discover -s tests` ao fim de cada task.
- **Datas locais**, nunca `toISOString` para nome/exibição (convenção do projeto); `datetime.now(timezone.utc).isoformat()` só nos campos de timestamp da fila, como o código já faz.
- **Nada de service_role no cliente**: escrita em `coleta_pedido` só via `criarClienteAdmin()` (server-only). Leitura pode usar `criarClienteServidor()` (JWT do usuário, RLS `authenticated`).
- **Ordem dos DELETEs, imutável:** `blocos → aulas_coletadas → aulas → capitulos → cursos → extracoes`.
- Commits em português, formato `<tipo>: <descrição>` (feat/fix/docs/test/chore).

---

### Task 1: Ler e validar o alvo JSON do pedido

**Files:**
- Create: `exclusao_coleta.py`
- Test: `tests/test_exclusao_coleta.py`

**Interfaces:**
- Consumes: `extrator_ldi.falha(msg)` — levanta `SystemExit` (convenção do projeto; `worker_coleta.processar_pedido` já captura `SystemExit` e vira status `erro`).
- Produces: `ler_pedido_exclusao(row) -> (termo: str, extracao_local: int, vacuum: bool)`

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/test_exclusao_coleta.py`:

```python
# -*- coding: utf-8 -*-
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import exclusao_coleta


class TestLerPedidoExclusao(unittest.TestCase):
    def test_alvo_completo(self):
        row = {"tipo": "excluir",
               "alvo": '{"termo":"BACEN","extracao_local":37,"snapshot_id":12,"vacuum":false}'}
        self.assertEqual(exclusao_coleta.ler_pedido_exclusao(row), ("BACEN", 37, False))

    def test_vacuum_ausente_vira_false(self):
        row = {"tipo": "excluir", "alvo": '{"termo":"PRF","extracao_local":3}'}
        self.assertEqual(exclusao_coleta.ler_pedido_exclusao(row), ("PRF", 3, False))

    def test_alvo_que_nao_e_json_falha(self):
        # é o alvo que um worker NOVO receberia de uma web velha: falha limpa
        with self.assertRaises(SystemExit):
            exclusao_coleta.ler_pedido_exclusao({"tipo": "excluir", "alvo": "BACEN"})

    def test_termo_vazio_falha(self):
        with self.assertRaises(SystemExit):
            exclusao_coleta.ler_pedido_exclusao(
                {"tipo": "excluir", "alvo": '{"termo":"","extracao_local":37}'})

    def test_extracao_local_invalida_falha(self):
        for alvo in ('{"termo":"BACEN"}',
                     '{"termo":"BACEN","extracao_local":"37"}',
                     '{"termo":"BACEN","extracao_local":0}'):
            with self.subTest(alvo=alvo):
                with self.assertRaises(SystemExit):
                    exclusao_coleta.ler_pedido_exclusao({"tipo": "excluir", "alvo": alvo})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar o teste e ver falhar**

Run: `py -m unittest tests.test_exclusao_coleta -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'exclusao_coleta'`

- [ ] **Step 3: Implementar o mínimo**

Criar `exclusao_coleta.py`:

```python
# -*- coding: utf-8 -*-
"""
============================================================
 EXCLUSÃO DE COLETA — funções puras (sem HTTP) usadas pelo
 worker para apagar uma extração do conteudo.db.
 Spec: docs/superpowers/specs/2026-07-30-exclusao-coleta-design.md

 INVARIANTE: cada função é IDEMPOTENTE de propósito. A
 reconciliação da subida do worker (worker_coleta.main) devolve
 pedidos presos em 'rodando' para 'pendente', então um pedido de
 exclusão pode reexecutar depois de já ter apagado parte das
 coisas. Não "otimizar" nenhum passo para pular a checagem de
 existência — é ela que segura a reexecução.
============================================================
"""
import json

import extrator_ldi


def ler_pedido_exclusao(row):
    """Deriva (termo, extracao_local, vacuum) de uma linha da fila tipo='excluir'.

    O alvo é um JSON, nunca um termo legível: se um worker ANTIGO pegar este
    pedido, ele trata o JSON inteiro como search_term, não acha curso nenhum e
    falha limpo — em vez de RECOLETAR o termo que se pediu para apagar."""
    try:
        alvo = json.loads(row.get("alvo") or "")
    except (ValueError, TypeError):
        raise extrator_ldi.falha(
            "pedido de exclusão com alvo ilegível (esperava JSON).")
    if not isinstance(alvo, dict):
        raise extrator_ldi.falha("pedido de exclusão com alvo que não é objeto JSON.")

    termo = alvo.get("termo")
    if not isinstance(termo, str) or not termo.strip():
        raise extrator_ldi.falha("pedido de exclusão sem termo.")

    extracao_local = alvo.get("extracao_local")
    # bool é subclasse de int em Python — True passaria como 1 sem esta guarda
    if not isinstance(extracao_local, int) or isinstance(extracao_local, bool) \
            or extracao_local <= 0:
        raise extrator_ldi.falha(
            f"pedido de exclusão com extracao_local inválida: {extracao_local!r}")

    return termo.strip(), extracao_local, bool(alvo.get("vacuum"))
```

- [ ] **Step 4: Rodar o teste e ver passar**

Run: `py -m unittest tests.test_exclusao_coleta -v`
Expected: PASS — 5 testes

- [ ] **Step 5: Commit**

```bash
git add exclusao_coleta.py tests/test_exclusao_coleta.py
git commit -m "feat: le e valida o alvo JSON do pedido de exclusao"
```

---

### Task 2: Apagar a extração — as 4 garantias

**Files:**
- Modify: `exclusao_coleta.py`
- Modify: `tests/test_exclusao_coleta.py`

**Interfaces:**
- Consumes: `banco_conteudo.abrir(caminho)`, `banco_conteudo.iniciar_extracao(con, termo, vertical)`, `banco_conteudo.gravar_arvore(con, extracao_id, cursos)`, `banco_conteudo.gravar_blocos_da_aula(con, extracao_id, item_id, blocos)`; `painel.dados_do_snapshot(con)`.
- Produces:
  - `TABELAS: tuple[str, ...]` — a ordem dos DELETEs
  - `conferir_extracao(con, extracao_id, termo) -> sqlite3.Row | None`
  - `era_a_mais_recente(con, extracao_id) -> bool`
  - `contar_pendencias(con, extracao_id) -> int`
  - `apagar_extracao(con, extracao_id) -> dict[str, int]`
  - `relatorio(termo, extracao_local, apagadas, pendencias, mais_recente, vacuum=False) -> str`

- [ ] **Step 1: Escrever os testes que falham**

Acrescentar a `tests/test_exclusao_coleta.py` (mantendo o que já existe; adicionar os imports novos no topo do arquivo):

```python
import sqlite3
import tempfile
from unittest.mock import patch

import banco_conteudo
import painel

CURSOS = [{
    "id": "c1", "name": "Curso A", "published": True,
    "created_at": "2024-01-01", "authors_name": "Prof X",
    "content_tree_cache": [{
        "chapter_id": "cap1", "name": "Cap 1", "order_index": 0,
        "items": [
            {"item_id": "i1", "name": "Aula 1", "path": "1.1",
             "block_type_count": {"question": 2, "tiptap": 1}},
            {"item_id": "i2", "name": "Aula 2", "path": "1.2",
             "block_type_count": {"videoMyDocuments": 1}},
        ],
    }],
}]

B1 = {"bloco_id": "b1", "tipo": "question", "ordem": 1, "ativo": 1, "rascunho": 0,
      "titulo": "", "questao_id": "111", "resposta_tipo": "TRUE_OR_FALSE",
      "tem_solucao": 1, "tem_video_solucao": 0, "video_id_antigo": "",
      "duracao_seg": None, "tamanho_texto": None, "meta": {"topicos": ["T"]}}

TABELAS_POVOADAS = ("blocos", "aulas_coletadas", "aulas", "capitulos", "cursos", "extracoes")


class TestApagarExtracao(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.con = banco_conteudo.abrir(os.path.join(self.dir.name, "x", "conteudo.db"))

    def tearDown(self):
        self.con.close()
        self.dir.cleanup()

    def _nova(self, termo="BACEN"):
        eid = banco_conteudo.iniciar_extracao(self.con, termo, "concursos")
        banco_conteudo.gravar_arvore(self.con, eid, CURSOS)
        banco_conteudo.gravar_blocos_da_aula(self.con, eid, "i1", [B1])
        banco_conteudo.gravar_blocos_da_aula(self.con, eid, "i2", [])
        return eid

    def _contagens(self, eid):
        return {t: self.con.execute(
            f"SELECT COUNT(*) FROM {t} WHERE {'id' if t == 'extracoes' else 'extracao_id'}=?",
            (eid,)).fetchone()[0] for t in TABELAS_POVOADAS}

    def _semear_pendencias(self, eid):
        self.con.execute(
            "INSERT INTO pendencias(chave, regra, severidade, curso_id, item_id, "
            "bloco_id, descricao, status, extracao_id_criada, extracao_id_ultima, criada_em) "
            "VALUES('k1','Q1','critica','c1','i1','b1','sem solução','nova',?,?,'2026-07-30')",
            (eid, eid))
        self.con.execute(
            "INSERT INTO acionamentos(chave_pendencia, status, observacao, registrado_em) "
            "VALUES('k1','enviada','','2026-07-30')")
        self.con.commit()

    def test_isolamento_a_outra_extracao_fica_intacta(self):
        eid1 = self._nova()
        eid2 = self._nova()
        antes2 = self._contagens(eid2)
        exclusao_coleta.apagar_extracao(self.con, eid1)
        self.assertEqual(self._contagens(eid1), dict.fromkeys(TABELAS_POVOADAS, 0))
        self.assertEqual(self._contagens(eid2), antes2)

    def test_pendencias_e_acionamentos_preservados(self):
        eid = self._nova()
        self._semear_pendencias(eid)
        antes = (self.con.execute("SELECT COUNT(*) FROM pendencias").fetchone()[0],
                 self.con.execute("SELECT COUNT(*) FROM acionamentos").fetchone()[0])
        exclusao_coleta.apagar_extracao(self.con, eid)
        depois = (self.con.execute("SELECT COUNT(*) FROM pendencias").fetchone()[0],
                  self.con.execute("SELECT COUNT(*) FROM acionamentos").fetchone()[0])
        self.assertEqual(depois, antes)
        self.assertEqual(antes, (1, 1))

    def test_atomicidade_falha_no_meio_nao_apaga_nada(self):
        """Se um DELETE do meio estourar, NADA pode ter sido apagado — é o teste
        que prova a ausência de órfão silencioso. Sem o `with con:`, os 3
        primeiros DELETEs teriam commitado sozinhos e este teste falharia."""
        eid = self._nova()
        antes = self._contagens(eid)
        quebrado = ("blocos", "aulas_coletadas", "aulas",
                    "tabela_que_nao_existe", "cursos", "extracoes")
        with patch.object(exclusao_coleta, "TABELAS", quebrado):
            with self.assertRaises(sqlite3.OperationalError):
                exclusao_coleta.apagar_extracao(self.con, eid)
        self.assertEqual(self._contagens(eid), antes)

    def test_idempotencia_segunda_passada_devolve_zeros(self):
        eid = self._nova()
        primeira = exclusao_coleta.apagar_extracao(self.con, eid)
        segunda = exclusao_coleta.apagar_extracao(self.con, eid)
        self.assertGreater(primeira["blocos"], 0)
        self.assertEqual(segunda, dict.fromkeys(TABELAS_POVOADAS, 0))

    def test_conferir_extracao(self):
        eid = self._nova()
        self.assertEqual(exclusao_coleta.conferir_extracao(self.con, eid, "BACEN")["id"], eid)
        # extração inexistente devolve None (idempotência: o snapshot pode ter sobrado)
        self.assertIsNone(exclusao_coleta.conferir_extracao(self.con, 9999, "BACEN"))
        # termo divergente nunca apaga o alvo errado
        with self.assertRaises(SystemExit):
            exclusao_coleta.conferir_extracao(self.con, eid, "PRF")

    def test_era_a_mais_recente_e_contar_pendencias(self):
        eid1 = self._nova()
        eid2 = self._nova()
        self._semear_pendencias(eid2)
        self.assertFalse(exclusao_coleta.era_a_mais_recente(self.con, eid1))
        self.assertTrue(exclusao_coleta.era_a_mais_recente(self.con, eid2))
        self.assertEqual(exclusao_coleta.contar_pendencias(self.con, eid2), 1)
        self.assertEqual(exclusao_coleta.contar_pendencias(self.con, eid1), 0)

    def test_regressao_painel_cai_para_a_anterior(self):
        """painel.py e sync_supabase.py fazem ORDER BY id DESC LIMIT 1 GLOBAL.
        Apagar a mais recente muda qual snapshot o painel local abre — este teste
        documenta o comportamento para ninguém "consertar" sem querer."""
        eid1 = self._nova()
        eid2 = self._nova()
        self.assertEqual(painel.dados_do_snapshot(self.con)["extracao"]["id"], eid2)
        exclusao_coleta.apagar_extracao(self.con, eid2)
        self.assertEqual(painel.dados_do_snapshot(self.con)["extracao"]["id"], eid1)


class TestRelatorio(unittest.TestCase):
    def test_relatorio_completo(self):
        texto = exclusao_coleta.relatorio(
            "BACEN", 37, {"blocos": 64838, "extracoes": 1}, 120, True)
        self.assertIn("BACEN #37", texto)
        self.assertIn("blocos: 64838", texto)
        self.assertIn("120 pendências", texto)
        self.assertIn("maior id", texto)

    def test_relatorio_sem_extracao_local(self):
        texto = exclusao_coleta.relatorio("BACEN", 37, {}, 0, False)
        self.assertIn("já não existia", texto)
        self.assertNotIn("pendências", texto)

    def test_relatorio_avisa_vacuum_nao_implementado(self):
        texto = exclusao_coleta.relatorio("BACEN", 37, {"blocos": 1}, 0, False, vacuum=True)
        self.assertIn("1b", texto)
```

- [ ] **Step 2: Rodar os testes e ver falhar**

Run: `py -m unittest tests.test_exclusao_coleta -v`
Expected: FAIL — `AttributeError: module 'exclusao_coleta' has no attribute 'apagar_extracao'`

- [ ] **Step 3: Implementar o mínimo**

Acrescentar a `exclusao_coleta.py`:

```python
# A ORDEM IMPORTA e não é imposição do banco — o SQLite não tem FK nenhuma
# (banco_conteudo.py:12-64), a ordem é escolha nossa. `extracoes` vem por
# ÚLTIMO: enquanto essa linha existir, o painel ainda ENXERGA a extração
# (visivelmente errada). Se sumisse primeiro e o processo caísse, ficariam
# centenas de MB de blocos que NENHUMA tela lista.
# Lixo visível é melhor que lixo invisível.
TABELAS = ("blocos", "aulas_coletadas", "aulas", "capitulos", "cursos", "extracoes")


def conferir_extracao(con, extracao_id, termo):
    """Devolve a linha de `extracoes` do alvo.

    None quando a extração não existe — NÃO é erro: o snapshot no Supabase pode
    ter sobrado de uma tentativa que morreu no meio (idempotência).
    Levanta quando o termo diverge — nunca apagar o alvo errado."""
    row = con.execute("SELECT * FROM extracoes WHERE id=?", (extracao_id,)).fetchone()
    if row is None:
        return None
    if (row["termo"] or "") != termo:
        raise extrator_ldi.falha(
            f"termo divergente: o pedido diz {termo!r}, mas a extração "
            f"{extracao_id} é de {row['termo']!r}. Nada foi apagado.")
    return row


def era_a_mais_recente(con, extracao_id):
    """True se esta é a extração de maior id — a que painel.py:49 e
    sync_supabase.py:62 abrem por padrão (ORDER BY id DESC LIMIT 1, GLOBAL,
    sem filtrar por termo). Chamar ANTES de apagar. Serve para RELATAR, não
    para bloquear: apagar a coleta ruim é justamente apagar a última."""
    maior = con.execute("SELECT MAX(id) FROM extracoes").fetchone()[0]
    return maior is not None and maior == extracao_id


def contar_pendencias(con, extracao_id):
    """Quantas pendências foram apuradas contra esta extração. Elas NÃO são
    apagadas (a chave é determinística e independe da extração); o worker só
    informa que os números vão continuar velhos até a próxima coleta."""
    return con.execute(
        "SELECT COUNT(*) FROM pendencias "
        "WHERE extracao_id_criada=? OR extracao_id_ultima=?",
        (extracao_id, extracao_id)).fetchone()[0]


def apagar_extracao(con, extracao_id):
    """Os 6 DELETEs numa ÚNICA transação. Devolve {tabela: linhas_apagadas}.

    Idempotente: rodar de novo devolve zeros sem levantar."""
    apagadas = {}
    with con:  # commit no fim, ROLLBACK em qualquer exceção
        for tabela in TABELAS:
            # nome de tabela vem da constante TABELAS, nunca de entrada externa
            coluna = "id" if tabela == "extracoes" else "extracao_id"
            cur = con.execute(f"DELETE FROM {tabela} WHERE {coluna}=?", (extracao_id,))
            apagadas[tabela] = cur.rowcount
    return apagadas


def relatorio(termo, extracao_local, apagadas, pendencias, mais_recente, vacuum=False):
    """Mensagem final do pedido (cabe em 400 caracteres na coluna `mensagem`)."""
    partes = [f"Coleta {termo} #{extracao_local} apagada."]
    if apagadas:
        partes.append(" · ".join(f"{t}: {n}" for t, n in apagadas.items()) + ".")
    else:
        partes.append("A extração já não existia no conteudo.db "
                      "(só o snapshot foi removido).")
    if pendencias:
        partes.append(f"{pendencias} pendências foram apuradas contra esta coleta e "
                      "continuarão abertas com os números antigos até a próxima "
                      "coleta deste termo.")
    if mais_recente:
        partes.append("Era a extração de maior id — o painel local passa a abrir "
                      "a anterior.")
    if vacuum:
        partes.append("VACUUM pedido, mas ainda não implementado (entrega 1b) — ignorado.")
    return " ".join(partes)
```

- [ ] **Step 4: Rodar os testes e ver passar**

Run: `py -m unittest tests.test_exclusao_coleta -v`
Expected: PASS — todos

- [ ] **Step 5: Provar que o teste de atomicidade discrimina**

Temporariamente trocar `with con:` por `pass  #` (ou seja, rodar os DELETEs sem transação) e confirmar que `test_atomicidade_falha_no_meio_nao_apaga_nada` **falha**. Depois desfazer.

Run: `py -m unittest tests.test_exclusao_coleta.TestApagarExtracao.test_atomicidade_falha_no_meio_nao_apaga_nada -v`
Expected: FAIL sem a transação, PASS com ela. Se passar nos dois, o teste é tautológico e **não serve** — corrigir antes de seguir.

- [ ] **Step 6: Rodar a suíte inteira**

Run: `py -m unittest discover -s tests`
Expected: OK, 119 + novos

- [ ] **Step 7: Commit**

```bash
git add exclusao_coleta.py tests/test_exclusao_coleta.py
git commit -m "feat: apaga uma extracao do conteudo.db numa transacao so"
```

---

### Task 3: Rotear o pedido no worker

**Files:**
- Modify: `worker_coleta.py`
- Modify: `tests/test_worker_coleta.py`

**Interfaces:**
- Consumes: tudo o que a Task 2 produziu; `sync_supabase._headers(key, prefer=None)`; `banco_conteudo.abrir(caminho)`; `worker_coleta._patch_pedido(rest, key, pedido_id, campos)`; `worker_coleta.BANCO`.
- Produces: `worker_coleta.processar_exclusao(rest, key, row) -> str`; `worker_coleta._apagar_snapshot(rest, key, termo, extracao_local)`; guarda de tipo desconhecido em `pedido_para_coleta`.

- [ ] **Step 1: Escrever os testes que falham**

Acrescentar a `tests/test_worker_coleta.py`:

```python
class TestRoteamentoExclusao(unittest.TestCase):
    """tipo='excluir' NÃO pode chamar o coletor nem provar o cookie — a exclusão
    não fala com o LDI, e um cookie vencido não pode bloquear limpeza de disco."""

    def test_tipo_desconhecido_falha(self):
        with self.assertRaises(SystemExit):
            worker_coleta.pedido_para_coleta(
                {"tipo": "xpto", "alvo": "qualquer", "rotulo": None})

    def test_excluir_nao_passa_por_pedido_para_coleta(self):
        with self.assertRaises(SystemExit):
            worker_coleta.pedido_para_coleta(
                {"tipo": "excluir", "alvo": '{"termo":"BACEN"}', "rotulo": None})

    @patch("worker_coleta.exclusao_coleta.relatorio", return_value="relatório")
    @patch("worker_coleta.exclusao_coleta.apagar_extracao")
    @patch("worker_coleta.exclusao_coleta.contar_pendencias", return_value=0)
    @patch("worker_coleta.exclusao_coleta.era_a_mais_recente", return_value=False)
    @patch("worker_coleta.exclusao_coleta.conferir_extracao", return_value={"id": 7})
    @patch("worker_coleta._apagar_snapshot")
    @patch("worker_coleta.banco_conteudo.abrir")
    @patch("worker_coleta.cookie_status.probar_cookie")
    @patch("worker_coleta.coletor_ldi.coletar")
    @patch("worker_coleta._patch_pedido")
    def test_exclusao_nao_coleta_nem_prova_cookie(
        self, mock_patch, mock_coletar, mock_probar, mock_abrir, mock_del_snap,
        mock_conferir, mock_recente, mock_pend, mock_apagar, mock_relatorio
    ):
        # Registra a ORDEM real das duas camadas: Supabase ANTES do SQLite.
        # Morrer no meio deixa "sumiu da web mas ainda ocupa disco" (retentável);
        # a ordem inversa deixaria a web mostrando coleta que não existe mais.
        ordem = []
        mock_del_snap.side_effect = lambda *a, **k: ordem.append("supabase")
        mock_apagar.side_effect = lambda *a, **k: (ordem.append("sqlite")
                                                   or {"blocos": 3})

        row = {"id": 60, "tipo": "excluir", "rotulo": None,
               "alvo": '{"termo":"BACEN","extracao_local":7,"snapshot_id":12,"vacuum":false}'}
        status = worker_coleta.processar_exclusao("http://mock", "k", row)

        self.assertEqual(status, "concluida")
        mock_coletar.assert_not_called()
        mock_probar.assert_not_called()
        mock_del_snap.assert_called_once_with("http://mock", "k", "BACEN", 7)
        self.assertEqual(ordem, ["supabase", "sqlite"])

    @patch("worker_coleta.banco_conteudo.abrir")
    @patch("worker_coleta._patch_pedido")
    def test_alvo_ilegivel_vira_erro(self, mock_patch, mock_abrir):
        row = {"id": 61, "tipo": "excluir", "alvo": "BACEN", "rotulo": None}
        self.assertEqual(
            worker_coleta.processar_exclusao("http://mock", "k", row), "erro")
        erro = [c for c in mock_patch.call_args_list
                if c[0][3].get("status") == "erro"]
        self.assertTrue(erro)

    @patch("worker_coleta.exclusao_coleta.apagar_extracao")
    @patch("worker_coleta._apagar_snapshot")
    @patch("worker_coleta.exclusao_coleta.conferir_extracao",
           side_effect=SystemExit("[ERRO] termo divergente"))
    @patch("worker_coleta.banco_conteudo.abrir")
    @patch("worker_coleta._patch_pedido")
    def test_termo_divergente_nao_apaga_nada(
        self, mock_patch, mock_abrir, mock_conferir, mock_del_snap, mock_apagar
    ):
        row = {"id": 62, "tipo": "excluir", "rotulo": None,
               "alvo": '{"termo":"PRF","extracao_local":7}'}
        self.assertEqual(
            worker_coleta.processar_exclusao("http://mock", "k", row), "erro")
        mock_del_snap.assert_not_called()
        mock_apagar.assert_not_called()
```

- [ ] **Step 2: Rodar os testes e ver falhar**

Run: `py -m unittest tests.test_worker_coleta.TestRoteamentoExclusao -v`
Expected: FAIL — `AttributeError: module 'worker_coleta' has no attribute 'processar_exclusao'`

- [ ] **Step 3: Implementar o mínimo**

Em `worker_coleta.py`, acrescentar aos imports (junto de `import coletor_ldi`):

```python
import banco_conteudo
import exclusao_coleta
```

Trocar `pedido_para_coleta` (linhas 43-49) por:

```python
def pedido_para_coleta(row):
    """Deriva (termo, ids) de uma linha da fila. termo=rótulo quando tipo=ids.

    Só trata os tipos de COLETA — 'excluir' é roteado antes, em main(), e
    qualquer tipo novo (entregas futuras) falha limpo em vez de virar busca."""
    if row["tipo"] == "ids":
        if not row.get("rotulo"):
            raise extrator_ldi.falha("pedido tipo=ids sem rótulo.")
        return row["rotulo"], coletor_ldi.extrair_ids(row["alvo"])
    if row["tipo"] != "termo":
        raise extrator_ldi.falha(f"tipo de pedido desconhecido: {row['tipo']!r}")
    return row["alvo"], None
```

Acrescentar, depois de `processar_pedido`:

```python
def _apagar_snapshot(rest, key, termo, extracao_local):
    """DELETE do snapshot no Supabase. avaliacao_curso e pendencia_resumo somem
    junto por `on delete cascade` (supabase/schema.sql:18,27)."""
    requests.delete(f"{rest}/snapshot", headers=sync_supabase._headers(key),
                    params={"termo": f"eq.{termo}",
                            "extracao_local": f"eq.{extracao_local}"},
                    timeout=60).raise_for_status()


def processar_exclusao(rest, key, row):
    """Apaga uma coleta nas DUAS camadas: snapshot no Supabase e extração no
    conteudo.db. Devolve o status final.

    NÃO prova o cookie — diferença deliberada de processar_pedido: a exclusão
    não fala com o LDI, e um cookie vencido não pode bloquear uma limpeza de
    disco. Cada passo é idempotente (ver docstring de exclusao_coleta)."""
    pid = row["id"]
    _patch_pedido(rest, key, pid, {"status": "rodando",
                                   "iniciado_em": datetime.now(timezone.utc).isoformat()})
    try:
        termo, extracao_local, vacuum = exclusao_coleta.ler_pedido_exclusao(row)
        con = banco_conteudo.abrir(BANCO)
        try:
            ext = exclusao_coleta.conferir_extracao(con, extracao_local, termo)
            mais_recente = bool(ext) and exclusao_coleta.era_a_mais_recente(con, extracao_local)
            pendencias = exclusao_coleta.contar_pendencias(con, extracao_local) if ext else 0
            # Supabase PRIMEIRO. Morrer aqui deixa "sumiu da web mas ainda ocupa
            # disco" — retentável e inofensivo. A ordem inversa deixaria a web
            # mostrando uma coleta que não existe mais na origem.
            _apagar_snapshot(rest, key, termo, extracao_local)
            apagadas = exclusao_coleta.apagar_extracao(con, extracao_local) if ext else {}
        finally:
            con.close()
    except SystemExit as e:   # extrator_ldi.falha (alvo ilegível, termo divergente)
        _patch_pedido(rest, key, pid, {"status": "erro", "mensagem": str(e)[:400]})
        return "erro"
    except Exception as e:
        _patch_pedido(rest, key, pid, {"status": "erro", "mensagem": str(e)[:400]})
        return "erro"

    _patch_pedido(rest, key, pid, {
        "status": "concluida", "extracao_id": extracao_local,
        "mensagem": exclusao_coleta.relatorio(termo, extracao_local, apagadas,
                                              pendencias, mais_recente, vacuum)[:400],
        "concluido_em": datetime.now(timezone.utc).isoformat()})
    return "concluida"
```

Em `main()`, trocar a chamada (linha 217) por:

```python
                if row["tipo"] == "excluir":
                    status = processar_exclusao(rest, key, row)
                else:
                    status = processar_pedido(rest, key, row, cfg)
```

- [ ] **Step 4: Rodar os testes e ver passar**

Run: `py -m unittest tests.test_worker_coleta -v`
Expected: PASS — os antigos e os 4 novos

- [ ] **Step 5: Rodar a suíte inteira**

Run: `py -m unittest discover -s tests`
Expected: OK

- [ ] **Step 6: Commit**

```bash
git add worker_coleta.py tests/test_worker_coleta.py
git commit -m "feat: worker roteia pedido de exclusao e falha limpo em tipo desconhecido"
```

---

### Task 4: Migração SQL + funções puras do TypeScript

**Files:**
- Create: `supabase/schema_coleta_exclusao.sql`
- Create: `web/checks/coleta.check.ts`
- Modify: `web/lib/coleta.ts`

**Interfaces:**
- Consumes: `Pedido`, `StatusPedido` (já existentes em `web/lib/coleta.ts`).
- Produces:
  - `type TipoPedido = "termo" | "ids" | "excluir"`
  - `interface AlvoExclusao { termo: string; extracaoLocal: number; snapshotId: number | null; vacuum: boolean }`
  - `interface SnapshotLinha` (shape cru da tabela `snapshot`)
  - `interface ColetaListada` (shape pronto para a tela)
  - `montarAlvoExclusao(a: AlvoExclusao): string`
  - `lerAlvoExclusao(alvo: string): AlvoExclusao | null`
  - `chaveColeta(termo: string, extracaoLocal: number): string`
  - `indexarPedidosExclusao(pedidos: Pedido[]): Map<string, Pedido>`
  - `montarListaColetas(snapshots: SnapshotLinha[], pedidos: Pedido[]): ColetaListada[]`

- [ ] **Step 1: Escrever a migração**

Criar `supabase/schema_coleta_exclusao.sql`:

```sql
-- Entrega 1a: pedidos de EXCLUSÃO na mesma fila das coletas.
-- Idempotente. Aplicar ANTES de atualizar o worker no VPS — é o que garante
-- que o worker antigo falhe limpo (o alvo é JSON, vira busca sem resultado).
-- Spec: docs/superpowers/specs/2026-07-30-exclusao-coleta-design.md

alter table coleta_pedido drop constraint if exists coleta_pedido_tipo_check;
alter table coleta_pedido add  constraint coleta_pedido_tipo_check
  check (tipo in ('termo','ids','excluir'));
```

- [ ] **Step 2: Escrever o check que falha**

Criar `web/checks/coleta.check.ts`:

```ts
// Checagem das funções puras de web/lib/coleta.ts. O web/ não tem test runner
// (package.json só tem dev/build/start) — este arquivo é o padrão da casa,
// rodado à mão: `cd web && node --experimental-strip-types checks/coleta.check.ts`
import assert from "node:assert/strict";
import {
  montarAlvoExclusao, lerAlvoExclusao, chaveColeta,
  indexarPedidosExclusao, montarListaColetas,
  type Pedido, type SnapshotLinha,
} from "../lib/coleta.ts";

// 1. round-trip do alvo
const alvo = montarAlvoExclusao({
  termo: "BACEN", extracaoLocal: 37, snapshotId: 12, vacuum: false,
});
assert.equal(alvo, '{"termo":"BACEN","extracao_local":37,"snapshot_id":12,"vacuum":false}');
assert.deepEqual(lerAlvoExclusao(alvo), {
  termo: "BACEN", extracaoLocal: 37, snapshotId: 12, vacuum: false,
});

// 2. alvo ilegível não derruba a tela
assert.equal(lerAlvoExclusao("BACEN"), null);
assert.equal(lerAlvoExclusao('{"termo":"BACEN"}'), null);
assert.equal(lerAlvoExclusao('{"extracao_local":37}'), null);

// 3. chave
assert.equal(chaveColeta("BACEN", 37), "BACEN#37");

const pedido = (id: number, status: Pedido["status"], alvoJson: string): Pedido => ({
  id, tipo: "excluir", alvo: alvoJson, rotulo: null, status,
  progresso: null, mensagem: null, extracao_id: null, pedido_por: null,
  criado_em: "2026-07-30T10:00:00Z", iniciado_em: null, concluido_em: null,
});

// 4. indexação ignora pedidos de coleta e alvos ilegíveis; fica com o 1º (mais novo)
const indice = indexarPedidosExclusao([
  pedido(3, "erro", '{"termo":"BACEN","extracao_local":37}'),
  pedido(2, "concluida", '{"termo":"BACEN","extracao_local":37}'),
  pedido(1, "pendente", "lixo"),
  { ...pedido(0, "pendente", "PRF"), tipo: "termo" },
]);
assert.equal(indice.size, 1);
assert.equal(indice.get("BACEN#37")?.id, 3);

// 5. montarListaColetas: mais recente, único e destino
const snap = (id: number, termo: string, extracaoLocal: number): SnapshotLinha => ({
  id, termo, extracao_local: extracaoLocal, status: "completa",
  iniciada_em: `2026-07-${String(extracaoLocal).padStart(2, "0")}T09:00:00`,
  resumo: { kpis: { cursos_total: 128, blocos: 64838 } },
  pronto: true, sincronizado_em: "2026-07-30T10:00:00Z",
});
const lista = montarListaColetas(
  [snap(1, "BACEN", 33), snap(2, "BACEN", 37), snap(3, "PRF", 10)],
  [pedido(9, "rodando", '{"termo":"BACEN","extracao_local":33}')]
);
const bacen37 = lista.find((c) => c.termo === "BACEN" && c.extracaoLocal === 37)!;
const bacen33 = lista.find((c) => c.termo === "BACEN" && c.extracaoLocal === 33)!;
const prf = lista.find((c) => c.termo === "PRF")!;

assert.equal(bacen37.ehMaisRecenteDoTermo, true);
assert.equal(bacen37.ehUnicoDoTermo, false);
assert.equal(bacen37.destino?.extracaoLocal, 33);   // a web cai para a #33
assert.equal(bacen33.ehMaisRecenteDoTermo, false);
assert.equal(bacen33.destino, null);
assert.equal(bacen33.pedido?.status, "rodando");    // selo na linha certa
assert.equal(bacen37.pedido, null);
assert.equal(prf.ehUnicoDoTermo, true);
assert.equal(prf.ehMaisRecenteDoTermo, true);
assert.equal(prf.destino, null);                    // não há para onde cair
assert.equal(prf.cursos, 128);
assert.equal(prf.blocos, 64838);

// 6. ordem: mais novo primeiro, agrupado por termo
assert.deepEqual(lista.map((c) => `${c.termo}#${c.extracaoLocal}`),
                 ["BACEN#37", "BACEN#33", "PRF#10"]);

console.log("ok — 6 checagens");
```

- [ ] **Step 3: Rodar o check e ver falhar**

Run: `cd web && node --experimental-strip-types checks/coleta.check.ts`
Expected: FAIL — `SyntaxError: The requested module '../lib/coleta.ts' does not provide an export named 'montarAlvoExclusao'`

- [ ] **Step 4: Implementar o mínimo**

Em `web/lib/coleta.ts`, trocar o tipo do campo `tipo` em `Pedido` e no parâmetro de `enfileirar` por `TipoPedido`, e acrescentar ao fim do arquivo:

```ts
export type TipoPedido = "termo" | "ids" | "excluir";

// O alvo de um pedido de exclusão é um JSON, nunca um termo legível — se o
// worker ANTIGO (sem git pull) pegar o pedido, ele trata o JSON como
// search_term, não acha curso nenhum e falha limpo. Um alvo legível faria o
// worker antigo RECOLETAR o termo que se pediu para apagar.
export interface AlvoExclusao {
  termo: string;
  extracaoLocal: number;
  snapshotId: number | null;
  vacuum: boolean;
}

export function montarAlvoExclusao(a: AlvoExclusao): string {
  return JSON.stringify({
    termo: a.termo,
    extracao_local: a.extracaoLocal,
    snapshot_id: a.snapshotId,
    vacuum: a.vacuum,
  });
}

// null quando o alvo não é um pedido de exclusão legível — a tela ignora a
// linha em vez de quebrar (um JSON malformado não pode derrubar a /admin).
export function lerAlvoExclusao(alvo: string): AlvoExclusao | null {
  try {
    const o = JSON.parse(alvo) as Record<string, unknown>;
    const termo = typeof o.termo === "string" ? o.termo.trim() : "";
    const extracaoLocal = typeof o.extracao_local === "number" ? o.extracao_local : null;
    if (!termo || extracaoLocal === null) return null;
    return {
      termo,
      extracaoLocal,
      snapshotId: typeof o.snapshot_id === "number" ? o.snapshot_id : null,
      vacuum: o.vacuum === true,
    };
  } catch {
    return null;
  }
}

// Chave natural da coleta: (termo, extracao_local). NÃO o snapshot_id — ele
// muda se o snapshot for republicado entre o pedido e a execução do worker.
export function chaveColeta(termo: string, extracaoLocal: number): string {
  return `${termo}#${extracaoLocal}`;
}

export function indexarPedidosExclusao(pedidos: Pedido[]): Map<string, Pedido> {
  const mapa = new Map<string, Pedido>();
  for (const p of pedidos) {
    if (p.tipo !== "excluir") continue;
    const alvo = lerAlvoExclusao(p.alvo);
    if (!alvo) continue;
    const chave = chaveColeta(alvo.termo, alvo.extracaoLocal);
    // a lista vem do mais novo para o mais velho: o primeiro é o que vale
    if (!mapa.has(chave)) mapa.set(chave, p);
  }
  return mapa;
}

// Shape cru da tabela `snapshot` (supabase/schema.sql). `resumo` é o
// painel.dados_do_snapshot() serializado pelo sync.
export interface SnapshotLinha {
  id: number;
  termo: string;
  extracao_local: number;
  status: string | null;
  iniciada_em: string | null;
  resumo: { kpis?: { cursos_total?: number; blocos?: number } } | null;
  pronto: boolean;
  sincronizado_em: string;
}

export interface ColetaListada {
  termo: string;
  extracaoLocal: number;
  snapshotId: number;
  pronto: boolean;
  iniciadaEm: string | null;
  sincronizadoEm: string;
  cursos: number | null;
  blocos: number | null;
  ehMaisRecenteDoTermo: boolean;
  ehUnicoDoTermo: boolean;
  // para onde a web cai se esta for apagada (só quando é a mais recente)
  destino: { extracaoLocal: number; iniciadaEm: string | null } | null;
  pedido: Pedido | null;
}

// Deriva tudo que a tela precisa saber ANTES de mostrar o botão. Os dois casos
// de risco (único do termo / mais recente do termo) saem daqui, não da UI:
// snapshot_atual faz `distinct on (termo) ... order by extracao_local desc`,
// então apagar a mais recente troca o que o time vê, em silêncio.
export function montarListaColetas(
  snapshots: SnapshotLinha[],
  pedidos: Pedido[]
): ColetaListada[] {
  const indice = indexarPedidosExclusao(pedidos);
  const porTermo = new Map<string, SnapshotLinha[]>();
  for (const s of snapshots) {
    porTermo.set(s.termo, [...(porTermo.get(s.termo) ?? []), s]);
  }

  const lista: ColetaListada[] = [];
  for (const termo of [...porTermo.keys()].sort((a, b) => a.localeCompare(b, "pt-BR"))) {
    const doTermo = [...(porTermo.get(termo) ?? [])].sort(
      (a, b) => b.extracao_local - a.extracao_local
    );
    doTermo.forEach((s, i) => {
      const anterior = i === 0 ? doTermo[1] : undefined;
      lista.push({
        termo: s.termo,
        extracaoLocal: s.extracao_local,
        snapshotId: s.id,
        pronto: s.pronto,
        iniciadaEm: s.iniciada_em,
        sincronizadoEm: s.sincronizado_em,
        cursos: s.resumo?.kpis?.cursos_total ?? null,
        blocos: s.resumo?.kpis?.blocos ?? null,
        ehMaisRecenteDoTermo: i === 0,
        ehUnicoDoTermo: doTermo.length === 1,
        destino: anterior
          ? { extracaoLocal: anterior.extracao_local, iniciadaEm: anterior.iniciada_em }
          : null,
        pedido: indice.get(chaveColeta(s.termo, s.extracao_local)) ?? null,
      });
    });
  }
  return lista;
}
```

- [ ] **Step 5: Rodar o check e ver passar**

Run: `cd web && node --experimental-strip-types checks/coleta.check.ts`
Expected: `ok — 6 checagens`

- [ ] **Step 6: Conferir os tipos e o build**

Run: `cd web && npx tsc --noEmit && npm run build`
Expected: sem erro de tipo; build limpo

- [ ] **Step 7: Commit**

```bash
git add supabase/schema_coleta_exclusao.sql web/lib/coleta.ts web/checks/coleta.check.ts
git commit -m "feat: alvo JSON da exclusao e derivacao da lista de coletas"
```

---

### Task 5: A server action com as travas

**Files:**
- Modify: `web/app/admin/actions.ts`

**Interfaces:**
- Consumes: `exigirAdmin()` de `web/lib/papeis.ts`; `criarClienteAdmin()` de `web/lib/supabase/admin.ts`; `montarAlvoExclusao`, `lerAlvoExclusao`, `chaveColeta`, `mudarStatus` de `web/lib/coleta.ts`.
- Produces: server actions `pedirExclusaoColeta(formData)` e `retentarExclusao(formData)`.

- [ ] **Step 1: Implementar as actions**

Acrescentar a `web/app/admin/actions.ts` (e ao import de `../../lib/coleta`):

```ts
import {
  montarAlvoExclusao, lerAlvoExclusao, chaveColeta, mudarStatus,
  type Pedido,
} from "../../lib/coleta";

// Pedidos de exclusão que ainda podem agir sobre o alvo.
const EXCLUSAO_EM_JOGO = ["pendente", "rodando"];

export async function pedirExclusaoColeta(formData: FormData) {
  const user = await exigirAdmin();
  const termo = String(formData.get("termo") ?? "").trim();
  const extracaoLocal = Number(formData.get("extracaoLocal"));
  const snapshotId = Number(formData.get("snapshotId"));
  const confirmacao = String(formData.get("confirmacao") ?? "").trim();

  if (!termo || !Number.isInteger(extracaoLocal) || extracaoLocal <= 0) {
    redirect("/admin?msg=exclusao-erro");
  }
  // A confirmação digitada é re-validada NO SERVIDOR — o botão desabilitado do
  // cliente é conveniência, não trava.
  if (confirmacao !== termo) redirect("/admin?msg=exclusao-confirmacao");

  const admin = criarClienteAdmin();

  // Trava 1: já existe pedido de exclusão em jogo para o mesmo alvo.
  const { data: pedidos, error: erroPedidos } = await admin
    .from("coleta_pedido")
    .select("*")
    .eq("tipo", "excluir")
    .in("status", EXCLUSAO_EM_JOGO);
  if (erroPedidos) {
    console.error("[admin] pedirExclusaoColeta (fila):", erroPedidos.message);
    redirect("/admin?msg=exclusao-erro");
  }
  const alvoChave = chaveColeta(termo, extracaoLocal);
  const jaPedido = (pedidos ?? []).some((p) => {
    const a = lerAlvoExclusao((p as Pedido).alvo);
    return a !== null && chaveColeta(a.termo, a.extracaoLocal) === alvoChave;
  });
  if (jaPedido) redirect("/admin?msg=exclusao-repetida");

  // Trava 2: não apagar o que está sendo escrito agora.
  // ATENÇÃO ao alcance real desta trava: `extracao_id` só é gravado no pedido
  // QUANDO ELE CONCLUI, então uma coleta em andamento normalmente tem
  // extracao_id nulo e não é pega aqui. Ela ainda vale para pedidos
  // reprocessados (que já têm o id de uma execução anterior), mas quem de fato
  // serializa exclusão × coleta é o WORKER SER ÚNICO E SERIAL — um pedido por
  // vez. Não remover a trava, mas também não confiar nela como se fosse a
  // garantia principal.
  const { data: rodando, error: erroRodando } = await admin
    .from("coleta_pedido")
    .select("id")
    .eq("status", "rodando")
    .eq("extracao_id", extracaoLocal)
    .limit(1);
  if (erroRodando) {
    console.error("[admin] pedirExclusaoColeta (rodando):", erroRodando.message);
    redirect("/admin?msg=exclusao-erro");
  }
  if ((rodando ?? []).length > 0) redirect("/admin?msg=exclusao-em-uso");

  const { error } = await admin.from("coleta_pedido").insert({
    tipo: "excluir",
    alvo: montarAlvoExclusao({
      termo,
      extracaoLocal,
      snapshotId: Number.isInteger(snapshotId) ? snapshotId : null,
      vacuum: false,   // VACUUM é a entrega 1b
    }),
    rotulo: null,
    pedido_por: user.email ?? "",
    status: "pendente",
  });
  if (error) {
    console.error("[admin] pedirExclusaoColeta (insert):", error.message);
    redirect("/admin?msg=exclusao-erro");
  }
  redirect("/admin?msg=exclusao-enfileirada");
}

export async function retentarExclusao(formData: FormData) {
  await exigirAdmin();
  const id = Number(formData.get("id"));
  if (!id) redirect("/admin?msg=exclusao-erro");

  const admin = criarClienteAdmin();
  let mudou: boolean;
  try {
    // Transição ATÔMICA (update condicional): se o status mudou entre o
    // render e o clique, zero linhas são atualizadas e nada é sobrescrito.
    mudou = await mudarStatus(admin, id, "pendente", ["erro"], {
      mensagem: null, progresso: null, iniciado_em: null,
      concluido_em: null, extracao_id: null,
    });
  } catch (e) {
    console.error("[admin] retentarExclusao:", e instanceof Error ? e.message : e);
    redirect("/admin?msg=exclusao-erro");
  }
  if (!mudou) redirect("/admin?msg=exclusao-status-mudou");
  redirect("/admin?msg=exclusao-retentada");
}
```

- [ ] **Step 2: Conferir os tipos**

Run: `cd web && npx tsc --noEmit`
Expected: sem erro

- [ ] **Step 3: Commit**

```bash
git add web/app/admin/actions.ts
git commit -m "feat: action de exclusao de coleta com travas de admin e de alvo em uso"
```

---

### Task 6: A tela

**Files:**
- Create: `web/app/admin/coletas.tsx`
- Modify: `web/app/admin/page.tsx`
- Modify: `web/app/coleta/fila.tsx`

**Interfaces:**
- Consumes: `montarListaColetas`, `ColetaListada`, `lerAlvoExclusao` de `web/lib/coleta.ts`; `pedirExclusaoColeta`, `retentarExclusao` de `web/app/admin/actions.ts`; `criarClienteServidor()` de `web/lib/supabase/servidor.ts`.
- Produces: componente cliente `ListaColetas({ coletas }: { coletas: ColetaListada[] })`.

- [ ] **Step 1: Criar o componente da lista**

Criar `web/app/admin/coletas.tsx`:

```tsx
"use client";

import { useState, type CSSProperties } from "react";
import type { ColetaListada } from "../../lib/coleta";
import { pedirExclusaoColeta, retentarExclusao } from "./actions";

const celula: CSSProperties = { padding: "8px 10px", borderBottom: "1px solid #e3e2dd" };

const dataLocal = (iso: string | null) =>
  iso
    ? new Date(iso).toLocaleString("pt-BR", {
        day: "2-digit", month: "2-digit", year: "2-digit",
        hour: "2-digit", minute: "2-digit", timeZone: "America/Sao_Paulo",
      })
    : "—";

const numero = (n: number | null) => (n === null ? "—" : n.toLocaleString("pt-BR"));

function Confirmacao({ coleta, aoFechar }: { coleta: ColetaListada; aoFechar: () => void }) {
  const [digitado, setDigitado] = useState("");
  const confere = digitado.trim() === coleta.termo;

  return (
    <form action={pedirExclusaoColeta} style={{
      border: "1px solid #e0b4ae", background: "#fdf6f5", borderRadius: 8,
      padding: "12px 14px", margin: "8px 0",
    }}>
      <input type="hidden" name="termo" value={coleta.termo} />
      <input type="hidden" name="extracaoLocal" value={coleta.extracaoLocal} />
      <input type="hidden" name="snapshotId" value={coleta.snapshotId} />

      <p style={{ margin: "0 0 8px", fontWeight: 600 }}>
        Excluir a coleta #{coleta.extracaoLocal} de {coleta.termo}
      </p>
      <p style={{ margin: "0 0 8px", fontSize: 12.5, color: "#52514e" }}>
        {numero(coleta.cursos)} cursos · {numero(coleta.blocos)} blocos ·{" "}
        {dataLocal(coleta.iniciadaEm)}. Apaga o snapshot na web <strong>e</strong> a
        extração no conteudo.db do VPS. Não tem volta.
      </p>

      {coleta.ehUnicoDoTermo && (
        <p style={{ margin: "0 0 8px", fontSize: 12.5, color: "#b9770e" }}>
          ⚠ É a única coleta de {coleta.termo} — o termo some do seletor da web.
        </p>
      )}
      {!coleta.ehUnicoDoTermo && coleta.ehMaisRecenteDoTermo && coleta.destino && (
        <p style={{ margin: "0 0 8px", fontSize: 12.5, color: "#b9770e" }}>
          ⚠ É a coleta mais recente de {coleta.termo} — a web passa a exibir a
          #{coleta.destino.extracaoLocal} de {dataLocal(coleta.destino.iniciadaEm)}.
        </p>
      )}

      <label style={{ fontSize: 12.5, display: "block", marginBottom: 6 }}>
        Digite <strong>{coleta.termo}</strong> para confirmar:
      </label>
      <input
        name="confirmacao" value={digitado} autoComplete="off"
        onChange={(e) => setDigitado(e.target.value)}
        style={{
          font: "inherit", padding: "6px 10px", border: "1px solid #e3e2dd",
          borderRadius: 6, width: 220, marginRight: 8,
        }}
      />
      <button type="button" onClick={aoFechar} style={{
        font: "inherit", fontSize: 13, cursor: "pointer", background: "transparent",
        border: "1px solid #cfceca", borderRadius: 6, padding: "5px 12px", marginRight: 6,
      }}>
        Cancelar
      </button>
      <button type="submit" disabled={!confere} style={{
        font: "inherit", fontSize: 13, fontWeight: 600,
        cursor: confere ? "pointer" : "not-allowed",
        background: confere ? "#c0392b" : "#e3e2dd",
        color: confere ? "#fff" : "#8a897f",
        border: 0, borderRadius: 6, padding: "6px 14px",
      }}>
        Excluir
      </button>
    </form>
  );
}

function EstadoDoPedido({ coleta }: { coleta: ColetaListada }) {
  const p = coleta.pedido;
  if (!p) return null;
  if (p.status === "pendente") return <span style={{ color: "#b9770e" }}>⏳ exclusão pedida</span>;
  if (p.status === "rodando") return <span style={{ color: "#2a5fa8" }}>⏳ exclusão rodando</span>;
  return (
    <form action={retentarExclusao} style={{ display: "inline" }}>
      <input type="hidden" name="id" value={p.id} />
      <span style={{ color: "#c0392b" }} title={p.mensagem ?? ""}>
        ⛔ falhou: {(p.mensagem ?? "erro").slice(0, 60)}
      </span>{" "}
      <button type="submit" style={{
        font: "inherit", fontSize: 12, cursor: "pointer", background: "transparent",
        border: "1px solid #cfceca", borderRadius: 6, padding: "2px 8px",
      }}>
        Retentar
      </button>
    </form>
  );
}

export function ListaColetas({ coletas }: { coletas: ColetaListada[] }) {
  const [abertaEm, setAbertaEm] = useState<string | null>(null);

  if (coletas.length === 0) {
    return <p style={{ color: "#8a897f", fontSize: 13 }}>Nenhuma coleta publicada ainda.</p>;
  }

  return (
    <>
      <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 13 }}>
        <thead>
          <tr>
            {["Termo", "#", "Quando", "Cursos", "Blocos", ""].map((t) => (
              <th key={t} style={{
                textAlign: "left", padding: "8px 10px", color: "#52514e",
                fontSize: 11, letterSpacing: ".07em", textTransform: "uppercase",
                borderBottom: "1px solid #e3e2dd",
              }}>{t}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {coletas.map((c) => {
            const chave = `${c.termo}#${c.extracaoLocal}`;
            return (
              <tr key={chave}>
                <td style={celula}>
                  {c.termo}
                  {!c.pronto && (
                    <span style={{ color: "#b9770e", fontSize: 11 }}> (incompleta)</span>
                  )}
                </td>
                <td style={celula}>{c.extracaoLocal}</td>
                <td style={celula}>{dataLocal(c.iniciadaEm)}</td>
                <td style={celula}>{numero(c.cursos)}</td>
                <td style={celula}>{numero(c.blocos)}</td>
                <td style={{ ...celula, whiteSpace: "nowrap" }}>
                  {c.pedido ? (
                    <EstadoDoPedido coleta={c} />
                  ) : (
                    <button
                      type="button"
                      onClick={() => setAbertaEm(abertaEm === chave ? null : chave)}
                      style={{
                        font: "inherit", fontSize: 12, cursor: "pointer",
                        background: "transparent", color: "#c0392b",
                        border: "1px solid #e0b4ae", borderRadius: 6, padding: "2px 8px",
                      }}
                    >
                      Excluir
                    </button>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {coletas
        .filter((c) => `${c.termo}#${c.extracaoLocal}` === abertaEm)
        .map((c) => (
          <Confirmacao
            key={`${c.termo}#${c.extracaoLocal}`}
            coleta={c}
            aoFechar={() => setAbertaEm(null)}
          />
        ))}

      <p style={{ color: "#8a897f", fontSize: 12, marginTop: 10 }}>
        Esta lista mostra o que está publicado na web. Coletas que ficaram só no
        conteudo.db do VPS (quando o sync falhou) ocupam disco e <strong>não
        aparecem aqui</strong>.
      </p>
    </>
  );
}
```

- [ ] **Step 2: Ligar na página**

Em `web/app/admin/page.tsx`, acrescentar aos imports:

```tsx
import { montarListaColetas, type SnapshotLinha, type Pedido } from "../../lib/coleta";
import { ListaColetas } from "./coletas";
```

Acrescentar às mensagens do `MENSAGENS`:

```tsx
  "exclusao-enfileirada": () =>
    "✅ Exclusão enfileirada — o worker executa em até 20 segundos.",
  "exclusao-repetida": () => "⚠ Já existe um pedido de exclusão para essa coleta.",
  "exclusao-em-uso": () => "⛔ Essa extração está sendo escrita por uma coleta em andamento.",
  "exclusao-confirmacao": () => "⚠ O termo digitado não confere — nada foi excluído.",
  "exclusao-status-mudou": () => "⚠ O status do pedido mudou — recarregue a página.",
  "exclusao-retentada": () => "✅ Pedido de exclusão devolvido para a fila.",
  "exclusao-erro": () => "❌ Não foi possível concluir a exclusão — tente de novo.",
```

Depois da consulta de `cookie_status`, acrescentar (usa `supabase`, o cliente com o JWT do
usuário — `snapshot` e `coleta_pedido` têm policy de leitura `authenticated`):

```tsx
  // A fonte é a TABELA snapshot, não a view snapshot_atual: a view faz
  // `distinct on (termo)` e filtra pronto, escondendo justamente os candidatos
  // a lixo (os antigos e os incompletos).
  const { data: snapshots } = await supabase
    .from("snapshot")
    .select("id, termo, extracao_local, status, iniciada_em, resumo, pronto, sincronizado_em")
    .order("termo")
    .order("extracao_local", { ascending: false });
  const { data: pedidos } = await supabase
    .from("coleta_pedido")
    .select("*")
    .eq("tipo", "excluir")
    .order("criado_em", { ascending: false })
    .limit(50);
  const coletas = montarListaColetas(
    (snapshots ?? []) as SnapshotLinha[],
    (pedidos ?? []) as Pedido[]
  );
```

E, antes de `<CookieLdi ... />`, acrescentar a seção:

```tsx
      <h2 style={{ fontSize: 17, fontWeight: 650, margin: "28px 0 4px" }}>
        Coletas publicadas
      </h2>
      <p style={{ color: "#52514e", fontSize: 13, margin: "0 0 12px" }}>
        Excluir apaga o snapshot na web <strong>e</strong> a extração no conteudo.db
        do VPS. As pendências são preservadas.
      </p>
      <ListaColetas coletas={coletas} />
```

- [ ] **Step 3: Deixar o pedido de exclusão legível na fila**

Em `web/app/coleta/fila.tsx`, acrescentar ao import de tipos e depois do helper `dataLocal`:

```tsx
import { lerAlvoExclusao } from "../../lib/coleta";

// Sem isto a coluna "Rótulo / alvo" despeja o JSON cru do pedido de exclusão.
function descreverAlvo(p: Pedido): string {
  if (p.tipo !== "excluir") return p.alvo;
  const alvo = lerAlvoExclusao(p.alvo);
  return alvo ? `excluir a coleta #${alvo.extracaoLocal} de ${alvo.termo}` : p.alvo;
}
```

E, na célula do alvo, trocar as duas ocorrências de `p.alvo` (o `title` e o texto)
por `descreverAlvo(p)`:

```tsx
            <td style={{ ...celula, maxWidth: 260 }} title={descreverAlvo(p)}>
              {p.rotulo ? <strong>{p.rotulo}</strong> : <span style={{ color: "#8a897f" }}>({p.tipo})</span>}
              <div
                style={{
                  fontSize: 11, color: "#8a897f", overflow: "hidden",
                  textOverflow: "ellipsis", whiteSpace: "nowrap",
                }}
              >
                {descreverAlvo(p)}
              </div>
            </td>
```

- [ ] **Step 4: Conferir tipos e build**

Run: `cd web && npx tsc --noEmit && npm run build`
Expected: build limpo

- [ ] **Step 5: Conferir que o bundle do cliente não vazou segredo**

Run: `cd web && grep -rl "service_role\|SUPABASE_SERVICE_KEY" .next/static/ ; echo "saida-acima-tem-de-ser-vazia"`
Expected: nenhum arquivo listado

- [ ] **Step 6: Rodar a suíte Python e o check TS de novo**

Run: `py -m unittest discover -s tests && cd web && node --experimental-strip-types checks/coleta.check.ts`
Expected: OK + `ok — 6 checagens`

- [ ] **Step 7: Commit**

```bash
git add web/app/admin/coletas.tsx web/app/admin/page.tsx web/app/coleta/fila.tsx
git commit -m "feat: tela de coletas publicadas com exclusao confirmada pelo termo"
```

---

## Verificação final (fora do código — exige o Clovis)

Na ordem do spec. **O passo 3 é o que não pode ser pulado.**

1. `py -m unittest discover -s tests` — suíte inteira verde.
2. Aplicar `supabase/schema_coleta_exclusao.sql` no Supabase (Dashboard → SQL Editor → Run);
   conferir com um `insert` de teste que `tipo='excluir'` é aceito e `tipo='xpto'` é recusado.
3. **Antes de atualizar o worker**, enfileirar um pedido `excluir` e confirmar que o worker
   antigo o marca `erro` sem coletar nada — a defesa da migração, provada e não presumida.
4. `git pull` + `systemctl restart worker-coleta` no VPS; retentar o mesmo pedido.
5. Alvo real: a **extração 1 ou 2 do BACEN** (64.838 blocos cada, duplicatas idênticas) —
   conferir que a outra fica intacta e que `pendencias`/`acionamentos` não mudam de contagem.
6. Conferir na web que o snapshot sumiu do seletor e que o termo caiu para a coleta anterior.

**Ordem de deploy:** SQL no Supabase → provar a falha limpa do worker antigo → `git pull` +
restart do worker → merge da web.
