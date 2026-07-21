# -*- coding: utf-8 -*-
"""
============================================================
 COLETOR LDI — Conteúdo completo por concurso (SOMENTE LEITURA)
 Varre TODOS os blocos (questões, textos, PDFs, vídeos...) dos
 cursos de um concurso e grava snapshots de METADADOS em
 saida\\conteudo.db (SQLite). O fluxo de vídeos (extrator_ldi)
 continua intacto — este script é a fundação do Painel de
 Conteúdo (spec docs/superpowers/specs/2026-07-05-*.md).

 Uso:  py coletor_ldi.py [--termo BACEN] [--continuar] [--com-videos] [--agendado]
       --termo       sobrepõe o termo_busca do config.json
       --continuar   retoma a coleta interrompida/parcial mais recente do termo
       --com-videos  além da base, emite o videos_*.json/csv clássico
       --agendado    não pede ENTER no final (p/ Agendador de Tarefas)
============================================================
"""
import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

import banco_conteudo
import extrator_ldi
import parse_blocos

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


class ColetaCancelada(Exception):
    """Sinalizado pelo callback de progresso para abortar a coleta em andamento."""


_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"

def extrair_ids(texto):
    """Aceita UUIDs soltos e/ou URLs do admin (…?id=<uuid>&team_id=…),
    separados por vírgula/espaço/linha. Pega SEMPRE o id= (nunca o team_id=).
    Devolve a lista de UUIDs em minúsculas; levanta se algum token não tiver ID."""
    ids = []
    for tok in re.split(r"[\s,]+", (texto or "").strip()):
        if not tok:
            continue
        m = re.search(rf"[?&]id=({_UUID})", tok)
        if m:
            ids.append(m.group(1).lower())
        elif re.fullmatch(_UUID, tok):
            ids.append(tok.lower())
        else:
            raise extrator_ldi.falha(f"Não achei um ID de curso em: {tok[:60]}")
    if not ids:
        raise extrator_ldi.falha("Nenhum ID de curso informado.")
    return ids


class CookieVencido(SystemExit):
    pass


def baixar_blocos(sessao, item_id, tentativa=1):
    url = f"{extrator_ldi.API}/bo/ldi/blocks?item_id={item_id}"
    try:
        r = sessao.get(url, timeout=60)
    except requests.RequestException as e:
        if tentativa < 4:
            time.sleep(0.7 * tentativa * tentativa)
            return baixar_blocos(sessao, item_id, tentativa + 1)
        raise RuntimeError(f"rede: {e}")
    if r.status_code in (401, 403):
        raise CookieVencido("\n[ERRO] A API respondeu 401/403 — o cookie venceu.\n"
                            "       Atualize o cookie.txt e rode com --continuar.")
    if r.status_code == 429 or r.status_code >= 500:
        if tentativa < 4:
            time.sleep(0.7 * tentativa * tentativa)
            return baixar_blocos(sessao, item_id, tentativa + 1)
        raise RuntimeError(f"HTTP {r.status_code}")
    if not r.ok:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:120]}")
    return r.json().get("data") or []


def _completar_autores(sessao, con, extracao_id, cursos, concorrencia):
    """A listagem devolve só UUIDs em authors; o detalhe do curso traz structured_authors."""
    def detalhe(cid):
        r = sessao.get(f"{extrator_ldi.API}/bo/ldi/courses/{cid}", timeout=60)
        if not r.ok:
            raise RuntimeError(f"HTTP {r.status_code}")
        return cid, (r.json().get("data") or {})

    falhas = 0
    with ThreadPoolExecutor(max_workers=int(concorrencia)) as pool:
        futuros = {pool.submit(detalhe, c.get("id")): c for c in cursos if c.get("id")}
        for fut in as_completed(futuros):
            try:
                cid, d = fut.result()
                nomes = parse_blocos.nomes_dos_autores(d)
                if nomes:
                    with con:
                        con.execute("UPDATE cursos SET autores=? WHERE extracao_id=? AND curso_id=?",
                                    (nomes, extracao_id, cid))
            except Exception:  # enriquecimento: falha pontual não derruba a coleta
                falhas += 1
    if falhas:
        print(f"      ({falhas} cursos sem professor identificado)")


