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
import gzip
import json
import os
import re
import sys
import threading
import webbrowser
from datetime import datetime

from flask import Flask, Response, request

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


def dados_do_snapshot(con, tipo="curso"):
    """Agrega o snapshot mais recente DO UNIVERSO pedido ('curso' ou 'mb').

    O filtro por tipo não é decoração: sem ele, coletar um Material Base faria o
    painel de cursos passar a mostrar o MB, que é a coleta de id mais alto."""
    ext = con.execute(
        "SELECT * FROM extracoes WHERE COALESCE(tipo,'curso')=? "
        "ORDER BY id DESC LIMIT 1", (tipo,)).fetchone()
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
    resultado = {
        "extracao": {"id": e, "termo": ext["termo"], "iniciada_em": ext["iniciada_em"],
                     "status": ext["status"],
                     "erros": len(json.loads(ext["erros_json"] or "{}")),
                     "tipo": ext["tipo"] or "curso",
                     "professor_nome": ext["professor_nome"] or "",
                     "disciplina": ext["disciplina"] or "",
                     "capitulos_ocultos": ext["capitulos_ocultos"] or 0},
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
            "itens_total": um("SELECT COUNT(*) FROM aulas WHERE extracao_id=? "
                              "AND vinculado_mb IS NOT NULL", e),
            "itens_mb": um("SELECT COUNT(*) FROM aulas WHERE extracao_id=? "
                           "AND vinculado_mb=1", e),
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
            "aulas_com_item_fora_mb": um(
                "SELECT COUNT(*) FROM (SELECT capitulo_id FROM aulas "
                "WHERE extracao_id=? AND vinculado_mb=0 GROUP BY curso_id, capitulo_id)", e),
        },
        "tipos": tipos,
        "cursos": cursos,
    }
    if (ext["tipo"] or "curso") == "mb":
        resultado["cobertura"] = cobertura_mb(con, e)
    return resultado


def cobertura_mb(con, extracao_id):
    """Quanto do Material Base chega de fato a um curso.

    Compara contra a coleta MAIS RECENTE de cada curso do banco (universo 'curso').
    Devolve também quantos cursos entraram na comparação — sem isso o percentual
    mente: 35% contra um único concurso não é 35% do catálogo.
    """
    itens_mb = con.execute(
        "SELECT COUNT(DISTINCT item_id) FROM aulas WHERE extracao_id=?",
        (extracao_id,)).fetchone()[0] or 0
    ultimas = con.execute(
        "SELECT a.curso_id, MAX(a.extracao_id) FROM aulas a "
        "JOIN extracoes x ON x.id = a.extracao_id "
        "WHERE COALESCE(x.tipo,'curso')='curso' GROUP BY a.curso_id").fetchall()
    if not ultimas:
        return {"itens_mb": itens_mb, "itens_em_curso": 0, "cursos_comparados": 0}
    pares = [(cid, eid) for cid, eid in ultimas]
    marcas = " OR ".join(["(a.curso_id=? AND a.extracao_id=?)"] * len(pares))
    valores = [v for par in pares for v in par]
    em_curso = con.execute(
        "SELECT COUNT(*) FROM (SELECT DISTINCT item_id FROM aulas WHERE extracao_id=?) m "
        f"WHERE m.item_id IN (SELECT DISTINCT a.item_id FROM aulas a WHERE {marcas})",
        (extracao_id, *valores)).fetchone()[0] or 0
    return {"itens_mb": itens_mb, "itens_em_curso": em_curso,
            "cursos_comparados": len(pares)}


_DEPARA = {"cache": None, "carregado": False}


def _depara():
    """Cache do de→para do Metabase (gravação real), carregado 1× por processo."""
    if not _DEPARA["carregado"]:
        _DEPARA["carregado"] = True
        caminho = os.path.join(PASTA_APP, "saida", "metabase_depara.json.gz")
        if os.path.exists(caminho):
            with gzip.open(caminho, "rt", encoding="utf-8") as f:
                _DEPARA["cache"] = json.load(f)
    return _DEPARA["cache"]


_RE_NUM_NOME = re.compile(r"^\s*(\d+)")


def _chave_path(path):
    """'13.1' -> (13, 1). Devolve () quando não há nenhum componente numérico.

    A ordem do LDI vem daqui: `capitulos.ordem` é zero em toda a base (a API manda
    order_index=0), então o path da aula é a única fonte real de posição — e ele é
    relativo ao curso (o mesmo item tem path diferente em cada pacote).
    """
    partes = [p.strip() for p in str(path or "").split(".") if p.strip() != ""]
    if not any(p.isdigit() for p in partes):
        return ()
    return tuple(int(p) if p.isdigit() else 0 for p in partes)


