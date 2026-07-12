# -*- coding: utf-8 -*-
"""
============================================================
 SYNC SUPABASE — publica o snapshot mais recente do conteudo.db
 no Supabase (Postgres) para o app web de leitura consumir.
 Só LÊ o conteudo.db e REUSA a agregação do painel.py — não
 toca na coleta. Spec: docs/superpowers/specs/2026-07-12-*.md

 Uso:  py sync_supabase.py [--termo BACEN]
============================================================
"""
import argparse
import os
import sys

import painel

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def montar_payload(con):
    """Monta as linhas de upsert a partir do snapshot mais recente do conteudo.db.

    Devolve None se a base ainda não tem coletas. A agregação é a MESMA do
    painel.py (garantia de paridade com a tela aprovada)."""
    ext = con.execute("SELECT * FROM extracoes ORDER BY id DESC LIMIT 1").fetchone()
    if ext is None:
        return None
    depara = painel._depara()
    cursos = con.execute(
        "SELECT c.curso_id, c.nome, c.autores FROM cursos c WHERE c.extracao_id=? "
        "AND EXISTS (SELECT 1 FROM aulas a WHERE a.extracao_id=c.extracao_id "
        "AND a.curso_id=c.curso_id) ORDER BY c.nome", (ext["id"],)).fetchall()
    avaliacoes = [{
        "curso_id": c["curso_id"],
        "curso_nome": c["nome"],
        "autores": c["autores"] or "",
        "payload": painel.dados_avaliacao(con, c["curso_id"], depara=depara),
    } for c in cursos]
    pend = con.execute(
        "SELECT severidade, regra, COUNT(*) FROM pendencias "
        "WHERE status IN ('nova','enviada') GROUP BY severidade, regra").fetchall()
    return {
        "snapshot": {
            "termo": ext["termo"], "extracao_local": ext["id"],
            "status": ext["status"], "iniciada_em": ext["iniciada_em"],
            "resumo": painel.dados_do_snapshot(con),
        },
        "avaliacoes": avaliacoes,
        "pendencias": [{"severidade": r[0], "regra": r[1], "abertas": r[2]} for r in pend],
    }
