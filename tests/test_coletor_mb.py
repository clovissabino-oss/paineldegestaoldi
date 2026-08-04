# -*- coding: utf-8 -*-
"""Camada de API do Material Base (sem rede: sessão dublê)."""
import unittest

import coletor_ldi


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

    def test_401_vira_cookie_vencido(self):
        s = _Sessao({"/base-material/": _Resposta({}, 401)})
        with self.assertRaises(coletor_ldi.CookieVencido):
            coletor_ldi.obter_mb(s, "mb-1")


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


import sys
from unittest import mock

import extrator_ldi


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