def _baixar_lote(sessao, con, extracao_id, pendentes, concorrencia,
                 videos_por_item=None, progresso=None):
    """Baixa e grava as aulas pendentes; devolve {item_id: erro} das que falharam.

    videos_por_item (opcional): dict a preencher com os blocos brutos de vídeo
    de cada aula (memória pequena) — usado pelo --com-videos.
    progresso (opcional): callable(feito:int, total:int) chamado a cada 20 aulas
    e ao fim; pode levantar ColetaCancelada para abortar a coleta.
    """
    erros, feitos = {}, 0
    with ThreadPoolExecutor(max_workers=int(concorrencia)) as pool:
        futuros = {pool.submit(baixar_blocos, sessao, i): i for i in pendentes}
        for fut in as_completed(futuros):
            item_id = futuros[fut]
            try:
                brutos = fut.result()
                metas = [parse_blocos.meta_do_bloco(b) for b in brutos]
                banco_conteudo.gravar_blocos_da_aula(con, extracao_id, item_id, metas)
                if videos_por_item is not None:
                    videos_por_item[item_id] = [
                        b for b in brutos if b.get("type") in extrator_ldi.TIPOS_VIDEO]
            except SystemExit:
                raise
            except Exception as e:  # falha pontual: registra e segue
                erros[item_id] = str(e)
            feitos += 1
            if feitos % 100 == 0 or feitos == len(pendentes):
                print(f"      ...{feitos}/{len(pendentes)}")
            if progresso and (feitos % 20 == 0 or feitos == len(pendentes)):
                progresso(feitos, len(pendentes))  # pode levantar ColetaCancelada
    return erros


def _emitir_videos(cfg, termo, pasta, tarefas, videos_por_item):
    """Grava o videos_<termo>_<data>.json/csv clássico (formato do extrator)."""
    from datetime import date
    import csv as _csv
    linhas = []
    for curso, cap, item in tarefas:
        achou = False
        for b in videos_por_item.get(item.get("item_id", ""), []):
            linhas.append(extrator_ldi.linha(cfg, curso, cap, item, b))
            achou = True
        if not achou:
            linhas.append(extrator_ldi.linha(cfg, curso, cap, item, None,
                                             "aula sem bloco de video na versao atual"))
    if not linhas:
        return
    termo_arq = re.sub(r"[^\w\-]+", "_", termo)
    base = os.path.join(pasta, f"videos_{termo_arq}_{date.today():%Y-%m-%d}")
    with open(base + ".json", "w", encoding="utf-8") as f:
        json.dump(linhas, f, ensure_ascii=False, indent=1)
    with open(base + ".csv", "w", newline="", encoding="utf-8-sig") as f:
        w = _csv.DictWriter(f, fieldnames=list(linhas[0].keys()),
                            delimiter=";", quoting=_csv.QUOTE_ALL)
        w.writeheader()
        w.writerows(linhas)
    print(f"      vídeos clássico: {base}.json/.csv")


