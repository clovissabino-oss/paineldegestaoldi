# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Antes de tudo

Leia **`PROXIMA-SESSAO.md`** — é o ponto de partida oficial de cada sessão: estado atual,
decisões do Luiz, armadilhas já resolvidas e backlog. O `TUTORIAL.md` tem o passo a passo
de uso leigo e uma "Nota técnica" no final com detalhes da API. Este CLAUDE.md resume o
que não muda entre sessões.

O projeto audita os vídeos dos cursos do sistema LDI da Estratégia (migração velho × novo):
identifica quais vídeos são gravações antigas reaproveitadas e quais são novos, e gerencia
propostas de substituição. Idioma do projeto: **pt-BR** (código, docs, UI e mensagens).

## Comandos

Não há build, lint nem testes automatizados — são 3 scripts Python standalone (Python 3.12,
deps: `requests` + `flask`). Sem git.

```powershell
# Ciclo completo (nesta ordem):
py extrator_ldi.py [--termo PRF] [--agendado]      # 1. extrai árvore do admin LDI → saida\videos_*.{csv,json}
py depara_metabase.py [--arquivo X.json] [--refresh]  # 2. cruza com Metabase (data real de gravação)
py visualizador.py [--sem-navegador]               # 3. tela analítica Flask em http://127.0.0.1:8765

# Painel de Conteúdo (fase 2 — specs/planos em docs\superpowers\):
py coletor_ldi.py [--termo X] [--continuar] [--com-videos] [--agendado]
#   varre TODOS os blocos (questões c/ banca-ano, textos c/ questões coladas, PDFs, vídeos,
#   professores) → snapshots em saida\conteudo.db; ao final roda as regras de qualidade
py regras_qualidade.py [--extracao N]              # motor de pendências avulso (baixa automática)
py painel.py [--sem-navegador]                     # painel em http://127.0.0.1:8766
#   / = inventário · /avaliacao = planilha de avaliação por disciplina (CSV/print)
py -m unittest discover -s tests                   # testes (parse, banco, coletor, regras, painel)
```

Os `.bat` (`_iniciar_extrator.bat`, `_depara_metabase.bat`, `_abrir_visualizador.bat`) só
fazem `cd` na pasta e chamam `py` — os usuários finais usam os `.exe`.

**Rebuild dos .exe (obrigatório após mexer em `ui.html`, `estoque.html` ou `visualizador.py` —
a UI vai embutida no exe):**

```powershell
py -m PyInstaller --onefile --clean --name ExtratorLDI extrator_ldi.py
py -m PyInstaller --onefile --clean --name VisualizadorLDI --add-data "ui.html;." --add-data "estoque.html;." visualizador.py
```

(usar caminho absoluto nos `--add-data` se rodar com `--specpath`)

## Arquitetura

Pipeline de 3 etapas, cada uma um script independente que se comunica pelos arquivos em `saida\`:

1. **`extrator_ldi.py`** — cliente da API `https://api.estrategia.com/bo/ldi/...` (somente
   leitura; exige header `x-vertical` + cookie `__Secure-SID` de `cookie.txt`). Busca cursos
   por `search_term`, varre `content_tree_cache` (Cursos→Capítulos→Aulas), baixa blocos de
   vídeo (`videoMyDocuments`/`cast`/`youtube`) em paralelo e grava CSV (`;`, utf-8-sig, pt-BR)
   + JSON. Extrai o `video_id_antigo` do nome (`videosintra…` ou dígitos no final).
2. **`depara_metabase.py`** — baixa a question **19885 (Videos BO)** inteira do Metabase
   (~540 mil linhas; cache gzip 7 dias em `saida\metabase_depara.json.gz`), casa por
   `video_id_antigo` e **reescreve o JSON/CSV da extração no lugar** acrescentando colunas
   `gravacao_*`, `mb_*`, `depara_ok`, `depara_confere`. A auth do Metabase é **reutilizada do
   app de Limpeza** (importa `experimento_metabase` de
   `C:\⚙️ Aplicativos\🦉 Relatório de Cursos - Árvores - Professores\6. Limpeza Unificada de Dados`).
