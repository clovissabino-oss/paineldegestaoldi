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
import argparse
import json
import os
import shutil
import sqlite3
import sys
from collections import namedtuple

import requests

import banco_conteudo
import extrator_ldi
import sync_supabase

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


# Pico de disco do VACUUM, MEDIDO em 03/08: 62,1 MB para um banco de 41,3 MB.
# Em WAL o VACUUM escreve o resultado no WAL antes de consolidar, então o pico é
# maior que o arquivo final — 1,0x NÃO basta.
FOLGA_VACUUM = 1.5


# Espera curta só para a CHECAGEM de lock. Com o busy_timeout padrão (5s), o
# BEGIN IMMEDIATE fica 5,5s parado antes de admitir que o banco está ocupado
# (medido) — o CLI pareceria travado. 300ms basta para distinguir "ocupado" de
# "livre" e é restaurado logo em seguida.
_ESPERA_CHECAGEM_MS = 300


def banco_em_uso(con):
    """True se há ESCRITA em andamento neste banco agora — não detecta leitor.

    Testa com BEGIN IMMEDIATE, que pega o lock de ESCRITA (o mesmo que o
    DELETE pegaria) e desfaz na hora — checado ANTES, quando ainda não há
    nada a reverter. Em modo WAL um leitor com transação aberta NÃO bloqueia
    isso (medido: com leitor solto, devolve False) — só outro escritor
    bloqueia. As mensagens que usam esta função não devem prometer mais do
    que isso."""
    anterior = con.execute("PRAGMA busy_timeout").fetchone()[0]
    con.execute(f"PRAGMA busy_timeout={_ESPERA_CHECAGEM_MS}")
    try:
        con.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError:
        return True
    else:
        con.rollback()
        return False
    finally:
        con.execute(f"PRAGMA busy_timeout={anterior}")


# Texto das duas checagens de banco_em_uso() no CLI (--excluir e --compactar).
# Reflete o que a função de fato testa: escrita em andamento, não leitor —
# ver a docstring de banco_em_uso.
_MSG_ESCRITA_EM_ANDAMENTO = (
    "há escrita em andamento neste banco agora (esta checagem detecta "
    "escritor, não leitor — painel.py aberto só para leitura não é pego). "
    "Aguarde terminar e tente de novo.")


def espaco_para_vacuum(caminho):
    """(cabe, precisa_bytes, livre_bytes) para compactar `caminho`.

    Checar ANTES de apagar: faltando espaço, falha limpa e retentável é mais
    previsível que 'apagou mas não compactou'."""
    tamanho = os.path.getsize(caminho) if os.path.exists(caminho) else 0
    precisa = int(tamanho * FOLGA_VACUUM)
    # Desempacota por posição (total, usado, livre) em vez de usar o atributo
    # `.free` do namedtuple: os testes mockam disk_usage devolvendo uma tupla
    # comum, que não tem esse atributo.
    _, _, livre = shutil.disk_usage(os.path.dirname(os.path.abspath(caminho)))
    return livre >= precisa, precisa, livre


def compactar(con, caminho):
    """Roda VACUUM e devolve (bytes_antes, bytes_depois) do arquivo principal.

    O checkpoint DEPOIS não é opcional: medido, o conjunto ainda ocupava
    41,5 MB logo após o VACUUM e só caiu para 20,7 MB depois dele — sem esse
    passo o comando diz "compactado" e o `ls` mostra o mesmo tamanho.

    Não promete ganho antes de rodar: `freelist_count` reportou 0 MB num banco
    com metade dos dados apagados que o VACUUM ainda reduziu à metade."""
    antes = os.path.getsize(caminho)
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.execute("VACUUM")            # fora de transação (isolation_level='' do projeto)
    busy, _log, _checkpointed = con.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    if busy:
        # busy=1: outra conexão está lendo e o SQLite não pôde truncar o WAL
        # agora. O VACUUM já rodou (não é erro) — só a consolidação final
        # ficou pendente, e o arquivo principal ainda não reflete o ganho.
        print("  [aviso] compactação concluída, mas a consolidação final ficou "
              "pendente — há outra conexão lendo o banco agora. O espaço "
              "aparece no disco quando essa conexão fechar.")
    return antes, os.path.getsize(caminho)


