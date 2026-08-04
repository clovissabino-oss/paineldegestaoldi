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

 Material Base do professor (universo separado — não roda regras de
 qualidade nem publica no Supabase):
       --mb-professor NOME  busca o professor e imprime o comando pronto de cada MB dele
       --mb ID_OU_URL       coleta esse Material Base (UUID ou URL do admin)
       --professor NOME     nome a rotular na coleta; só vale junto com --mb
                            (sem ele, o professor fica com o UUID do LDI)
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


# A classe mora no extrator_ldi (onde está o get_json que detecta o 401);
# o alias preserva a interface usada pelo worker e pelos testes.
CookieVencido = extrator_ldi.CookieVencido


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


def _completar_vinculo_mb(sessao, con, extracao_id, cursos, concorrencia):
    """Vínculo com o Material Base por item (has_base_material) — vem só de
    GET /bo/ldi/chapters/{id}/items (o flag de capítulo subnotifica)."""
    caps = [cap.get("chapter_id") for c in cursos
            for cap in (c.get("content_tree_cache") or []) if cap.get("chapter_id")]

    def itens_do_cap(ch):
        r = sessao.get(f"{extrator_ldi.API}/bo/ldi/chapters/{ch}/items", timeout=60)
        if r.status_code in (401, 403):
            raise CookieVencido(1)
        if not r.ok:
            raise RuntimeError(f"HTTP {r.status_code}")
        return parse_blocos.vinculo_mb_dos_itens(r.json().get("data") or [])

    falhas = recebidos = casadas = 0
    with ThreadPoolExecutor(max_workers=int(concorrencia)) as pool:
        futuros = {pool.submit(itens_do_cap, ch): ch for ch in caps}
        for fut in as_completed(futuros):
            try:
                vinc = fut.result()
                if vinc:
                    recebidos += len(vinc)
                    casadas += banco_conteudo.gravar_vinculo_mb(con, extracao_id, vinc)
            except CookieVencido:
                raise
            except Exception:  # enriquecimento: capítulo pontual falho não derruba
                falhas += 1
    if falhas:
        print(f"      ({falhas} capítulos sem vínculo de MB lido)")
    if recebidos and not casadas:
        print("      ⚠ vínculo de MB: recebi itens da API mas nenhum casou com a árvore "
              "(possível mudança de formato do endpoint) — vinculado_mb ficou vazio.")


# ── Material Base do professor (universo separado do LDI de curso) ──────────

_MIN_TERMO_PROFESSOR = 3


def extrair_id_mb(texto):
    """UUID do MB a partir de um UUID solto ou da URL do admin
    (…/base-material/edit?id=<uuid>&team_id). Pega SEMPRE o id=, nunca o team_id=."""
    tok = (texto or "").strip()
    m = re.search(rf"[?&]id=({_UUID})", tok)
    if m:
        return m.group(1).lower()
    if re.fullmatch(_UUID, tok):
        return tok.lower()
    raise extrator_ldi.falha(f"Não achei um ID de Material Base em: {tok[:60]}")


def _get_mb(sessao, caminho):
    """GET no LDI pelo caminho relativo, com o MESMO tratamento do resto do
    projeto: 4 tentativas com backoff em 429/5xx e em falha de rede, e 401/403
    imprimindo o motivo ANTES de levantar CookieVencido — sem isso o usuário
    via só "Pressione ENTER para fechar"."""
    return extrator_ldi.get_json(sessao, f"{extrator_ldi.API}{caminho}")


def obter_mb(sessao, mb_id):
    """Detalhe do Material Base: name (disciplina), user_id, hide_chapters."""
    return _get_mb(sessao, f"/bo/ldi/base-material/{mb_id}").get("data") or {}


def capitulos_do_mb(sessao, mb_id):
    """A árvore INTEIRA numa requisição (medido: 36 capítulos, 366 KB, 1,1 s)."""
    return _get_mb(sessao, f"/bo/ldi/base-material/{mb_id}/chapters?page=1&per_page=100"
                   ).get("data") or []