Além do pipeline de vídeos, existe o **Painel de Conteúdo** (`coletor_ldi.py` +
`parse_blocos.py` + `banco_conteudo.py` + `regras_qualidade.py` + `painel.py`): o coletor
varre TODOS os blocos de um concurso (questões com banca/ano/tópicos/soluções, textos com
detector de questões coladas, vídeos com ID antigo, professores via detalhe do curso) e grava
snapshots em `saida\conteudo.db` (SQLite WAL, retomável). Ao fim de cada coleta, o motor de
qualidade materializa `pendencias` (catálogo declarativo, chave determinística, baixa
automática no snapshot seguinte). O `painel.py` (porta 8766, `painel.html`/`avaliacao.html`
embutidas no exe) serve o inventário e a planilha de Avaliação por disciplina (a idade real
de gravação vem do cache `metabase_depara.json.gz`). Specs/planos em `docs\superpowers\`.

3. **`visualizador.py` + `ui.html`** — servidor Flask (porta 8765) que serve a `ui.html`
   (single-file, ~100 KB, todo o front em JS vanilla inline) e expõe a API local:
   `/api/dados` (extração mais recente), `/api/cookie*`, `/api/analises` (→ `analises.json`),
   `/api/propostas` (→ `propostas.json`, upsert por uuid), `/api/estoque/*` (sugestão
   automática por similaridade de nome — SequenceMatcher + Jaccard) e `/api/extrair`
   (dispara o extrator da tela). `estoque.html` é servida em `/estoque`.
   `visualizador.py` importa `extrator_ldi` para reusar config/cookie/sessão.

Fonte do estoque de professores (sugestão automática): preferencial são as árvores
`arvore_*.xlsx` da pasta da Limpeza (todos os caminhos por vídeo; cache próprio em
`saida\estoque_arvores.json.gz`, leitura 100% read-only da pasta); a question 19885 fica só
de cobertura para professores sem xlsx.

### Dois cookies, dois sistemas

- **LDI (admin)**: `cookie.txt` na pasta — só o `__Secure-SID` importa (JWT, ~30 dias).
  Troca pela tela do Visualizador (botão 🍪) ou editando o arquivo.
- **Metabase**: `metabase_cookies.json` da pasta da Limpeza — Cloudflare, ~24h, **exige
  Warp ativo**. Recarrega-se colando o header em `cookies.txt` LÁ (o app de lá apaga o
  arquivo após ler).

## Armadilhas conhecidas (não regredir)

- **ID com ponto de milhar**: `videosintra248.487` = 248487. A extração de ID pega só
  dígitos — se mexer, manter o comportamento em `extrator_ldi.py`, `ui.html` E
  `depara_metabase.py` (e no plano B `EXTRATOR-LDI-VIDEOS.js`).
- **Prova por duração** (`depara_confere`): o Metabase às vezes arredonda ao minuto
  (`:00`) → tolerância adaptativa (60s se arredondado, senão 5s).
- **Question 19885 ignora o parâmetro `id_video` via API** → baixa-se a tabela inteira e
  casa-se localmente. Não tentar filtrar no servidor.
- **Porta 8765 aceita bind duplo no Windows**: se a tela servir código velho, matar
  instâncias antigas de python/VisualizadorLDI (conferir CommandLine — NÃO tocar no python
  de `src\backend\app.py`, que é outro app).
- Nomes de arquivo exportados usam **data local** (não `toISOString`/UTC — virava o dia
  seguinte à noite).
- CSVs abertos no Excel dão `PermissionError` — os scripts já salvam com sufixo `_HHhMM`;
  manter esse padrão.
- Blocos `cast` ficam **fora da análise por padrão** na tela (decisão do Luiz — dados não
  batem); o checkbox pode religar.

## Arquivos de dados (na pasta do app, não versionados)

| Arquivo | O quê |
|---|---|
| `config.json` | `termo_busca`, `filtro_local`, `vertical`, `pasta_saida`, `incluir_url`, `concorrencia` |
| `cookie.txt` | Cookie do admin LDI |
| `analises.json` / `propostas.json` | Estado salvo pela tela (análises nomeadas / propostas de substituição) |
| `saida\videos_<termo>_<data>.{json,csv}` | Resultado da extração (enriquecido in-place pelo de→para) |
| `saida\conteudo.db` | Base SQLite do Painel de Conteúdo (snapshots de TODOS os blocos por concurso) |
| `saida\metabase_depara.json.gz` / `saida\estoque_arvores.json.gz` | Caches (question 19885 / árvores xlsx) |
