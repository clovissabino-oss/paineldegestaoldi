# -*- coding: utf-8 -*-
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

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
               "alvo": '{"termo":"BACEN","extracao_local":37,"snapshot_id":12,'
                       '"iniciada_em":"2026-07-06T23:56:22+00:00","vacuum":false}'}
        self.assertEqual(exclusao_coleta.ler_pedido_exclusao(row),
                         ("BACEN", 37, "2026-07-06T23:56:22+00:00", False))

    def test_vacuum_ausente_vira_false(self):
        row = {"tipo": "excluir",
               "alvo": '{"termo":"PRF","extracao_local":3,'
                       '"iniciada_em":"2026-07-20T16:07:00"}'}
        self.assertFalse(exclusao_coleta.ler_pedido_exclusao(row).vacuum)

    def test_sem_iniciada_em_recusa(self):
        """Alvo do formato antigo (pedido #16 de 31/07). Sem a data não dá para
        saber de QUAL banco é a extração N — recusar é a única resposta segura."""
        row = {"tipo": "excluir",
               "alvo": '{"termo":"BACEN","extracao_local":2,"vacuum":false}'}
        with self.assertRaises(SystemExit) as ctx:
            exclusao_coleta.ler_pedido_exclusao(row)
        self.assertIn("iniciada_em", str(ctx.exception))

    def test_mensagem_do_erro_chega_na_excecao(self):
        """extrator_ldi.falha levanta SystemExit(1) e a fila mostra "1". Aqui a
        mensagem tem de VIAJAR na exceção, senão o admin lê "1" na tela."""
        with self.assertRaises(SystemExit) as ctx:
            exclusao_coleta.ler_pedido_exclusao({"tipo": "excluir", "alvo": "BACEN"})
        self.assertIn("alvo ilegível", str(ctx.exception))
        self.assertNotEqual(str(ctx.exception), "1")

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

    def _data(self, eid):
        return self.con.execute("SELECT iniciada_em FROM extracoes WHERE id=?",
                                (eid,)).fetchone()[0]

    def test_conferir_extracao(self):
        eid = self._nova()
        data = self._data(eid)
        self.assertEqual(
            exclusao_coleta.conferir_extracao(self.con, eid, "BACEN", data)["id"], eid)
        # extração inexistente devolve None (idempotência: o snapshot pode ter sobrado)
        self.assertIsNone(
            exclusao_coleta.conferir_extracao(self.con, 9999, "BACEN", data))
        # termo divergente nunca apaga o alvo errado
        with self.assertRaises(SystemExit):
            exclusao_coleta.conferir_extracao(self.con, eid, "PRF", data)

    def test_data_do_supabase_com_fuso_casa_com_a_naive_do_sqlite(self):
        """O SQLite guarda '2026-07-06T23:56:22'; o Supabase devolve
        '2026-07-06T23:56:22+00:00'. Têm de casar, senão nada seria apagável."""
        eid = self._nova()
        self.assertIsNotNone(exclusao_coleta.conferir_extracao(
            self.con, eid, "BACEN", self._data(eid)[:19] + "+00:00"))

    def test_mesmo_numero_e_mesmo_termo_mas_outra_origem_recusa(self):
        """O caso REAL de 31/07: o Supabase tinha BACEN extracao_local=1 de
        30/07, e a extração 1 deste banco era outro BACEN, de 06/07. Só o termo
        não desempata — a data desempata, e a recusa evita apagar a errada."""
        eid = self._nova()
        antes = self._contagens(eid)
        with self.assertRaises(SystemExit) as ctx:
            exclusao_coleta.conferir_extracao(self.con, eid, "BACEN",
                                              "2030-01-01T00:00:00+00:00")
        self.assertIn("coletas diferentes com o mesmo número", str(ctx.exception))
        self.assertEqual(self._contagens(eid), antes)  # nada tocado

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

    def test_listar_marca_publicada_e_aceita_desconhecido(self):
        """A coluna 'publicada?' é o que evita apagar a origem de uma coleta que a
        web ainda usa. Sem rede (publicadas=None) a listagem NÃO pode quebrar —
        listar é leitura e tem de funcionar offline."""
        eid1 = self._nova()
        eid2 = self._nova("PRF")
        data1 = self._data(eid1)
        linhas = exclusao_coleta.listar_extracoes(
            self.con, {("BACEN", data1[:19])})
        por_id = {l["id"]: l for l in linhas}
        self.assertIs(por_id[eid1]["publicada"], True)
        self.assertIs(por_id[eid2]["publicada"], False)
        self.assertEqual(por_id[eid1]["termo"], "BACEN")
        self.assertGreater(por_id[eid1]["blocos"], 0)
        # sem informação do Supabase: publicada = None (a tela mostra "?")
        linhas = exclusao_coleta.listar_extracoes(self.con, None)
        self.assertTrue(all(l["publicada"] is None for l in linhas))


class TestPublicadasNoSupabase(unittest.TestCase):
    @patch("exclusao_coleta.sync_supabase.esta_configurado", return_value=False)
    def test_sem_credencial_devolve_none(self, _):
        self.assertIsNone(exclusao_coleta.publicadas_no_supabase())

    @patch("exclusao_coleta.requests.get", side_effect=Exception("rede fora"))
    @patch("exclusao_coleta.sync_supabase._config", return_value=("http://x", "k"))
    @patch("exclusao_coleta.sync_supabase.esta_configurado", return_value=True)
    def test_rede_fora_devolve_none_sem_levantar(self, *_):
        """Listar é leitura: rede fora vira '?' na coluna, nunca um traceback."""
        self.assertIsNone(exclusao_coleta.publicadas_no_supabase())

    @patch("exclusao_coleta.sync_supabase._config", return_value=("http://x", "k"))
    @patch("exclusao_coleta.sync_supabase.esta_configurado", return_value=True)
    @patch("exclusao_coleta.requests.get")
    def test_normaliza_a_data_para_19_caracteres(self, mock_get, *_):
        mock_get.return_value = MagicMock(
            raise_for_status=lambda: None,
            json=lambda: [{"termo": "BACEN", "iniciada_em": "2026-07-06T23:56:22+00:00"},
                          {"termo": "PRF", "iniciada_em": None}])
        pub = exclusao_coleta.publicadas_no_supabase()
        self.assertIn(("BACEN", "2026-07-06T23:56:22"), pub)
        self.assertEqual(len(pub), 1)   # linha sem data é descartada


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
