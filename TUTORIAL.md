# 🎬 Extrator LDI — Tutorial

Extrai do admin da Estratégia (LDI) a lista de **cursos → capítulos → aulas → vídeos**,
com ID, duração, data de criação e o **ID da plataforma antiga** de cada vídeo.

> 🔒 **Somente leitura.** Só faz consultas (GET). Não altera, não exclui, não publica nada.

Há duas formas de usar. **A recomendada é o aplicativo (.exe)** — roda sem navegador,
grava direto na pasta `saida\` e pode ser agendado para todo dia.

---

# PARTE A — Aplicativo `ExtratorLDI.exe` (recomendado)

## Passo 1 — Colar o cookie (só na primeira vez, e quando vencer)

O app entra na API usando a sua sessão do admin. Para isso ele precisa do "cookie"
(o crachá da sua sessão). Pegar ele leva 1 minuto:

1. Abra o Chrome em `https://admin.estrategia.com`, **logado**.
2. Aperte **F12** e clique na aba **Network** (ou **Rede**).
3. Aperte **F5** para recarregar a página (a lista da aba vai encher).
4. Na caixinha de filtro da aba Network, digite: `api.estrategia.com`
5. Clique em **qualquer linha** da lista (ex.: `courses` ou `filters`).
6. No painel que abre à direita, fique na aba **Headers** (Cabeçalhos) e desça até
   **Request Headers** (Cabeçalhos da solicitação).
7. Ache a linha que começa com **`cookie:`**. Clique 3 vezes seguidas em cima do
   texto do valor (isso seleciona ele inteiro — é um texto bem comprido) e copie
   com `Ctrl + C`.
8. Abra o arquivo **`cookie.txt`** (nesta pasta) no Bloco de Notas, **apague tudo**
   que estiver nele, cole (`Ctrl + V`) e salve (`Ctrl + S`).

> 💡 Pode colar com ou sem o `cookie:` do começo — o app entende os dois.

## Passo 2 — Rodar

- Dê **2 cliques em `ExtratorLDI.exe`**. Só isso.
- A janela mostra o progresso e, no final, os arquivos ficam em:
  - `saida\videos_PRF_2026-07-02.csv` ← abre direto no Excel
  - `saida\videos_PRF_2026-07-02.json` ← para sistemas
- Para a PRF leva de 2 a 5 minutos (≈ 1.100 consultas, uma por aula com vídeo).

## Trocar o concurso pesquisado

Duas opções:

- **No `config.json`** (Bloco de Notas): mude `"termo_busca": "PRF"` para
  `"PF"`, `"Receita Federal"`, etc. e salve.
- **Sem mexer no config** — atalho ou prompt com parâmetro:
  `ExtratorLDI.exe --termo "PF"`

Outras opções do `config.json`:

| Chave | Para quê |
|---|---|
| `filtro_local` | Regex opcional p/ manter só cursos cujo nome bate. Ex.: `"PRF\|Rodovi"` elimina "intrusos" que a busca trouxer |
| `pasta_saida` | Onde salvar os arquivos (padrão: `saida`) |
| `incluir_url` | `false` = CSV sem a coluna do link do vídeo (fica mais leve) |
| `concorrencia` | Consultas simultâneas (padrão 4 — não precisa mexer) |

## Rodar todo dia sozinho (Agendador do Windows)

1. Menu Iniciar → digite **Agendador de Tarefas** → abra.
2. À direita: **Criar Tarefa Básica...**
3. Nome: `Extrator LDI PRF` → Avançar → **Diariamente** → escolha o horário → Avançar.
4. Ação: **Iniciar um programa** → em "Programa": clique Procurar e escolha o
   `ExtratorLDI.exe` → em **"Adicione argumentos"** escreva: `--agendado`
   → em **"Iniciar em"** cole o caminho da pasta:
   `C:\⚙️ Projetos_Dev\🎬 EXTRATOR_LDI_VIDEOS`
5. Concluir. Cada dia sai um CSV novo datado na pasta `saida\`.

## Quando o cookie vencer

Em algum momento a sessão expira e o app avisa:

```
[ERRO] A API respondeu 401 (não autenticado).
       O cookie venceu — atualize o cookie.txt
```

É só repetir o **Passo 1** (2 minutos) e rodar de novo.

---

# PARTE B — Visualizador (tela analítica) 📊

Dê **2 cliques em `VisualizadorLDI.exe`** (ou no `_abrir_visualizador.bat`).
Ele abre o navegador sozinho em `http://127.0.0.1:8765` com:

