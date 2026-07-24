# -*- coding: utf-8 -*-
"""
============================================================
 SYNC DEPARA SUPABASE — publica o de→para de vídeos (Metabase)
 na tabela depara_video do Supabase, para a web/VPS casarem a
 data real de gravação sem o cache gz local.
 Roda no LOCAL (onde existe saida/metabase_depara.json.gz).
 Uso:  py sync_depara_supabase.py [--gz CAMINHO]
============================================================
"""
import argparse
import gzip
import json
import os
import sys

import requests

import sync_supabase  # reusa _config / _headers

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

LOTE = 5000
_CAMPOS = ("data", "status", "titulo", "raiz", "path", "dur", "n")


def gz_padrao():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "saida", "metabase_depara.json.gz")


def linhas_do_gz(depara):
    """Transforma {video_id: {campos}} nas linhas de upsert de depara_video."""
    linhas = []
    for vid, rec in (depara or {}).items():
        rec = rec or {}
        linha = {"video_id": str(vid)}
        for c in _CAMPOS:
            linha[c] = rec.get(c)
        linhas.append(linha)
    return linhas


def em_lotes(seq, tamanho):
    for i in range(0, len(seq), tamanho):
        yield seq[i:i + tamanho]


def publicar(gz_path=None, url=None, key=None):
    """Lê o gz e faz upsert em lotes em depara_video. Devolve o total publicado."""
    if url is None or key is None:
        url, key = sync_supabase._config()
    rest = f"{url}/rest/v1"
    gz_path = gz_path or gz_padrao()
    if not os.path.exists(gz_path):
        raise SystemExit(f"[depara] gz não encontrado: {gz_path}\n"
                         "       Rode antes: py depara_metabase.py --refresh (Warp + Metabase).")
    with gzip.open(gz_path, "rt", encoding="utf-8") as f:
        depara = json.load(f)
    linhas = linhas_do_gz(depara)
    # ping: falha na cara antes de escrever se a credencial estiver errada
    png = requests.get(f"{rest}/depara_video?select=video_id&limit=1",
                       headers=sync_supabase._headers(key), timeout=30)
    png.raise_for_status()
    total, lotes = 0, (len(linhas) + LOTE - 1) // LOTE
    for i, lote in enumerate(em_lotes(linhas, LOTE), 1):
        requests.post(f"{rest}/depara_video",
                      headers=sync_supabase._headers(key, "resolution=merge-duplicates"),
                      params={"on_conflict": "video_id"}, json=lote, timeout=120
                      ).raise_for_status()
        total += len(lote)
        print(f"[depara] lote {i}/{lotes} — {total}/{len(linhas)}")
    print(f"[depara] publicado: {total} vídeos em depara_video.")
    return total


def main():
    parser = argparse.ArgumentParser(description="Publica o de→para de vídeos no Supabase")
    parser.add_argument("--gz", help="caminho do metabase_depara.json.gz (padrão: saida/)")
    args = parser.parse_args()
    publicar(gz_path=args.gz)


if __name__ == "__main__":
    main()
