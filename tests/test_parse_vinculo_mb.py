import unittest
import parse_blocos


class TestVinculoMbDosItens(unittest.TestCase):
    def test_extrai_flag_por_item(self):
        data = [
            {"id": "i1", "has_base_material": True, "name": "A"},
            {"id": "i2", "has_base_material": False, "name": "B"},
        ]
        self.assertEqual(parse_blocos.vinculo_mb_dos_itens(data),
                         {"i1": True, "i2": False})

    def test_ausencia_de_flag_vira_false(self):
        data = [{"id": "i3", "name": "C"}]  # sem has_base_material
        self.assertEqual(parse_blocos.vinculo_mb_dos_itens(data), {"i3": False})

    def test_ignora_sem_id(self):
        data = [{"has_base_material": True}, {"id": "", "has_base_material": True}]
        self.assertEqual(parse_blocos.vinculo_mb_dos_itens(data), {})

    def test_lista_vazia(self):
        self.assertEqual(parse_blocos.vinculo_mb_dos_itens([]), {})


if __name__ == "__main__":
    unittest.main()