- **Árvore Cursos → Capítulos → Aulas → Vídeos**, com contagens e duração por ramo;
  na linha do **curso**, o botão **↗** antes do nome abre o curso direto no LDI Admin
  (`admin.estrategia.com/#/concursos/ecommerce/produtos/<id>`) em nova aba.
  ⚠ O admin é um app de página única: se a aba nova cair na **raiz** (`#/`) por causa
  do login, o link já foi **copiado automaticamente** — cole na barra de endereço
  dessa aba e dê Enter;
- **KPIs**: cursos, aulas, vídeos, duração total, tamanho, vídeos **sem ID antigo**, erros;
- **Gráficos**: vídeos por ano de entrada no acervo + top 10 cursos por duração;
- **Filtros**: busca livre, **seleção de cursos** (marque 1, 2 ou quantos quiser —
  vazio = todos; tem busca na lista e "Limpar seleção"), ano, professor/equipe,
  tipo de bloco, publicado, rascunho, duração, com/sem ID antigo, só erros;
- **Detalhes**: clique num vídeo → painel com todos os campos e botões "copiar";
- **Exportar filtro (CSV)**: baixa só o que está filtrado na tela;
- **⧉ Copiar** (na barra da árvore): copia a tabela filtrada para a área de
  transferência — é só colar no Excel/Sheets (colunas: curso, capítulo, aula,
  vídeo, ID antigo, duração, anos, tipo, de→para...);
- **📄 Relatório** (na barra da árvore): gera um arquivo HTML único com a árvore
  no **mesmo layout da tela** (hierarquia, selos, durações), respeitando os
  filtros ativos — bom para arquivar ou compartilhar; Ctrl+P nele vira PDF;
- **🍪 Cookie**: o selo no canto mostra o status e a validade (fica verde/amarelo/
  vermelho); clicando nele você vê os detalhes e **cola um cookie novo** sem mexer
  em arquivo;
- **🔄 Nova extração**: roda o extrator direto da tela, com barra de progresso, e
  carrega os dados novos ao terminar;
- **✕ Remover curso**: passe o mouse na linha do curso e clique no ✕ do canto —
  ele sai de TODOS os números, gráficos e da árvore. A lista "🚫 Cursos removidos"
  aparece nos filtros, com "restaurar" individual ou "Restaurar todos";
- **💾 Análises salvas**: o botão "💾 Análises" salva o contexto completo com um
  nome (extração + filtros + cursos removidos). Para voltar a ele depois, use o
  seletor "📌 Análises…" no topo. Tudo fica no arquivo `analises.json`, ao lado do
  aplicativo (entra no backup da pasta);
- **📝 Propostas de substituição**: passe o mouse num **capítulo, aula ou vídeo**
  da árvore e clique no **📝** que aparece à direita. Abre um formulário que já
  mostra os **vídeos atuais** daquele ponto (nome, duração, ano de gravação e ID)
  e onde você cadastra os **vídeos propostos** (nome + ID), uma observação para o
  time e o status (🟡 proposta / 🔵 enviada / 🟢 atendida). O alvo ganha um selo
  **💡 N proposto(s)** na árvore. Tudo fica no arquivo `propostas.json`, ao lado
  do aplicativo — as propostas valem para qualquer extração carregada;
- **✏️ Preencher IDs (modo coluna)** — o jeito RÁPIDO de propor substituições:
  clique em **✏️ Preencher IDs** na barra da árvore e aparece um campo na frente
  de **cada capítulo, aula e vídeo**. Digite os IDs dos vídeos substitutos
  (ex.: `245017 245018` — espaço ou vírgula, tanto faz) e dê **Tab ou Enter**:
  - salva sozinho como proposta (sem abrir formulário nenhum);
  - o **nome do vídeo vem automaticamente do estoque** pelo ID — passe o mouse
    no campo para conferir (borda **verde** = todos os IDs achados; **amarela** =
    algum ID não existe no estoque);
  - esvaziar o campo remove a proposta (observações feitas no 📝 são preservadas);
  - o 📝 continua servindo para observação, status e revisão fina.
