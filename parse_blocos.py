# -*- coding: utf-8 -*-
"""Funções puras: payload da API do BO -> metadados p/ o banco de conteúdo.

É a camada com maior risco quando a API mudar — por isso é pura e testada
com payloads reais (tests/test_parse_blocos.py).
"""
import extrator_ldi

# famílias de contagem (chaves do block_type_count da árvore)
_VIDEOS = ("videoMyDocuments", "youtube")
_MAPA = {"question": "qtd_questoes", "tiptap": "qtd_textos",
         "pdfMyDocuments": "qtd_pdfs", "cast": "qtd_casts"}


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
        "meta": {},
    }
    if tipo == "question":
        sol = res.get("solution") or {}
        linha["questao_id"] = str(res.get("id") or d.get("value") or "")
        linha["resposta_tipo"] = res.get("answer_type", "")
        linha["tem_solucao"] = 1 if (sol.get("brief") or sol.get("complete")) else 0
        linha["tem_video_solucao"] = 1 if res.get("has_video_solution") else 0
        linha["meta"] = {
            "slug": res.get("slug", ""),
            "topicos": [t.get("name") for t in (res.get("topics") or [])
                        if isinstance(t, dict) and t.get("name")],
            "provas": [e.get("name") for e in (res.get("exams") or [])
                       if isinstance(e, dict) and e.get("name")],
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
    elif tipo == "pdfMyDocuments":
        linha["meta"] = {"media_id": res.get("id", "") or d.get("value", ""),
                         "criado_em": res.get("created_at", "")}
    return linha
