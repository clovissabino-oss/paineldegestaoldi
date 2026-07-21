# 🎬 Extrator LDI — Estado atual (norte da próxima sessão)

_Última atualização: 21/07/2026 (sessão 9: Fase 4 — coleta, cookie e fila pela interface web)._

Este arquivo é o **ponto de partida** de qualquer nova sessão. Para o passo a passo
de uso, veja o `TUTORIAL.md`. Para a visão do projeto, a memória do Claude
(`projeto_extrator_ldi_videos.md`).

---

## 🎯 O que este projeto faz

Auditar os **vídeos dos cursos** do novo sistema LDI (Livros Digitais Interativos)
da Estratégia para a **migração velho × novo**: quais vídeos são gravações antigas
reaproveitadas e quais são novos. Nasceu porque a tela do admin não deixava filtrar
nem ver essas informações.

O ciclo tem **3 etapas** (3 executáveis / .bat), todos em
`C:\⚙️ Projetos_Dev\🎬 EXTRATOR_LDI_VIDEOS`:

1. **`ExtratorLDI.exe`** — extrai do admin LDI a árvore Cursos→Capítulos→Aulas→Vídeos
   (com ID, duração, tamanho, data de entrada no acervo) → gera CSV+JSON em `saida\`.
2. **`_depara_metabase.bat`** — casa o ID antigo de cada vídeo com o Metabase
   (question 19885 "Videos BO") e acrescenta a **data real de gravação** + árvore antiga.
3. **`VisualizadorLDI.exe`** — tela analítica (árvore, filtros, gráficos, detalhes,
   análises salvas, cookie na tela). Abre no navegador em `http://127.0.0.1:8765`.

**Fluxo para um concurso novo:** ExtratorLDI (ou 🔄 na tela, mudando o termo) →
`_depara_metabase.bat` → VisualizadorLDI.

---

## ✅ Status: CONCLUÍDO e validado para a PRF (02/07/2026)

- **28 cursos** com vídeo, **3.570 vídeos** (2.741 únicos), **1.744h**, 540 GB.
- De→para Metabase: **3.438 casados (99,3%** dos que têm ID antigo).
  - 3.267 com duração idêntica (alta confiança);
  - **89 regravações** detectadas (mesmo vídeo, duração diferente = sinal velho×novo);
  - **3 casamentos ambíguos** para revisão manual (IDs 125237 e 182127);
  - 24 sem casar + 108 sem ID no nome.
- Gravação real vai de **2016 a 2026, pico em 2022 (1.173)** — enquanto a entrada no
  acervo novo foi só em 2023/24. Esse é o mapa de regravação.

Dataset atual: `saida\videos_PRF_2026-07-02.json` (+ .csv), já com todas as colunas.

## ✅ Sessão 2 (02/07 noite): propostas de substituição + cast fora

1. **Blocos "cast" fora da análise por padrão** (dados não batem — decisão do Clovis).
   Checkbox `cast` em "Tipo de bloco" começa desmarcado; dá para religar na mão.
   O snapshot de "vídeos atuais" das propostas também respeita esse filtro.
2. **📝 Propostas de substituição de vídeos** — a novidade grande:
   - Botão **📝** (hover) em **capítulo, aula ou vídeo** na árvore → formulário com
     os vídeos atuais daquele ponto (nome/duração/ano grav./ID) + cadastro dos
     **vídeos propostos (nome + ID)** + observação + status (🟡 proposta /
     🔵 enviada / 🟢 atendida). Selo **💡 N proposto(s)** aparece no alvo.
   - **📋 Central** no topo: lista tudo por curso, edita, exclui.
   - **📄 Relatório HTML** standalone e limpo (curso → alvo → atuais × propostos +
     obs) para divulgar aos times — baixa 1 arquivo; Ctrl+P vira PDF. Também tem
     **⬇ CSV** (uma linha por vídeo proposto).
   - Persistência: `propostas.json` ao lado do app; endpoints Flask
     `/api/propostas` (GET/POST/excluir), upsert por `id` (uuid), preserva
     `criada_em`. Chave do alvo: capítulo `curso_id::capitulo_id`, aula
     `curso_id::item_id`, vídeo `bloco_id`. Snapshot `videos_atuais` é gravado na
     proposta (o relatório fica autossuficiente mesmo trocando a extração).
   - Testado ponta a ponta (API + UI no Chrome com dados da PRF). Ficou **1
     proposta de EXEMPLO** cadastrada (capítulo de Estrutura Organizacional do
     curso de Administração PRF, marcada "pode excluir") para o Clovis ver o fluxo.
