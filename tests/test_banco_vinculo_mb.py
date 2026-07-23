import os, tempfile, unittest
import banco_conteudo


class TestVinculoMB(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.db = os.path.join(self.dir, "c.db")

    def _semear_aula(self, con, e, item_id):
        con.execute(
            "INSERT OR REPLACE INTO aulas(extracao_id, curso_id, capitulo_id, item_id, nome) "
            "VALUES(?,?,?,?,?)", (e, "cur1", "cap1", item_id, "Item " + item_id))
        con.commit()

    def test_coluna_existe_e_default_null(self):
        con = banco_conteudo.abrir(self.db)
        self._semear_aula(con, 1, "i1")
        v = con.execute("SELECT vinculado_mb FROM aulas WHERE item_id='i1'").fetchone()[0]
        self.assertIsNone(v)  # desconhecido até a coleta gravar

    def test_gravar_vinculo_mb(self):
        con = banco_conteudo.abrir(self.db)
        for i in ("i1", "i2", "i3"):
            self._semear_aula(con, 1, i)
        banco_conteudo.gravar_vinculo_mb(con, 1, {"i1": True, "i2": False})
        got = {r[0]: r[1] for r in con.execute(
            "SELECT item_id, vinculado_mb FROM aulas WHERE extracao_id=1")}
        self.assertEqual(got["i1"], 1)
        self.assertEqual(got["i2"], 0)
        self.assertIsNone(got["i3"])  # não informado permanece NULL


if __name__ == "__main__":
    unittest.main()
