# -*- coding: utf-8 -*-
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import banco_conteudo
import painel
from tests.test_banco_conteudo import CURSOS, B1

B_TIPTAP = {"bloco_id": "b2", "tipo": "tiptap", "ordem": 2, "ativo": 1, "rascunho": 0,
            "titulo": "", "questao_id": "", "resposta_tipo": "",
            "tem_solucao": None, "tem_video_solucao": None, "video_id_antigo": "",
            "duracao_seg": None, "tamanho_texto": 99, "meta": {}}


class TestDadosDoSnapshot(unittest.TestCase):
    def test_base_vazia_devolve_none(self):
        with tempfile.TemporaryDirectory() as d:
            con = banco_conteudo.abrir(os.path.join(d, "conteudo.db"))
            self.assertIsNone(painel.dados_do_snapshot(con))
            con.close()

    def test_agrega_snapshot_mais_recente(self):
        with tempfile.TemporaryDirectory() as d:
            con = banco_conteudo.abrir(os.path.join(d, "conteudo.db"))
            eid = banco_conteudo.iniciar_extracao(con, "BACEN", "concursos")
            banco_conteudo.gravar_arvore(con, eid, CURSOS)
            banco_conteudo.gravar_blocos_da_aula(con, eid, "i1", [B1])
            banco_conteudo.gravar_blocos_da_aula(con, eid, "i2", [B_TIPTAP])
            banco_conteudo.finalizar_extracao(con, eid, {})

            dados = painel.dados_do_snapshot(con)
            con.close()

            self.assertEqual(dados["extracao"]["termo"], "BACEN")
            self.assertEqual(dados["extracao"]["status"], "completa")
            k = dados["kpis"]
            self.assertEqual((k["cursos_total"], k["cursos_com_aulas"]), (2, 2))
            self.assertEqual((k["aulas_unicas"], k["vinculos"], k["blocos"]), (2, 3, 2))
            self.assertEqual((k["questoes"], k["textos"]), (1, 1))
            self.assertEqual(dados["tipos"][0], ["Questões", 1])
            self.assertEqual(len(dados["cursos"]), 2)
            self.assertEqual(dados["achados"]["q_sem_solucao"], 0)
            # só o Curso B fica sem vídeo (o A tem a aula i2 com videoMyDocuments)
            self.assertEqual(dados["achados"]["cursos_sem_video"], 1)


if __name__ == "__main__":
    unittest.main()