3. Nomes de arquivo exportados agora usam data local (antes toISOString/UTC
   virava o dia seguinte à noite).

## ✅ Sessão 3 (03/07 manhã): tabela compartilhável + sugestão automática

1. **⧉ Copiar** (barra da árvore): tabela filtrada em TSV na área de transferência
   (cola direto no Excel/Sheets). **📄 Relatório** (barra da árvore): HTML único no
   mesmo layout da tela (hierarquia + selos + KPIs + filtros ativos no cabeçalho).
2. **Seletor de cursos** nos filtros (checkbox múltiplo com busca; vazio = todos).
   Entra no estado das análises salvas (`cursos`).
3. **🤖 Sugerir do estoque** (botão no formulário de proposta) — a automação:
   - Fonte: o próprio cache `saida\metabase_depara.json.gz` (283.762 vídeos únicos,
     ~540 mil linhas da question 19885) = **árvore/estoque dos professores**.
   - Backend novo em `visualizador.py`: `/api/estoque/status`, `/raizes`,
     `/topicos` (ranqueados por semelhança com o nome do alvo) e `POST /sugerir`
     (similaridade de nome: SequenceMatcher + Jaccard de palavras sobre nomes
     normalizados — sem acento/caixa/numeração/IDs; validado: "Noções Inciais"
     × "Noções Iniciais - 83480" = 0.97).
   - UI: escolher professor → marcar tópicos (o mais parecido já vem marcado) →
     buscar → pré-marca prováveis regravações (sim ≥ 0.75 e ID ≠ atuais); mesmo
     ID = "já está no alvo"; ➕ adiciona nome+ID na proposta.
   - Cache em memória no servidor (primeira chamada demora alguns segundos).
   - ⚠ O cache ATUAL guarda só 1 caminho por vídeo (`path`). O `depara_metabase.py`
     já foi atualizado para guardar TODOS (`paths`, limite 12) — **vale a partir do
     próximo `--refresh` com Warp ativo**. A tela avisa quando o cache é do formato
     antigo. Backend lê os dois formatos.
4. **✏️ Preencher IDs (modo coluna)** — feedback do Clovis: o modal era moroso; o
   fluxo real dele é digitar ID a ID direto na árvore. Botão na barra da árvore
   liga o modo; input inline em capítulo/aula/vídeo; Tab/Enter salva a proposta
   automaticamente e resolve o **nome pelo ID** via `POST /api/estoque/resolver`
   (borda verde = ok, amarela = ID fora do estoque; esvaziar = exclui, preservando
   obs/nomes manuais). Sem re-render da árvore no save (não perde o foco).
5. **🌳 Estoque** — página nova `estoque.html` servida em `/estoque` (aba própria,
   para usar lado a lado): professor → tópicos → vídeos com botão **⧉ copiar ID**.
   Reusa os endpoints de estoque. Embutida no exe (2º `--add-data`).
6. **Fonte do estoque trocada (pedido do Clovis)** — preferencial agora são as
   **árvores `arvore_*.xlsx`** de `C:\⚙️ Aplicativos\🦉 Relatório de Cursos - Árvores
   - Professores\6. Limpeza Unificada de Dados\downloads_metabase` (93 professores,
   95 mil vídeos, **todos os caminhos** por vídeo — resolveu a limitação de 1 path
   sem precisar de Warp). A question 19885 (gz) fica só de **cobertura** para
   professores sem xlsx. Consolidação com cache próprio em
   `saida\estoque_arvores.json.gz` (invalida sozinho quando aparecer xlsx novo —
   pega sempre o mais recente por professor; subpasta `_arquivados_*` é ignorada).
   Professores com árvore fresca ganham selo **🌿** nas listas. Leitura 100% read-only
   da pasta da Limpeza. Na mesma pasta há também `cursos_T_*.csv` /
   `cursos_consolidado_*.csv` (curso antigo → vídeos; até 1 GB) — ainda NÃO usados;
   possível fonte futura.
