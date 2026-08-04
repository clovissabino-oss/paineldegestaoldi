# -*- coding: utf-8 -*-
"""Camada de API do Material Base (sem rede: sessão dublê)."""
import contextlib
import io
import unittest
from unittest import mock

import coletor_ldi
import extrator_ldi


class _Resposta:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.ok = 200 <= status < 300
        self.text = str(payload)

    def json(self):
        return self._payload


class _Sessao:
    """Dublê: responde por trecho da URL e guarda as chamadas feitas."""

    def __init__(self, rotas):
        self.rotas = rotas
        self.chamadas = []

    def get(self, url, **kw):
        self.chamadas.append(url)
        for trecho, resp in self.rotas.items():
            if trecho in url:
                return resp(url) if callable(resp) else resp
        return _Resposta({"error": {"message": "nao mapeado"}}, 404)


class TestExtrairIdMB(unittest.TestCase):
    def test_aceita_url_do_admin_e_ignora_team_id(self):
        url = ("https://admin.estrategia.com/#/concursos/livros-digitais-interativos/"
               "base-material/edit?id=3e8e7c78-cdc4-4dc2-90ad-0dae39b827f5&team_id")
        self.assertEqual(coletor_ldi.extrair_id_mb(url),
                         "3e8e7c78-cdc4-4dc2-90ad-0dae39b827f5")

    def test_aceita_uuid_solto(self):
        self.assertEqual(coletor_ldi.extrair_id_mb("3E8E7C78-CDC4-4DC2-90AD-0DAE39B827F5"),
                         "3e8e7c78-cdc4-4dc2-90ad-0dae39b827f5")

    def test_texto_sem_id_levanta(self):
        with self.assertRaises(SystemExit):
            coletor_ldi.extrair_id_mb("Direito Constitucional")


class TestObterMB(unittest.TestCase):
    def test_detalhe_e_capitulos(self):
        s = _Sessao({
            "/chapters": _Resposta({"data": [{"id": "cap-a", "items": []}],
                                    "meta": {"total": 1}}),
            "/base-material/mb-1": _Resposta({"data": {"id": "mb-1", "name": "Penal"}}),
        })
        self.assertEqual(coletor_ldi.obter_mb(s, "mb-1")["name"], "Penal")
        caps = coletor_ldi.capitulos_do_mb(s, "mb-1")
        self.assertEqual(len(caps), 1)
        self.assertIn("per_page=100", s.chamadas[-1])

    def test_401_vira_cookie_vencido_com_o_motivo_impresso(self):
        """Levantar mudo deixava o usuário só com "Pressione ENTER para fechar".
        Delegar ao extrator_ldi.get_json é o que imprime o motivo."""
        s = _Sessao({"/base-material/": _Resposta({}, 401)})
        saida = io.StringIO()
        with contextlib.redirect_stdout(saida):
            with self.assertRaises(coletor_ldi.CookieVencido):
                coletor_ldi.obter_mb(s, "mb-1")
        self.assertIn("cookie", saida.getvalue().lower())

    def test_5xx_tenta_de_novo_como_o_resto_do_projeto(self):
        """Antes, um 500 pontual derrubava a coleta do MB na primeira tentativa,
        enquanto todo o resto do projeto tenta 4× com backoff."""
        tentativas = []

        def responder(url):
            tentativas.append(url)
            return _Resposta({"data": {"id": "mb-1", "name": "Penal"}}) \
                if len(tentativas) > 2 else _Resposta({}, 503)

        s = _Sessao({"/base-material/mb-1": responder})
        with mock.patch.object(extrator_ldi.time, "sleep"):
            self.assertEqual(coletor_ldi.obter_mb(s, "mb-1")["name"], "Penal")
        self.assertEqual(len(tentativas), 3)


class TestBuscaDeProfessor(unittest.TestCase):
    def _sessao(self):
        # A rota /base-material? atende o índice (1 página incompleta) — é dele que
        # sai quem é professor. `u-aluno` não tem MB e por isso some do resultado.
        return _Sessao({
            "/users?": _Resposta({"data": [
                {"id": "u-prof", "full_name": "Profa Nilza Ciciliati",
                 "email": "nilza@x.com"},
                {"id": "u-aluno", "full_name": "Joao Ciciliati", "email": "joao@x.com"},
            ]}),
            "/base-material?": _Resposta({"data": [
                {"id": "mb-1", "name": "Serviço Social ", "user_id": "u-prof"},
            ]}),
        })

    def test_so_devolve_quem_tem_material_base(self):
        """O diretório do LDI é de TODOS os usuários; sem este filtro a busca
        devolveria alunos homônimos."""
        achados = coletor_ldi.buscar_professores_com_mb(self._sessao(), "Ciciliati")
        self.assertEqual([a["nome"] for a in achados], ["Profa Nilza Ciciliati"])
        self.assertEqual(achados[0]["mbs"], [{"id": "mb-1", "disciplina": "Serviço Social"}])

    def test_termo_curto_e_recusado_antes_da_rede(self):
        s = _Sessao({})
        with self.assertRaises(SystemExit):
            coletor_ldi.buscar_professores_com_mb(s, "ab")
        self.assertEqual(s.chamadas, [])  # nada foi à rede

    def test_termo_com_espaco_e_acento_vai_escapado_na_url(self):
        """O spec prevê o usuário digitando duas palavras; sem escapar, o espaço
        quebra a query (mesmo tratamento do search_term em extrator_ldi)."""
        s = self._sessao()
        coletor_ldi.buscar_professores_com_mb(s, "Nilza Ciciliati")
        url = next(u for u in s.chamadas if "/users?" in u)
        self.assertIn("term=Nilza%20Ciciliati", url)
        self.assertNotIn(" ", url)


