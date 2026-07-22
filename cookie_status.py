# -*- coding: utf-8 -*-
"""Validade do cookie __Secure-SID do LDI (compartilhado: visualizador e worker)."""
import base64
import json
import re
import time
from datetime import datetime, timezone


# Endpoint mais barato do LDI para provar a sessão (espelho de extrator_ldi.API;
# constante local para o módulo continuar sem dependências além de stdlib).
URL_PROBE = ("https://api.estrategia.com/bo/ldi/courses"
             "?page=1&per_page=1&sort=desc&order_by=created_at")


def probar_cookie(sessao):
    """Prova o cookie contra a API (o exp do JWT mente quando o servidor derruba
    a sessão). Devolve True (aceito), False (401/403 = recusado) ou None
    (inconclusivo: rede fora ou 5xx — não é veredito sobre o cookie).
    `sessao` = requests.Session já montada (extrator_ldi.montar_sessao)."""
    try:
        r = sessao.get(URL_PROBE, timeout=15)
    except Exception:
        return None
    if r.status_code in (401, 403):
        return False
    if r.ok:
        return True
    return None


def decodifica_sid(cookie_bruto):
    """Extrai {email, expira_ts} do token __Secure-SID; {} se não achar/decodificar."""
    m = re.search(r"__Secure-SID=([^;\s]+)", cookie_bruto or "")
    if not m:
        return {}
    try:
        payload = m.group(1).split(".")[1]
        payload += "=" * (-len(payload) % 4)
        j = json.loads(base64.urlsafe_b64decode(payload))
        return {"email": j.get("email", ""), "expira_ts": j.get("exp")}
    except Exception:
        return {}


def resumo_validade(cookie_bruto):
    """Resumo sem rede: {email, expira_em(iso|None), dias_restantes(float|None), valido}.
    valido = há exp no futuro (não faz probe HTTP; o worker pode complementar com probe)."""
    sid = decodifica_sid(cookie_bruto)
    exp = sid.get("expira_ts")
    if not exp:
        return {"email": "", "expira_em": None, "dias_restantes": None, "valido": False}
    return {
        "email": sid.get("email", ""),
        "expira_em": datetime.fromtimestamp(exp, timezone.utc).isoformat(),
        "dias_restantes": round((exp - time.time()) / 86400, 1),
        "valido": exp > time.time(),
    }
