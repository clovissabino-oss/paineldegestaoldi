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
import json
import os
import sys
from datetime import datetime

import requests

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


def _config():
    """URL + service_role key: env vars primeiro, fallback supabase.json (gitignored)."""
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if (not url or not key):
        caminho = os.path.join(os.path.dirname(os.path.abspath(__file__)), "supabase.json")
        if os.path.exists(caminho):
            with open(caminho, encoding="utf-8") as f:
                j = json.load(f)
            url = url or j.get("url")
            key = key or j.get("service_key")
    if not url or not key:
        raise SystemExit("[sync] Faltam SUPABASE_URL e SUPABASE_SERVICE_KEY "
                         "(ou um supabase.json com {url, service_key}).")
    return url.rstrip("/"), key


def esta_configurado():
    if os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_KEY"):
        return True
    return os.path.exists(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "supabase.json"))


def _headers(key, prefer=None):
    h = {"apikey": key, "Authorization": f"Bearer {key}",
         "Content-Type": "application/json"}
    if prefer:
        h["Prefer"] = prefer
    return h


def enviar(rows, url=None, key=None):
    """Upsert no Supabase com visibilidade atômica (pronto=false → filhos → pronto=true)."""
    if url is None or key is None:
        url, key = _config()
    rest = f"{url}/rest/v1"

    # ping: falha na cara ANTES de escrever se a credencial estiver errada
    png = requests.get(f"{rest}/snapshot?select=id&limit=1", headers=_headers(key), timeout=30)
    png.raise_for_status()

    # 1. upsert do snapshot (pronto=false), devolve o id
    corpo = {**rows["snapshot"], "pronto": False,
             "sincronizado_em": datetime.now().isoformat(timespec="seconds")}
    r = requests.post(f"{rest}/snapshot", headers=_headers(
        key, "resolution=merge-duplicates,return=representation"),
        params={"on_conflict": "termo,extracao_local"}, json=corpo, timeout=60)
    r.raise_for_status()
    sid = r.json()[0]["id"]

    # 2. limpa filhos desse snapshot (re-run idempotente)
    for tab in ("avaliacao_curso", "pendencia_resumo"):
        d = requests.delete(f"{rest}/{tab}", headers=_headers(key),
                            params={"snapshot_id": f"eq.{sid}"}, timeout=60)
        d.raise_for_status()

    # 3. insere os filhos
    avals = [{"snapshot_id": sid, **a} for a in rows["avaliacoes"]]
    if avals:
        requests.post(f"{rest}/avaliacao_curso", headers=_headers(key),
                      json=avals, timeout=120).raise_for_status()
    pend = [{"snapshot_id": sid, **p} for p in rows["pendencias"]]
    if pend:
        requests.post(f"{rest}/pendencia_resumo", headers=_headers(key),
                      json=pend, timeout=60).raise_for_status()

    # 4. marca pronto=true → só agora a view snapshot_atual enxerga
    requests.patch(f"{rest}/snapshot", headers=_headers(key),
                   params={"id": f"eq.{sid}"}, json={"pronto": True},
                   timeout=60).raise_for_status()
    return sid


def main():
    import banco_conteudo
    import extrator_ldi
    parser = argparse.ArgumentParser(description="Publica o snapshot mais recente no Supabase")
    parser.add_argument("--termo", help="guarda: recusa se o snapshot mais recente não for deste termo")
    args = parser.parse_args()

    caminho = os.path.join(extrator_ldi.PASTA_APP,
                           extrator_ldi.carregar_config()["pasta_saida"], "conteudo.db")
    con = banco_conteudo.abrir(caminho)
    try:
        rows = montar_payload(con)
    finally:
        con.close()
    if rows is None:
        raise SystemExit("[sync] Base sem coletas — rode o coletor primeiro.")
    if args.termo and rows["snapshot"]["termo"] != args.termo:
        raise SystemExit(f"[sync] Snapshot mais recente é '{rows['snapshot']['termo']}', "
                         f"não '{args.termo}'. Colete '{args.termo}' antes.")
    sid = enviar(rows)
    print(f"[sync] snapshot {sid} publicado: {len(rows['avaliacoes'])} cursos, "
          f"{len(rows['pendencias'])} linhas de pendência.")


if __name__ == "__main__":
    main()