def coletar(cfg, sessao, termo, caminho_banco, continuar=False, com_videos=False,
            ids=None, progresso=None):
    con = banco_conteudo.abrir(caminho_banco)
    try:
        tarefas, videos_por_item = [], ({} if com_videos else None)
        if continuar:
            ext = banco_conteudo.extracao_em_andamento(con, termo)
            if ext is None:
                raise extrator_ldi.falha(
                    f"Nenhuma coleta retomável de \"{termo}\" na base.")
            extracao_id = ext["id"]
            print(f"[1/4] Retomando a coleta #{extracao_id} de \"{termo}\"...")
        else:
            if ids:
                print(f"[1/4] Buscando {len(ids)} curso(s) por ID (rótulo \"{termo}\")...")
                cursos = [c for c in (extrator_ldi.obter_curso(sessao, i) for i in ids) if c]
                if not cursos:
                    raise extrator_ldi.falha("Nenhum curso encontrado para as IDs informadas.")
            else:
                print(f"[1/4] Buscando cursos com \"{termo}\"...")
                cursos = extrator_ldi.listar_cursos(sessao, termo)
                if cfg.get("filtro_local"):
                    rx = re.compile(cfg["filtro_local"], re.I)
                    cursos = [c for c in cursos if rx.search(c.get("name") or "")]
                if not cursos:
                    raise extrator_ldi.falha("Nenhum curso encontrado — confira o termo.")
            extracao_id = banco_conteudo.iniciar_extracao(con, termo, cfg["vertical"])
            n_cursos, n_aulas = banco_conteudo.gravar_arvore(con, extracao_id, cursos)
            print(f"      {n_cursos} cursos, {n_aulas} aulas únicas (snapshot #{extracao_id})")
            print("      buscando professores (detalhe de cada curso)...")
            _completar_autores(sessao, con, extracao_id, cursos, cfg["concorrencia"])
            if com_videos:
                for curso in cursos:
                    for cap in (curso.get("content_tree_cache") or []):
                        for item in (cap.get("items") or []):
                            tarefas.append((curso, cap, item))

        pendentes = banco_conteudo.aulas_pendentes(con, extracao_id)
        print(f"[2/4] {len(pendentes)} aulas a baixar")
        print(f"[3/4] Baixando blocos ({cfg['concorrencia']} por vez)...")
        erros = _baixar_lote(sessao, con, extracao_id, pendentes,
                             cfg["concorrencia"], videos_por_item, progresso)
        if erros:  # 1 rodada de retry
            print(f"      retry de {len(erros)} aulas com falha...")
            erros = _baixar_lote(sessao, con, extracao_id, list(erros),
                                 cfg["concorrencia"], videos_por_item, progresso)

        status = banco_conteudo.finalizar_extracao(con, extracao_id, erros)
        tot = con.execute("SELECT total_aulas, total_blocos FROM extracoes WHERE id=?",
                          (extracao_id,)).fetchone()
        print(f"[4/4] Coleta {status}: {tot[0]} aulas, {tot[1]} blocos"
              + (f" | {len(erros)} aulas com erro (retomável com --continuar)" if erros else ""))
        try:
            import regras_qualidade
            print("      avaliando regras de qualidade...")
            r = regras_qualidade.avaliar(con, extracao_id,
                                         depara=regras_qualidade.carregar_depara())
            print(f"      pendências: {r['novas']} novas, {r['reabertas']} reabertas, "
                  f"{r['resolvidas']} resolvidas")
        except Exception as e:
            print(f"      (regras de qualidade falharam: {e} — rode py regras_qualidade.py)")
        try:
            import sync_supabase
            if sync_supabase.esta_configurado():
                print("      publicando no Supabase...")
                rows = sync_supabase.montar_payload(con)
                if rows:
                    sid = sync_supabase.enviar(rows)
                    print(f"      Supabase: snapshot {sid} publicado.")
            else:
                print("      (Supabase não configurado — pulei o sync; "
                      "rode py sync_supabase.py quando quiser)")
        except Exception as e:  # publicação não pode derrubar a coleta já gravada
            print(f"      (sync com Supabase falhou: {e} — rode py sync_supabase.py)")
        if com_videos and tarefas:
            _emitir_videos(cfg, termo, os.path.dirname(os.path.abspath(caminho_banco)),
                           tarefas, videos_por_item)
        return extracao_id
    finally:
        con.close()


def main():
    parser = argparse.ArgumentParser(
        description="Coletor LDI — conteúdo completo por concurso (somente leitura)")
    parser.add_argument("--termo", help="termo de busca (sobrepõe o config.json)")
    parser.add_argument("--ids", help="coleta cursos por ID do LDI (UUIDs ou URLs do admin, "
                                      "separados por vírgula/espaço); exige --rotulo")
    parser.add_argument("--rotulo", help="nome do concurso sob o qual as --ids aparecem no "
                                         "app (vira o 'termo' do snapshot)")
    parser.add_argument("--continuar", action="store_true",
                        help="retoma a coleta interrompida/parcial mais recente do termo")
    parser.add_argument("--com-videos", action="store_true",
                        help="além da base, emite o videos_*.json/csv clássico")
    parser.add_argument("--agendado", action="store_true", help="não pede ENTER no final")
    args = parser.parse_args()

    cfg = extrator_ldi.carregar_config()
    if args.continuar and args.com_videos:
        raise extrator_ldi.falha("--com-videos não funciona com --continuar "
                                 "(rode uma coleta nova).")
    if args.ids:
        if not args.rotulo:
            raise extrator_ldi.falha("--ids exige --rotulo (o nome do concurso no app).")
        if args.continuar:
            raise extrator_ldi.falha("--ids não combina com --continuar "
                                     "(para retomar, use --termo \"<rótulo>\" --continuar).")
        ids = extrair_ids(args.ids)
        termo = args.rotulo
    else:
        ids = None
        termo = args.termo or cfg["termo_busca"]
    sessao = extrator_ldi.montar_sessao(cfg, extrator_ldi.carregar_cookie())
    caminho = os.path.join(extrator_ldi.PASTA_APP, cfg["pasta_saida"], "conteudo.db")

    print("=" * 60)
    print(f" COLETOR LDI  |  termo: {termo}  |  banco: {caminho}")
    print("=" * 60)
    coletar(cfg, sessao, termo, caminho,
            continuar=args.continuar, com_videos=args.com_videos, ids=ids)
    if not args.agendado:
        input("\nPressione ENTER para fechar...")


if __name__ == "__main__":
    try:
        main()
    except SystemExit as e:
        if e.code and "--agendado" not in sys.argv:
            input("\nPressione ENTER para fechar...")
        raise
