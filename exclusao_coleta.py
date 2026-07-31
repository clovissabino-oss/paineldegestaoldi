# -*- coding: utf-8 -*-
"""
============================================================
 EXCLUSÃO DE COLETA — funções puras (sem HTTP) usadas pelo
 worker para apagar uma extração do conteudo.db.
 Spec: docs/superpowers/specs/2026-07-30-exclusao-coleta-design.md

 INVARIANTE: cada função é IDEMPOTENTE de propósito. A
 reconciliação da subida do worker (worker_coleta.main) devolve
 pedidos presos em 'rodando' para 'pendente', então um pedido de
 exclusão pode reexecutar depois de já ter apagado parte das
 coisas. Não "otimizar" nenhum passo para pular a checagem de
 existência — é ela que segura a reexecução.
============================================================
"""
import json

import extrator_ldi


def ler_pedido_exclusao(row):
    """Deriva (termo, extracao_local, vacuum) de uma linha da fila tipo='excluir'.

    O alvo é um JSON, nunca um termo legível: se um worker ANTIGO pegar este
    pedido, ele trata o JSON inteiro como search_term, não acha curso nenhum e
    falha limpo — em vez de RECOLETAR o termo que se pediu para apagar."""
    try:
        alvo = json.loads(row.get("alvo") or "")
    except (ValueError, TypeError):
        raise extrator_ldi.falha(
            "pedido de exclusão com alvo ilegível (esperava JSON).")
    if not isinstance(alvo, dict):
        raise extrator_ldi.falha("pedido de exclusão com alvo que não é objeto JSON.")

    termo = alvo.get("termo")
    if not isinstance(termo, str) or not termo.strip():
        raise extrator_ldi.falha("pedido de exclusão sem termo.")

    extracao_local = alvo.get("extracao_local")
    # bool é subclasse de int em Python — True passaria como 1 sem esta guarda
    if not isinstance(extracao_local, int) or isinstance(extracao_local, bool) \
            or extracao_local <= 0:
        raise extrator_ldi.falha(
            f"pedido de exclusão com extracao_local inválida: {extracao_local!r}")

    return termo.strip(), extracao_local, bool(alvo.get("vacuum"))
