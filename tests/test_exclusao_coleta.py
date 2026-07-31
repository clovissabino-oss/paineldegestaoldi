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
