# -*- coding: utf-8 -*-
"""
============================================================
 EXTRATOR LDI — Vídeos por curso (SOMENTE LEITURA)
 Versão aplicativo: roda fora do navegador, usando o cookie
 da sessão do admin (cole em cookie.txt — ver TUTORIAL.md).
============================================================
 1. Busca os cursos no LDI pelo termo do config.json
 2. Varre a árvore (capítulos > aulas) de cada curso
 3. Baixa os blocos das aulas com vídeo e extrai:
    ID do vídeo, nome, nome original (legado), intra_video_id,
    duração, data de criação, tamanho
 4. Grava CSV (Excel pt-BR) e JSON direto na pasta de saída

 Uso:  py extrator_ldi.py [--termo PRF] [--agendado]
       --termo     sobrepõe o termo_busca do config.json
       --agendado  não pede ENTER no final (p/ Agendador de Tarefas)
============================================================
"""
import sys
import os
import re
import json
import csv
import time
import argparse
from datetime import date
from concurrent.futures import ThreadPoolExecutor, as_completed

import warnings

# aviso cosmético do requests dentro do .exe (detecção de charset) — não nos afeta:
# a API sempre responde JSON em UTF-8 declarado
warnings.filterwarnings("ignore", message=".*character detection dependency.*")

import requests  # noqa: E402

# Console do Windows às vezes não é UTF-8 — evita erro de acentuação
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PASTA_APP = os.path.dirname(os.path.abspath(sys.argv[0]))
API = "https://api.estrategia.com"
TIPOS_VIDEO = ("videoMyDocuments", "cast", "youtube")


def falha(msg):
    print(f"\n[ERRO] {msg}")
    return SystemExit(1)


def carregar_config():
    caminho = os.path.join(PASTA_APP, "config.json")
    if not os.path.exists(caminho):
        raise falha("config.json não encontrado ao lado do programa.")
    with open(caminho, encoding="utf-8-sig") as f:
        cfg = json.load(f)
    cfg.setdefault("termo_busca", "PRF")
    cfg.setdefault("filtro_local", "")
    cfg.setdefault("vertical", "concursos")
    cfg.setdefault("pasta_saida", "saida")
    cfg.setdefault("incluir_url", True)
    cfg.setdefault("concorrencia", 4)
    return cfg


def carregar_cookie():
    caminho = os.path.join(PASTA_APP, "cookie.txt")
    if not os.path.exists(caminho):
        raise falha("cookie.txt não encontrado. Crie o arquivo ao lado do programa\n"
                    "       e cole nele o cookie do admin (passo a passo no TUTORIAL.md).")
    with open(caminho, encoding="utf-8-sig") as f:
        bruto = f.read().strip()
    # aceita colar com ou sem o prefixo "cookie:"
    bruto = re.sub(r"^cookie\s*:\s*", "", bruto, flags=re.I).strip()
    bruto = " ".join(bruto.split())  # remove quebras de linha acidentais
    if not bruto or "COLE_AQUI" in bruto:
        raise falha("cookie.txt está vazio (ou ainda com o texto de exemplo).\n"
                    "       Cole o cookie do admin nele — passo a passo no TUTORIAL.md.")
    return bruto


def montar_sessao(cfg, cookie):
    s = requests.Session()
    s.headers.update({
        "x-vertical": cfg["vertical"],
        "Cookie": cookie,
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
        "Accept": "application/json",
    })
    return s


def get_json(sessao, url, tentativa=1):
    try:
        r = sessao.get(url, timeout=60)
    except requests.RequestException as e:
        if tentativa < 4:
            time.sleep(0.7 * tentativa * tentativa)
            return get_json(sessao, url, tentativa + 1)
        raise falha(f"Falha de rede repetida em {url}: {e}")
    if r.status_code == 401:
        raise falha("A API respondeu 401 (não autenticado).\n"
                    "       O cookie venceu — atualize o cookie.txt (TUTORIAL.md, seção 'Atualizar o cookie').")
    if r.status_code == 429 or r.status_code >= 500:
        if tentativa < 4:
            time.sleep(0.7 * tentativa * tentativa)
            return get_json(sessao, url, tentativa + 1)
        raise falha(f"API instável (HTTP {r.status_code}) em {url}")
    if not r.ok:
        raise falha(f"HTTP {r.status_code} em {url}: {r.text[:200]}")
    return r.json()


def segundos(dur):
    """'01:06:53.80' -> 4014 (segundos)"""
    if not isinstance(dur, str):
        return ""
    m = re.search(r"(\d+):(\d+):(\d+(?:\.\d+)?)", dur)
    if not m:
        return ""
    return round(int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)))


def listar_cursos(sessao, termo):
    cursos = []
    for page in range(1, 51):
        url = (f"{API}/bo/ldi/courses?page={page}&per_page=100&sort=desc"
               f"&order_by=created_at&include_authors_names=true"
               f"&search_term={requests.utils.quote(termo)}")
        lote = get_json(sessao, url).get("data") or []
        cursos.extend(lote)
        if len(lote) < 100:
            break
    return cursos


