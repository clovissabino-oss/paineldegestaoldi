# -*- coding: utf-8 -*-
"""Base de conteúdo do BO (saida\\conteudo.db): schema + escrita/leitura.

Princípio: snapshot é a unidade — cada rodada do coletor grava suas linhas
com extracao_id; nada é sobrescrito (spec 2026-07-05, seção Modelo de dados).
"""
import json
import os
import sqlite3
from datetime import datetime

_SCHEMA = """
CREATE TABLE IF NOT EXISTS extracoes(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  termo TEXT NOT NULL, vertical TEXT NOT NULL,
  iniciada_em TEXT NOT NULL, concluida_em TEXT,
  status TEXT NOT NULL DEFAULT 'em_andamento',
  total_cursos INTEGER DEFAULT 0, total_aulas INTEGER DEFAULT 0,
  total_blocos INTEGER DEFAULT 0, erros_json TEXT DEFAULT '{}');
CREATE TABLE IF NOT EXISTS cursos(
  extracao_id INTEGER NOT NULL, curso_id TEXT NOT NULL,
  nome TEXT, publicado INTEGER, autores TEXT, criado_em_bo TEXT,
  PRIMARY KEY(extracao_id, curso_id));
CREATE TABLE IF NOT EXISTS capitulos(
  extracao_id INTEGER NOT NULL, curso_id TEXT NOT NULL, capitulo_id TEXT NOT NULL,
  nome TEXT, ordem INTEGER, versao TEXT, publicado_em TEXT,
  PRIMARY KEY(extracao_id, curso_id, capitulo_id));
CREATE TABLE IF NOT EXISTS aulas(
  extracao_id INTEGER NOT NULL, curso_id TEXT NOT NULL,
  capitulo_id TEXT NOT NULL, item_id TEXT NOT NULL,
  nome TEXT, path TEXT, atualizada_em TEXT,
  qtd_videos INTEGER DEFAULT 0, qtd_questoes INTEGER DEFAULT 0,
  qtd_textos INTEGER DEFAULT 0, qtd_pdfs INTEGER DEFAULT 0,
  qtd_casts INTEGER DEFAULT 0, qtd_outros INTEGER DEFAULT 0,
  PRIMARY KEY(extracao_id, curso_id, capitulo_id, item_id));
CREATE TABLE IF NOT EXISTS aulas_coletadas(
  extracao_id INTEGER NOT NULL, item_id TEXT NOT NULL,
  qtd_blocos INTEGER DEFAULT 0, coletada_em TEXT,
  PRIMARY KEY(extracao_id, item_id));
CREATE TABLE IF NOT EXISTS blocos(
  extracao_id INTEGER NOT NULL, item_id TEXT NOT NULL, bloco_id TEXT NOT NULL,
  tipo TEXT, ordem INTEGER, ativo INTEGER, rascunho INTEGER, titulo TEXT,
  questao_id TEXT, resposta_tipo TEXT, tem_solucao INTEGER, tem_video_solucao INTEGER,
  video_id_antigo TEXT, duracao_seg INTEGER, tamanho_texto INTEGER,
  banca TEXT, ano INTEGER, qtd_questoes_texto INTEGER, meta TEXT,
  PRIMARY KEY(extracao_id, item_id, bloco_id));
CREATE TABLE IF NOT EXISTS pendencias(
  chave TEXT PRIMARY KEY,
  regra TEXT NOT NULL, severidade TEXT NOT NULL,
  curso_id TEXT NOT NULL, item_id TEXT DEFAULT '', bloco_id TEXT DEFAULT '',
  descricao TEXT,
  status TEXT NOT NULL DEFAULT 'nova',
  extracao_id_criada INTEGER, extracao_id_ultima INTEGER,
  criada_em TEXT, resolvida_em TEXT);
CREATE INDEX IF NOT EXISTS ix_pend_status ON pendencias(status, severidade);
CREATE TABLE IF NOT EXISTS acionamentos(
  chave_pendencia TEXT NOT NULL, status TEXT NOT NULL,
  observacao TEXT DEFAULT '', registrado_em TEXT);
CREATE INDEX IF NOT EXISTS ix_blocos_extracao ON blocos(extracao_id);
CREATE INDEX IF NOT EXISTS ix_blocos_tipo ON blocos(extracao_id, tipo);
CREATE INDEX IF NOT EXISTS ix_blocos_questao ON blocos(questao_id);
CREATE INDEX IF NOT EXISTS ix_blocos_vid_antigo ON blocos(video_id_antigo);
"""

_COLS_BLOCO = ("bloco_id", "tipo", "ordem", "ativo", "rascunho", "titulo",
               "questao_id", "resposta_tipo", "tem_solucao", "tem_video_solucao",
               "video_id_antigo", "duracao_seg", "tamanho_texto",
               "banca", "ano", "qtd_questoes_texto")


