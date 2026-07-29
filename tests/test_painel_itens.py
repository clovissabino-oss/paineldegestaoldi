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
