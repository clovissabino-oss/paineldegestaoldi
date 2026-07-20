import unittest
from unittest.mock import MagicMock
import extrator_ldi

class TestObterCurso(unittest.TestCase):
    def _sessao(self, payload, status=200):
        s = MagicMock()
        resp = MagicMock(status_code=status, ok=(status == 200))
        resp.json.return_value = payload
        s.get.return_value = resp
        return s

    def test_devolve_curso_com_arvore(self):
        curso = {"id": "42f7-uuid", "name": "Curso X",
                 "content_tree_cache": [{"chapter_id": "c1", "items": [{"item_id": "i1"}]}]}
        s = self._sessao({"data": curso})
        r = extrator_ldi.obter_curso(s, "42f7-uuid")
        self.assertEqual(r["id"], "42f7-uuid")
        self.assertIn("content_tree_cache", r)
        # usou o endpoint por ID
        self.assertIn("/bo/ldi/courses/42f7-uuid", s.get.call_args[0][0])

    def test_data_vazio_vira_none(self):
        s = self._sessao({"data": None})
        self.assertIsNone(extrator_ldi.obter_curso(s, "x"))

if __name__ == "__main__":
    unittest.main()