class TestIndiceDeMBs(unittest.TestCase):
    def test_pagina_ate_a_pagina_incompleta(self):
        paginas = {1: [{"id": f"m{i}", "user_id": "u", "name": "D"} for i in range(100)],
                   2: [{"id": "m100", "user_id": "u", "name": "D"}]}

        def responder(url):
            pag = int(url.split("page=")[1].split("&")[0])
            return _Resposta({"data": paginas.get(pag, [])})

        s = _Sessao({"/base-material?": responder})
        self.assertEqual(len(coletor_ldi.indice_de_mbs(s)), 101)
        self.assertEqual(len(s.chamadas), 2)  # parou na página incompleta

    def test_trava_de_paginas_avisa_em_vez_de_truncar_em_silencio(self):
        """Truncar mudo faria a busca "não achar" um professor que existe."""
        cheia = _Resposta({"data": [{"id": f"m{i}", "user_id": "u", "name": "D"}
                                    for i in range(100)]})
        s = _Sessao({"/base-material?": cheia})
        saida = io.StringIO()
        with contextlib.redirect_stdout(saida):
            todos = coletor_ldi.indice_de_mbs(s)
        self.assertEqual(len(todos), 100 * coletor_ldi._MAX_PAGINAS_MB)
        self.assertIn("aviso", saida.getvalue())
        self.assertIn("ainda havia mais", saida.getvalue())


import os
import tempfile

import banco_conteudo


