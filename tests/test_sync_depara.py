import unittest
import sync_depara_supabase as sd


class TestLinhasDoGz(unittest.TestCase):
    def test_transforma_registro_completo(self):
        gz = {"37025": {"data": "2019-02-11T21:49:49", "status": "Disponível",
                        "titulo": "T", "raiz": "R", "path": "P", "dur": "00:20:33", "n": 3}}
        linhas = sd.linhas_do_gz(gz)
        self.assertEqual(len(linhas), 1)
        r = linhas[0]
        self.assertEqual(r["video_id"], "37025")
        self.assertEqual(r["data"], "2019-02-11T21:49:49")
        self.assertEqual(r["dur"], "00:20:33")
        self.assertEqual(r["n"], 3)

    def test_campos_ausentes_viram_none(self):
        gz = {"1": {"data": "2020-01-01T00:00:00"}}  # só data
        r = sd.linhas_do_gz(gz)[0]
        self.assertEqual(r["video_id"], "1")
        self.assertIsNone(r["titulo"])
        self.assertIsNone(r["n"])

    def test_gz_vazio(self):
        self.assertEqual(sd.linhas_do_gz({}), [])


class TestEmLotes(unittest.TestCase):
    def test_divide_em_lotes(self):
        got = list(sd.em_lotes(list(range(23)), 10))
        self.assertEqual([len(x) for x in got], [10, 10, 3])

    def test_vazio(self):
        self.assertEqual(list(sd.em_lotes([], 10)), [])


if __name__ == "__main__":
    unittest.main()
