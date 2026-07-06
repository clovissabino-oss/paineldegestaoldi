# -*- coding: utf-8 -*-
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import parse_blocos

BLOCO_QUESTION = {
    "id": "83dcc1f5-9541-4a41-85a5-5658e06b2c99", "type": "question",
    "order_index": 8, "is_active": True, "is_draft": False,
    "data": {
        "value": "58532862",
        "resolved": {
            "id": "58532862", "slug": "Com-escrituraca1991e48272",
            "answer_type": "TRUE_OR_FALSE",
            "alternatives": [{"id": "a"}, {"id": "b"}],
            "topics": [{"name": "Escrituração"}],
            "exams": [{"name": "CESPE 2020"}],
            "solution": {"brief": "Certo, pois...", "complete": "<p>...</p>"},
            "has_video_solution": False, "solution_video_url": "",
        },
    },
}

BLOCO_VIDEO = {
    "id": "b1", "type": "videoMyDocuments", "order_index": 2,
    "is_active": True, "is_draft": False,
    "data": {"title": "Aula 01", "resolved": {
        "id": "v-uuid", "name": "Contabilidade - 248487",
        "original_name": "videosintra248.487.mp4",
        "intra_video_id": "", "video_duration": "01:06:53.80",
        "file_size": 123456, "created_at": "2024-10-11T18:36:34Z",
    }},
}

BLOCO_TIPTAP = {
    "id": "37b868af", "type": "tiptap", "order_index": 7,
    "is_active": True, "is_draft": False, "content_length": 1830,
    "data": {"type": "doc", "block_content_length": 0, "content": []},
}

BLOCO_PDF = {
    "id": "p1", "type": "pdfMyDocuments", "order_index": 3,
    "is_active": True, "is_draft": True,
    "data": {"title": "Baixar Slide - Parte 01",
             "value": "a87dff46-1e7d-4193-b19f-1257f52a539a",
             "resolved": {"id": "a87dff46", "created_at": "2024-10-11T18:36:34Z"}},
}


class TestContagens(unittest.TestCase):
    def test_soma_por_familia_e_outros(self):
        item = {"block_type_count": {"videoMyDocuments": 2, "youtube": 1,
                                     "cast": 3, "question": 10, "tiptap": 5,
                                     "pdfMyDocuments": 1, "notebook": 1}}
        c = parse_blocos.contagens_da_aula(item)
        self.assertEqual(c, {"qtd_videos": 3, "qtd_questoes": 10, "qtd_textos": 5,
                             "qtd_pdfs": 1, "qtd_casts": 3, "qtd_outros": 1})

    def test_mescla_simple_e_normal_e_vazio(self):
        item = {"simple_block_type_count": {"question": 4},
                "block_type_count": {"question": 7}}
        self.assertEqual(parse_blocos.contagens_da_aula(item)["qtd_questoes"], 7)
        self.assertEqual(parse_blocos.contagens_da_aula({})["qtd_videos"], 0)


class TestMetaDoBloco(unittest.TestCase):
    def test_question(self):
        m = parse_blocos.meta_do_bloco(BLOCO_QUESTION)
        self.assertEqual(m["tipo"], "question")
        self.assertEqual(m["questao_id"], "58532862")
        self.assertEqual(m["resposta_tipo"], "TRUE_OR_FALSE")
        self.assertEqual(m["tem_solucao"], 1)
        self.assertEqual(m["tem_video_solucao"], 0)
        self.assertEqual(m["meta"]["topicos"], ["Escrituração"])
        self.assertEqual(m["meta"]["provas"], ["CESPE 2020"])
        self.assertEqual(m["meta"]["qtd_alternativas"], 2)

    def test_video_id_antigo_com_ponto_de_milhar(self):
        m = parse_blocos.meta_do_bloco(BLOCO_VIDEO)
        self.assertEqual(m["video_id_antigo"], "248487")   # armadilha resolvida
        self.assertEqual(m["duracao_seg"], 4014)
        self.assertEqual(m["titulo"], "Aula 01")

    def test_tiptap_tamanho(self):
        m = parse_blocos.meta_do_bloco(BLOCO_TIPTAP)
        self.assertEqual(m["tamanho_texto"], 1830)

    def test_pdf_e_rascunho(self):
        m = parse_blocos.meta_do_bloco(BLOCO_PDF)
        self.assertEqual(m["rascunho"], 1)
        self.assertEqual(m["titulo"], "Baixar Slide - Parte 01")
        self.assertEqual(m["meta"]["media_id"], "a87dff46")

    def test_tipo_desconhecido_nao_estoura(self):
        m = parse_blocos.meta_do_bloco({"id": "x", "type": "notebook"})
        self.assertEqual(m["tipo"], "notebook")
        self.assertEqual(m["meta"], {})


class TestAutores(unittest.TestCase):
    def test_prefere_authors_name_e_filtra_uuid(self):
        self.assertEqual(parse_blocos.autores_do_curso(
            {"authors_name": "Fulano | Beltrano"}), "Fulano | Beltrano")
        self.assertEqual(parse_blocos.autores_do_curso(
            {"authors": [{"name": "Fulano"},
                         {"name": "83dcc1f5-9541-4a41-85a5-5658e06b2c99"}]}), "Fulano")


if __name__ == "__main__":
    unittest.main()
