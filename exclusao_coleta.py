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
from collections import namedtuple

import extrator_ldi

PedidoExclusao = namedtuple("PedidoExclusao",
                            "termo extracao_local iniciada_em vacuum")

# "YYYY-MM-DDTHH:MM:SS" — o SQLite guarda a data naive
# ('2026-07-06T23:56:22') e o Supabase devolve timestamptz
# ('2026-07-06T23:56:22+00:00'). Comparar os 19 primeiros caracteres casa os
# dois sem depender de conversão de fuso.
_TAM_DATA = 19


def _falhar(msg):
    """Como extrator_ldi.falha, mas a exceção CARREGA o texto.

    O falha() do projeto faz `print(msg)` e levanta `SystemExit(1)`, então a
    coluna `mensagem` da fila recebe literalmente "1" (visto no pedido #16 de
    31/07). Aqui a mensagem É o produto: "a extração N é de outra origem, nada
    foi apagado" é justamente o que o admin precisa ler na tela."""
    print(f"\n[ERRO] {msg}")
    return SystemExit(msg)

# A ORDEM IMPORTA e não é imposição do banco — o SQLite não tem FK nenhuma
# (banco_conteudo.py:12-64), a ordem é escolha nossa. `extracoes` vem por
# ÚLTIMO: enquanto essa linha existir, o painel ainda ENXERGA a extração
# (visivelmente errada). Se sumisse primeiro e o processo caísse, ficariam
# centenas de MB de blocos que NENHUMA tela lista.
# Lixo visível é melhor que lixo invisível.
TABELAS = ("blocos", "aulas_coletadas", "aulas", "capitulos", "cursos", "extracoes")


def ler_pedido_exclusao(row):
    """Deriva um PedidoExclusao de uma linha da fila tipo='excluir'.

    O alvo é um JSON, nunca um termo legível: se um worker ANTIGO pegar este
    pedido, ele trata o JSON inteiro como search_term, não acha curso nenhum e
    falha limpo — em vez de RECOLETAR o termo que se pediu para apagar."""
    try:
        alvo = json.loads(row.get("alvo") or "")
    except (ValueError, TypeError):
        raise _falhar("pedido de exclusão com alvo ilegível (esperava JSON).")
    if not isinstance(alvo, dict):
        raise _falhar("pedido de exclusão com alvo que não é objeto JSON.")

    termo = alvo.get("termo")
    if not isinstance(termo, str) or not termo.strip():
        raise _falhar("pedido de exclusão sem termo.")

    extracao_local = alvo.get("extracao_local")
    # bool é subclasse de int em Python — True passaria como 1 sem esta guarda
    if not isinstance(extracao_local, int) or isinstance(extracao_local, bool) \
            or extracao_local <= 0:
        raise _falhar(
            f"pedido de exclusão com extracao_local inválida: {extracao_local!r}")

    iniciada_em = alvo.get("iniciada_em")
    if not isinstance(iniciada_em, str) or not iniciada_em.strip():
        # Sem a data não dá para saber DE QUAL BANCO a extração N é — ver a
        # docstring de conferir_extracao. Recusar é a única resposta segura.
        raise _falhar(
            "pedido de exclusão sem iniciada_em (formato antigo do alvo). "
            "Refaça o pedido pela tela — sem a data não é possível confirmar "
            "que a extração local é a mesma coleta que está na web.")

    return PedidoExclusao(termo.strip(), extracao_local, iniciada_em.strip(),
                          bool(alvo.get("vacuum")))


def conferir_extracao(con, extracao_id, termo, iniciada_em):
    """Devolve a linha de `extracoes` do alvo, ou None se ela não existe aqui.

    None NÃO é erro: o snapshot no Supabase pode ter sobrado de uma tentativa
    que morreu no meio (idempotência) — ou a coleta pode ter sido publicada por
    OUTRA máquina, e então não há nada a apagar neste disco.

    Por que a data também é conferida, e não só o termo
    ---------------------------------------------------
    `extracao_local` é o `extracoes.id`, um AUTOINCREMENT **por banco**. Vários
    `conteudo.db` publicam no mesmo Supabase (o do VPS, o do notebook do Clovis
    e ao menos um terceiro — constatado em 31/07: o Supabase tinha
    `BACEN extracao_local=1` iniciada em 30/07, enquanto a #1 do VPS era
    `TESTE-VPS-APAGAR` e a #1 do notebook era um BACEN de 06/07).

    Ou seja: `(termo, extracao_local)` **não** identifica uma coleta
    globalmente. Só o termo protegeria contra apagar coleta de outro concurso,
    mas não contra apagar o BACEN errado — que é exatamente o caso que existe.
    A data de início desempata, já vem no `snapshot` e não custou migração."""
    row = con.execute("SELECT * FROM extracoes WHERE id=?", (extracao_id,)).fetchone()
    if row is None:
        return None
    if (row["termo"] or "") != termo:
        raise _falhar(
            f"termo divergente: o pedido diz {termo!r}, mas a extração "
            f"{extracao_id} deste banco é de {row['termo']!r}. Nada foi apagado.")
    if (row["iniciada_em"] or "")[:_TAM_DATA] != (iniciada_em or "")[:_TAM_DATA]:
        raise _falhar(
            f"a extração {extracao_id} deste banco começou em "
            f"{(row['iniciada_em'] or '?')[:_TAM_DATA]}, mas a coleta pedida "
            f"começou em {(iniciada_em or '?')[:_TAM_DATA]} — são coletas "
            "diferentes com o mesmo número (bancos distintos publicando no "
            "mesmo Supabase). Nada foi apagado.")
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