- **🌳 Estoque** (botão no topo): abre **em outra aba** a árvore de vídeos dos
  professores — escolha o professor, navegue pelos tópicos e clique em **⧉ ID**
  para copiar. Deixe as duas abas lado a lado: consulta o estoque numa, cola o
  ID na outra. Somente consulta, nada de mexer no sistema.
  **De onde vêm os dados do estoque:** a fonte preferencial são as árvores
  **`arvore_*.xlsx`** exportadas pela Limpeza (pasta `downloads_metabase`) —
  são as mais atuais e trazem **todos** os locais de cada vídeo; professores
  cobertos por elas aparecem com o selo **🌿**. Quem não tem árvore exportada
  vem da base ampla (question 19885 do de→para). Exportou uma árvore nova na
  Limpeza? O Visualizador percebe sozinho na próxima consulta;
- **Professor certo, sem adivinhar**: no 🤖, o professor NÃO é deduzido pelo
  nome do curso — o sistema olha as **raízes onde os vídeos já vinculados
  vivem** (via de→para) e mostra chips "🎯 detectado pelos vídeos vinculados"
  (ex.: Constitucional → Adriane Fauth). Um clique carrega a árvore certa;
- **🤖 Sugerir do estoque** (dentro do formulário de proposta): a automação que
  monta a proposta para você. Ela usa a base do de→para (PARTE C) como **estoque
  dos professores** e funciona em 3 passos:
  1. **Professor** — já vem pré-preenchido com o professor do curso; a lista
     mostra as raízes da árvore antiga que batem com o nome;
  2. **Tópicos a varrer** — a lista de tópicos do professor vem **ordenada por
     semelhança com o nome do alvo** (🎯 = muito parecido; o melhor já vem
     marcado). Marque os que quiser varrer;
  3. **🔎 Buscar sugestões** — o sistema compara cada vídeo do estoque com os
     vídeos atuais do alvo **por similaridade de nome** (ignora acentos,
     maiúsculas, numeração e o ID no nome — pega até erro de digitação).
     Os muito parecidos com um vídeo atual e **com ID diferente** (provável
     regravação) já vêm pré-marcados; os com o mesmo ID aparecem como "já está
     no alvo"; o resto aparece como "novo". Revise, marque o que quiser e clique
     **➕ Adicionar** — as linhas nome + ID entram na proposta prontas;
- **📋 Central de propostas**: o botão "📋 Propostas" no topo lista tudo o que
  foi cadastrado, agrupado por curso, com edição e exclusão. Dali saem:
  - **📄 Gerar relatório (HTML)** — arquivo único e limpo (curso → tópico →
    vídeos atuais × vídeos propostos + observação), pronto para mandar por
    e-mail/Teams. Abre em qualquer navegador e **Ctrl+P vira PDF**;
  - **⬇ CSV** — as mesmas informações em planilha (uma linha por vídeo proposto).

> A janela preta que abre junto é o servidor — **deixe aberta** enquanto usa a tela.
> Para fechar o app, feche essa janela.

⚠️ **Atenção às datas:** a coluna `video_criado_em` é a data em que o vídeo **entrou
no acervo novo** (LDI) — NÃO é a data de gravação. A data real de gravação virá do
cruzamento (de→para) do **`video_id_antigo`** com o sistema antigo (Metabase).

⚠️ **Blocos "cast" ficam fora da análise por padrão** (os dados deles não batem com
o acervo de vídeos). O checkbox `cast` em "Tipo de bloco" começa desmarcado — dá
para religar manualmente se algum dia precisar.

---

# PARTE C — De→para Metabase (data real de gravação) 🎯

O nome dos vídeos carrega o ID do sistema antigo; a question **19885 (Videos BO)**
do Metabase devolve a **data real de gravação** e a localização na árvore antiga.
O script `depara_metabase.py` faz o casamento inteiro sozinho:

1. **Cookie do Metabase**: ele reutiliza a sessão do app de Limpeza
   (`6. Limpeza Unificada de Dados\metabase_cookies.json`). Quando vencer
   (o Cloudflare dura ~24 h), cole o cookie novo em `cookies.txt` **na pasta da
   Limpeza** (mesmo ritual: DevTools → Network → linha `cookie:`) e rode de novo.
2. **Warp precisa estar ativo** (sem ele não há rota até o Metabase).
3. Dê 2 cliques em **`_depara_metabase.bat`**. Ele:
   - baixa a tabela inteira (~540 mil linhas, ~1 min) e guarda um resumo local
     comprimido (`saida\metabase_depara.json.gz`) válido por 7 dias — nas
     próximas rodadas nem consulta o Metabase (use `--refresh` para forçar);
   - casa com o levantamento mais recente (`--arquivo x.json` para escolher outro);
   - atualiza o JSON + CSV com as colunas novas.

