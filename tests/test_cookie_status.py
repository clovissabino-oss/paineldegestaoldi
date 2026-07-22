import base64, json, time, unittest
import cookie_status

def _sid(email, exp):
    payload = base64.urlsafe_b64encode(
        json.dumps({"email": email, "exp": exp}).encode()).decode().rstrip("=")
    return f"__Secure-SID=x.{payload}.y; outra=coisa"

class TestCookieStatus(unittest.TestCase):
    def test_decodifica(self):
        d = cookie_status.decodifica_sid(_sid("a@b.com", 9999999999))
        self.assertEqual(d["email"], "a@b.com")
        self.assertEqual(d["expira_ts"], 9999999999)

    def test_sem_sid(self):
        self.assertEqual(cookie_status.decodifica_sid("nada aqui"), {})

    def test_resumo_valido_futuro(self):
        r = cookie_status.resumo_validade(_sid("a@b.com", int(time.time()) + 5 * 86400))
        self.assertTrue(r["valido"])
        self.assertEqual(r["email"], "a@b.com")
        self.assertGreater(r["dias_restantes"], 4)

    def test_resumo_vencido(self):
        r = cookie_status.resumo_validade(_sid("a@b.com", int(time.time()) - 10))
        self.assertFalse(r["valido"])


class _Resp:
    def __init__(self, status):
        self.status_code = status
        self.ok = 200 <= status < 300


class _Sessao:
    def __init__(self, status=None, erro=None):
        self._status, self._erro = status, erro

    def get(self, url, timeout=15):
        if self._erro:
            raise self._erro
        return _Resp(self._status)


class TestProbarCookie(unittest.TestCase):
    """Prova o cookie contra a API de verdade — o exp do JWT mente quando o
    servidor derruba a sessão (caso real de 21/07: AUTH.USER_SESSION_NOT_FOUND
    com 28 dias de exp pela frente)."""

    def test_200_aceito(self):
        self.assertIs(cookie_status.probar_cookie(_Sessao(200)), True)

    def test_401_recusado(self):
        self.assertIs(cookie_status.probar_cookie(_Sessao(401)), False)

    def test_403_recusado(self):
        self.assertIs(cookie_status.probar_cookie(_Sessao(403)), False)

    def test_erro_de_rede_inconclusivo(self):
        self.assertIsNone(cookie_status.probar_cookie(_Sessao(erro=OSError("rede"))))

    def test_5xx_inconclusivo(self):
        # instabilidade do servidor não é veredito sobre o cookie
        self.assertIsNone(cookie_status.probar_cookie(_Sessao(503)))


if __name__ == "__main__":
    unittest.main()
