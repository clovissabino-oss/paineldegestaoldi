# -*- coding: utf-8 -*-
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import banco_conteudo
import exclusao_coleta
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


if __name__ == "__main__":
    unittest.main()
