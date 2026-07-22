import unittest

import coletor_ldi
import extrator_ldi


class _Resposta401:
    status_code = 401
    ok = False
    text = '{"error": {"tag": "AUTH.USER_SESSION_NOT_FOUND"}}'

    def json(self):
        return {"error": {"tag": "AUTH.USER_SESSION_NOT_FOUND"}, "data": None}


class _Sessao401:
    def get(self, url, timeout=60):
        return _Resposta401()


class TestGetJson401(unittest.TestCase):
    """Cookie derrubado pelo servidor NA PRIMEIRA chamada (obter_curso/listar_cursos)
    tem que virar CookieVencido — não SystemExit(1) genérico. (Caso real: pedido #2
    da fila, coleta por ID de Itajaí, terminou 'erro' mudo em vez de aguardando_cookie.)"""

    def test_get_json_401_levanta_cookie_vencido(self):
        with self.assertRaises(extrator_ldi.CookieVencido):
            extrator_ldi.get_json(_Sessao401(), "http://exemplo/bo/ldi/courses/x")

    def test_cookie_vencido_e_a_mesma_classe_no_coletor(self):
        # o worker captura coletor_ldi.CookieVencido — precisa ser a MESMA classe
        self.assertIs(coletor_ldi.CookieVencido, extrator_ldi.CookieVencido)

    def test_obter_curso_401_levanta_cookie_vencido(self):
        with self.assertRaises(coletor_ldi.CookieVencido):
            extrator_ldi.obter_curso(_Sessao401(),
                                     "d8970f8c-732d-4bc6-8bf3-bf9d53a9f314")

    def test_get_json_403_tambem_levanta_cookie_vencido(self):
        # o LDI também derruba sessão com 403 — mesmo tratamento do 401
        # (baixar_blocos já cobre 401/403; get_json precisa do par)
        class _Sessao403(_Sessao401):
            def get(self, url, timeout=60):
                r = _Resposta401()
                r.status_code = 403
                return r

        with self.assertRaises(extrator_ldi.CookieVencido):
            extrator_ldi.get_json(_Sessao403(), "http://exemplo/bo/ldi/courses")

    def test_cookie_vencido_continua_sendo_system_exit(self):
        # os .exe/CLI tratam SystemExit como fim limpo — não pode virar crash
        self.assertTrue(issubclass(extrator_ldi.CookieVencido, SystemExit))


if __name__ == "__main__":
    unittest.main()
