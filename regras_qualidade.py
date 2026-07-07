# -*- coding: utf-8 -*-
"""Motor de qualidade: catálogo declarativo -> pendências materializadas em conteudo.db.

Regra nova = entrada nova no CATALOGO. Cada achado vira uma linha em `pendencias` com
chave determinística (regra|curso|aula|bloco) — é ela que permite a baixa automática:
no snapshot seguinte, o que não reaparece é resolvido sozinho (spec 2026-07-06).
Roda ao fim de cada coleta ou avulso:
    py regras_qualidade.py [--extracao N]
"""
import argparse
import gzip
import json
import os
import sys
from datetime import datetime

import banco_conteudo

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PASTA_APP = os.path.dirname(os.path.abspath(sys.argv[0]))


def _sql(con, sql, **p):
    return con.execute(sql, p).fetchall()


def q1_questao_sem_solucao(con, e, ctx):
    return [(r[0], r[1], r[2], f"Questão #{r[3]} sem solução cadastrada") for r in _sql(con, """
        SELECT a.curso_id, b.item_id, b.bloco_id, b.questao_id FROM blocos b
        JOIN aulas a ON a.extracao_id = b.extracao_id AND a.item_id = b.item_id
        WHERE b.extracao_id = :e AND b.tipo='question' AND b.tem_solucao = 0""", e=e)]


def q2_questao_desatualizada(con, e, ctx):
    corte_crit = ctx["ano_atual"] - 6      # régua 2/5: > 5 anos = crítica
    corte_aten = ctx["ano_atual"] - 3      # 3-5 anos = atenção
    out = []
    for r in _sql(con, """
        SELECT a.curso_id, b.item_id, b.bloco_id, b.questao_id, b.ano FROM blocos b
        JOIN aulas a ON a.extracao_id = b.extracao_id AND a.item_id = b.item_id
        WHERE b.extracao_id = :e AND b.tipo='question' AND b.ano IS NOT NULL
          AND b.ano <= :corte""", e=e, corte=corte_aten):
        nivel = "crítica" if r[4] <= corte_crit else "atenção"
        out.append((r[0], r[1], r[2],
                    f"Questão #{r[3]} de prova de {r[4]} ({nivel} pela régua 2/5)"))
    return out


def v1_video_envelhecido(con, e, ctx):
    depara = ctx.get("depara")
    if not depara:
        return None  # sem cache do Metabase: regra pulada nesta rodada (não dá baixa)
    corte_crit = ctx["ano_atual"] - 6
    corte_aten = ctx["ano_atual"] - 3
    out = []
    for r in _sql(con, """
        SELECT a.curso_id, b.item_id, b.bloco_id, b.video_id_antigo, b.titulo FROM blocos b
        JOIN aulas a ON a.extracao_id = b.extracao_id AND a.item_id = b.item_id
        WHERE b.extracao_id = :e AND b.tipo='videoMyDocuments' AND b.video_id_antigo <> ''""", e=e):
        data = (depara.get(r[3]) or {}).get("data") or ""
        if not data[:4].isdigit():
            continue
        ano = int(data[:4])
        if ano <= corte_aten:
            nivel = "crítica" if ano <= corte_crit else "atenção"
            out.append((r[0], r[1], r[2],
                        f"Vídeo gravado em {ano} ({nivel} pela régua 2/5): {r[4] or r[3]}"))
    return out


def v2_video_fora_depara(con, e, ctx):
    return [(r[0], r[1], r[2], f"Vídeo sem ID do sistema antigo: {r[3] or '(sem título)'}")
            for r in _sql(con, """
        SELECT a.curso_id, b.item_id, b.bloco_id, b.titulo FROM blocos b
        JOIN aulas a ON a.extracao_id = b.extracao_id AND a.item_id = b.item_id
        WHERE b.extracao_id = :e AND b.tipo='videoMyDocuments' AND b.video_id_antigo = ''""", e=e)]


def c1_curso_sem_aula(con, e, ctx):
    return [(r[0], "", "", f"Curso sem nenhuma aula na árvore: {r[1]}") for r in _sql(con, """
        SELECT curso_id, nome FROM cursos WHERE extracao_id = :e AND curso_id NOT IN
          (SELECT DISTINCT curso_id FROM aulas WHERE extracao_id = :e)""", e=e)]


def a1_aula_sem_questao(con, e, ctx):
    return [(r[0], r[1], "", f"Aula sem nenhuma questão (embedada ou em texto): {r[2]}")
            for r in _sql(con, """
        SELECT a.curso_id, a.item_id, a.nome FROM aulas a
        JOIN aulas_coletadas ac ON ac.extracao_id = a.extracao_id AND ac.item_id = a.item_id
        WHERE a.extracao_id = :e
          AND NOT EXISTS (SELECT 1 FROM blocos b WHERE b.extracao_id = a.extracao_id
                          AND b.item_id = a.item_id
                          AND (b.tipo = 'question' OR COALESCE(b.qtd_questoes_texto, 0) > 0))""",
        e=e)]


def a3_aula_sem_texto(con, e, ctx):
    return [(r[0], r[1], "", f"Aula com texto abaixo de 1.000 caracteres: {r[2]}")
            for r in _sql(con, """
        SELECT a.curso_id, a.item_id, a.nome FROM aulas a
        JOIN aulas_coletadas ac ON ac.extracao_id = a.extracao_id AND ac.item_id = a.item_id
        WHERE a.extracao_id = :e
          AND (SELECT COALESCE(SUM(b.tamanho_texto), 0) FROM blocos b
               WHERE b.extracao_id = a.extracao_id AND b.item_id = a.item_id
                 AND b.tipo = 'tiptap') < 1000""", e=e)]


