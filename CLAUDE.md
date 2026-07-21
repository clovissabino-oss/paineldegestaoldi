# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Antes de tudo

Leia **`PROXIMA-SESSAO.md`** — é o ponto de partida oficial de cada sessão: estado atual,
decisões do Clovis, armadilhas já resolvidas e backlog. O `TUTORIAL.md` tem o passo a passo
de uso leigo e uma "Nota técnica" no final com detalhes da API. Este CLAUDE.md resume o
que não muda entre sessões.

O projeto audita os vídeos dos cursos do sistema LDI da Estratégia (migração velho × novo):
identifica quais vídeos são gravações antigas reaproveitadas e quais são novos, e gerencia
propostas de substituição. Idioma do projeto: **pt-BR** (código, docs, UI e mensagens).

## Comandos

O lado Python são scripts standalone (Python 3.12, deps: `requests` + `flask`); o app web
fica em `web\` (Next.js 15, Node 22+).

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

# Publicação web (Supabase + Vercel):
py sync_supabase.py [--termo X]                    # publica o snapshot mais recente no Supabase
#   (também roda sozinho, não-fatal, ao fim de cada coleta do coletor_ldi.py)
cd web; npm run dev                                # app web local em http://localhost:3000
cd web; npm run build                              # build de produção (mesmo do Vercel)
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

### Publicação web (`web\` — Supabase + Vercel)

O Painel de Conteúdo tem uma vitrine web de **leitura** para o time: `sync_supabase.py`
roda a agregação do `painel.py` sobre o `conteudo.db` e faz upsert do resultado pronto em
3 tabelas do Supabase (`snapshot`/`avaliacao_curso`/`pendencia_resumo` + view
`snapshot_atual`, só `pronto=true`; schema versionado em `supabase\schema.sql`, RLS leitura
`authenticated`). O app Next.js em `web\` (deploy no Vercel, Root Directory `web`) serve as
telas com login **magic-link por convite** (Supabase Auth, sessão em cookie via
`@supabase/ssr`, middleware gate). As telas web `web\telas\{painel,avaliacao}.html` são
**cópias** das da raiz com 3 edições cada (link sair, selo de frescor, estado vazio) —
mudou a tela da raiz, replicar na cópia. As telas chamam `/api/...` (handlers Next com o
JWT do usuário — NÃO usar supabase-js no navegador: sessão em localStorage é incompatível
com o gate por cookie). Service_role no app: só no módulo server-only
`web\lib\supabase\admin.ts` (env `SUPABASE_SERVICE_KEY`, sem NEXT_PUBLIC_) — nunca em
componente cliente/navegador. Acesso: @estrategia.com entra direto pelo login (auto-
provisionado); externos por convite na tela `/admin` (admin = `app_metadata.role="admin"`;
hoje só o Clovis). **Papéis** (Fase 4): `admin` (tudo) e `operador` (dispara coletas) —
gate compartilhado em `web\lib\papeis.ts` (`exigirAdmin`/`exigirOperador`, re-checado no
servidor em toda action); concessão pelo seletor de papel no `/admin`.

**Coleta pela web (Fase 4)**: a tela **`/coleta`** (admin+operador; outros → 404) dispara
coletas por **termo** ou por **IDs+rótulo** (aceita colar a URL do admin; `extrairIds` em
`web\lib\coleta.ts` é porta fiel do `coletor_ldi.extrair_ids` — pega `id=`, nunca
`team_id=`) inserindo em `coleta_pedido` (`pendente`); o worker no VPS processa. Painel da
fila com polling 5s (`/api/fila`) e ações só-admin: cancelar (`pendente`→`cancelada`),
retentar (`erro`/`aguardando_cookie`→`pendente`), cancelar em andamento
(`rodando`→`cancelando`, o worker converte) — transições **atômicas** (update condicional
`.in("status", esperados)`; zero linhas = status mudou). O cookie do LDI é renovado pelo
`/admin` (só admin; upsert em `config_ldi` via service_role — a tabela não tem policy de
leitura, o valor nunca chega ao cliente) e o estado derivado (`cookie_status`, publicado
pelo worker) aparece via `/api/cookie-status` como **banner** (vermelho vencido / amarelo
≤3 dias) nas telas React (`BannerCookie.tsx`) e nas cópias vanilla de `web\telas\`.

- **Supabase**: projeto na conta **Estratégia** (ref `zpjsoidxhfwziprjxpqx`) — NUNCA o
  Supabase pessoal do Clovis. Credenciais: `supabase.json` na raiz (service_role, só para o
  sync Python) e `web\.env.local` (anon key) — ambos gitignored.
- **E-mail do magic link**: o remetente embutido do Supabase é só para dev (rate limit).
  Para o time, plugar SMTP próprio em Auth → SMTP Settings — o Clovis tem **Resend** integrado
  na infosab (outro projeto dele); reusar essa conta/API key.
- **Git flow (enxuto)**: `main` = **produção** (o Vercel deploya a `main`). Trabalho em
  `feat/*` **curtas e descartáveis** → PR pra `main` → o merge deploya; a branch morre depois.
  Ajuste pequeno e seguro pode ir direto na `main`. **Sem `develop`** (era um degrau a mais
  para um dev só; aposentada em 20/07). Se um dia entrar outra pessoa no *desenvolvimento*
  (não na visualização — o time já vê tudo), reavaliar uma branch de homologação.
  Push e merge exigem login interativo do Clovis (a integração do GitHub aqui é só leitura) —
  o merge de PR pode ser feito pelo site do GitHub.

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
- Blocos `cast` ficam **fora da análise por padrão** na tela (decisão do Clovis — dados não
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
| `supabase.json` | URL + service_role do Supabase (usado só pelo `sync_supabase.py`) |
| `web\.env.local` | URL + anon key do Supabase para o app web local |
