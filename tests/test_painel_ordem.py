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