7. **Professor detectado pelos vídeos, não pelo nome do curso (pedido do Clovis:
   "constitucional é a Fauth")** — o modal 🤖 agora vota nas raízes `mb_raiz` dos
   vídeos já vinculados ao alvo e mostra chips "🎯 detectado pelos vídeos
   vinculados"; clicar já carrega a árvore certa. Zero risco de árvore errada.
   O resolver do preenchimento inline avisa "⚠fora da árvore atual" quando o ID
   existe na base ampla mas não na árvore vigente do professor.
8. **↗ Link para o LDI Admin** na linha do curso (só no curso, antes do nome):
   `https://admin.estrategia.com/#/concursos/ecommerce/produtos/{curso_id}`.
   ⚠ O admin (SPA) perde o `#/...` no redirect de login e cai na raiz — por isso o
   clique também COPIA o link (toast orienta a colar na barra de endereço).
9. **Filtro "Cursos" desconta os removidos (✕)** — `renderListaCursos` filtra
   `excluidos`, `removerCurso` tira o id de `cursosAtivos`, e
   `atualizarCampoExcluidos` re-renderiza a lista (restaurar também atualiza).

## ✅ Sessão 4 (04/07): painel "Cookie e extração" (colar → 1 clique → árvore)

O popover do cookie virou o **ponto de partida**: cola-se o cookie do F12, escolhe-se
o concurso (campo novo, salvo no `config.json` via `/api/cookie`) e o botão
**💾 Salvar e extrair** salva, valida, extrai do zero e abre a árvore — reusando a
UI de progresso da extração. Metabase segue **oculto** na tela (nota "em breve"); o
de→para continua pelo `_depara_metabase.bat`. Lógica de persistência do concurso
isolada em `config_util.py` (com teste `unittest`). Fase futura registrada: quando
houver API oficial do Metabase, buscar por nome direto na tela.

⚠ **Falta reempacotar o `VisualizadorLDI.exe`** na máquina de dev (PyInstaller):
`py -m PyInstaller --onefile --clean --name VisualizadorLDI --add-data "ui.html;." --add-data "estoque.html;." visualizador.py`
Sem isso, o `.exe` serve a UI antiga (o código-fonte `ui.html`/`visualizador.py` já está novo).

Projeto agora versionado em `github.com/clovissabino-oss/videosldi`
(branch de trabalho `feat/painel-cookie-extracao`).

## ✅ Sessão 5 (05-06/07): fundação do Painel de Conteúdo (coletor + conteudo.db)

Decisão do Clovis: ampliar a ferramenta para um **painel de gestão/auditoria de conteúdo do
novo BO** (inventário, qualidade, migração, evolução no tempo) — a API `/bo/ldi` entrega
TUDO que a tela mostra (censo real BACEN: 115.526 questions, 55.690 tiptap, 10.264 vídeos,
3.048 PDFs em 128 cursos/10.545 aulas), então **Playwright/scraping foi descartado**.
Spec aprovado seção a seção: `docs\superpowers\specs\2026-07-05-painel-conteudo-fundacao-design.md`
(decisões: por concurso acumulando, metadados+referência, app novo ao lado, hospedável no
infosab). Plano executado: `docs\superpowers\plans\2026-07-05-coletor-conteudo.md`.

**O que foi construído (branch `feat/coletor-conteudo`, TDD, 20 testes verdes):**
- `parse_blocos.py` — parse puro payload→metadados por tipo (question/tiptap/pdf/vídeo),
  testado com payloads reais; vídeo reusa `id_sistema_antigo()` (ponto de milhar ok).
- `banco_conteudo.py` — `saida\conteudo.db` (SQLite WAL): extracoes/cursos/capitulos/
  aulas (com contagens por tipo)/aulas_coletadas/blocos (colunas promovidas + meta JSON).
  Cada execução = 1 snapshot; nada é sobrescrito (é o que habilita o diff futuro).
- `coletor_ldi.py` — CLI: `py coletor_ldi.py [--termo X] [--continuar] [--com-videos]
  [--agendado]`. Todas as aulas (não só com vídeo); 1 aula = 1 transação; 401/403 aborta
  claro (CookieVencido); falha pontual registra e segue + 1 retry; `--continuar` retoma
  `em_andamento`/`parcial`; `--com-videos` emite o videos_*.json/csv clássico.

