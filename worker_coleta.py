# -*- coding: utf-8 -*-
"""
============================================================
 WORKER DE COLETA — roda no VPS (systemd). Observa a fila
 coleta_pedido no Supabase, executa coletor_ldi.coletar()
 (que publica o snapshot no fim), reporta status/progresso,
 honra cancelamento e avisa por e-mail (Resend) quando o
 cookie do LDI cai. Spec: docs/superpowers/specs/2026-07-20-*.
 Uso: py worker_coleta.py   (laço; Ctrl-C encerra)

 Limitações conhecidas: o cancelamento só age na fase de download de
 blocos e drena os downloads já enfileirados (não é instantâneo); as
 fases de listar cursos/professores não checam cancelamento.
============================================================
"""
import os
import sys
import time
from datetime import datetime, timezone

import requests

import extrator_ldi
import banco_conteudo
import coletor_ldi
import cookie_status
import exclusao_coleta
import sync_supabase

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

INTERVALO = 20          # segundos entre ciclos
PROBE_A_CADA = 45       # ciclos entre provas HTTP do cookie (~15 min)
BANCO = os.path.join(extrator_ldi.PASTA_APP, "saida", "conteudo.db")

# Último veredito do probe HTTP, mantido entre ciclos. Sem isso, a publicação
# de 20s (que deriva `valido` só do exp do JWT) sobrescreveria o "sessão
# derrubada" logo depois do incidente — o bug do status mentiroso de 21/07.
_probe = {"cookie": None, "resultado": None, "ciclo": 0}


def pedido_para_coleta(row):
    """Deriva (termo, ids) de uma linha da fila. termo=rótulo quando tipo=ids.

    Só trata os tipos de COLETA — 'excluir' é roteado antes, em main(), e
    qualquer tipo novo (entregas futuras) falha limpo em vez de virar busca."""
    if row["tipo"] == "ids":
        if not row.get("rotulo"):
            raise extrator_ldi.falha("pedido tipo=ids sem rótulo.")
        return row["rotulo"], coletor_ldi.extrair_ids(row["alvo"])
    if row["tipo"] != "termo":
        raise extrator_ldi.falha(f"tipo de pedido desconhecido: {row['tipo']!r}")
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
    cookie = (linhas[0]["cookie"] if linhas else None) or None
    # a web pode gravar só o valor do JWT; o header Cookie exige o par completo
    if cookie and "__Secure-SID=" not in cookie:
        cookie = f"__Secure-SID={cookie}"
    return cookie


def _publicar_cookie_status(rest, key, cookie, forcar_invalido=False, probe=None):
    """Publica o status COMBINADO: valido = exp do JWT no futuro E o último
    probe HTTP não recusou (probe False = sessão derrubada pelo servidor).
    O front infere o motivo: valido=False com dias_restantes>0 = derrubada."""
    r = cookie_status.resumo_validade(cookie or "")
    if forcar_invalido or probe is False:
        r = {**r, "valido": False}
    corpo = {"id": 1, **r, "atualizado_em": datetime.now(timezone.utc).isoformat()}
    requests.post(f"{rest}/cookie_status",
                  headers=sync_supabase._headers(key, "resolution=merge-duplicates"),
                  params={"on_conflict": "id"}, json=corpo, timeout=30).raise_for_status()
    return r


def _avaliar_cookie(rest, key, cfg, forcar_probe=False):
    """Lê o cookie, mantém o veredito do probe entre ciclos e publica o status
    combinado. Prova quando: o cookie mudou (renovado → atualiza o banner na
    hora), a cada PROBE_A_CADA ciclos, ou forcar_probe (antes de um pedido).
    Devolve (cookie, veredito) — veredito None = nunca provado/inconclusivo."""
    cookie = _ler_cookie(rest, key)
    if cookie != _probe["cookie"]:
        _probe.update(cookie=cookie, resultado=None, ciclo=0)
        forcar_probe = True
    if cookie and (forcar_probe or _probe["ciclo"] % PROBE_A_CADA == 0):
        veredito = cookie_status.probar_cookie(extrator_ldi.montar_sessao(cfg, cookie))
        if veredito is not None:  # inconclusivo (rede/5xx) preserva o anterior
            _probe["resultado"] = veredito
    _probe["ciclo"] += 1
    try:
        _publicar_cookie_status(rest, key, cookie, probe=_probe["resultado"])
    except Exception as e:
        print(f"[worker] publicar cookie_status falhou (segue): {e}")
    return cookie, _probe["resultado"]


