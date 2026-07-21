import unittest
from unittest.mock import MagicMock, patch
import coletor_ldi

class TestProgressoCancel(unittest.TestCase):
    def _con(self):
        return MagicMock()

    @patch("coletor_ldi.banco_conteudo.gravar_blocos_da_aula")
    @patch("coletor_ldi.baixar_blocos", return_value=[])
    def test_callback_recebe_progresso(self, _bb, _gb):
        chamadas = []
        coletor_ldi._baixar_lote(MagicMock(), self._con(), 1, ["i1", "i2"], 2,
                                 progresso=lambda f, t: chamadas.append((f, t)))
        self.assertEqual(chamadas[-1], (2, 2))  # dispara ao terminar

    @patch("coletor_ldi.banco_conteudo.gravar_blocos_da_aula")
    @patch("coletor_ldi.baixar_blocos", return_value=[])
    def test_cancelamento_aborta(self, _bb, _gb):
        def cancela(f, t):
            raise coletor_ldi.ColetaCancelada()
        with self.assertRaises(coletor_ldi.ColetaCancelada):
            coletor_ldi._baixar_lote(MagicMock(), self._con(), 1, ["i1"], 1,
                                     progresso=cancela)

if __name__ == "__main__":
    unittest.main()
