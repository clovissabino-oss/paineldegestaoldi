import os, tempfile, unittest
import banco_conteudo
import painel


def _semear(con):
    con.execute("INSERT INTO extracoes(id, termo, vertical, iniciada_em, status) "
                "VALUES(1,'X','concursos','2026-07-23T00:00:00','completa')")
    con.execute("INSERT INTO cursos(extracao_id, curso_id, nome) VALUES(1,'cur1','Curso 1')")
    con.execute("INSERT INTO capitulos(extracao_id, curso_id, capitulo_id, nome, ordem) "
                "VALUES(1,'cur1','capA','Aula A',1)")
    con.execute("INSERT INTO capitulos(extracao_id, curso_id, capitulo_id, nome, ordem) "
                "VALUES(1,'cur1','capB','Aula B',2)")
    # capA: i1 vinculado, i2 fora  -> aula MISTA (conta como fora)
    # capB: i3 vinculado, i4 desconhecido(NULL)
    dados = [("capA", "i1", 1), ("capA", "i2", 0), ("capB", "i3", 1), ("capB", "i4", None)]
    for cap, item, v in dados:
        con.execute("INSERT INTO aulas(extracao_id, curso_id, capitulo_id, item_id, nome, vinculado_mb) "
                    "VALUES(1,'cur1',?,?,?,?)", (cap, item, item, v))
    con.commit()


class TestPainelVinculoMB(unittest.TestCase):
    def setUp(self):
        self.db = os.path.join(tempfile.mkdtemp(), "c.db")
        self.con = banco_conteudo.abrir(self.db)
        _semear(self.con)

    def test_kpi_itens_mb(self):
        d = painel.dados_do_snapshot(self.con)
        # conhecidos: i1,i2,i3 (i4 NULL não entra no total); vinculados: i1,i3
        self.assertEqual(d["kpis"]["itens_total"], 3)
        self.assertEqual(d["kpis"]["itens_mb"], 2)

    def test_achado_aulas_com_item_fora(self):
        d = painel.dados_do_snapshot(self.con)
        # só capA tem item conhecido fora do MB (i2=0); capB não tem 0
        self.assertEqual(d["achados"]["aulas_com_item_fora_mb"], 1)

    def test_avaliacao_por_aula(self):
        d = painel.dados_avaliacao(self.con, "cur1", depara={})
        por_nome = {c["nome"]: c for c in d["capitulos"]}
        self.assertEqual((por_nome["Aula A"]["itens_mb"], por_nome["Aula A"]["itens_total"]), (1, 2))
        self.assertEqual((por_nome["Aula B"]["itens_mb"], por_nome["Aula B"]["itens_total"]), (1, 1))


if __name__ == "__main__":
    unittest.main()
