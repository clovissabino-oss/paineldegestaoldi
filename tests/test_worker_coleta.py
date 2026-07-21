import unittest
import worker_coleta

class TestPedidoParaColeta(unittest.TestCase):
    def test_tipo_termo(self):
        termo, ids = worker_coleta.pedido_para_coleta(
            {"tipo": "termo", "alvo": "PRF", "rotulo": None})
        self.assertEqual(termo, "PRF")
        self.assertIsNone(ids)

    def test_tipo_ids_usa_rotulo_como_termo(self):
        u = "42f74fb0-3e13-4812-a499-5e7652a06331"
        termo, ids = worker_coleta.pedido_para_coleta(
            {"tipo": "ids", "alvo": u, "rotulo": "Meu Concurso"})
        self.assertEqual(termo, "Meu Concurso")
        self.assertEqual(ids, [u])

    def test_ids_sem_rotulo_erro(self):
        # extrator_ldi.falha() levanta SystemExit (padrão do projeto)
        with self.assertRaises(SystemExit):
            worker_coleta.pedido_para_coleta(
                {"tipo": "ids", "alvo": "x", "rotulo": None})

if __name__ == "__main__":
    unittest.main()