def b1_bloco_rascunho(con, e, ctx):
    # spec previa ">30 dias", mas a data do bloco não é armazenada; hoje = 0 casos (sentinela)
    return [(r[0], r[1], r[2], f"Bloco em rascunho: {r[3] or r[2]}") for r in _sql(con, """
        SELECT a.curso_id, b.item_id, b.bloco_id, b.titulo FROM blocos b
        JOIN aulas a ON a.extracao_id = b.extracao_id AND a.item_id = b.item_id
        WHERE b.extracao_id = :e AND b.rascunho = 1""", e=e)]


# (id, severidade, função) — A2 "aula sem vídeo" é INFORMATIVA por decisão do Luiz
# (73% das aulas): indicador de tela, não pendência.
CATALOGO = (
    ("Q1", "critica", q1_questao_sem_solucao),
    ("Q2", "atencao", q2_questao_desatualizada),
    ("V1", "atencao", v1_video_envelhecido),
    ("V2", "critica", v2_video_fora_depara),
    ("C1", "atencao", c1_curso_sem_aula),
    ("A1", "atencao", a1_aula_sem_questao),
    ("A3", "atencao", a3_aula_sem_texto),
    ("B1", "atencao", b1_bloco_rascunho),
)


def _agora():
    return datetime.now().isoformat(timespec="seconds")


def avaliar(con, extracao_id, depara=None):
    """Roda o catálogo sobre o snapshot, faz upsert em pendencias + baixa automática."""
    ctx = {"depara": depara, "ano_atual": datetime.now().year}
    achados, puladas = {}, []
    for regra, sev, fn in CATALOGO:
        rows = fn(con, extracao_id, ctx)
        if rows is None:
            puladas.append(regra)
            continue
        for curso_id, item_id, bloco_id, desc in rows:
            chave = f"{regra}|{curso_id}|{item_id}|{bloco_id}"
            achados[chave] = (regra, sev, curso_id, item_id, bloco_id, desc)

    novas = reabertas = resolvidas = 0
    with con:
        existentes = {r["chave"]: r["status"] for r in con.execute(
            "SELECT chave, status FROM pendencias")}
        for chave, (regra, sev, curso_id, item_id, bloco_id, desc) in achados.items():
            status = existentes.get(chave)
            if status is None:
                con.execute(
                    "INSERT INTO pendencias(chave, regra, severidade, curso_id, item_id, "
                    "bloco_id, descricao, status, extracao_id_criada, extracao_id_ultima, "
                    "criada_em) VALUES(?,?,?,?,?,?,?,'nova',?,?,?)",
                    (chave, regra, sev, curso_id, item_id, bloco_id, desc,
                     extracao_id, extracao_id, _agora()))
                novas += 1
            elif status == "resolvida":   # voltou: reabre como nova, com histórico
                con.execute("UPDATE pendencias SET status='nova', resolvida_em=NULL, "
                            "extracao_id_ultima=?, descricao=? WHERE chave=?",
                            (extracao_id, desc, chave))
                con.execute("INSERT INTO acionamentos VALUES(?,?,?,?)",
                            (chave, "nova", "reaberta pela coleta", _agora()))
                reabertas += 1
            elif status in ("nova", "enviada"):
                con.execute("UPDATE pendencias SET extracao_id_ultima=?, descricao=? "
                            "WHERE chave=?", (extracao_id, desc, chave))
            # ignorada: não reabre, não atualiza

        for chave, status in existentes.items():
            regra = chave.split("|", 1)[0]
            if status in ("nova", "enviada") and chave not in achados and regra not in puladas:
                con.execute("UPDATE pendencias SET status='resolvida', resolvida_em=? "
                            "WHERE chave=?", (_agora(), chave))
                con.execute("INSERT INTO acionamentos VALUES(?,?,?,?)",
                            (chave, "resolvida", "baixa automática (sumiu do BO)", _agora()))
                resolvidas += 1

    abertas_por_regra = {r[0]: r[1] for r in con.execute(
        "SELECT regra, COUNT(*) FROM pendencias WHERE status IN ('nova','enviada') "
        "GROUP BY regra")}
    return {"novas": novas, "reabertas": reabertas, "resolvidas": resolvidas,
            "abertas_por_regra": abertas_por_regra}


def carregar_depara():
    caminho = os.path.join(PASTA_APP, "saida", "metabase_depara.json.gz")
    if not os.path.exists(caminho):
        return None
    with gzip.open(caminho, "rt", encoding="utf-8") as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(description="Motor de qualidade (pendências)")
    parser.add_argument("--extracao", type=int, help="id da extração (padrão: a mais recente)")
    args = parser.parse_args()
    con = banco_conteudo.abrir(os.path.join(PASTA_APP, "saida", "conteudo.db"))
    try:
        eid = args.extracao or con.execute(
            "SELECT id FROM extracoes ORDER BY id DESC LIMIT 1").fetchone()[0]
        print(f"Avaliando regras sobre a extração #{eid}...")
        r = avaliar(con, eid, depara=carregar_depara())
        print(f"novas: {r['novas']} | reabertas: {r['reabertas']} | resolvidas: {r['resolvidas']}")
        for regra, qtd in sorted(r["abertas_por_regra"].items()):
            print(f"  {regra}: {qtd} abertas")
    finally:
        con.close()


if __name__ == "__main__":
    main()