def enviar_email_cookie(assunto, corpo_html):
    """Avisa o admin por e-mail (Resend). Sem RESEND_API_KEY, apenas loga."""
    cfg = sync_supabase._config_json() if hasattr(sync_supabase, "_config_json") else {}
    api = os.environ.get("RESEND_API_KEY") or cfg.get("resend_api_key")
    para = os.environ.get("ADMIN_EMAIL") or cfg.get("admin_email")
    if not api or not para:
        print(f"[worker] (sem Resend/admin_email — não enviei) {assunto}")
        return
    resp = requests.post("https://api.resend.com/emails",
                  headers={"Authorization": f"Bearer {api}", "Content-Type": "application/json"},
                  json={"from": "Painel de Conteúdo <painel@infosab.com.br>",
                        "to": [para], "subject": assunto, "html": corpo_html},
                  timeout=30)
    print(f"[worker] e-mail cookie -> Resend {resp.status_code}")


def processar_pedido(rest, key, row, cfg):
    """Executa um pedido; devolve o status final."""
    pid = row["id"]
    _patch_pedido(rest, key, pid, {"status": "rodando",
                                   "iniciado_em": datetime.now(timezone.utc).isoformat()})
    # prova o cookie DE VERDADE antes de coletar (o exp do JWT mente quando o
    # servidor derruba a sessão); probe inconclusivo (None) não bloqueia.
    cookie, probe = _avaliar_cookie(rest, key, cfg, forcar_probe=True)
    if not cookie or not cookie_status.resumo_validade(cookie)["valido"] or probe is False:
        _patch_pedido(rest, key, pid, {"status": "aguardando_cookie",
                                       "mensagem": "cookie ausente, vencido ou recusado pelo LDI"})
        enviar_email_cookie("Cookie do LDI precisa ser renovado",
                            "<p>Uma coleta ficou esperando: o cookie do LDI está ausente, vencido "
                            "ou a sessão foi derrubada pelo servidor. "
                            "Renove-o na tela de coleta do painel.</p>")
        return "aguardando_cookie"

    def progresso(feito, total):
        try:
            _patch_pedido(rest, key, pid, {"progresso": f"{feito}/{total} itens"})
            cancelar = _status_pedido(rest, key, pid) == "cancelando"
        except Exception:
            return  # blip de rede no Supabase não derruba a coleta em andamento
        if cancelar:
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
    except coletor_ldi.CookieVencido as e:
        _patch_pedido(rest, key, pid, {"status": "aguardando_cookie", "mensagem": str(e)[:400]})
        _probe["resultado"] = False  # o veredito persiste — o loop de 20s não pode voltar a dizer "válido"
        _publicar_cookie_status(rest, key, cookie, forcar_invalido=True)  # publica o status do cookie (agora inválido) para o banner
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


def _apagar_snapshot(rest, key, termo, extracao_local):
    """DELETE do snapshot no Supabase. avaliacao_curso e pendencia_resumo somem
    junto por `on delete cascade` (supabase/schema.sql:18,27)."""
    requests.delete(f"{rest}/snapshot", headers=sync_supabase._headers(key),
                    params={"termo": f"eq.{termo}",
                            "extracao_local": f"eq.{extracao_local}"},
                    timeout=60).raise_for_status()


