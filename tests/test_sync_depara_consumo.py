import os, tempfile, unittest
from unittest.mock import patch, MagicMock
import banco_conteudo
import sync_supabase


def _base_com_videos(caminho):
    con = banco_conteudo.abrir(caminho)
    con.execute("INSERT INTO extracoes(id, termo, vertical, iniciada_em, status) "
                "VALUES(1,'X','concursos','2026-07-23T00:00:00','completa')")
    con.execute("INSERT INTO aulas(extracao_id, curso_id, capitulo_id, item_id, nome) "
                "VALUES(1,'c1','cap1','i1','Aula')")
    # dois vídeos: um com id antigo, um sem (id vazio deve ser ignorado)
    con.execute("INSERT INTO blocos(extracao_id, item_id, bloco_id, tipo, video_id_antigo) "
                "VALUES(1,'i1','b1','videoMyDocuments','37025')")
    con.execute("INSERT INTO blocos(extracao_id, item_id, bloco_id, tipo, video_id_antigo) "
                "VALUES(1,'i1','b2','videoMyDocuments','')")
    con.commit()
    return con


class TestDeparaDoSupabase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.con = _base_com_videos(os.path.join(self.tmp, "c.db"))

    @patch("sync_supabase.requests.get")
    def test_monta_dict_shape_do_gz(self, mock_get):
        mock_get.return_value = MagicMock(
            raise_for_status=lambda: None,
            json=lambda: [{"video_id": "37025", "data": "2019-02-11T21:49:49",
                           "dur": "00:20:33", "status": "Disponível",
                           "titulo": "T", "raiz": "R", "path": "P", "n": 3}])
        depara = sync_supabase.depara_do_supabase("http://mock/rest/v1", "k", self.con, 1)
        self.assertIn("37025", depara)
        self.assertEqual(depara["37025"]["data"], "2019-02-11T21:49:49")
        # só o id não-vazio foi consultado
        chamada = mock_get.call_args
        self.assertIn("37025", str(chamada))
        self.assertNotIn("in.()", str(chamada))  # não consulta lista vazia

    @patch("sync_supabase.requests.get")
    def test_sem_ids_devolve_vazio(self, mock_get):
        con = banco_conteudo.abrir(os.path.join(self.tmp, "vazia.db"))
        con.execute("INSERT INTO extracoes(id, termo, vertical, iniciada_em, status) "
                    "VALUES(1,'X','c','2026-07-23T00:00:00','completa')")
        con.commit()
        depara = sync_supabase.depara_do_supabase("http://mock/rest/v1", "k", con, 1)
        self.assertEqual(depara, {})
        mock_get.assert_not_called()  # sem ids, nem consulta


if __name__ == "__main__":
    unittest.main()
