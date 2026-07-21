# -*- coding: utf-8 -*-
"""
============================================================
 WORKER DE COLETA — roda no VPS (systemd). Observa a fila
 coleta_pedido no Supabase, executa coletor_ldi.coletar()
 (que publica o snapshot no fim), reporta status/progresso,
 honra cancelamento e avisa por e-mail (Resend) quando o
 cookie do LDI cai. Spec: docs/superpowers/specs/2026-07-20-*.
 Uso: py worker_coleta.py   (laço; Ctrl-C encerra)
============================================================
"""
import os
import sys
import time
from datetime import datetime, timezone

import requests

import extrator_ldi
import coletor_ldi
import cookie_status
import sync_supabase

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

INTERVALO = 20          # segundos entre ciclos
BANCO = os.path.join(extrator_ldi.PASTA_APP, "saida", "conteudo.db")


def pedido_para_coleta(row):
    """Deriva (termo, ids) de uma linha da fila. termo=rótulo quando tipo=ids."""
    if row["tipo"] == "ids":
        if not row.get("rotulo"):
            raise extrator_ldi.falha("pedido tipo=ids sem rótulo.")
        return row["rotulo"], coletor_ldi.extrair_ids(row["alvo"])
    return row["alvo"], None


def _rest():
    url, key = sync_supabase._config()
    return f"{url}/rest/v1", key


def _patch_pedido(rest, key, pedido_id, campos):
    requests.patch(f"{rest}/coleta_pedido", headers=sync_supabase._headers(key),
                   params={"id": f"eq.{pedido_id}"}, json=campos, timeout=30
                   ).raise_for_status()


def _status_pedido(rest, key, pedido_id):
    r = requests.get(f"{rest}/coleta_pedido", headers=sync_supabase._headers(key),
                     params={"id": f"eq.{pedido_id}", "select": "status"}, timeout=30)
    r.raise_for_status()
    linhas = r.json()
    return linhas[0]["status"] if linhas else None


def _ler_cookie(rest, key):
    r = requests.get(f"{rest}/config_ldi", headers=sync_supabase._headers(key),
                     params={"id": "eq.1", "select": "cookie"}, timeout=30)
    r.raise_for_status()
    linhas = r.json()
    return (linhas[0]["cookie"] if linhas else None) or None


def _publicar_cookie_status(rest, key, cookie):
    r = cookie_status.resumo_validade(cookie or "")
    corpo = {"id": 1, **r, "atualizado_em": datetime.now(timezone.utc).isoformat()}
    requests.post(f"{rest}/cookie_status",
                  headers=sync_supabase._headers(key, "resolution=merge-duplicates"),
                  params={"on_conflict": "id"}, json=corpo, timeout=30).raise_for_status()
    return r


def enviar_email_cookie(assunto, corpo_html):
    """Avisa o admin por e-mail (Resend). Sem RESEND_API_KEY, apenas loga."""
    cfg = sync_supabase._config_json() if hasattr(sync_supabase, "_config_json") else {}
    api = os.environ.get("RESEND_API_KEY") or cfg.get("resend_api_key")
    para = os.environ.get("ADMIN_EMAIL") or cfg.get("admin_email")
    if not api or not para:
        print(f"[worker] (sem Resend/admin_email — não enviei) {assunto}")
        return
    requests.post("https://api.resend.com/emails",
                  headers={"Authorization": f"Bearer {api}", "Content-Type": "application/json"},
                  json={"from": "Painel de Conteúdo <painel@infosab.com.br>",
                        "to": [para], "subject": assunto, "html": corpo_html},
                  timeout=30)


def processar_pedido(rest, key, row, cfg):
    """Executa um pedido; devolve o status final."""
    pid = row["id"]
    _patch_pedido(rest, key, pid, {"status": "rodando",
                                   "iniciado_em": datetime.now(timezone.utc).isoformat()})
    cookie = _ler_cookie(rest, key)
    if not cookie or not cookie_status.resumo_validade(cookie)["valido"]:
        _patch_pedido(rest, key, pid, {"status": "aguardando_cookie",
                                       "mensagem": "cookie ausente ou vencido"})
        enviar_email_cookie("Cookie do LDI precisa ser renovado",
                            "<p>Uma coleta ficou esperando: o cookie do LDI está ausente ou vencido. "
                            "Atualize-o na tela de admin do painel.</p>")
        return "aguardando_cookie"

    def progresso(feito, total):
        _patch_pedido(rest, key, pid, {"progresso": f"{feito}/{total} aulas"})
        if _status_pedido(rest, key, pid) == "cancelando":
            raise coletor_ldi.ColetaCancelada()

    try:
        # dentro do try: um pedido malformado (extrator_ldi.falha=SystemExit)
        # vira status 'erro' em vez de derrubar o worker.
        termo, ids = pedido_para_coleta(row)
        sessao = extrator_ldi.montar_sessao(cfg, cookie)
        extracao_id = coletor_ldi.coletar(cfg, sessao, termo, BANCO,
                                          ids=ids, progresso=progresso)
    except coletor_ldi.ColetaCancelada:
        _patch_pedido(rest, key, pid, {"status": "cancelada",
                                       "concluido_em": datetime.now(timezone.utc).isoformat()})
        return "cancelada"
    except extrator_ldi.CookieVencido as e:
        _patch_pedido(rest, key, pid, {"status": "aguardando_cookie", "mensagem": str(e)[:400]})
        _publicar_cookie_status(rest, key, cookie)  # provavelmente valido=false após probe futuro
        enviar_email_cookie("Cookie do LDI caiu durante a coleta",
                            "<p>A coleta falhou com 401/403 — o cookie do LDI caiu. "
                            "Renove-o na tela de admin e use \"retentar\".</p>")
        return "aguardando_cookie"
    except SystemExit as e:  # falhas do extrator (extrator_ldi.falha) chegam como SystemExit
        _patch_pedido(rest, key, pid, {"status": "erro", "mensagem": str(e)[:400]})
        return "erro"
    except Exception as e:
        _patch_pedido(rest, key, pid, {"status": "erro", "mensagem": str(e)[:400]})
        return "erro"

    _patch_pedido(rest, key, pid, {"status": "concluida", "extracao_id": extracao_id,
                                   "concluido_em": datetime.now(timezone.utc).isoformat()})
    return "concluida"


def main():
    cfg = extrator_ldi.carregar_config()
    rest, key = _rest()
    print(f"[worker] no ar. fila: {rest}/coleta_pedido  |  banco: {BANCO}")
    while True:
        try:
            cookie = _ler_cookie(rest, key)
            _publicar_cookie_status(rest, key, cookie)
            r = requests.get(f"{rest}/coleta_pedido", headers=sync_supabase._headers(key),
                             params={"status": "eq.pendente", "order": "criado_em.asc",
                                     "limit": "1", "select": "*"}, timeout=30)
            r.raise_for_status()
            fila = r.json()
            if fila:
                row = fila[0]
                print(f"[worker] pedido #{row['id']} ({row['tipo']}: {row['alvo'][:40]})")
                status = processar_pedido(rest, key, row, cfg)
                print(f"[worker] pedido #{row['id']} -> {status}")
                continue  # busca o próximo já
        except Exception as e:
            print(f"[worker] ciclo falhou (segue): {e}")
        time.sleep(INTERVALO)


if __name__ == "__main__":
    main()
