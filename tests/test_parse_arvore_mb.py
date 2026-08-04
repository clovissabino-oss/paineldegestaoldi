# -*- coding: utf-8 -*-
"""Árvore do Material Base -> curso sintético (formato do content_tree_cache)."""
import unittest

import parse_blocos

# Fragmento fiel ao payload real de GET /bo/ldi/base-material/{id}/chapters
# (o item-pai "14" tem 149 questões que são a SOMA dos filhos — ver plano).
DETALHE = {
    "id": "mb-1", "name": "Direito Constitucional ",
    "main_classification_id": "cls-1", "user_id": "prof-1",
    "hide_chapters": ["h1", "h2", "h3"],
}
CAPITULOS = [
    {"id": "cap-a", "parent_chapter_id": "", "path": "", "name": "Teoria Geral",
     "title": "", "is_draft": False,
     "type_count": {"block_type_count": {}, "simple_block_type_count": {}},
     "items": [
         {"id": "it-1", "parent_chapter_id": "cap-a", "path": "1",
          "name": "1.1 Constitucionalismo", "title": "Constitucionalismo",
          "is_draft": False,
          "type_count": {"block_type_count": {"question": 11, "tiptap": 10,
                                              "videoMyDocuments": 4, "pdfMyDocuments": 2},
                         "simple_block_type_count": {"question": 3}},
          "items": []},
         {"id": "it-2", "parent_chapter_id": "cap-a", "path": "14",
          "name": "9.14 Questões (Hora de Praticar)", "title": "Questões",
          "is_draft": False,
          "type_count": {"block_type_count": {"question": 149, "tiptap": 3},
                         "simple_block_type_count": {"question": 46}},
          "items": [
              {"id": "it-2a", "parent_chapter_id": "cap-a", "path": "14.1",
               "name": "9.14.1 Comentadas Cebraspe", "title": "Comentadas",
               "is_draft": False,
               "type_count": {"block_type_count": {"question": 69, "tiptap": 1},
                              "simple_block_type_count": {"question": 12}},
               "items": []},
              {"id": "it-2b", "parent_chapter_id": "cap-a", "path": "14.2",
               "name": "9.14.2 Comentadas FGV", "title": "Comentadas FGV",
               "is_draft": False,
               "type_count": {"block_type_count": {"question": 80, "tiptap": 2},
                              "simple_block_type_count": {"question": 34}},
               "items": []},
          ]},
     ]},
    {"id": "cap-b", "parent_chapter_id": "", "path": "", "name": "Direitos Fundamentais",
     "title": "", "is_draft": False,
     "type_count": {"block_type_count": {}, "simple_block_type_count": {}},
     "items": []},
]


class TestArvoreDoMB(unittest.TestCase):
    def setUp(self):
        self.curso = parse_blocos.arvore_do_mb(DETALHE, CAPITULOS, professor_nome="Profa Fulana")

    def test_curso_sintetico_usa_o_id_do_mb_e_a_disciplina_sem_sujeira(self):
        self.assertEqual(self.curso["id"], "mb-1")
        self.assertEqual(self.curso["name"], "Direito Constitucional")  # sem espaço à direita
        self.assertEqual(self.curso["authors_name"], "Profa Fulana")

    def test_capitulos_saem_na_ordem_do_array_com_order_index_crescente(self):
        caps = self.curso["content_tree_cache"]
        self.assertEqual([c["chapter_id"] for c in caps], ["cap-a", "cap-b"])
        self.assertEqual([c["order_index"] for c in caps], [0, 1])

    def test_sub_itens_viram_itens_do_mesmo_capitulo_preservando_o_path(self):
        itens = self.curso["content_tree_cache"][0]["items"]
        self.assertEqual([i["item_id"] for i in itens], ["it-1", "it-2", "it-2a", "it-2b"])
        self.assertEqual([i["path"] for i in itens], ["1", "14", "14.1", "14.2"])

    def test_item_pai_nao_soma_de_novo_as_questoes_dos_filhos(self):
        """O type_count do pai JÁ inclui os descendentes (medido na API: 149 = 69+80).
        Guardar o pai com 149 dobraria o capítulo."""
        por_id = {i["item_id"]: i for i in self.curso["content_tree_cache"][0]["items"]}
        self.assertEqual(por_id["it-2"]["block_type_count"].get("question", 0), 0)
        self.assertEqual(por_id["it-2"]["block_type_count"].get("tiptap", 0), 0)  # 3 - (1+2)
        self.assertEqual(por_id["it-2a"]["block_type_count"]["question"], 69)
        self.assertEqual(por_id["it-2b"]["block_type_count"]["question"], 80)

    def test_o_capitulo_soma_exatamente_o_que_a_api_disse_do_pai(self):
        itens = self.curso["content_tree_cache"][0]["items"]
        total = sum(i["block_type_count"].get("question", 0) for i in itens)
        self.assertEqual(total, 11 + 149)  # it-1 + o galho do it-2 inteiro, sem duplicar

    def test_item_sem_filhos_mantem_a_contagem_intacta(self):
        it1 = self.curso["content_tree_cache"][0]["items"][0]
        self.assertEqual(it1["block_type_count"],
                         {"question": 11, "tiptap": 10, "videoMyDocuments": 4,
                          "pdfMyDocuments": 2})
        self.assertEqual(it1["simple_block_type_count"], {"question": 3})

    def test_contagens_da_aula_le_o_formato_produzido(self):
        """O contrato com gravar_arvore: as contagens ficam no TOPO do item."""
        it1 = self.curso["content_tree_cache"][0]["items"][0]
        c = parse_blocos.contagens_da_aula(it1)
        self.assertEqual(c["qtd_questoes"], 11)
        self.assertEqual(c["qtd_videos"], 4)
        self.assertEqual(c["qtd_pdfs"], 2)

    def test_capitulo_sem_itens_nao_quebra(self):
        self.assertEqual(self.curso["content_tree_cache"][1]["items"], [])

    def test_updated_at_ausente_vira_string_vazia(self):
        it1 = self.curso["content_tree_cache"][0]["items"][0]
        self.assertEqual(it1["updated_at"], "")

    def test_subtracao_nunca_fica_negativa(self):
        detalhe = {"id": "mb-x", "name": "X", "user_id": "u"}
        caps = [{"id": "c", "name": "C", "items": [
            {"id": "p", "path": "1", "name": "P",
             "type_count": {"block_type_count": {"question": 2}},
             "items": [{"id": "f", "path": "1.1", "name": "F",
                        "type_count": {"block_type_count": {"question": 9}},
                        "items": []}]}]}]
        curso = parse_blocos.arvore_do_mb(detalhe, caps)
        pai = curso["content_tree_cache"][0]["items"][0]
        self.assertEqual(pai["block_type_count"].get("question", 0), 0)


if __name__ == "__main__":
    unittest.main()
