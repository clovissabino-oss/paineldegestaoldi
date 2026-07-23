# -*- coding: utf-8 -*-
"""Testa a agregação pura do sync (montar_payload) contra um conteudo.db de fixture."""
import os
import tempfile
import unittest

import banco_conteudo
import painel
import sync_supabase


def _fixture(caminho):
    """Um snapshot mínimo: 1 curso, 1 capítulo, 1 aula, 1 questão, 1 vídeo, 1 pendência."""
    con = banco_conteudo.abrir(caminho)
    with con:
        con.execute("INSERT INTO extracoes(id,termo,vertical,iniciada_em,status) "
                    "VALUES(1,'TESTE','x','2026-07-06T10:00:00','completa')")
        con.execute("INSERT INTO cursos VALUES(1,'C1','Curso Um',1,'Prof A','')")
        con.execute("INSERT INTO capitulos VALUES(1,'C1','CAP1','Capitulo 1',0,'','')")
        con.execute("INSERT INTO aulas VALUES(1,'C1','CAP1','IT1','Aula 1','','',1,1,0,0,0,0,NULL)")
        con.execute("INSERT INTO aulas_coletadas VALUES(1,'IT1',2,'2026-07-06T10:05:00')")
        con.execute("INSERT INTO blocos(extracao_id,item_id,bloco_id,tipo,tem_solucao,"
                    "tem_video_solucao,banca,ano) "
                    "VALUES(1,'IT1','B1','question',1,0,'CESPE',2020)")
        con.execute("INSERT INTO blocos(extracao_id,item_id,bloco_id,tipo,"
                    "video_id_antigo,duracao_seg) "
                    "VALUES(1,'IT1','B2','videoMyDocuments','123',600)")
        con.execute("INSERT INTO pendencias(chave,regra,severidade,curso_id,status) "
                    "VALUES('k1','Q1','alta','C1','nova')")
    return con


class TestMontarPayload(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.con = _fixture(os.path.join(self.tmp, "conteudo.db"))

    def tearDown(self):
        self.con.close()

    def test_snapshot_reflete_a_extracao(self):
        rows = sync_supabase.montar_payload(self.con)
        self.assertEqual(rows["snapshot"]["termo"], "TESTE")
        self.assertEqual(rows["snapshot"]["extracao_local"], 1)
        self.assertEqual(rows["snapshot"]["status"], "completa")
        self.assertIsNotNone(rows["snapshot"]["resumo"])

    def test_uma_avaliacao_por_curso_com_aulas(self):
        rows = sync_supabase.montar_payload(self.con)
        self.assertEqual(len(rows["avaliacoes"]), 1)
        self.assertEqual(rows["avaliacoes"][0]["curso_id"], "C1")
        self.assertEqual(rows["avaliacoes"][0]["curso_nome"], "Curso Um")

    def test_paridade_com_painel(self):
        # o número na web tem que ser LITERALMENTE o do painel.py
        rows = sync_supabase.montar_payload(self.con)
        esperado = painel.dados_avaliacao(self.con, "C1", depara=painel._depara())
        self.assertEqual(rows["avaliacoes"][0]["payload"], esperado)

    def test_pendencias_abertas(self):
        rows = sync_supabase.montar_payload(self.con)
        self.assertIn({"severidade": "alta", "regra": "Q1", "abertas": 1},
                      rows["pendencias"])

    def test_base_vazia_devolve_none(self):
        con = banco_conteudo.abrir(os.path.join(self.tmp, "vazia.db"))
        try:
            self.assertIsNone(sync_supabase.montar_payload(con))
        finally:
            con.close()


if __name__ == "__main__":
    unittest.main()