def _chave_capitulo(paths, nome):
    """Ordem do capítulo: menor path entre os itens; sem itens, o número do nome;
    sem nada disso, vai para o fim em ordem alfabética. Nunca lança."""
    nm = (nome or "").strip().lower()
    chaves = [k for k in (_chave_path(p) for p in paths) if k]
    if chaves:
        return (0, min(chaves), nm)
    achado = _RE_NUM_NOME.match(nome or "")
    if achado:
        return (0, (int(achado.group(1)),), nm)
    return (1, (), nm)


def _chave_item(path, nome):
    """Ordem do item dentro do capítulo; sem path utilizável, vai para o fim."""
    nm = (nome or "").strip().lower()
    k = _chave_path(path)
    return (0, k, nm) if k else (1, (), nm)


def _num_capitulo(chave):
    """Numeração exibida do capítulo: '13'."""
    return str(chave[1][0]) if chave[0] == 0 and chave[1] else ""


def _num_item(chave):
    """Numeração exibida do item: '13.1'."""
    return ".".join(str(x) for x in chave[1]) if chave[0] == 0 and chave[1] else ""


_CONTADORES = ("q_emb", "q_txt", "itens_mb", "itens_total", "q_ate", "q_meio", "q_novo",
               "q_com_ano", "sol_texto", "sol_video", "vids", "dur", "v_com_data",
               "v_ate", "v_meio", "v_novo")


def _metricas_zeradas(nome, num, aulas=1):
    """Linha da planilha de avaliação. Capítulo e item usam o MESMO formato — o item é
    uma linha com aulas=1, o que deixa tela e CSV desenharem os dois níveis igual."""
    m = {"nome": nome, "num": num, "aulas": aulas, "bancas": {}}
    m.update({k: 0 for k in _CONTADORES})
    return m


def _acumular(m, b, depara, corte_crit, corte_aten):
    """Aplica um bloco sobre uma linha de métricas."""
    def faixa(pref, ano):
        m["q_com_ano" if pref == "q" else "v_com_data"] += 1
        if ano <= corte_crit:
            m[f"{pref}_ate"] += 1
        elif ano <= corte_aten:
            m[f"{pref}_meio"] += 1
        else:
            m[f"{pref}_novo"] += 1

    if b["tipo"] == "question":
        m["q_emb"] += 1
        m["sol_texto"] += b["tem_solucao"] or 0
        m["sol_video"] += b["tem_video_solucao"] or 0
        if b["banca"]:
            m["bancas"][b["banca"]] = m["bancas"].get(b["banca"], 0) + 1
        if b["ano"]:
            faixa("q", b["ano"])
    elif b["tipo"] == "tiptap" and (b["qtd_questoes_texto"] or 0) > 0:
        m["q_txt"] += b["qtd_questoes_texto"]
        for ref in (json.loads(b["meta"] or "{}").get("questoes_texto") or []):
            if ref.get("banca"):
                m["bancas"][ref["banca"]] = m["bancas"].get(ref["banca"], 0) + 1
            if ref.get("ano"):
                faixa("q", ref["ano"])
    elif b["tipo"] in ("videoMyDocuments", "cast", "youtube"):
        m["vids"] += 1
        m["dur"] += b["duracao_seg"] or 0
        data = ((depara or {}).get(b["video_id_antigo"]) or {}).get("data") or ""
        if data[:4].isdigit():
            faixa("v", int(data[:4]))


def _somar(destino, origem):
    """Soma uma linha na outra: números somam, mapa de bancas mescla."""
    for k in _CONTADORES:
        destino[k] += origem[k]
    for banca, n in origem["bancas"].items():
        destino["bancas"][banca] = destino["bancas"].get(banca, 0) + n


