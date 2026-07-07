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
            # anos (ano_atual=2026): 2019 e 2016 = faixa crítica; 2025 = recente
            self.assertEqual((cap["q_ate"], cap["q_meio"], cap["q_novo"]), (2, 0, 1))
            self.assertEqual(cap["q_com_ano"], 3)
            self.assertEqual((cap["sol_texto"], cap["sol_video"]), (1, 0))
            # vídeo gravado em 2019: 7 anos -> faixa crítica
            self.assertEqual((cap["vids"], cap["v_com_data"], cap["v_ate"]), (1, 1, 1))
            self.assertEqual(cap["dur"], 600)


if __name__ == "__main__":
    unittest.main()