_MAX_PAGINAS_MB = 10  # trava de segurança; hoje são 4 páginas (387 MBs)


def indice_de_mbs(sessao):
    """Os ~387 MBs da base. Serve para saber QUEM é professor: o LDI não tem
    endpoint de professores, e a busca de usuários devolve alunos também."""
    todos, pagina = [], 1
    while pagina <= _MAX_PAGINAS_MB:
        lote = _get_mb(sessao, f"/bo/ldi/base-material?page={pagina}&per_page=100"
                       ).get("data") or []
        todos += lote
        if len(lote) < 100:
            return todos
        pagina += 1
    # Truncar em silêncio faria a busca de professor "não achar" alguém que
    # existe — o usuário precisa saber que a lista veio pela metade.
    print(f"  [aviso] parei na página {_MAX_PAGINAS_MB} do índice de Materiais Base "
          f"({len(todos)} lidos) e ainda havia mais. A busca de professor pode não "
          f"achar quem está nas páginas seguintes — aumente _MAX_PAGINAS_MB.")
    return todos


def buscar_professores_com_mb(sessao, termo):
    """Busca no diretório do LDI e devolve SÓ quem tem Material Base.

    O `users?term=` varre todos os usuários (alunos inclusive), ignora per_page e
    devolve ~50 sem ranking — sozinho ele é inútil. Cruzar com o índice de MBs é o
    que transforma isso numa busca de professor.
    """
    termo = (termo or "").strip()
    if len(termo) < _MIN_TERMO_PROFESSOR:
        raise extrator_ldi.falha(
            f"Busque o professor com pelo menos {_MIN_TERMO_PROFESSOR} letras "
            "(tente só o sobrenome — a busca do LDI é de uma palavra só).")
    # mesmo tratamento que extrator_ldi.listar_cursos dá ao search_term: o nome
    # do professor pode ter espaço, acento ou "&" e não pode quebrar a query
    usuarios = _get_mb(
        sessao, f"/bo/ldi/users?page=1&per_page=50"
                f"&term={requests.utils.quote(termo)}").get("data") or []
    por_dono = {}
    for mb in indice_de_mbs(sessao):
        por_dono.setdefault(mb.get("user_id"), []).append(
            {"id": mb.get("id"), "disciplina": (mb.get("name") or "").strip()})
    achados = []
    for u in usuarios:
        mbs = por_dono.get(u.get("id"))
        if mbs:
            achados.append({"user_id": u.get("id"),
                            "nome": u.get("full_name") or u.get("id"),
                            "email": u.get("email") or "",
                            "mbs": sorted(mbs, key=lambda m: m["disciplina"])})
    return achados


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
            print("      lendo vínculo com o Material Base (por item)...")
            _completar_vinculo_mb(sessao, con, extracao_id, cursos, cfg["concorrencia"])
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


