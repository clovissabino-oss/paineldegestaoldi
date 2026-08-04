# -*- coding: utf-8 -*-
"""O painel nunca mistura curso com Material Base."""
import os
import tempfile
import unittest

import banco_conteudo
import painel


def _semear(caminho):
    con = banco_conteudo.abrir(caminho)
    curso = banco_conteudo.iniciar_extracao(con, "BACEN", "concursos")
    banco_conteudo.gravar_arvore(con, curso, [{
        "id": "c-1", "name": "Constitucional para BACEN", "published": True,
        "content_tree_cache": [{"chapter_id": "cap", "name": "Cap", "order_index": 0,
                                "items": [{"item_id": "it-1", "name": "A", "path": "1",
                                           "block_type_count": {"question": 3}},
                                          {"item_id": "it-2", "name": "B", "path": "2",
                                           "block_type_count": {"question": 1}}]}]}])
    mb = banco_conteudo.iniciar_extracao(
        con, "MB · Profa Fulana · Direito Constitucional", "concursos", tipo="mb",
        professor_id="u-prof", professor_nome="Profa Fulana",
        disciplina="Direito Constitucional", capitulos_ocultos=111)
    banco_conteudo.gravar_arvore(con, mb, [{
        "id": "mb-1", "name": "Direito Constitucional", "published": False,
        "authors_name": "Profa Fulana",
        "content_tree_cache": [{"chapter_id": "cap-mb", "name": "Cap MB", "order_index": 0,
                                "items": [{"item_id": "it-1", "name": "A", "path": "1",
                                           "block_type_count": {"question": 3}},
                                          {"item_id": "it-9", "name": "Z", "path": "9",
                                           "block_type_count": {"question": 7}},
                                          {"item_id": "it-10", "name": "W", "path": "10",
                                           "block_type_count": {"question": 2}}]}]}])
    return con, curso, mb


class TestUniversos(unittest.TestCase):
    def setUp(self):
        self.caminho = os.path.join(tempfile.mkdtemp(), "t.db")
        self.con, self.curso, self.mb = _semear(self.caminho)

    def tearDown(self):
        self.con.close()

    def test_default_continua_sendo_curso_mesmo_com_mb_mais_recente(self):
        """Sem o filtro de tipo, o painel abriria mostrando o MB como se fosse curso."""
        d = painel.dados_do_snapshot(self.con)
        self.assertEqual(d["extracao"]["id"], self.curso)
        self.assertEqual(d["extracao"]["termo"], "BACEN")
        self.assertEqual([c["nome"] for c in d["cursos"]], ["Constitucional para BACEN"])

    def test_universo_mb_traz_o_material_base(self):
        d = painel.dados_do_snapshot(self.con, tipo="mb")
        self.assertEqual(d["extracao"]["id"], self.mb)
        self.assertEqual(d["extracao"]["tipo"], "mb")
        self.assertEqual(d["extracao"]["professor_nome"], "Profa Fulana")
        self.assertEqual(d["extracao"]["disciplina"], "Direito Constitucional")
        self.assertEqual(d["extracao"]["capitulos_ocultos"], 111)

    def test_kpis_de_curso_ignoram_os_itens_do_mb(self):
        """O MB tem 3 itens únicos (it-1, it-9, it-10) e o curso só 2 (it-1, it-2) —
        números diferentes de propósito, para que o teste acuse o bug de verdade: com a
        consulta antiga (sem filtro de tipo), o painel agregaria sobre o MB e devolveria 3,
        não 2."""
        d = painel.dados_do_snapshot(self.con)
        self.assertEqual(d["kpis"]["aulas_unicas"], 2)

    def test_sem_coleta_do_universo_devolve_none(self):
        con2 = banco_conteudo.abrir(os.path.join(tempfile.mkdtemp(), "so_curso.db"))
        try:
            banco_conteudo.iniciar_extracao(con2, "PRF", "concursos")
            self.assertIsNone(painel.dados_do_snapshot(con2, tipo="mb"))
        finally:
            con2.close()

    def test_dados_avaliacao_resolve_o_universo_pelo_curso_id(self):
        """dados_avaliacao NÃO filtra por tipo (painel.py:235) — e está certo assim: o
        curso_id de um MB é o próprio mb_id, num namespace que não colide com o de um
        curso, então a consulta por curso_id já resolve o universo certo por construção."""
        av_curso = painel.dados_avaliacao(self.con, "c-1")
        av_mb = painel.dados_avaliacao(self.con, "mb-1")
        self.assertEqual([c["nome"] for c in av_curso["capitulos"]], ["Cap"])
        self.assertEqual([c["nome"] for c in av_mb["capitulos"]], ["Cap MB"])

    def test_api_cursos_respeita_o_universo(self):
        painel.app.config["TESTING"] = True
        painel.caminho_banco = lambda: self.caminho
        cli = painel.app.test_client()
        curso = cli.get("/api/cursos").get_json()["data"]
        mb = cli.get("/api/cursos?universo=mb").get_json()["data"]
        self.assertEqual([c["curso_id"] for c in curso], ["c-1"])
        self.assertEqual([c["curso_id"] for c in mb], ["mb-1"])


if __name__ == "__main__":
    unittest.main()