| Coluna nova | O que é |
|---|---|
| `gravacao_data` / `gravacao_ano` | **Data/ano REAL de gravação** (sistema antigo) |
| `mb_status` | Status do vídeo no sistema antigo (ex.: Disponível) |
| `mb_titulo` | Título no sistema antigo (para conferência) |
| `mb_raiz` / `mb_arvore_path` | Raiz e caminho completo na árvore antiga |
| `mb_duracao` | Duração no sistema antigo (usada para conferir o casamento) |
| `mb_qtd_locais` | Em quantos pontos da árvore antiga o vídeo aparece |
| `depara_ok` | `sim` = casou; `nao` = tem ID mas não achou no Metabase |
| `depara_confere` | Prova por duração: `sim` = LDI e antigo têm a mesma duração (±5s); `nao` = divergem (casamento suspeito); vazio = falta a duração de um dos lados |

> 🔎 **Prova por duração:** o ID do vídeo aparece no nome com **ponto de milhar**
> em alguns casos (`videosintra248.487` = ID 248487). O script já lê isso certo.
> Para pegar qualquer casamento errado que sobre, ele compara a duração dos dois
> lados — o filtro "Casados mas duração diverge ⚠" na tela isola esses casos.
> (Essa coluna só é preenchida após um `--refresh` feito com o Warp ativo.)

No visualizador, o de→para aparece como: gráfico **"ano de gravação real"**,
chips de filtro por ano de gravação, seletor "De→para Metabase", KPI "% com data
real", selo verde 🎥 com o ano em cada vídeo e um bloco "Sistema antigo" no
painel de detalhes.

**Fluxo completo de um concurso novo:** `ExtratorLDI.exe` (ou 🔄 na tela) →
`_depara_metabase.bat` → abrir o `VisualizadorLDI.exe`.

---

# PARTE C½ — Painel de Conteúdo (novo): avaliação de disciplinas e qualidade

Além dos vídeos, dá para auditar **todo o conteúdo** de um concurso (questões com banca e
ano, questões coladas no texto, PDFs, vídeos com idade de gravação):

1. **Coletar**: 2 cliques em `ColetorLDI.exe` (ou `py coletor_ldi.py --termo BACEN`).
   Usa o mesmo `cookie.txt` do extrator. Leva alguns minutos e guarda tudo em
   `saida\conteudo.db` — cada rodada vira um "retrato" datado; nada é sobrescrito.
   Se cair no meio (ou o cookie vencer), rode de novo com `--continuar`.
2. **Abrir o painel**: `PainelLDI.exe` (ou `py painel.py`) → abre `http://127.0.0.1:8766`.
   - A página inicial mostra o inventário do concurso (cursos, aulas, blocos por tipo)
     e os achados de qualidade;
   - **📋 Avaliação de disciplina** (`/avaliacao`): escolha o curso e a banca-alvo
     (opcional) → sai a planilha por capítulo com questões (banca, ano, soluções em
     texto/vídeo) e vídeos (tempo e período de gravação real). **⬇ CSV** abre no Excel;
     🖨 vira PDF.
3. **Pendências**: a cada coleta o sistema compara com a anterior e dá baixa sozinho no
   que foi corrigido no BO (questão que ganhou solução some da lista, por exemplo).

A idade real de gravação dos vídeos usa o mesmo de→para do Metabase da PARTE C — rode o
`_depara_metabase.bat` de vez em quando para manter o cache fresco.

---

# PARTE D — Script de console (alternativa, sem instalar nada)

O arquivo `EXTRATOR-LDI-VIDEOS.js` faz a mesma extração colado no console do
navegador (F12 → Console → colar → Enter), com a página do admin aberta e logada.
Os arquivos caem na pasta Downloads. Útil como plano B ou em outro computador.

- Se o Chrome não deixar colar: digite `allow pasting` no console e cole de novo.
- Se perguntar "Permitir downloads múltiplos?": clique **Permitir**.
- Para trocar o concurso: edite `const TERMO_BUSCA = 'PRF'` no topo do arquivo.

---

# O que significa cada coluna

