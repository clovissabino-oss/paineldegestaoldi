# -*- coding: utf-8 -*-
"""Funções puras: payload da API do BO -> metadados p/ o banco de conteúdo.

É a camada com maior risco quando a API mudar — por isso é pura e testada
com payloads reais (tests/test_parse_blocos.py).
"""
import re

import extrator_ldi

# famílias de contagem (chaves do block_type_count da árvore)
_VIDEOS = ("videoMyDocuments", "youtube")
_MAPA = {"question": "qtd_questoes", "tiptap": "qtd_textos",
         "pdfMyDocuments": "qtd_pdfs", "cast": "qtd_casts"}

# questões coladas no corpo do texto: "(BANCA/ANO/Órgão...)" — padrão real do LDI
_RX_QUESTAO_TEXTO = re.compile(
    r"\((CESPE[^/)]*|CEBRASPE[^/)]*|FGV|FCC|VUNESP|IADES|ESAF|CESGRANRIO|AOCP|QUADRIX|"
    r"Banca\s+[^/)]+|Instituto\s+[^/)]+|In[eé]ditas?[^/)]*)\s*[/\-–]\s*(\d{4})([^)]*)\)",
    re.I)
_RX_PROF_NO_NOME = re.compile(r"[-–]\s*(Profs?\.\s*[^-–]+?)\s*$", re.I)


def _texto_do_no(no, acc):
    if isinstance(no, dict):
        if isinstance(no.get("text"), str):
            acc.append(no["text"])
        for v in no.values():
            _texto_do_no(v, acc)
    elif isinstance(no, list):
        for v in no:
            _texto_do_no(v, acc)
    return acc


def questoes_no_texto(conteudo):
    """Refs de questões coladas no corpo do tiptap -> [{banca, ano, resto}]. Nunca guarda o texto."""
    if not conteudo:
        return []
    txt = " ".join(_texto_do_no(conteudo, []))
    return [{"banca": m.group(1).strip(), "ano": int(m.group(2)),
             "resto": m.group(3).strip(" /-–")[:60]}
            for m in _RX_QUESTAO_TEXTO.finditer(txt)]


def nomes_dos_autores(detalhe_curso):
    """Nomes do GET /bo/ldi/courses/{id} (structured_authors); fallback: 'Prof. X' no nome."""
    nomes = [a.get("full_name") or a.get("public_name") or ""
             for a in (detalhe_curso.get("structured_authors") or []) if isinstance(a, dict)]
    nomes = [n for n in nomes if n]
    if nomes:
        return " | ".join(nomes)
    m = _RX_PROF_NO_NOME.search(detalhe_curso.get("name") or "")
    return m.group(1).strip() if m else ""


def contagens_da_aula(item):
    btc = {**(item.get("simple_block_type_count") or {}),
           **(item.get("block_type_count") or {})}
    c = {"qtd_videos": 0, "qtd_questoes": 0, "qtd_textos": 0,
         "qtd_pdfs": 0, "qtd_casts": 0, "qtd_outros": 0}
    for tipo, n in btc.items():
        n = n or 0
        if tipo in _VIDEOS:
            c["qtd_videos"] += n
        elif tipo in _MAPA:
            c[_MAPA[tipo]] += n
        else:
            c["qtd_outros"] += n
    return c


def autores_do_curso(curso):
    if curso.get("authors_name"):
        return str(curso["authors_name"])
    nomes = []
    for a in (curso.get("authors") or []):
        n = a.get("name") if isinstance(a, dict) else str(a)
        if n and not extrator_ldi._RX_UUID.match(str(n)):
            nomes.append(str(n))
    return " | ".join(nomes)


def meta_do_bloco(bloco):
    d = bloco.get("data") or {}
    res = d.get("resolved") or ((bloco.get("simple_data") or {}).get("resolved") or {})
    tipo = bloco.get("type") or ""
    linha = {
        "bloco_id": bloco.get("id", ""),
        "tipo": tipo,
        "ordem": bloco.get("order_index"),
        "ativo": 1 if bloco.get("is_active") else 0,
        "rascunho": 1 if bloco.get("is_draft") else 0,
        "titulo": d.get("title") or res.get("name") or res.get("title") or "",
        "questao_id": "", "resposta_tipo": "",
        "tem_solucao": None, "tem_video_solucao": None,
        "video_id_antigo": "", "duracao_seg": None, "tamanho_texto": None,
        "banca": "", "ano": None, "qtd_questoes_texto": None,
        "meta": {},
    }
    if tipo == "question":
        sol = res.get("solution") or {}
        linha["questao_id"] = str(res.get("id") or d.get("value") or "")
        linha["resposta_tipo"] = res.get("answer_type", "")
        linha["tem_solucao"] = 1 if (sol.get("brief") or sol.get("complete")) else 0
        linha["tem_video_solucao"] = 1 if res.get("has_video_solution") else 0
        exs = res.get("exams") or []
        e0 = exs[0] if exs and isinstance(exs[0], dict) else {}
        badges = [b.get("text", "") for b in (e0.get("badges") or [])
                  if isinstance(b, dict) and b.get("type") != "YEAR" and b.get("text")]
        topicos = [t for t in (res.get("topics") or []) if isinstance(t, dict)]
        principal = next((t for t in topicos if t.get("is_main_classification")),
                         topicos[0] if topicos else None)
        caminho = (principal or {}).get("path_name") or []
        linha["banca"] = badges[0] if badges else ""
        linha["ano"] = e0.get("year")
        linha["meta"] = {
            "slug": res.get("slug", ""),
            "orgao": badges[1] if len(badges) > 1 else "",
            "topico": caminho[-1] if caminho else "",
            "topico_caminho": " > ".join(caminho),
            "qtd_alternativas": len(res.get("alternatives") or []),
        }
    elif tipo in extrator_ldi.TIPOS_VIDEO:
        dur = res.get("video_duration") or res.get("duration") or ""
        seg = extrator_ldi.segundos(dur)
        linha["video_id_antigo"] = extrator_ldi.id_sistema_antigo(res)
        linha["duracao_seg"] = seg if seg != "" else None
        linha["meta"] = {
            "video_id": res.get("id", ""),
            "nome_original": res.get("original_name", ""),
            "intra_video_id": res.get("intra_video_id", ""),
            "tamanho_bytes": res.get("file_size", ""),
            "criado_em": res.get("created_at", ""),
        }
    elif tipo == "tiptap":
        linha["tamanho_texto"] = (bloco.get("content_length")
                                  or d.get("block_content_length") or 0)
        refs = questoes_no_texto(d.get("content"))
        linha["qtd_questoes_texto"] = len(refs)
        if refs:
            linha["meta"] = {"questoes_texto": refs[:200]}
    elif tipo == "pdfMyDocuments":
        linha["meta"] = {"media_id": res.get("id", "") or d.get("value", ""),
                         "criado_em": res.get("created_at", "")}
    return linha
