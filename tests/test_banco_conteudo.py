# -*- coding: utf-8 -*-
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import banco_conteudo

CURSOS = [{
    "id": "c1", "name": "Curso A", "published": True,
    "created_at": "2024-01-01", "authors_name": "Prof X",
    "content_tree_cache": [{
        "chapter_id": "cap1", "name": "Cap 1", "order_index": 0,
        "items": [
            {"item_id": "i1", "name": "Aula 1", "path": "1",
             "block_type_count": {"question": 2, "tiptap": 1}},
            {"item_id": "i2", "name": "Aula 2", "path": "2",
             "block_type_count": {"videoMyDocuments": 1}},
        ],
    }],
}, {
    "id": "c2", "name": "Curso B", "published": False,
    "content_tree_cache": [{
        "chapter_id": "cap2", "name": "Cap 1", "order_index": 0,
        "items": [{"item_id": "i1", "name": "Aula 1", "path": "1",
                   "block_type_count": {"question": 2, "tiptap": 1}}],
    }],
}]

B1 = {"bloco_id": "b1", "tipo": "question", "ordem": 1, "ativo": 1, "rascunho": 0,
      "titulo": "", "questao_id": "111", "resposta_tipo": "TRUE_OR_FALSE",
      "tem_solucao": 1, "tem_video_solucao": 0, "video_id_antigo": "",
      "duracao_seg": None, "tamanho_texto": None, "meta": {"topicos": ["T"]}}


class TestBanco(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.con = banco_conteudo.abrir(os.path.join(self.dir.name, "x", "conteudo.db"))

    def tearDown(self):
        self.con.close()
        self.dir.cleanup()

    def _nova(self):
        eid = banco_conteudo.iniciar_extracao(self.con, "BACEN", "concursos")
        banco_conteudo.gravar_arvore(self.con, eid, CURSOS)
        return eid

    def test_arvore_grava_cursos_aulas_e_contagens(self):
        eid = self._nova()
        n = self.con.execute("SELECT COUNT(*) FROM cursos WHERE extracao_id=?", (eid,)).fetchone()[0]
        self.assertEqual(n, 2)
        # aula i1 vinculada a 2 cursos = 2 linhas em aulas, mas 1 pendente
        n = self.con.execute("SELECT COUNT(*) FROM aulas WHERE extracao_id=? AND item_id='i1'", (eid,)).fetchone()[0]
        self.assertEqual(n, 2)
        row = self.con.execute("SELECT qtd_questoes, qtd_textos FROM aulas "
                               "WHERE extracao_id=? AND item_id='i1' AND curso_id='c1'", (eid,)).fetchone()
        self.assertEqual((row[0], row[1]), (2, 1))
        self.assertEqual(sorted(banco_conteudo.aulas_pendentes(self.con, eid)), ["i1", "i2"])

    def test_gravar_blocos_tira_da_pendencia_mesmo_vazia(self):
        eid = self._nova()
        banco_conteudo.gravar_blocos_da_aula(self.con, eid, "i1", [B1])
        banco_conteudo.gravar_blocos_da_aula(self.con, eid, "i2", [])   # aula sem blocos
        self.assertEqual(banco_conteudo.aulas_pendentes(self.con, eid), [])
        row = self.con.execute("SELECT questao_id, meta FROM blocos WHERE extracao_id=? AND item_id='i1'", (eid,)).fetchone()
        self.assertEqual(row["questao_id"], "111")
        self.assertIn("topicos", row["meta"])

    def test_finalizar_completa_e_parcial(self):
        eid = self._nova()
        banco_conteudo.gravar_blocos_da_aula(self.con, eid, "i1", [B1])
        self.assertEqual(banco_conteudo.finalizar_extracao(self.con, eid, {"i2": "rede"}), "parcial")
        eid2 = banco_conteudo.iniciar_extracao(self.con, "BACEN", "concursos")
        banco_conteudo.gravar_arvore(self.con, eid2, CURSOS)
        banco_conteudo.gravar_blocos_da_aula(self.con, eid2, "i1", [B1])
        banco_conteudo.gravar_blocos_da_aula(self.con, eid2, "i2", [])
        self.assertEqual(banco_conteudo.finalizar_extracao(self.con, eid2, {}), "completa")
        row = self.con.execute("SELECT total_cursos, total_aulas, total_blocos, status FROM extracoes WHERE id=?", (eid2,)).fetchone()
        self.assertEqual((row[0], row[1], row[2], row[3]), (2, 2, 1, "completa"))

    def test_extracao_em_andamento_acha_a_mais_recente_do_termo(self):
        self.assertIsNone(banco_conteudo.extracao_em_andamento(self.con, "BACEN"))
        self._nova()
        eid2 = self._nova()
        achada = banco_conteudo.extracao_em_andamento(self.con, "BACEN")
        self.assertEqual(achada["id"], eid2)
        self.assertIsNone(banco_conteudo.extracao_em_andamento(self.con, "PF"))


if __name__ == "__main__":
    unittest.main()