def publicadas_no_supabase():
    """Devolve {(termo, iniciada_em[:19])} das coletas publicadas na web.

    None quando não deu para consultar (sem credencial, sem rede, erro) — o
    chamador mostra "?" na coluna. LISTAR É LEITURA: nunca pode levantar, senão
    um blip de rede impede o Clovis de ver o que tem na própria máquina."""
    if not sync_supabase.esta_configurado():
        return None
    try:
        url, key = sync_supabase._config()
        r = requests.get(f"{url}/rest/v1/snapshot",
                         headers=sync_supabase._headers(key),
                         params={"select": "termo,iniciada_em"}, timeout=30)
        r.raise_for_status()
        return {(x["termo"], (x["iniciada_em"] or "")[:_TAM_DATA])
                for x in r.json() if x.get("iniciada_em")}
    # SystemExit herda de BaseException, não de Exception — um `except Exception`
    # sozinho não pegaria esse caminho. sync_supabase._config() levanta SystemExit
    # quando a FONTE de config existe (esta_configurado()==True) mas está pela
    # metade (ex.: supabase.json sem service_key, ou só uma das duas env vars).
    except (Exception, SystemExit) as e:
        print(f"[aviso] não consegui consultar o Supabase ({e}); "
              "a coluna 'publicada?' fica como '?'.")
        return None


def listar_extracoes(con, publicadas):
    """Uma linha por extração do banco local, com o peso e se está publicada.

    `publicadas` = saída de publicadas_no_supabase() (None = desconhecido).
    A comparação usa os 19 primeiros caracteres da data: o SQLite grava naive
    ('2026-07-06T23:56:22') e o Supabase devolve timestamptz ('...+00:00')."""
    linhas = []
    for r in con.execute(
            "SELECT e.id, e.termo, e.iniciada_em, e.status, e.total_cursos, "
            "       (SELECT COUNT(*) FROM blocos b WHERE b.extracao_id = e.id) blocos "
            "FROM extracoes e ORDER BY e.id"):
        chave = (r["termo"], (r["iniciada_em"] or "")[:_TAM_DATA])
        linhas.append({
            "id": r["id"], "termo": r["termo"],
            "iniciada_em": (r["iniciada_em"] or "")[:16].replace("T", " "),
            "status": r["status"], "cursos": r["total_cursos"] or 0,
            "blocos": r["blocos"] or 0,
            "publicada": None if publicadas is None else (chave in publicadas),
        })
    return linhas


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


def _texto_aviso_publicada(publicada):
    """Aviso sobre o estado 'publicada?' do alvo escolhido para --excluir, ou
    None quando não há nada a avisar (não publicada).

    `publicada` tem TRÊS estados (ver listar_extracoes/publicadas_no_supabase):
    True, False e None (Supabase fora do ar, sem credencial, blip de rede).
    A confirmação do --excluir é POR TERMO, e duas coletas do mesmo termo
    (mesmo banco ou bancos diferentes) não se distinguem só por ele — este
    aviso é o único sinal, então None não pode ficar mudo."""
    if publicada is True:
        return ("⚠ Esta coleta está publicada na web — o snapshot continua lá, "
                "mas some a origem local (recoleta/diff futuros).")
    if publicada is None:
        return ("⚠ Não foi possível saber se esta coleta está publicada na web "
                "(Supabase fora do ar, sem credencial, ou falha de rede) — "
                "confira na tela antes de seguir.")
    return None


def _caminho_banco():
    """Mesmo caminho que o coletor e o painel usam (respeita o config.json)."""
    import extrator_ldi as _e
    cfg = _e.carregar_config()
    return os.path.join(_e.PASTA_APP, cfg["pasta_saida"], "conteudo.db")


def _imprimir_listagem(linhas):
    if not linhas:
        print("  (nenhuma extração no banco)")
        return
    print(f"  {'#':>3}  {'termo':28}  {'quando':16}  {'cursos':>6}  {'blocos':>7}  publicada?")
    for l in linhas:
        pub = {True: "sim", False: "não", None: "?"}[l["publicada"]]
        print(f"  {l['id']:>3}  {l['termo'][:28]:28}  {l['iniciada_em']:16}  "
              f"{l['cursos']:>6}  {l['blocos']:>7}  {pub}")
    print("\n  'publicada?' = a coleta está no Supabase (o time vê na web).")
    print("  Apagar aqui NÃO tira nada do ar — a web tem tela própria para isso.")