def _agora():
    return datetime.now().isoformat(timespec="seconds")  # data LOCAL (convenção)


def abrir(caminho):
    os.makedirs(os.path.dirname(os.path.abspath(caminho)), exist_ok=True)
    con = sqlite3.connect(caminho)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(_SCHEMA)
    # migração de bases anteriores à v1.1 (idempotente)
    for sql in ("ALTER TABLE blocos ADD COLUMN banca TEXT",
                "ALTER TABLE blocos ADD COLUMN ano INTEGER",
                "ALTER TABLE blocos ADD COLUMN qtd_questoes_texto INTEGER"):
        try:
            con.execute(sql)
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e):
                raise
    con.execute("CREATE INDEX IF NOT EXISTS ix_blocos_item ON blocos(item_id)")
    return con


def iniciar_extracao(con, termo, vertical):
    with con:
        cur = con.execute(
            "INSERT INTO extracoes(termo, vertical, iniciada_em) VALUES(?,?,?)",
            (termo, vertical, _agora()))
    return cur.lastrowid


def gravar_arvore(con, extracao_id, cursos):
    import parse_blocos
    itens = set()
    with con:
        for c in cursos:
            con.execute(
                "INSERT OR REPLACE INTO cursos VALUES(?,?,?,?,?,?)",
                (extracao_id, c.get("id", ""), c.get("name", ""),
                 1 if c.get("published") else 0,
                 parse_blocos.autores_do_curso(c), c.get("created_at", "")))
            for cap in (c.get("content_tree_cache") or []):
                con.execute(
                    "INSERT OR REPLACE INTO capitulos VALUES(?,?,?,?,?,?,?)",
                    (extracao_id, c.get("id", ""), cap.get("chapter_id", ""),
                     cap.get("name", ""), cap.get("order_index"),
                     str(cap.get("chapter_version", "")), cap.get("published_at") or ""))
                for item in (cap.get("items") or []):
                    q = parse_blocos.contagens_da_aula(item)
                    con.execute(
                        "INSERT OR REPLACE INTO aulas VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (extracao_id, c.get("id", ""), cap.get("chapter_id", ""),
                         item.get("item_id", ""),
                         item.get("name") or item.get("title") or "",
                         item.get("path", ""), item.get("updated_at", ""),
                         q["qtd_videos"], q["qtd_questoes"], q["qtd_textos"],
                         q["qtd_pdfs"], q["qtd_casts"], q["qtd_outros"]))
                    itens.add(item.get("item_id", ""))
    return len(cursos), len(itens)


def aulas_pendentes(con, extracao_id):
    rows = con.execute(
        "SELECT DISTINCT a.item_id FROM aulas a "
        "LEFT JOIN aulas_coletadas ac "
        "  ON ac.extracao_id = a.extracao_id AND ac.item_id = a.item_id "
        "WHERE a.extracao_id = ? AND ac.item_id IS NULL", (extracao_id,))
    return [r[0] for r in rows]


def gravar_blocos_da_aula(con, extracao_id, item_id, blocos):
    with con:  # 1 aula = 1 transação (retomada segura)
        for b in blocos:
            con.execute(
                f"INSERT OR REPLACE INTO blocos(extracao_id, item_id, "
                f"{', '.join(_COLS_BLOCO)}, meta) "
                f"VALUES({','.join('?' * (len(_COLS_BLOCO) + 3))})",
                (extracao_id, item_id, *[b.get(c) for c in _COLS_BLOCO],
                 json.dumps(b.get("meta") or {}, ensure_ascii=False)))
        con.execute(
            "INSERT OR REPLACE INTO aulas_coletadas VALUES(?,?,?,?)",
            (extracao_id, item_id, len(blocos), _agora()))


def extracao_em_andamento(con, termo):
    """A extração retomável (em andamento ou parcial) mais recente do termo."""
    return con.execute(
        "SELECT * FROM extracoes WHERE termo = ? "
        "AND status IN ('em_andamento','parcial') "
        "ORDER BY id DESC LIMIT 1", (termo,)).fetchone()


def finalizar_extracao(con, extracao_id, erros):
    pendentes = aulas_pendentes(con, extracao_id)
    status = "parcial" if (erros or pendentes) else "completa"
    tot = con.execute(
        "SELECT (SELECT COUNT(*) FROM cursos WHERE extracao_id = :e),"
        "       (SELECT COUNT(*) FROM aulas_coletadas WHERE extracao_id = :e),"
        "       (SELECT COUNT(*) FROM blocos WHERE extracao_id = :e)",
        {"e": extracao_id}).fetchone()
    with con:
        con.execute(
            "UPDATE extracoes SET concluida_em=?, status=?, total_cursos=?, "
            "total_aulas=?, total_blocos=?, erros_json=? WHERE id=?",
            (_agora(), status, tot[0], tot[1], tot[2],
             json.dumps(erros, ensure_ascii=False), extracao_id))
    return status