**✅ Verificado com dados reais (06/07):** coleta do BACEN `completa`, 0 erros —
snapshot #1: 128 cursos, **3.612 aulas únicas** (10.544 vínculos curso↔aula),
**64.838 blocos únicos** (40.964 questions, 20.241 tiptap, 2.693 vídeos, 861 PDFs,
78 casts). Somas por vínculo bateram com o censo da sondagem (vídeos/PDFs/casts exatos).
Nota: o censo de "185 mil blocos" contava por vínculo; deduplicado entre cursos é ~65 mil.
Primeiros achados de auditoria: **12.837 questões sem solução (31,3%)**, 21 cursos sem
aula na árvore, 11 cursos sem vídeo, 3 vídeos sem ID antigo. **Amostra visual do painel**
(dados reais, estática) publicada como Artifact na sessão — a fase 2 entrega isso como app.
(Durante a verificação o cookie do LDI foi invalidado no servidor e recolado — o abort
claro do 401 funcionou como projetado.)

**Fases seguintes (specs próprios na hora certa):** 2-Inventário (painel.py porta 8766),
3-Qualidade (regras SQL), 4-Evolução (diff snapshots), 5-Migração de questões (investigar
se existe fonte do sistema antigo para questões, como a 19885 é para vídeos).

## ✅ Sessão 6 (06-07/07): fase 2 — Avaliação de disciplina + controle de qualidade

Norte definido com o Clovis a partir do `Modelo de Planilha - Dados.xlsx` (levantamento da PRF):
o produto principal é a **planilha de Avaliação por livro/disciplina, 100% automática** (sem
colunas de julgamento — decisão dele), com o motor de pendências por trás. Mockups iterados
até aprovação (v6) e modelo de QC publicado como Artifact. Specs/planos:
`docs\superpowers\{specs,plans}\2026-07-06-*`.

**Construído (branch `feat/fase2-avaliacao-qualidade`, TDD, 38 testes verdes):**
- **Coletor v1.1**: banca/ano das questões (objeto `exams.year`+`badges` — a listagem
  `authors_name` vem `None`; nomes agora do `GET /bo/ldi/courses/{id}` → `structured_authors`),
  tópicos (`path_name`), **detector de questões coladas no texto** (regex `(BANCA/ANO/...)`
  no conteúdo tiptap durante a coleta — só metadados, nunca o texto), migração idempotente
  (colunas `banca`/`ano`/`qtd_questoes_texto` + índice `ix_blocos_item`).
- **`regras_qualidade.py`**: catálogo declarativo (Q1/Q2/V1/V2/C1/A1/A3/B1; A2 informativa),
  pendências materializadas com chave determinística, **baixa automática** no snapshot
  seguinte (resolvida sozinha se sumiu; reabre se voltou; ignorada nunca reabre). Roda ao
  fim de cada coleta.
- **`painel.py` + `avaliacao.html`**: rota `/avaliacao` — seletor de disciplina + banca-alvo
  (opcional), tabela por capítulo (questões emb.+texto, bancas, % por ano da prova, soluções
  📝/🎬, vídeos qtd·tempo, % por ano de gravação real via cache do de→para), dashboard e
  ⬇CSV. APIs: `/api/cursos`, `/api/avaliacao`, `/api/pendencias/resumo`.