| Coluna | O que é |
|---|---|
| `curso_id` | ID do curso no LDI (UUID) |
| `curso_nome` | Nome completo do curso |
| `curso_publicado` | `sim`/`nao` |
| `curso_criado_em` | Data de criação do curso |
| `professores` | Autores do curso |
| `capitulo_ordem` / `capitulo_nome` | Posição e nome do capítulo (aula 00, 01...) |
| `capitulo_versao` | Versão do capítulo no LDI |
| `capitulo_publicado` | Data de publicação do capítulo |
| `aula_path` / `aula_nome` | Posição (ex.: `1.3`) e nome do item/aula |
| `item_id` | ID do item (usado para buscar os blocos) |
| `bloco_tipo` | `videoMyDocuments` (vídeo comum), `cast` ou `youtube` |
| `bloco_rascunho` | `sim` = bloco ainda em rascunho |
| `bloco_criado_em` | Quando o bloco foi inserido no material |
| `video_id` | **Código único do vídeo** (UUID no acervo novo; número no cast) |
| `video_nome` | Nome de exibição do vídeo |
| `video_nome_original` | Nome do arquivo original — **carrega o código legado** (ex.: `ed_bcaldas_INT1110062785_videosintra116648_01`) |
| `video_intra_id` | ID "INT" que aparece no nome original (ex.: `1110062785`) |
| `video_id_antigo` | **ID do vídeo no sistema antigo** (4-6 dígitos do final do nome / `videosintra`) ← **chave do de→para no Metabase** |
| `video_duracao` | Duração `HH:MM:SS` |
| `video_duracao_seg` | Duração em segundos (para somar no Excel) |
| `video_criado_em` | Data de **entrada no acervo novo** (⚠ não é a data de gravação — essa virá do de→para) |
| `video_tamanho_bytes` | Tamanho do arquivo |
| `video_url` | Endereço do arquivo de vídeo (link assinado) |
| `erro` | Preenchida quando a aula não retornou blocos (raro) |

---

# Problemas comuns

| Sintoma | Causa / solução |
|---|---|
| `[ERRO] ... 401 (não autenticado)` | Cookie venceu ou foi colado incompleto — refaça o Passo 1 |
| `cookie.txt está vazio` | Cole o cookie no arquivo (Passo 1) |
| Nenhum curso encontrado | Confira o `termo_busca` — a busca é por palavra exata no nome |
| Veio curso que não é do concurso | Filtre por `curso_nome` no Excel ou use `filtro_local` |
| Demorando muito | Normal: 1 consulta por aula com vídeo (PRF ≈ 1.100) |
| Windows alertou sobre o .exe | Normal em .exe caseiro (SmartScreen): "Mais informações" → "Executar assim mesmo" |

---

# Nota técnica (para manutenção futura)

- API: `https://api.estrategia.com/bo/ldi/...` — exige header `x-vertical: concursos`
  e o cookie de sessão do admin (HttpOnly, por isso é copiado do DevTools).
- Sem cookie → `401 AUTH.NOT_AUTHENTICATED`; com cookie → 200. Não há bearer token
  necessário: o cookie basta.
- Busca de cursos: `GET /bo/ldi/courses?...&search_term=PRF` (o `meta.total` ignora
  o filtro; paginar até vir página incompleta; 100 por página).
- Árvore (capítulos/aulas) já vem na listagem, campo `content_tree_cache`.
- Blocos de uma aula: `GET /bo/ldi/blocks?item_id={item_id}` — vídeos são blocos
  `videoMyDocuments`/`cast`/`youtube`, dados em `data.resolved`
  (id, name, original_name, intra_video_id, video_duration, created_at, file_size).
- Filtros do admin por classificação (`POST /filters-values`) têm paginação quebrada
  (máx. 100 opções) e o filtro "Concurso" (type `goal`) retorna sempre vazio — por
  isso a tela "não acha" e a extração usa `search_term`.
- Dos ~39 cookies do admin, a API só exige o **`__Secure-SID`** (JWT com validade de
  ~30 dias). O `CF_Authorization` (Cloudflare, 24 h) é só do site, não da API — por
  isso o cookie colado dura um mês.
- `video_id_antigo`: regex `videosintra(\d+)` no `original_name`; fallback
  `[-–—]\s*(\d{4,7})$` no nome de exibição.
- Rebuild dos .exe (Python 3.12 + requests + Flask + PyInstaller 6.14):
  - `py -m PyInstaller --onefile --clean --name ExtratorLDI extrator_ldi.py`
  - `py -m PyInstaller --onefile --clean --name VisualizadorLDI --add-data "ui.html;." --add-data "estoque.html;." visualizador.py`
    (usar caminho **absoluto** nos `--add-data` se rodar com `--specpath`)
