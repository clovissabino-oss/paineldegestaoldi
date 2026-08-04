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


class TestSeletorDeMBs(unittest.TestCase):
    """Cada MB é uma extração PRÓPRIA — pegar só a de maior id deixaria apenas o
    último MB coletado alcançável na tela (e o aceite 'coletar o mesmo MB duas
    vezes e comparar' impossível de conferir)."""

    def setUp(self):
        self.caminho = os.path.join(tempfile.mkdtemp(), "t.db")
        self.con, self.curso, self.mb = _semear(self.caminho)

    def tearDown(self):
        self.con.close()

    def _mb(self, mb_id, disciplina):
        ext = banco_conteudo.iniciar_extracao(
            self.con, f"MB · P · {disciplina}", "concursos", tipo="mb")
        banco_conteudo.gravar_arvore(self.con, ext, [{
            "id": mb_id, "name": disciplina, "authors_name": "P",
            "content_tree_cache": [{"chapter_id": "c", "name": "C", "order_index": 0,
                                    "items": [{"item_id": f"{mb_id}-i", "name": "A",
                                               "path": "1", "block_type_count": {}}]}]}])
        return ext

    def test_lista_todos_os_mbs_do_banco_e_nao_so_o_ultimo(self):
        self._mb("mb-2", "Matemática")
        rows = painel.cursos_do_universo(self.con, "mb")
        self.assertEqual([r["curso_id"] for r in rows], ["mb-1", "mb-2"])
        self.assertEqual([r["nome"] for r in rows],
                         ["Direito Constitucional", "Matemática"])
        self.assertEqual(rows[0]["autores"], "Profa Fulana")

    def test_mb_recoletado_aparece_uma_vez_so_pela_coleta_mais_recente(self):
        nova = self._mb("mb-1", "Direito Constitucional (v2)")
        rows = painel.cursos_do_universo(self.con, "mb")
        self.assertEqual([r["curso_id"] for r in rows], ["mb-1"])
        self.assertEqual(rows[0]["nome"], "Direito Constitucional (v2)")
        self.assertEqual(self.con.execute(
            "SELECT MAX(extracao_id) FROM cursos WHERE curso_id='mb-1'"
        ).fetchone()[0], nova)

    def test_universo_curso_continua_na_coleta_mais_recente_de_curso(self):
        """Não regride: o seletor de curso ignora os MBs (mesmo com id maior) e
        continua trazendo só os cursos da última coleta de curso."""
        self._mb("mb-2", "Matemática")
        outra = banco_conteudo.iniciar_extracao(self.con, "PRF", "concursos")
        banco_conteudo.gravar_arvore(self.con, outra, [{
            "id": "c-9", "name": "Constitucional para PRF",
            "content_tree_cache": [{"chapter_id": "cap", "name": "Cap", "order_index": 0,
                                    "items": [{"item_id": "it-9", "name": "A",
                                               "path": "1", "block_type_count": {}}]}]}])
        rows = painel.cursos_do_universo(self.con, "curso")
        self.assertEqual([r["curso_id"] for r in rows], ["c-9"])


class TestCoberturaMB(unittest.TestCase):
    """Quanto do acervo do professor chega de fato a um curso."""

    def setUp(self):
        self.caminho = os.path.join(tempfile.mkdtemp(), "t.db")
        self.con, self.curso, self.mb = _semear(self.caminho)

    def tearDown(self):
        self.con.close()

    def test_conta_so_os_itens_que_estao_em_curso(self):
        """O MB tem it-1, it-9 e it-10; o curso tem it-1 e it-2. Só it-1 é cobertura.
        Sem o filtro de tipo, o próprio MB entraria como 'curso' e daria 3 de 3."""
        c = painel.cobertura_mb(self.con, self.mb)
        self.assertEqual(c["itens_mb"], 3)
        self.assertEqual(c["itens_em_curso"], 1)
        self.assertEqual(c["cursos_comparados"], 1)

    def test_sem_curso_no_banco_a_cobertura_e_zero_e_diz_contra_quantos_comparou(self):
        con2 = banco_conteudo.abrir(os.path.join(tempfile.mkdtemp(), "so_mb.db"))
        try:
            mb = banco_conteudo.iniciar_extracao(con2, "MB · X · Y", "concursos", tipo="mb")
            banco_conteudo.gravar_arvore(con2, mb, [{
                "id": "mb-9", "name": "Y",
                "content_tree_cache": [{"chapter_id": "c", "name": "C", "order_index": 0,
                                        "items": [{"item_id": "z", "name": "Z", "path": "1",
                                                   "block_type_count": {}}]}]}])
            c = painel.cobertura_mb(con2, mb)
            self.assertEqual((c["itens_em_curso"], c["cursos_comparados"]), (0, 0))
        finally:
            con2.close()

    def test_curso_recoletado_conta_uma_vez_so(self):
        """Duas coletas do mesmo curso não podem inflar 'cursos_comparados'."""
        outra = banco_conteudo.iniciar_extracao(self.con, "BACEN", "concursos")
        banco_conteudo.gravar_arvore(self.con, outra, [{
            "id": "c-1", "name": "Constitucional para BACEN", "published": True,
            "content_tree_cache": [{"chapter_id": "cap", "name": "Cap", "order_index": 0,
                                    "items": [{"item_id": "it-1", "name": "A", "path": "1",
                                               "block_type_count": {}}]}]}])
        c = painel.cobertura_mb(self.con, self.mb)
        self.assertEqual(c["cursos_comparados"], 1)
        self.assertEqual(c["itens_em_curso"], 1)

    def test_o_dict_do_painel_traz_cobertura_so_no_universo_mb(self):
        self.assertIn("cobertura", painel.dados_do_snapshot(self.con, tipo="mb"))
        self.assertNotIn("cobertura", painel.dados_do_snapshot(self.con))


if __name__ == "__main__":
    unittest.main()