def obter_curso(sessao, curso_id):
    """Detalhe de um curso pelo ID (UUID). O payload já traz content_tree_cache
    (capítulos→aulas) e structured_authors — mesmo formato de um item de
    listar_cursos. Devolve o dict do curso, ou None se a API não trouxer dados."""
    dados = get_json(sessao, f"{API}/bo/ldi/courses/{curso_id}").get("data")
    return dados or None


_RX_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
# aceita separador de milhar dentro do número: 'videosintra248.487' -> 248487
_RX_VIDEOSINTRA = re.compile(r"videosintra\s*([\d.,]{3,12})", re.I)
_RX_FIM_NOME = re.compile(r"[-–—]\s*([\d.,]{4,9})\s*$")


def _so_digitos(trecho, minimo):
    n = re.sub(r"\D", "", trecho or "")
    return n if minimo <= len(n) <= 8 else ""


def id_sistema_antigo(res):
    """ID do vídeo no sistema antigo: 'videosintra116648' (ou 'videosintra248.487',
    com ponto de milhar) no nome original, ou os dígitos no final do nome de
    exibição ('... - 248487')."""
    m = _RX_VIDEOSINTRA.search(res.get("original_name") or "")
    if m:
        n = _so_digitos(m.group(1), 3)
        if n:
            return n
    m = _RX_FIM_NOME.search((res.get("name") or res.get("title") or "").strip())
    return _so_digitos(m.group(1), 4) if m else ""


def linha(cfg, curso, cap, item, bloco, erro=""):
    d = (bloco or {}).get("data") or {}
    res = d.get("resolved") or ((bloco or {}).get("simple_data") or {}).get("resolved") or {}
    nomes = []
    for a in (curso.get("authors") or []):
        n = a.get("name") if isinstance(a, dict) else str(a)
        if n and not _RX_UUID.match(str(n)):  # a API às vezes manda só o UUID do autor
            nomes.append(str(n))
    autores = curso.get("authors_name") or " | ".join(nomes)
    ordem = cap.get("order_index")
    dur = res.get("video_duration") or res.get("duration") or ""
    url_video = res.get("data") if isinstance(res.get("data"), str) else (res.get("url") or "")
    return {
        "curso_id": curso.get("id", ""),
        "curso_nome": curso.get("name", ""),
        "curso_publicado": "sim" if curso.get("published") else "nao",
        "curso_criado_em": curso.get("created_at", ""),
        "professores": autores or "",
        "capitulo_ordem": (ordem + 1) if isinstance(ordem, int) else "",
        "capitulo_nome": cap.get("name", ""),
        "capitulo_versao": cap.get("chapter_version", ""),
        "capitulo_publicado": cap.get("published_at") or "",
        "capitulo_id": cap.get("chapter_id", ""),
        "aula_path": item.get("path", ""),
        "aula_nome": item.get("name") or item.get("title") or "",
        "aula_atualizada_em": item.get("updated_at", ""),
        "item_id": item.get("item_id", ""),
        "bloco_tipo": (bloco or {}).get("type", ""),
        "bloco_id": (bloco or {}).get("id", ""),
        "bloco_ordem": (bloco or {}).get("order_index", ""),
        "bloco_rascunho": ("sim" if bloco.get("is_draft") else "nao") if bloco else "",
        "bloco_criado_em": (bloco or {}).get("created_at", ""),
        "bloco_atualizado_em": (bloco or {}).get("updated_at", ""),
        "video_id": res.get("id", d.get("videoId", (bloco or {}).get("content_id", ""))),
        "video_nome": res.get("name") or res.get("title") or "",
        "video_nome_original": res.get("original_name", ""),
        "video_intra_id": res.get("intra_video_id", ""),
        "video_id_antigo": id_sistema_antigo(res),
        "video_duracao": dur,
        "video_duracao_seg": segundos(dur),
        "video_criado_em": res.get("created_at", ""),
        "video_tamanho_bytes": res.get("file_size", ""),
        "video_url": url_video if cfg["incluir_url"] else "",
        "erro": erro,
    }


