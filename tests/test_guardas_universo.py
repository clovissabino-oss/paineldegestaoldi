# -*- coding: utf-8 -*-
"""Uma extração de MB não pode ser confundida com curso pelos caminhos globais."""
import os
import tempfile
import unittest

import banco_conteudo
import sync_supabase


def _semear(caminho):
    """Um curso, e DEPOIS um MB (o MB é o id mais alto — é essa a armadilha)."""
    con = banco_conteudo.abrir(caminho)
    curso = banco_conteudo.iniciar_extracao(con, "BACEN", "concursos")
    banco_conteudo.gravar_arvore(con, curso, [{
        "id": "c-1", "name": "Direito Constitucional para BACEN", "published": True,
        "content_tree_cache": [{"chapter_id": "cap", "name": "Cap", "order_index": 0,
                                "items": [{"item_id": "it-1", "name": "Item", "path": "1",
                                           "block_type_count": {"question": 3}}]}]}])
    mb = banco_conteudo.iniciar_extracao(
        con, "MB · Profa Fulana · Direito Constitucional", "concursos", tipo="mb",
        professor_id="u-prof", professor_nome="Profa Fulana",
        disciplina="Direito Constitucional")
    banco_conteudo.gravar_arvore(con, mb, [{
        "id": "mb-1", "name": "Direito Constitucional", "published": False,
        "content_tree_cache": [{"chapter_id": "cap-mb", "name": "Cap MB", "order_index": 0,
                                "items": [{"item_id": "it-1", "name": "Item", "path": "1",
                                           "block_type_count": {"question": 3}}]}]}])
    return con, curso, mb


class TestGuardasDeUniverso(unittest.TestCase):
    def setUp(self):
        self.caminho = os.path.join(tempfile.mkdtemp(), "t.db")
        self.con, self.curso, self.mb = _semear(self.caminho)

    def tearDown(self):
        self.con.close()

    def test_o_mb_e_mesmo_a_extracao_mais_recente(self):
        """Guarda do próprio teste: se isto falhar, os outros não provam nada."""
        maior = self.con.execute("SELECT MAX(id) FROM extracoes").fetchone()[0]
        self.assertEqual(maior, self.mb)

    def test_sync_publica_o_curso_e_nunca_o_mb(self):
        escolhida = sync_supabase.extracao_publicavel(self.con)
        self.assertEqual(escolhida["id"], self.curso)
        self.assertEqual(escolhida["termo"], "BACEN")

    def test_regras_de_qualidade_escolhem_a_ultima_coleta_de_curso(self):
        import regras_qualidade
        self.assertEqual(regras_qualidade.ultima_extracao_de_curso(self.con), self.curso)

    def test_sem_coleta_de_curso_o_sync_nao_publica_nada(self):
        con2 = banco_conteudo.abrir(os.path.join(tempfile.mkdtemp(), "so_mb.db"))
        try:
            banco_conteudo.iniciar_extracao(con2, "MB · X · Y", "concursos", tipo="mb")
            self.assertIsNone(sync_supabase.extracao_publicavel(con2))
        finally:
            con2.close()


if __name__ == "__main__":
    unittest.main()