def processar_exclusao(rest, key, row):
    """Apaga uma coleta nas DUAS camadas: snapshot no Supabase e extração no
    conteudo.db. Devolve o status final.

    NÃO prova o cookie — diferença deliberada de processar_pedido: a exclusão
    não fala com o LDI, e um cookie vencido não pode bloquear uma limpeza de
    disco. Cada passo é idempotente (ver docstring de exclusao_coleta)."""
    pid = row["id"]
    _patch_pedido(rest, key, pid, {"status": "rodando",
                                   "iniciado_em": datetime.now(timezone.utc).isoformat()})
    try:
        p = exclusao_coleta.ler_pedido_exclusao(row)
        termo, extracao_local, vacuum = p.termo, p.extracao_local, p.vacuum
        con = banco_conteudo.abrir(BANCO)
        try:
            # Confere ANTES de tocar no Supabase: termo E data de início. A data
            # é o que impede apagar a coleta errada quando outro conteudo.db
            # publicou uma extração com o mesmo número (ver conferir_extracao).
            ext = exclusao_coleta.conferir_extracao(con, extracao_local, termo,
                                                    p.iniciada_em)
            mais_recente = bool(ext) and exclusao_coleta.era_a_mais_recente(con, extracao_local)
            pendencias = exclusao_coleta.contar_pendencias(con, extracao_local) if ext else 0
            # Supabase PRIMEIRO. Morrer aqui deixa "sumiu da web mas ainda ocupa
            # disco" — retentável e inofensivo. A ordem inversa deixaria a web
            # mostrando uma coleta que não existe mais na origem.
            _apagar_snapshot(rest, key, termo, extracao_local)
            apagadas = exclusao_coleta.apagar_extracao(con, extracao_local) if ext else {}
        finally:
            con.close()
    except SystemExit as e:   # extrator_ldi.falha (alvo ilegível, termo divergente)
        _patch_pedido(rest, key, pid, {"status": "erro", "mensagem": str(e)[:400]})
        return "erro"
    except Exception as e:
        _patch_pedido(rest, key, pid, {"status": "erro", "mensagem": str(e)[:400]})
        return "erro"

    _patch_pedido(rest, key, pid, {
        "status": "concluida", "extracao_id": extracao_local,
        "mensagem": exclusao_coleta.relatorio(termo, extracao_local, apagadas,
                                              pendencias, mais_recente, vacuum)[:400],
        "concluido_em": datetime.now(timezone.utc).isoformat()})
    return "concluida"


def main():
    cfg = extrator_ldi.carregar_config()
    rest, key = _rest()
    print(f"[worker] no ar. fila: {rest}/coleta_pedido  |  banco: {BANCO}")

    # reconciliação: pedidos presos em rodando/cancelando (worker caiu) voltam à fila
    try:
        requests.patch(f"{rest}/coleta_pedido", headers=sync_supabase._headers(key),
                       params={"status": "in.(rodando,cancelando)"},
                       json={"status": "pendente",
                             "mensagem": "reprocessado após reinício do worker"},
                       timeout=30).raise_for_status()
    except Exception as e:
        print(f"[worker] reconciliação falhou (segue): {e}")

    while True:
        try:
            _avaliar_cookie(rest, key, cfg)
            r = requests.get(f"{rest}/coleta_pedido", headers=sync_supabase._headers(key),
                             params={"status": "eq.pendente", "order": "criado_em.asc",
                                     "limit": "1", "select": "*"}, timeout=30)
            r.raise_for_status()
            fila = r.json()
            if fila:
                row = fila[0]
                print(f"[worker] pedido #{row['id']} ({row['tipo']}: {row['alvo'][:40]})")
                if row["tipo"] == "excluir":
                    status = processar_exclusao(rest, key, row)
                else:
                    status = processar_pedido(rest, key, row, cfg)
                print(f"[worker] pedido #{row['id']} -> {status}")
                continue  # busca o próximo já
        except Exception as e:
            print(f"[worker] ciclo falhou (segue): {e}")
        time.sleep(INTERVALO)


if __name__ == "__main__":
    main()