**Verificado com dados reais (snapshot #2 do BACEN, 07/07):** 99,4% das questões com banca
(40.726; CESPE 16.890), 997 questões em texto, professores em 126/128 cursos, 157.309
pendências (Q1 críticas 33.262 · Q2 108.341 · V1 8.940 · V2 11 · A1 3.457 · A3 3.277 ·
C1 21). `/avaliacao` do Direito Penal bate com o mockup aprovado.

**⚠ Notas para a próxima sessão:**
- **Q2 (questão desatualizada) gerou 108 mil pendências** — a régua por questão é fiel à
  decisão do Clovis, mas o volume sugere discutir agregação por aula no acionamento (fase 2.1).
- **Fase 2.1 (backlog priorizado):** tela rica de Pendências (mockup v3: por professor/curso,
  status enviada/resolvida na tela, relatório/CSV de acionamento) — o motor e a API já dão
  o dado; falta a tela. Investigar também o `block_type_count` da árvore (conta versões:
  163 vs 53 no Direito Penal) e o capítulo vazio ("24. Crimes..." com 0 aulas) que a tela expôs.
- Coletas antigas (snapshot #1) não têm banca/questões-texto (colunas NULL) — normal.

## ✅ Sessão 7 (12–19/07): publicação web — fundação Supabase NO AR

Decisão do Clovis: publicar o Painel de Conteúdo como **app web de leitura para o time**
(Supabase = fonte, Vercel = vitrine; a coleta continua local). Spec aprovado:
`docs\superpowers\specs\2026-07-12-publicacao-web-supabase-vercel-design.md`; plano:
`docs\superpowers\plans\2026-07-12-fundacao-dados-nuvem-supabase.md`.

**Construído (branch `feat/publicacao-web-supabase-vercel`, TDD, 43 testes verdes):**
- `supabase/schema.sql` — tabelas `snapshot`/`avaliacao_curso`/`pendencia_resumo` +
  view `snapshot_atual` (só `pronto=true`) + RLS (leitura `authenticated`, escrita só
  `service_role`). Idempotente.
- `sync_supabase.py` — reusa a agregação do `painel.py` (zero divergência com a tela)
  e faz upsert atômico via PostgREST (snapshot só vira `pronto` no final).
- Gancho não-fatal no `coletor_ldi.py`: publica ao fim de cada coleta.

**✅ Verificado com dados reais (18-19/07):** projeto Supabase criado na **conta da
Estratégia** (ref `zpjsoidxhfwziprjxpqx` — NUNCA usar o Supabase pessoal do Clovis),
schema aplicado via Management API, `py sync_supabase.py` publicou o snapshot #2 do
BACEN: **107 cursos em `avaliacao_curso`, 7 linhas de pendência, `pronto=true`**.
Sem credencial → 401 (RLS ok).

**Credenciais:** `supabase.json` na raiz (gitignored) com `{url, service_key}` —
se sumir de novo, pegar no Dashboard da conta Estratégia → Settings → API. O access
token `sbp_...` usado para aplicar o schema pode (deve) ser revogado — o sync do dia
a dia só precisa de URL + service_role.

**⚠ Próximos passos da sessão 8:** (a) push da branch (7+ commits locais; o Clovis faz o
login interativo); (b) **app Next.js no Vercel** — login Supabase Auth magic-link +
telas lendo `snapshot_atual`/`avaliacao_curso`/`pendencia_resumo` (o payload já vem
mastigado do sync; o front só renderiza o mesmo `{data: ...}` do painel local).

## ✅ Sessão 8 (19/07): app web construído (falta só a config manual)

Plano executado com subagentes (implementador + revisor por task, 2 fixes de revisão):
`docs\superpowers\plans\2026-07-19-app-web-vercel.md`. **App Next.js completo em `web\`**
(subpasta deste repo; Vercel com Root Directory = `web`):

- **Auth**: login magic-link por convite (`shouldCreateUser:false`), sessão em cookie via
  `@supabase/ssr`, middleware gate (sem sessão → `/login`), `/auth/confirm` (token_hash) e
  `/auth/sair`.
- **Desvio consciente do spec**: em vez de `supabase-js` direto no navegador (sessão em
  localStorage, incompatível com o gate por cookie), as telas continuam chamando `/api/...`
  e handlers Next consultam o Supabase com o JWT do usuário (RLS `authenticated` vale igual).
  Telas com **zero mudança de fetch**.
- **Telas**: `web\telas\{painel,avaliacao}.html` = cópias das da raiz + 3 edições cada
  (link sair, selo "Dados de DD/MM HH:MM", estado vazio). **As telas da raiz não mudaram**
  (byte-idênticas fora das edições — verificado com diff na revisão). Rota `/` injeta
  `__DADOS__` como o Flask; `/avaliacao` consome `/api/cursos` + `/api/avaliacao`.
- Build limpo, gate verificado por curl (307 → /login). `.env.local` gitignored
  (anon key placeholder até o Clovis colar a real).

**Acesso por domínio + tela /admin (mesma sessão, spec+plano 2026-07-19):**
@estrategia.com entra direto pelo login (auto-provisionado via admin API, `disable_signup`
segue ligado); externos só por convite, agora pela tela **`/admin`** (convidar/listar/
remover; admin = `app_metadata.role="admin"`, hoje só o Clovis — já gravado no usuário).
Service_role server-only em `web\lib\supabase\admin.ts` (`SUPABASE_SERVICE_KEY`, sem
NEXT_PUBLIC_; conferido ausente do bundle do navegador). E-mail: SMTP do **Resend**
plugado no Supabase Auth (remetente painel@infosab.com.br), signup off, templates pt-BR,
rate limit 30/h. Convite enviado ao Clovis (pendente de aceite no 1º teste).

**⚠ Para o app entrar no ar falta SÓ a config manual (Task 5 do plano):** anon key no
`.env.local`, Dashboard Auth (desligar signup, 2 templates de e-mail com token_hash,
convidar e-mails, Site URL/Redirect URLs), projeto Vercel (Root Directory `web`, Node 22+,
2 env vars) e a verificação de paridade dos números contra o painel local (critério de
aceite). Checklist detalhado na Task 5 do plano.

## ✅ Sessão 9 (21/07): Fase 4 — coleta, cookie e fila pela interface web

Especificada e executada em cima da Fase 3 (worker no VPS já no ar): agora dispara-se
coleta, renova-se o cookie e gere-se a fila **pelo app web** — o Clovis sai da linha de
comando. Spec: `docs\superpowers\specs\2026-07-21-fase4-tela-coleta-design.md`; plano
executado por subagentes (implementador + revisor por task, 1 fix Important).

**Construído (branch `feat/fase4-tela-coleta`, 6 commits):**
- **Papel `operador`** — `web\lib\papeis.ts` (`exigirPapel`/`exigirAdmin`/`exigirOperador`,
  re-checado no servidor em toda action); seletor de papel por usuário no `/admin`
  (`definirPapel`, só admin, não muda o próprio papel).
- **Cookie do LDI pelo `/admin`** (só admin): campo colar `__Secure-SID` (aceita valor puro
  ou header completo) → upsert `config_ldi` via service_role. A tela mostra só o
  `cookie_status` derivado (o valor do cookie nunca chega ao cliente — `config_ldi` sem
  policy de leitura). Rota nova `GET /api/cookie-status`.
- **Banner de cookie** nas 4 telas: `BannerCookie.tsx` (React, `/admin` e `/coleta`) +
  snippet fetch nas cópias vanilla `web\telas\{painel,avaliacao}.html` — vermelho vencido,
  amarelo ≤3 dias (usa `--crit`/`--warn`, dark ok). Telas da raiz intocadas.
- **Tela `/coleta`** (admin+operador; outros → 404): disparo por termo OU IDs+rótulo
  (cola a URL do admin; `extrairIds` em `web\lib\coleta.ts` = porta fiel do Python, 6/6
  checks Node — nunca pega `team_id=`); fila com polling 5s (`/api/fila`) e ações só-admin
  cancelar/retentar/cancelar-em-andamento. **Transições atômicas** (fix da revisão: update
  condicional `.in("status", esperados)` — fecha corrida com o worker; zero linhas
  atualizadas = "status mudou", nada é sobrescrito).
- Todas as 6 tasks revisadas (spec+qualidade); build limpo em cada uma; bundle conferido
  sem service key/cookie.

**⚠ Pendências da sessão 9 (aceite manual do Clovis):**
1. Push da branch + PR → `main` (login interativo do Clovis; merge deploya no Vercel).
2. Aceite do spec: operador dispara → worker (VPS) processa → concurso no seletor;
   admin cola cookie novo → `cookie_status` reflete; forçar `valido=false`/`dias=2` no
   Supabase e conferir o banner nas 4 telas; cancelar/retentar/cancelar-em-andamento.
3. Conceder papel `operador` a quem for disparar coletas (seletor no `/admin`).
4. Minors deferidos (lista no ledger `.superpowers/sdd/progress.md`): texto do banner
   expandido além do brief (confirmar), `import "server-only"` em `lib/coleta.ts`,
   `dataLocal` duplicado, marcador `__Secure-SID=` case-sensitive.

---

## 🔑 Coisas que a próxima sessão PRECISA saber

### Cookies (dois sistemas, dois cookies diferentes)
- **LDI (admin)**: `cookie.txt` na pasta do projeto. Só o `__Secure-SID` importa,
  vale **~30 dias** (o atual expira **05/08/2026**) — mas pode ser invalidado antes
  pelo servidor (relogin derruba a sessão antiga: `AUTH.USER_SESSION_NOT_FOUND`).
  Trocar pela tela do Visualizador (botão 🍪) ou editando o arquivo. Jeito à prova
  de engano de pegar o novo: F12 → **Application** → Cookies → copiar o Value de
  `__Secure-SID` (a aba Network guarda requisições velhas com o cookie morto).
- **Metabase**: reusa a auth do app de Limpeza em
  `C:\⚙️ Aplicativos\🦉 Relatório de Cursos - Árvores - Professores\6. Limpeza Unificada de Dados`
  (`metabase_cookies.json` de lá). Cookie do Cloudflare vale **~24h** e **exige o Warp
  ativo**. Recarregar colando o header em `cookies.txt` DENTRO da pasta da Limpeza
  (o app apaga o arquivo após ler, por segurança).

### Armadilhas já resolvidas (não repetir)
- **ID com ponto de milhar**: o ID antigo aparece no nome como `videosintra248.487`
  (= 248487). A regex antiga parava no ponto e casava o vídeo errado. **Já corrigido**
  (pega só dígitos). Se mexer na extração de ID, manter isso em extrator+ui+depara.
- **Prova por duração**: `depara_confere` compara a duração LDI×Metabase. O Metabase às
  vezes arredonda ao minuto (`:00`) → tolerância adaptativa (60s se arredondado, senão 5s).
- **Question 19885 ignora o parâmetro `id_video` via API** → baixamos a tabela inteira
  (~540 mil linhas, ~1 min) e casamos localmente. Cache gzip 7 dias em
  `saida\metabase_depara.json.gz`.
- **Porta 8765 aceita bind duplo no Windows**: se a tela servir código velho, matar
  instâncias antigas de python/VisualizadorLDI (conferir CommandLine — NÃO tocar no
  python de `src\backend\app.py`, que é outro app).
- Ao mudar `ui.html` ou `visualizador.py`, **reempacotar** o VisualizadorLDI.exe
  (a ui.html vai embutida via `--add-data`).

---

## 🚧 Backlog / próximos passos possíveis

1. **Revisar os 3 casamentos ambíguos** (filtro "Casados mas duração diverge ⚠" na tela).
2. **Outros concursos** (PF, Receita…): mudar o termo e rodar o mesmo ciclo.
3. **Expandir para o sistema inteiro** (~123 mil cursos): trocar CSV/JSON por **SQLite
   local** (padrão do MEU_NOTION), primeira carga noturna retomável + sync incremental
   diário via `updated_at`. Fundação já pronta; é a evolução natural.
4. Opcional: botão "importar de→para" na tela e/ou agendamento diário do ciclo completo.

---

## 🗂️ Arquivos da pasta (referência)

| Arquivo | O quê |
|---|---|
| `ExtratorLDI.exe` / `extrator_ldi.py` | Extração do LDI |
| `depara_metabase.py` / `_depara_metabase.bat` | Cruzamento com o Metabase |
| `VisualizadorLDI.exe` / `visualizador.py` + `ui.html` | Tela analítica |
| `estoque.html` (rota `/estoque`) | Árvore de vídeos dos professores p/ consulta e copiar IDs |
| `config.json` | termo_busca, filtro_local, pasta_saida |
| `cookie.txt` | Cookie do admin LDI (só `__Secure-SID` conta) |
| `analises.json` | Análises salvas na tela (contextos nomeados) |
| `propostas.json` | Propostas de substituição de vídeos (cadastradas na tela) |
| `EXTRATOR-LDI-VIDEOS.js` | Plano B: extração pelo console do navegador |
| `saida\` | CSVs/JSONs de resultado + cache do de→para |
| `TUTORIAL.md` | Passo a passo leigo de tudo |