def main():
    parser = argparse.ArgumentParser(description="Extrator LDI — vídeos por curso (somente leitura)")
    parser.add_argument("--termo", help="termo de busca (sobrepõe o config.json)")
    parser.add_argument("--agendado", action="store_true", help="não pede ENTER no final")
    args = parser.parse_args()

    cfg = carregar_config()
    if args.termo:
        cfg["termo_busca"] = args.termo
    cookie = carregar_cookie()
    sessao = montar_sessao(cfg, cookie)
    termo = cfg["termo_busca"]

    print("=" * 60)
    print(f" EXTRATOR LDI  |  termo: {termo}  |  {date.today():%d/%m/%Y}")
    print("=" * 60)

    # 1) cursos
    print(f"[1/4] Buscando cursos com \"{termo}\"...")
    cursos = listar_cursos(sessao, termo)
    if cfg["filtro_local"]:
        rx = re.compile(cfg["filtro_local"], re.I)
        antes = len(cursos)
        cursos = [c for c in cursos if rx.search(c.get("name") or "")]
        print(f"      filtro_local manteve {len(cursos)} de {antes} cursos")
    print(f"      {len(cursos)} cursos encontrados")
    if not cursos:
        raise falha("Nenhum curso encontrado — confira o termo_busca no config.json.")

    # 2) aulas com vídeo (via cache da árvore que já vem na listagem)
    tarefas = []
    for curso in cursos:
        for cap in (curso.get("content_tree_cache") or []):
            for item in (cap.get("items") or []):
                btc = {**(item.get("simple_block_type_count") or {}),
                       **(item.get("block_type_count") or {})}
                if any(btc.get(t) for t in TIPOS_VIDEO):
                    tarefas.append((curso, cap, item))
    ids_unicos = sorted({item["item_id"] for _, _, item in tarefas})
    print(f"[2/4] {len(tarefas)} aulas com vídeo ({len(ids_unicos)} consultas — aulas repetidas entre cursos são baixadas 1x)")

    # 3) blocos (paralelo, com barra de progresso simples)
    blocos_por_item, erros_por_item = {}, {}
    feitos = 0

    def baixar(item_id):
        j = get_json(sessao, f"{API}/bo/ldi/blocks?item_id={item_id}")
        return item_id, (j.get("data") or [])

    print(f"[3/4] Baixando blocos ({cfg['concorrencia']} por vez)...")
    with ThreadPoolExecutor(max_workers=int(cfg["concorrencia"])) as pool:
        futuros = {pool.submit(baixar, i): i for i in ids_unicos}
        for fut in as_completed(futuros):
            item_id = futuros[fut]
            try:
                _, blocos = fut.result()
                blocos_por_item[item_id] = blocos
            except SystemExit:
                raise
            except Exception as e:  # rede/formato inesperado: registra e segue
                erros_por_item[item_id] = str(e)
            feitos += 1
            if feitos % 100 == 0 or feitos == len(ids_unicos):
                print(f"      ...{feitos}/{len(ids_unicos)}")

    # 4) monta linhas, ordena e grava
    linhas = []
    for curso, cap, item in tarefas:
        item_id = item["item_id"]
        if item_id in erros_por_item:
            linhas.append(linha(cfg, curso, cap, item, None, "ERRO: " + erros_por_item[item_id]))
            continue
        achou = False
        for b in blocos_por_item.get(item_id, []):
            if b.get("type") in TIPOS_VIDEO:
                linhas.append(linha(cfg, curso, cap, item, b))
                achou = True
        if not achou:
            linhas.append(linha(cfg, curso, cap, item, None, "aula sem bloco de video na versao atual"))

    def chave_path(p):
        return [int(x) if x.isdigit() else 0 for x in str(p or "").split(".")]

    linhas.sort(key=lambda l: (l["curso_nome"], l["capitulo_ordem"] or 0,
                               chave_path(l["aula_path"]), l["bloco_ordem"] or 0))

    pasta = os.path.join(PASTA_APP, cfg["pasta_saida"])
    os.makedirs(pasta, exist_ok=True)
    termo_arq = re.sub(r"[^\w\-]+", "_", termo)
    base = os.path.join(pasta, f"videos_{termo_arq}_{date.today():%Y-%m-%d}")

    colunas = list(linhas[0].keys())
    try:
        f = open(base + ".csv", "w", newline="", encoding="utf-8-sig")
    except PermissionError:
        # arquivo aberto no Excel — grava com sufixo em vez de falhar
        base = base + time.strftime("_%Hh%M")
        print("      (CSV anterior está aberto/travado — salvando como "
              + os.path.basename(base) + ".csv)")
        f = open(base + ".csv", "w", newline="", encoding="utf-8-sig")
    with f:
        w = csv.DictWriter(f, fieldnames=colunas, delimiter=";", quoting=csv.QUOTE_ALL)
        w.writeheader()
        w.writerows(linhas)
    with open(base + ".json", "w", encoding="utf-8") as f:
        json.dump(linhas, f, ensure_ascii=False, indent=1)

    n_erros = sum(1 for l in linhas if l["erro"].startswith("ERRO"))
    print(f"[4/4] Concluído!")
    print(f"      {len(linhas)} linhas | {len(cursos)} cursos | {n_erros} erros de download")
    print(f"      CSV : {base}.csv")
    print(f"      JSON: {base}.json")

    if not args.agendado:
        input("\nPressione ENTER para fechar...")


if __name__ == "__main__":
    try:
        main()
    except SystemExit as e:
        if e.code and "--agendado" not in sys.argv:
            input("\nPressione ENTER para fechar...")
        raise