def dados_avaliacao(con, curso_id, depara=None):
    """Planilha de avaliação por capítulo do LDI (formato aprovado — mockup v6)."""
    e = con.execute("SELECT MAX(extracao_id) FROM cursos WHERE curso_id=?",
                    (curso_id,)).fetchone()[0]
    curso = con.execute("SELECT nome, autores FROM cursos WHERE extracao_id=? AND curso_id=?",
                        (e, curso_id)).fetchone()
    ano_atual = datetime.now().year
    corte_crit, corte_aten = ano_atual - 6, ano_atual - 3

    caps = []
    for cap in con.execute("SELECT capitulo_id, nome FROM capitulos "
                           "WHERE extracao_id=? AND curso_id=?", (e, curso_id)):
        linhas = con.execute(
            "SELECT item_id, nome, path, vinculado_mb FROM aulas "
            "WHERE extracao_id=? AND curso_id=? AND capitulo_id=?",
            (e, curso_id, cap["capitulo_id"])).fetchall()
        chave_cap = _chave_capitulo([r["path"] for r in linhas], cap["nome"])

        itens, por_id = [], {}
        for r in linhas:
            chave = _chave_item(r["path"], r["nome"])
            m = _metricas_zeradas(r["nome"] or "", _num_item(chave))
            m["_chave"] = chave
            if r["vinculado_mb"] is not None:
                m["itens_total"] = 1
                m["itens_mb"] = 1 if r["vinculado_mb"] else 0
            itens.append(m)
            por_id[r["item_id"]] = m

        if por_id:
            # UMA consulta por capítulo (como antes) — os baldes são separados aqui.
            marks = ",".join("?" * len(por_id))
            for b in con.execute(
                    f"SELECT item_id, tipo, banca, ano, tem_solucao, tem_video_solucao, "
                    f"video_id_antigo, duracao_seg, qtd_questoes_texto, meta FROM blocos "
                    f"WHERE extracao_id=? AND item_id IN ({marks})", (e, *por_id)):
                m = por_id.get(b["item_id"])
                if m is not None:
                    _acumular(m, b, depara, corte_crit, corte_aten)

        itens.sort(key=lambda m: m["_chave"])
        c = _metricas_zeradas(cap["nome"] or "", _num_capitulo(chave_cap), aulas=len(itens))
        for m in itens:
            _somar(c, m)
        c["_chave"] = chave_cap
        c["itens"] = [{k: v for k, v in m.items() if k != "_chave"} for m in itens]
        caps.append(c)
    caps.sort(key=lambda c: c["_chave"])
    for c in caps:
        c.pop("_chave")
    return {"curso": curso["nome"], "autores": curso["autores"] or "", "capitulos": caps}


def _html():
    # embutida no exe via --add-data (mesmo padrão da ui.html do Visualizador)
    caminho = os.path.join(getattr(sys, "_MEIPASS", PASTA_APP), "painel.html")
    with open(caminho, encoding="utf-8") as f:
        return f.read()


app = Flask(__name__)


@app.route("/")
def index():
    universo = "mb" if request.args.get("universo") == "mb" else "curso"
    con = banco_conteudo.abrir(caminho_banco())
    try:
        dados = dados_do_snapshot(con, tipo=universo)
    finally:
        con.close()
    if dados is None:
        vazio = ("Nenhum Material Base coletado ainda.</h1>"
                 "<p>Rode <code>py coletor_ldi.py --mb &lt;id do MB&gt;</code>"
                 if universo == "mb" else
                 "Sem coletas na base ainda.</h1>"
                 "<p>Rode <code>py coletor_ldi.py --termo SEU_CONCURSO</code>")
        return Response(f"<h1>{vazio} e recarregue esta página.</p>", mimetype="text/html")
    html = _html().replace("__DADOS__", json.dumps(dados, ensure_ascii=False))
    return Response(html, mimetype="text/html")


@app.route("/avaliacao")
def avaliacao():
    caminho = os.path.join(getattr(sys, "_MEIPASS", PASTA_APP), "avaliacao.html")
    with open(caminho, encoding="utf-8") as f:
        return Response(f.read(), mimetype="text/html")


@app.route("/api/cursos")
def api_cursos():
    universo = "mb" if request.args.get("universo") == "mb" else "curso"
    con = banco_conteudo.abrir(caminho_banco())
    try:
        r = con.execute("SELECT MAX(id) FROM extracoes "
                        "WHERE COALESCE(tipo,'curso')=?", (universo,)).fetchone()
        e = r[0] or 0
        rows = [dict(r) for r in con.execute(
            "SELECT c.curso_id, c.nome, c.autores FROM cursos c WHERE c.extracao_id=? "
            "AND EXISTS (SELECT 1 FROM aulas a WHERE a.extracao_id=c.extracao_id "
            "AND a.curso_id=c.curso_id) ORDER BY c.nome", (e,))]
    finally:
        con.close()
    return {"data": rows}


@app.route("/api/avaliacao")
def api_avaliacao():
    con = banco_conteudo.abrir(caminho_banco())
    try:
        dados = dados_avaliacao(con, request.args.get("curso_id", ""), depara=_depara())
    finally:
        con.close()
    return {"data": dados}


@app.route("/api/pendencias/resumo")
def api_pendencias_resumo():
    con = banco_conteudo.abrir(caminho_banco())
    try:
        rows = con.execute("SELECT severidade, regra, COUNT(*) FROM pendencias "
                           "WHERE status IN ('nova','enviada') GROUP BY severidade, regra")
        resumo = [dict(severidade=r[0], regra=r[1], abertas=r[2]) for r in rows]
    finally:
        con.close()
    return {"data": resumo}


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
