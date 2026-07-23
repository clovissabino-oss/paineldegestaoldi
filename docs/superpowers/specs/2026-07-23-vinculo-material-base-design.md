# Vínculo com o Material Base (por item) — design

_Data: 2026-07-23 · Autor: Clovis + Claude · Status: aprovado no chat (blocos 1–3)_

## Objetivo

Mostrar, no Painel de Conteúdo, **quantos itens de cada curso estão vinculados ao
Material Base (MB)** do professor — o local oficial onde ele guarda as aulas que usa nos
cursos. Serve para auditar se o professor de fato armazenou todo o conteúdo no MB. A tag
"Vinculado ao MB" existe na tela do admin, mas não era exposta em lugar nenhum das nossas
telas.

## Descoberta técnica (validada com dados reais em 23/07)

- A tag vem do campo booleano **`has_base_material`**, que existe **por item**.
- Fonte confiável: **`GET /bo/ldi/chapters/{chapter_id}/items`** → `data[]`, cada item com
  `has_base_material`. Uma chamada por capítulo (barata).
- **O item-level diverge do capítulo-level** e é o único confiável:
  - `courses/{id}/chapters?...&load_has_base_material=true` dá um `has_base_material`
    **por capítulo** que **subnotifica grosseiramente** (DMAE: 1/36 capítulos, mas
    **319/345 itens**). NÃO usar como métrica.
  - Existem capítulos "mistos" (itens vinculados e não-vinculados no mesmo capítulo):
    Amparo 1, DMAE 7 — prova de que contar por item agrega informação real.
- Números de referência (aceite): **Amparo 68/75 (91%)**, **DMAE 319/345 (92%)**.
- O endpoint que a coleta usa hoje (`courses/{id}` → `content_tree_cache`) traz o campo
  por item, porém sempre `false` — por isso é obrigatório o passo novo por capítulo.

## Arquitetura

Segue o pipeline existente do Painel de Conteúdo (coletor → `conteudo.db` → `painel.py`
→ telas + `sync_supabase.py`). Terminologia LDI: Curso → **Aula** (capítulo) → **Item**
(tópico) → **Bloco**.

### 1. Coleta — novo passo `_completar_vinculo_mb` (`coletor_ldi.py`)

- Espelha `_completar_autores`: após `gravar_arvore`, varre os capítulos de cada curso
  (o `chapter_id` já está no `content_tree_cache`), chama `chapters/{id}/items` em paralelo
  (respeitando `cfg["concorrencia"]`), monta `{item_id: has_base_material}`.
- Reusa o tratamento de auth existente: 401/403 → `CookieVencido`; falha pontual de
  capítulo registra e segue (não derruba a coleta) — mesmo espírito de `_baixar_lote`.
- Grava `vinculado_mb` (INTEGER 0/1, nulo = desconhecido) na tabela de **aulas/itens** do
  `conteudo.db` (`banco_conteudo.py`), por `(extracao_id, item_id)`. Migração idempotente
  (`ALTER TABLE ... ADD COLUMN vinculado_mb` sob `try/except`, padrão do projeto).
- Snapshots antigos ficam com `vinculado_mb` NULL (normal — as telas tratam como "—").

### 2. Agregação (`painel.py`)

- **Inventário** (`dados` da visão geral): novos campos no resumo por curso e no total —
  `itens_mb` (vinculados) e `itens_total` (com flag conhecido). % = itens_mb/itens_total.
- **Achado de auditoria**: `aulas_com_item_fora_mb` = nº de aulas com ≥1 item não-vinculado
  (inclui capítulos mistos e totalmente fora). Entra na lista de achados como as demais
  regras (contável, formato dos "achados" existentes).
- **Avaliação** (`dados_avaliacao`): por aula (capítulo), `itens_mb` e `itens_total`.

### 3. Telas

- **`painel.html`** (visão geral): KPI novo *"Itens no Material Base"* → `68 de 75 (91%)`;
  achado *"N aulas com itens fora do MB"* na lista de achados. Contagem sobre itens com
  flag conhecido; se todos NULL (snapshot antigo), o card mostra "—".
- **`avaliacao.html`**: coluna nova *"Itens no MB"* por aula → `vinculados / total`
  (verde quando completo, amarelo quando incompleto, "—" quando desconhecido).
- Regra do projeto: `painel.html`/`avaliacao.html` da raiz mudam **e** suas cópias em
  `web/telas/` recebem as mesmas mudanças (byte-idênticas fora das edições web-only).

### 4. Publicação web (`sync_supabase.py`)

- O agregado já é montado reusando `painel.py`; incluir `itens_mb`/`itens_total` no
  payload de `snapshot.resumo` e de `avaliacao_curso`. Nenhuma mudança de schema no
  Supabase se o payload for JSON dentro das colunas existentes (`resumo` etc.); se houver
  coluna dedicada, é aditivo (task própria). O front web renderiza o mesmo `{data}`.

## Não-regressão

- Não muda o parse de blocos nem a régua de qualidade existente.
- Custo de coleta: +1 chamada por capítulo (~12–36 por curso; numa coleta cheia do BACEN,
  ~3,8 mil sobre as ~10 mil já feitas — incremental, em paralelo).
- `vinculado_mb` NULL em snapshots pré-feature é esperado e tratado nas telas.

## Testes / aceite

1. **Unit (Python, `tests/`)**: parse de `{item_id: has_base_material}` a partir de um
   payload real de `chapters/{id}/items`; migração idempotente da coluna; agregação
   itens_mb/itens_total no `painel.py` (com item NULL contando como desconhecido, não como
   não-vinculado).
2. **Real (com cookie válido)**: coletar Amparo e DMAE →
   **Amparo 68/75, DMAE 319/345** (bate com a sondagem); capítulos mistos aparecem no
   achado de auditoria.
3. **Telas**: KPI e achado na visão geral; coluna por aula na avaliação; snapshot antigo
   mostra "—" sem quebrar. Paridade da versão web com a local.

## Fora de escopo

- Detalhar QUAL item está fora do MB item a item na tela (o achado conta aulas; o
  drill-down fino fica para depois).
- Ação de vincular pelo painel (é read-only; a vinculação é feita no admin do LDI).
