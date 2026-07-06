# -*- coding: utf-8 -*-
"""
============================================================
 PAINEL DE CONTEÚDO — preview do Inventário (fase 2)
 Servidor Flask (porta 8766) que lê SOMENTE saida\\conteudo.db
 (populada pelo coletor_ldi.py) — nunca chama a API do BO.
 Serve a painel.html com os dados do snapshot mais recente.

 Uso:  py painel.py [--sem-navegador]
============================================================
"""
import argparse
import json
import os
import sys
import threading
import webbrowser

from flask import Flask, Response

import banco_conteudo

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PASTA_APP = os.path.dirname(os.path.abspath(sys.argv[0]))
PORTA = 8766

_ROTULOS_TIPO = {"question": "Questões", "tiptap": "Textos (tiptap)",
                 "videoMyDocuments": "Vídeos", "pdfMyDocuments": "PDFs",
                 "cast": "Casts", "youtube": "YouTube"}


def caminho_banco():
    import extrator_ldi
    cfg = extrator_ldi.carregar_config()
    return os.path.join(PASTA_APP, cfg["pasta_saida"], "conteudo.db")


def dados_do_snapshot(con):
    """Agrega o snapshot mais recente da base num dict pronto para a tela.
    Devolve None se ainda não houver coleta."""
    ext = con.execute("SELECT * FROM extracoes ORDER BY id DESC LIMIT 1").fetchone()
    if ext is None:
        return None
    e = ext["id"]

    def um(sql, *p):
        return con.execute(sql, p).fetchone()[0] or 0

    tipos = [[_ROTULOS_TIPO.get(r[0], r[0] or "?"), r[1]] for r in con.execute(
        "SELECT tipo, COUNT(*) FROM blocos WHERE extracao_id=? "
        "GROUP BY tipo ORDER BY 2 DESC", (e,))]
    cursos = [dict(r) for r in con.execute(
        "SELECT c.nome, c.autores, COUNT(a.item_id) aulas, "
        "       SUM(a.qtd_videos) videos, SUM(a.qtd_questoes) questoes, "
        "       SUM(a.qtd_textos) textos, SUM(a.qtd_pdfs) pdfs "
        "FROM cursos c JOIN aulas a "
        "  ON a.extracao_id = c.extracao_id AND a.curso_id = c.curso_id "
        "WHERE c.extracao_id=? GROUP BY c.curso_id ORDER BY questoes DESC", (e,))]
    q_unicas = um("SELECT COUNT(*) FROM blocos WHERE extracao_id=? AND tipo='question'", e)
    return {
        "extracao": {"id": e, "termo": ext["termo"], "iniciada_em": ext["iniciada_em"],
                     "status": ext["status"],
                     "erros": len(json.loads(ext["erros_json"] or "{}"))},
        "kpis": {
            "cursos_total": um("SELECT COUNT(*) FROM cursos WHERE extracao_id=?", e),
            "cursos_com_aulas": len(cursos),
            "aulas_unicas": um("SELECT COUNT(DISTINCT item_id) FROM aulas WHERE extracao_id=?", e),
            "vinculos": um("SELECT COUNT(*) FROM aulas WHERE extracao_id=?", e),
            "blocos": um("SELECT COUNT(*) FROM blocos WHERE extracao_id=?", e),
            "questoes": q_unicas,
            "textos": um("SELECT COUNT(*) FROM blocos WHERE extracao_id=? AND tipo='tiptap'", e),
            "videos": um("SELECT COUNT(*) FROM blocos WHERE extracao_id=? "
                         "AND tipo IN ('videoMyDocuments','cast','youtube')", e),
            "casts": um("SELECT COUNT(*) FROM blocos WHERE extracao_id=? AND tipo='cast'", e),
        },
        "achados": {
            "q_unicas": q_unicas,
            "q_sem_solucao": um("SELECT COUNT(*) FROM blocos WHERE extracao_id=? "
                                "AND tipo='question' AND tem_solucao=0", e),
            "q_com_video": um("SELECT COUNT(*) FROM blocos WHERE extracao_id=? "
                              "AND tipo='question' AND tem_video_solucao=1", e),
            "v_sem_id": um("SELECT COUNT(*) FROM blocos WHERE extracao_id=? "
                           "AND tipo='videoMyDocuments' AND video_id_antigo=''", e),
            "aulas_vazias": um("SELECT COUNT(*) FROM aulas_coletadas "
                               "WHERE extracao_id=? AND qtd_blocos=0", e),
            "rascunhos": um("SELECT COUNT(*) FROM blocos WHERE extracao_id=? AND rascunho=1", e),
            "cursos_sem_video": sum(1 for c in cursos if not c["videos"]),
            "cursos_sem_pdf": sum(1 for c in cursos if not c["pdfs"]),
        },
        "tipos": tipos,
        "cursos": cursos,
    }


def _html():
    # embutida no exe via --add-data (mesmo padrão da ui.html do Visualizador)
    caminho = os.path.join(getattr(sys, "_MEIPASS", PASTA_APP), "painel.html")
    with open(caminho, encoding="utf-8") as f:
        return f.read()


app = Flask(__name__)


@app.route("/")
def index():
    con = banco_conteudo.abrir(caminho_banco())
    try:
        dados = dados_do_snapshot(con)
    finally:
        con.close()
    if dados is None:
        return Response("<h1>Sem coletas na base ainda.</h1>"
                        "<p>Rode <code>py coletor_ldi.py --termo SEU_CONCURSO</code> "
                        "e recarregue esta página.</p>", mimetype="text/html")
    html = _html().replace("__DADOS__", json.dumps(dados, ensure_ascii=False))
    return Response(html, mimetype="text/html")


def main():
    parser = argparse.ArgumentParser(description="Painel de Conteúdo (preview do Inventário)")
    parser.add_argument("--sem-navegador", action="store_true",
                        help="não abre o navegador automaticamente")
    args = parser.parse_args()
    url = f"http://127.0.0.1:{PORTA}"
    print("=" * 60)
    print(f" PAINEL DE CONTEÚDO  |  {url}  |  banco: {caminho_banco()}")
    print("=" * 60)
    if not args.sem_navegador:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=PORTA, debug=False)


if __name__ == "__main__":
    main()
