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

# A ORDEM IMPORTA e não é imposição do banco — o SQLite não tem FK nenhuma
# (banco_conteudo.py:12-64), a ordem é escolha nossa. `extracoes` vem por
# ÚLTIMO: enquanto essa linha existir, o painel ainda ENXERGA a extração
# (visivelmente errada). Se sumisse primeiro e o processo caísse, ficariam
# centenas de MB de blocos que NENHUMA tela lista.
# Lixo visível é melhor que lixo invisível.
TABELAS = ("blocos", "aulas_coletadas", "aulas", "capitulos", "cursos", "extracoes")


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


def conferir_extracao(con, extracao_id, termo):
    """Devolve a linha de `extracoes` do alvo.

    None quando a extração não existe — NÃO é erro: o snapshot no Supabase pode
    ter sobrado de uma tentativa que morreu no meio (idempotência).
    Levanta quando o termo diverge — nunca apagar o alvo errado."""
    row = con.execute("SELECT * FROM extracoes WHERE id=?", (extracao_id,)).fetchone()
    if row is None:
        return None
    if (row["termo"] or "") != termo:
        raise extrator_ldi.falha(
            f"termo divergente: o pedido diz {termo!r}, mas a extração "
            f"{extracao_id} é de {row['termo']!r}. Nada foi apagado.")
    return row


def era_a_mais_recente(con, extracao_id):
    """True se esta é a extração de maior id — a que painel.py:49 e
    sync_supabase.py:62 abrem por padrão (ORDER BY id DESC LIMIT 1, GLOBAL,
    sem filtrar por termo). Chamar ANTES de apagar. Serve para RELATAR, não
    para bloquear: apagar a coleta ruim é justamente apagar a última."""
    maior = con.execute("SELECT MAX(id) FROM extracoes").fetchone()[0]
    return maior is not None and maior == extracao_id


def contar_pendencias(con, extracao_id):
    """Quantas pendências foram apuradas contra esta extração. Elas NÃO são
    apagadas (a chave é determinística e independe da extração); o worker só
    informa que os números vão continuar velhos até a próxima coleta."""
    return con.execute(
        "SELECT COUNT(*) FROM pendencias "
        "WHERE extracao_id_criada=? OR extracao_id_ultima=?",
        (extracao_id, extracao_id)).fetchone()[0]


def apagar_extracao(con, extracao_id):
    """Os 6 DELETEs numa ÚNICA transação. Devolve {tabela: linhas_apagadas}.

    Idempotente: rodar de novo devolve zeros sem levantar."""
    apagadas = {}
    with con:  # commit no fim, ROLLBACK em qualquer exceção
        for tabela in TABELAS:
            # nome de tabela vem da constante TABELAS, nunca de entrada externa
            coluna = "id" if tabela == "extracoes" else "extracao_id"
            cur = con.execute(f"DELETE FROM {tabela} WHERE {coluna}=?", (extracao_id,))
            apagadas[tabela] = cur.rowcount
    return apagadas


def relatorio(termo, extracao_local, apagadas, pendencias, mais_recente, vacuum=False):
    """Mensagem final do pedido (cabe em 400 caracteres na coluna `mensagem`)."""
    partes = [f"Coleta {termo} #{extracao_local} apagada."]
    if apagadas:
        partes.append(" · ".join(f"{t}: {n}" for t, n in apagadas.items()) + ".")
    else:
        partes.append("A extração já não existia no conteudo.db "
                      "(só o snapshot foi removido).")
    if pendencias:
        partes.append(f"{pendencias} pendências foram apuradas contra esta coleta e "
                      "continuarão abertas com os números antigos até a próxima "
                      "coleta deste termo.")
    if mais_recente:
        partes.append("Era a extração de maior id — o painel local passa a abrir "
                      "a anterior.")
    if vacuum:
        partes.append("VACUUM pedido, mas ainda não implementado (entrega 1b) — ignorado.")
    return " ".join(partes)