def coletar_mb(cfg, sessao, mb_id, caminho_banco, professor_nome="", progresso=None):
    """Coleta o Material Base de um professor (universo separado do LDI de curso).

    Do item para baixo é o mesmo caminho da coleta de curso (_baixar_lote); só a
    origem da árvore muda. NÃO roda regras de qualidade nem publica no Supabase —
    ver o spec 2026-08-03-coleta-material-base-design.md.
    """
    con = banco_conteudo.abrir(caminho_banco)
    try:
        print(f"[1/4] Lendo o Material Base {mb_id}...")
        detalhe = obter_mb(sessao, mb_id)
        if not detalhe.get("id"):
            raise extrator_ldi.falha(f"Material Base não encontrado: {mb_id}")
        disciplina = (detalhe.get("name") or "").strip()
        # Sem nome no diretório, o UUID VIRA o nome — em todo lugar, não só no
        # termo. É o risco nº 2 do spec: a tela tem de mostrar o UUID, e não
        # "professor sem nome no diretório", que parece defeito.
        professor = professor_nome or detalhe.get("user_id") or "?"
        ocultos = len(detalhe.get("hide_chapters") or [])
        capitulos = capitulos_do_mb(sessao, mb_id)
        curso = parse_blocos.arvore_do_mb(detalhe, capitulos, professor_nome=professor)

        extracao_id = banco_conteudo.iniciar_extracao(
            con, f"MB · {professor} · {disciplina}", cfg["vertical"], tipo="mb",
            professor_id=detalhe.get("user_id", ""), professor_nome=professor,
            disciplina=disciplina,
            classificacao_id=detalhe.get("main_classification_id", ""),
            capitulos_ocultos=ocultos)
        _, n_aulas = banco_conteudo.gravar_arvore(con, extracao_id, [curso])
        with con:  # todo item de MB está, por definição, no Material Base
            con.execute("UPDATE aulas SET vinculado_mb=1 WHERE extracao_id=?", (extracao_id,))
        # len(curso["content_tree_cache"]), não len(capitulos): arvore_do_mb
        # descarta capítulo sem `id`, e este número é o gabarito do aceite
        # ("36 capítulos") e da comparação dupla do risco nº 1 do spec.
        print(f"      {len(curso['content_tree_cache'])} capítulos, {n_aulas} itens "
              f"(snapshot #{extracao_id})"
              + (f" · {ocultos} capítulos ocultos pelo professor, fora desta coleta"
                 if ocultos else ""))

        pendentes = banco_conteudo.aulas_pendentes(con, extracao_id)
        print(f"[2/4] {len(pendentes)} itens a baixar")
        print(f"[3/4] Baixando blocos ({cfg['concorrencia']} por vez)...")
        erros = _baixar_lote(sessao, con, extracao_id, pendentes,
                             cfg["concorrencia"], None, progresso)
        if erros:
            print(f"      retry de {len(erros)} itens com falha...")
            erros = _baixar_lote(sessao, con, extracao_id, list(erros),
                                 cfg["concorrencia"], None, progresso)
        status = banco_conteudo.finalizar_extracao(con, extracao_id, erros)
        tot = con.execute("SELECT total_aulas, total_blocos FROM extracoes WHERE id=?",
                          (extracao_id,)).fetchone()
        print(f"[4/4] Coleta {status}: {tot[0]} itens, {tot[1]} blocos")
        print("      (Material Base não roda regras de qualidade nem publica na web)")
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
    parser.add_argument("--mb", help="coleta o Material Base de um professor "
                                     "(UUID ou URL do admin)")
    parser.add_argument("--mb-professor", dest="mb_professor",
                        help="busca o professor pelo nome e lista os Materiais Base dele")
    parser.add_argument("--professor", help="nome do professor a rotular na coleta do MB "
                                            "(o --mb-professor imprime o comando pronto com ele)")
    parser.add_argument("--agendado", action="store_true", help="não pede ENTER no final")
    args = parser.parse_args()

    cfg = extrator_ldi.carregar_config()
    if args.continuar and args.com_videos:
        raise extrator_ldi.falha("--com-videos não funciona com --continuar "
                                 "(rode uma coleta nova).")
    if args.professor and not args.mb:
        raise extrator_ldi.falha("--professor só vale acompanhado de --mb.")
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

    if args.mb_professor:
        achados = buscar_professores_com_mb(sessao, args.mb_professor)
        if not achados:
            print(f'Nenhum professor com Material Base para "{args.mb_professor}".\n'
                  "Tente só o sobrenome — a busca do LDI é de uma palavra só.")
            return
        for a in achados:
            print(f"\n{a['nome']}  <{a['email']}>  ({a['user_id']})")
            for mb in a["mbs"]:
                print(f'   py coletor_ldi.py --mb {mb["id"]} --professor "{a["nome"]}"'
                      f'   # {mb["disciplina"]}')
        return

    if args.mb:
        mb_id = extrair_id_mb(args.mb)
        coletar_mb(cfg, sessao, mb_id, caminho, professor_nome=args.professor or "")
        return

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