def main():
    parser = argparse.ArgumentParser(
        description="Exclusão e compactação do conteudo.db LOCAL. "
                    "Não toca no Supabase — a web tem tela própria para isso.")
    parser.add_argument("--listar", action="store_true",
                        help="mostra as extrações do banco e quais estão publicadas")
    parser.add_argument("--excluir", type=int, metavar="N",
                        help="apaga a extração N (pede o termo por confirmação)")
    parser.add_argument("--compactar", action="store_true",
                        help="roda VACUUM e devolve o espaço ao disco")
    args = parser.parse_args()

    if not (args.listar or args.excluir is not None or args.compactar):
        parser.print_help()
        return

    caminho = _caminho_banco()
    con = banco_conteudo.abrir(caminho)
    try:
        print("=" * 66)
        print(f" EXCLUSÃO LOCAL  |  banco: {caminho}")
        print("=" * 66)

        if args.listar or args.excluir is not None:
            linhas = listar_extracoes(con, publicadas_no_supabase())

        if args.listar:
            _imprimir_listagem(linhas)
            if args.excluir is None and not args.compactar:
                return

        if args.excluir is not None:
            alvo = next((l for l in linhas if l["id"] == args.excluir), None)
            if alvo is None:
                raise _falhar(f"não existe extração #{args.excluir} neste banco.")
            if not args.listar:
                _imprimir_listagem([alvo])
            if banco_em_uso(con):
                raise _falhar(_MSG_ESCRITA_EM_ANDAMENTO)
            if args.compactar:
                cabe, precisa, livre = espaco_para_vacuum(caminho)
                if not cabe:
                    raise _falhar(
                        f"espaço insuficiente para compactar: precisa de "
                        f"{precisa/1048576:.0f} MB livres, há {livre/1048576:.0f} MB. "
                        "Nada foi apagado.")
            print(f"\n  Isto apaga a extração #{alvo['id']} ({alvo['blocos']} blocos) "
                  "do banco local. NÃO tem volta.")
            aviso = _texto_aviso_publicada(alvo["publicada"])
            if aviso:
                print(f"  {aviso}")
            if not sys.stdin.isatty():
                raise _falhar(
                    "a confirmação exige um terminal interativo — exclusão não "
                    "deve ser automatizada por pipe ou agendamento.")
            digitado = input(
                f"  Digite {alvo['termo']} para confirmar a exclusão da "
                f"#{alvo['id']} de {alvo['iniciada_em']}: ").strip()
            if digitado != alvo["termo"]:
                raise _falhar("o termo digitado não confere. Nada foi apagado.")

            # `conferir_extracao` não é chamada aqui de propósito: ela existe para
            # o worker, que recebe termo e data de FORA (do pedido na fila) e
            # precisa provar que batem com o banco. No CLI o alvo veio da listagem
            # do próprio banco — conferi-lo contra ele mesmo seria tautológico.
            # A proteção que vale aqui é a confirmação digitada, acima.
            pend = contar_pendencias(con, alvo["id"])
            recente = era_a_mais_recente(con, alvo["id"])
            apagadas = apagar_extracao(con, alvo["id"])
            print("\n  " + relatorio(alvo["termo"], alvo["id"], apagadas, pend, recente))

        if args.compactar:
            if banco_em_uso(con):
                raise _falhar(_MSG_ESCRITA_EM_ANDAMENTO)
            cabe, precisa, livre = espaco_para_vacuum(caminho)
            if not cabe:
                raise _falhar(f"espaço insuficiente: precisa de {precisa/1048576:.0f} MB "
                              f"livres, há {livre/1048576:.0f} MB.")
            print("\n  Compactando (o banco fica travado durante a operação)...")
            antes, depois = compactar(con, caminho)
            print(f"  {antes/1048576:.1f} MB → {depois/1048576:.1f} MB "
                  f"(devolvidos {(antes-depois)/1048576:.1f} MB)")
    finally:
        con.close()


if __name__ == "__main__":
    main()