class TestColetarMB(unittest.TestCase):
    """Coleta ponta a ponta com sessão dublê — prova o que grava no banco."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.caminho = os.path.join(self.dir, "t.db")
        self.cfg = {"vertical": "concursos", "concorrencia": 2}

    def _sessao(self):
        detalhe = {"id": "mb-1", "name": "Direito Constitucional ", "user_id": "u-prof",
                   "main_classification_id": "cls-1", "hide_chapters": ["h1", "h2"]}
        caps = [{"id": "cap-a", "name": "Teoria", "items": [
            {"id": "it-1", "path": "1", "name": "Item 1",
             "type_count": {"block_type_count": {"question": 2}}, "items": []},
        ]}]
        blocos = {"data": [
            {"id": "b1", "type": "question", "order": 1, "is_active": True},
            {"id": "b2", "type": "question", "order": 2, "is_active": True},
        ]}
        return _Sessao({
            "/chapters": _Resposta({"data": caps}),
            "/base-material/mb-1": _Resposta({"data": detalhe}),
            "/blocks?item_id=": _Resposta(blocos),
        })

    def test_grava_extracao_de_mb_com_metadados_e_blocos(self):
        eid = coletor_ldi.coletar_mb(self.cfg, self._sessao(), "mb-1", self.caminho,
                                     professor_nome="Profa Fulana")
        con = banco_conteudo.abrir(self.caminho)
        try:
            ext = con.execute("SELECT * FROM extracoes WHERE id=?", (eid,)).fetchone()
            self.assertEqual(ext["tipo"], "mb")
            self.assertEqual(ext["disciplina"], "Direito Constitucional")
            self.assertEqual(ext["professor_nome"], "Profa Fulana")
            self.assertEqual(ext["professor_id"], "u-prof")
            self.assertEqual(ext["capitulos_ocultos"], 2)
            self.assertEqual(ext["termo"], "MB · Profa Fulana · Direito Constitucional")
            self.assertEqual(con.execute(
                "SELECT COUNT(*) FROM blocos WHERE extracao_id=?", (eid,)).fetchone()[0], 2)
            self.assertEqual(con.execute(
                "SELECT curso_id, nome FROM cursos WHERE extracao_id=?",
                (eid,)).fetchone()[:2], ("mb-1", "Direito Constitucional"))
        finally:
            con.close()

    def test_todo_item_de_mb_nasce_vinculado_ao_mb(self):
        eid = coletor_ldi.coletar_mb(self.cfg, self._sessao(), "mb-1", self.caminho)
        con = banco_conteudo.abrir(self.caminho)
        try:
            self.assertEqual(con.execute(
                "SELECT vinculado_mb FROM aulas WHERE extracao_id=?", (eid,)).fetchone()[0], 1)
        finally:
            con.close()

    def test_nao_roda_regras_de_qualidade(self):
        """O motor dá baixa automática no snapshot seguinte; rodá-lo sobre um MB
        resolveria em massa pendências de curso que continuam abertas."""
        coletor_ldi.coletar_mb(self.cfg, self._sessao(), "mb-1", self.caminho)
        con = banco_conteudo.abrir(self.caminho)
        try:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM pendencias").fetchone()[0], 0)
        finally:
            con.close()

    def test_sem_professor_conhecido_usa_o_uuid_no_termo(self):
        eid = coletor_ldi.coletar_mb(self.cfg, self._sessao(), "mb-1", self.caminho)
        con = banco_conteudo.abrir(self.caminho)
        try:
            termo = con.execute("SELECT termo FROM extracoes WHERE id=?", (eid,)).fetchone()[0]
            self.assertIn("u-prof", termo)  # UUID visível, não "—"
        finally:
            con.close()

    def test_sem_professor_conhecido_o_uuid_tambem_chega_a_tela(self):
        """Risco nº 2 do spec: a tela mostra o UUID, não "—" nem "professor sem
        nome no diretório" (que parece defeito). O termo já trazia o UUID, mas
        professor_nome e autores ficavam vazios — que é o que a tela lê."""
        eid = coletor_ldi.coletar_mb(self.cfg, self._sessao(), "mb-1", self.caminho)
        con = banco_conteudo.abrir(self.caminho)
        try:
            self.assertEqual(con.execute(
                "SELECT professor_nome FROM extracoes WHERE id=?", (eid,)).fetchone()[0],
                "u-prof")
            self.assertEqual(con.execute(
                "SELECT autores FROM cursos WHERE extracao_id=?", (eid,)).fetchone()[0],
                "u-prof")
        finally:
            con.close()

    def test_conta_os_capitulos_que_entraram_na_arvore_e_nao_os_crus(self):
        """arvore_do_mb descarta capítulo sem `id`; a mensagem tem de anunciar o
        número que FOI coletado — é o gabarito do aceite e da comparação dupla."""
        detalhe = {"id": "mb-1", "name": "D", "user_id": "u-prof"}
        caps = [{"id": "cap-a", "name": "Vale", "items": []},
                {"name": "Sem id — descartado", "items": []}]
        s = _Sessao({"/chapters": _Resposta({"data": caps}),
                     "/base-material/mb-1": _Resposta({"data": detalhe}),
                     "/blocks?item_id=": _Resposta({"data": []})})
        saida = io.StringIO()
        with contextlib.redirect_stdout(saida):
            coletor_ldi.coletar_mb(self.cfg, s, "mb-1", self.caminho)
        self.assertIn("1 capítulos", saida.getvalue())
        self.assertNotIn("2 capítulos", saida.getvalue())


import sys


class TestCLIProfessor(unittest.TestCase):
    """--professor: o nome do professor NÃO pode vir de resolução automática pela
    disciplina (defeito da revisão da Task 4) — quem o informa é quem chama o CLI.
    Cobre só o parse/roteamento de main(); nenhum destes testes toca rede."""

    def _cfg(self):
        return {"termo_busca": "PRF", "filtro_local": "", "vertical": "concursos",
                "pasta_saida": "saida", "concorrencia": 2}

    def test_mb_com_professor_repassa_o_nome_para_coletar_mb(self):
        argv = ["coletor_ldi.py", "--mb",
                "3e8e7c78-cdc4-4dc2-90ad-0dae39b827f5", "--professor", "Profa Fulana"]
        with mock.patch.object(sys, "argv", argv), \
             mock.patch.object(extrator_ldi, "carregar_config", return_value=self._cfg()), \
             mock.patch.object(extrator_ldi, "carregar_cookie", return_value="c"), \
             mock.patch.object(extrator_ldi, "montar_sessao", return_value=object()), \
             mock.patch.object(coletor_ldi, "coletar_mb") as m:
            coletor_ldi.main()
        self.assertEqual(m.call_args.kwargs.get("professor_nome"), "Profa Fulana")

    def test_professor_sem_mb_levanta_antes_de_montar_sessao(self):
        argv = ["coletor_ldi.py", "--professor", "Profa Fulana"]
        with mock.patch.object(sys, "argv", argv), \
             mock.patch.object(extrator_ldi, "carregar_config", return_value=self._cfg()), \
             mock.patch.object(extrator_ldi, "montar_sessao") as sessao_mock:
            with self.assertRaises(SystemExit):
                coletor_ldi.main()
            sessao_mock.assert_not_called()  # falhou antes de qualquer chamada de rede


if __name__ == "__main__":
    unittest.main()
