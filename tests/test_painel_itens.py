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


if __name__ == "__main__":
    unittest.main()
