# Coleta do Material Base do professor — design

_Data: 2026-08-03 · Autor: Clovis + Claude · Status: aprovado no chat (blocos 1–4)_

## Objetivo

Hoje toda extração é de um **LDI de curso**. Este spec acrescenta a extração do
**Material Base (MB)** — o ambiente interno onde o professor guarda o acervo dele — e
separa os dois universos no dado e na visão do usuário.

O MB responde uma pergunta que o curso não responde: **o que o professor tem**, e não
apenas o que foi montado num curso específico. É uma leitura enraizada na realidade do
professor, e é a fundação para a comparação entre professores da mesma disciplina (ciclo
seguinte, fora deste spec).

## Descobertas técnicas (medidas em 03/08/2026, com cookie válido)

Todas verificadas contra a API real. Não re-derivar.

### Endpoints

| Precisa | Endpoint | Custo medido |
|---|---|---|
| Listar MBs | `GET /bo/ldi/base-material?page&per_page` | 387 MBs; `user_id=` filtra; `name=` filtra |
| Detalhe | `GET /bo/ldi/base-material/{id}` | `name`, `user_id`, `main_classification_id`, `sort_chapter_ids`, `hide_chapters` |
| **Árvore inteira** | `GET /bo/ldi/base-material/{id}/chapters?per_page=100` | **1 req · 366 KB · 1,1 s** (36 caps, ~646 itens) |
| Blocos | `GET /bo/ldi/blocks?item_id=` | **o mesmo de hoje**, sem alteração |
| Buscar professor | `GET /bo/ldi/users?term=<palavra>` | ~1,5 s; ver limitações abaixo |

Plurais dão 404: é `base-material` (**singular**). `search_term=`/`q=` são **ignorados** na
listagem de MB; só `name=` e `user_id=` filtram.

### Cardinalidade: 1 MB = (professor × disciplina)

387 MBs para **226 professores**. Distribuição medida: 155 professores com 1 MB, 28 com 2,
19 com 3, 15 com 4, 3 com 5, 2 com 6, 3 com 7 e **1 com 11**.

O `name` do MB é a disciplina ("Direito Constitucional", "Matemática"). São 164 nomes
distintos para 144 `main_classification_id` — o **nome tem sujeira** (`'Pedagogia   '` com
espaços à direita), então a classificação é a chave estável para agrupar disciplina.

Massa para a comparação futura: **17 professores com MB de "Língua Portuguesa"**, 10 de
Matemática, 7 de Direito Constitucional.

### O item do curso É o item do MB (mesmo `item_id`)

**A descoberta que mais influenciou o desenho.** Não é cópia: dos 646 itens do MB
`3e8e7c78…` (Direito Constitucional), **225 já existem nos cursos coletados** no
`conteudo.db` — 122 deles nos seis cursos de Direito Constitucional do BACEN. Conferidos
os blocos de um item compartilhado: **21 dos 22 batem** (o 22º é evolução posterior à
coleta).

Consequências:

1. O cruzamento MB × curso é um `join` por `item_id` — de graça.
2. Guardar MB em tabelas próprias **duplicaria as mesmas linhas** e jogaria fora esse join.
3. O `has_base_material` já coletado ganha sentido: marca o item de curso que **veio** do MB.

### Forma da árvore

- **Não há sub-capítulos** (`parent_chapter_id` vazio em 100% dos capítulos dos 2 MBs
  sondados), mas **há sub-itens**: 25 itens com filhos no Dir. Constitucional, 4 no
  Dir. Administrativo.
- `hide_chapters` traz **111 capítulos ocultos** no Dir. Constitucional, e **nenhum deles
  vem na árvore** — o endpoint entrega só o visível. O acervo real do professor é maior
  que a coleta.
- `sort_chapter_ids` é **incompleto** (27 ids para 36 capítulos no Dir. Constitucional;
  completo no Dir. Administrativo) — não serve como fonte de ordem. Usa-se a ordem que a
  API devolve.
- Ao contrário do curso (onde `order_index` é 0 em todos os 2.547 capítulos da base), no MB
  a ordem devolvida é real.

### Limitações da busca de professor

`GET /bo/ldi/users?term=` varre o **diretório inteiro de usuários, alunos incluídos**:

- devolve ~50 resultados sem ranking e **ignora `per_page`**;
- `term=Fauth` trouxe 8 homônimos e **nenhum** professor com MB;
- `term=Fauth Nathalia` (duas palavras) trouxe **zero** — o termo parece ser de uma palavra;
- `term=Ciciliati` trouxe 12 usuários, e o cruzamento com a lista de MBs isolou exatamente
  **Profa Nilza Ciciliati · Serviço Social**.

Não existe lookup por id (`?id=`/`?ids=` são ignorados), nem endpoint de classificações
(404 em todas as variantes testadas). O nome do professor só é resolvível por busca
textual — ou pelo `structured_authors` de um curso que ele autore (**provado**: o
`structured_authors[].id` de um curso é o mesmo espaço de ids do `base-material.user_id`).

## Arquitetura

Opção escolhida: **o MB é uma coleta como outra qualquer, com discriminador de tipo** —
entra nas tabelas existentes. As alternativas foram descartadas: tabelas próprias
duplicariam linhas e perderiam o join por `item_id`; refatorar para um "acervo de itens"
com dupla vinculação seria reformar um pipeline que está no ar e provado.

### 1. Coleta (`coletor_ldi.py`)

Modo novo que troca **só a origem da árvore**. Do item para baixo (blocos, parse,
banca/ano, questões coladas) **nada muda**.

```powershell
py coletor_ldi.py --mb "<id ou URL do MB>"   # coleta um Material Base
py coletor_ldi.py --mb-professor "Ciciliati" # lista os MBs do professor e pergunta quais
```

1. `GET /bo/ldi/base-material/{id}` → disciplina, `user_id`, classificação.
2. `GET /bo/ldi/base-material/{id}/chapters?per_page=100` → árvore inteira.
3. Achatar capítulo → item → **sub-item** (recursivo). O sub-item vira aula preservando o
   `path` do pai, para não perder a posição.
4. Itens → `_baixar_lote` **sem alteração**.
5. `regras_qualidade` **não roda** em extração de MB (ver "Fora de escopo"). Isso não é só
   economia: o motor dá **baixa automática** no snapshot seguinte, e rodá-lo sobre um MB
   resolveria em massa pendências de curso que continuam abertas na realidade.

Tratamento de auth, retry e falha pontual: os mesmos de hoje (401/403 → `CookieVencido`;
falha de capítulo registra e segue).

### 2. Modelo (`banco_conteudo.py`) — migrações idempotentes

| Tabela | Mudança |
|---|---|
| `extracoes` | + `tipo` (`'curso'`\|`'mb'`, default `'curso'`), `professor_id`, `professor_nome`, `disciplina`, `classificacao_id`, `capitulos_ocultos`. `termo` = `"MB · <Professor> · <Disciplina>"` |
| `cursos` | **1 linha sintética** por MB: `curso_id` = `mb_id`, `nome` = disciplina, `autores` = professor |
| `capitulos` | sem mudança de schema; `ordem` recebe a posição real da API |
| `aulas` | sem mudança; `vinculado_mb` = 1 (todo item de MB está no MB, por definição) |
| `blocos` | **sem mudança nenhuma** |

Migração no padrão do projeto (`ALTER TABLE ... ADD COLUMN` sob `try/except`). Extrações
antigas ficam com `tipo='curso'` por default — nenhuma recoleta é necessária.

### 3. Agregação (`painel.py`) — a regra dura

**Nenhuma consulta roda sem `tipo` explícito.** Não é convenção: é teste de regressão que
semeia um curso e um MB no mesmo banco e exige que os KPIs de curso ignorem o MB (com as
consultas de hoje, o teste falha).

Novos agregados para o universo MB:

- `capitulos_ocultos` no cabeçalho ("o professor tem 111 capítulos fora desta coleta").
- **Cobertura MB → cursos**: itens do MB que aparecem em algum curso coletado. Regra
  explícita, porque o número mente sem ela: conta contra **a coleta mais recente de cada
  curso no mesmo banco**, e a tela informa **contra quantos cursos comparou**.

### 4. Telas

Seletor de universo no topo, **antes** de qualquer filtro:

```
  ( ) Cursos (LDI)          (•) Material Base (professores)
      seletor: curso            seletor: professor · disciplina
```

Trocar o universo troca o seletor, os KPIs e as colunas — não é um filtro dentro da mesma
lista. Os dois **nunca** entram na mesma soma.

A `/avaliacao` serve o MB quase inteira (já mede por capítulo/item: questões, bancas, anos,
soluções, vídeos, idade de gravação) — é o maior ganho do desenho, sem agregação nova.

| Coluna | Curso | MB |
|---|---|---|
| Itens no MB | `68/75` | **some** (100% por definição) |
| Ordem dos capítulos | derivada do `path` | ordem real da API |
| Capítulos ocultos | — | **nova**, no cabeçalho |

Regra do projeto: `painel.html`/`avaliacao.html` da raiz mudam **e** as cópias em
`web/telas/` recebem as mesmas mudanças.

### 5. Publicação web (Supabase + Vercel)

**Correção obrigatória de chave.** A view `snapshot_atual` faz `distinct on (termo)`; sete
professores têm MB de "Direito Constitucional" e seis sumiriam **em silêncio**.

- `snapshot` ganha `tipo` e `chave`; a view passa a `distinct on (tipo, chave)`.
- Curso: `chave` = `termo` (comportamento idêntico ao de hoje).
- MB: `chave` = **`mb_id`** — UUID, colisão impossível por construção.
- Migração `supabase/schema_mb.sql`, aplicada **antes** do `git pull` do worker.

### 6. Fila e `/coleta`

Terceiro modo, ao lado de "termo" e "IDs": busca de professor → lista dos MBs dele →
seleção → **cada MB marcado vira um pedido próprio** (`tipo='mb'`).

O alvo vai em **JSON, nunca legível** (`{"mb_id","professor_id","professor_nome",
"disciplina"}`) — mesma lição da entrega 1a: worker desatualizado falha limpo em vez de
fazer a coisa errada.

Marcar o professor marca todos os MBs dele; dá para desmarcar um. Onze MBs = onze coletas,
não uma coleta gigante — assim cada disciplina fica comparável com a de outro professor.

A rede do LDI **não toca o navegador**: a busca roda em handler Next reusando
`web/lib/ldi.ts`; a checagem de bundle existente (`sem api.estrategia.com`) segue valendo
como prova. O índice dos 387 MBs é baixado **no servidor** (4 requisições, ~700 KB, ~3 s) e
guardado em memória do processo — sem tabela nova, que exigiria decidir quem a atualiza.

A tela precisa dizer a limitação da busca ("tente só o sobrenome") em vez de fingir que a
pessoa não existe.

**A `/admin` ganha a coluna `tipo`** na lista de coletas excluíveis: sem ela, "Direito
Constitucional" aparece sete vezes sem nada que as distinga, e a confirmação por digitar o
termo — a trava de segurança da exclusão — vira roleta. O `--listar` do
`exclusao_coleta.py` também mostra o `tipo`.

**O worker precisa de `git pull` + `systemctl restart worker-coleta`** — sem ambiguidade
desta vez: é um `tipo` de pedido que ele não conhece, e o `painel.py` (que molda o payload
publicado) muda.

## Testes

Os que discriminam código velho de novo (os demais são higiene):

1. **Separação dos universos** — curso e MB no mesmo banco; KPIs de curso ignoram o MB.
   Falha com as consultas de hoje.
2. **Colisão de chave na web** — dois MBs de "Direito Constitucional" de professores
   diferentes; a `snapshot_atual` devolve **os dois**. Com `distinct on (termo)`, devolve
   um. É o defeito silencioso mais caro do desenho.
3. **Sub-item não some** — árvore com item que tem filhos; a contagem final os inclui.
4. **Achatar preserva a ordem** — o `path` do pai governa a posição do sub-item.
5. Parse da árvore do MB a partir de payload real; migrações idempotentes.

## Aceite com dados reais (gabarito já medido)

1. Coletar o MB `3e8e7c78-cdc4-4dc2-90ad-0dae39b827f5` (Direito Constitucional) →
   **36 capítulos, ~646–651 itens**, cabeçalho anunciando **111 capítulos ocultos**.
2. Cobertura MB → cursos ≈ **225 itens** contra o BACEN já coletado, com a tela dizendo
   contra quantos cursos comparou.
3. Buscar "Ciciliati" na `/coleta` → **um** resultado (Profa Nilza · Serviço Social).
4. Buscar "Fauth" → só quem tem MB, não os oito homônimos.
5. Painel: universo "Cursos" com números **idênticos** aos de antes da mudança.

## Riscos

1. **A contagem do MB pode não ser estável.** Duas leituras do mesmo MB com ~10 min de
   intervalo deram **646 e 651 itens**. Se for edição ao vivo do professor, é semântica de
   snapshot e está tudo certo. Se for paginação instável, a coleta perde itens em silêncio.
   **A primeira coleta real precisa ser feita duas vezes** e os totais comparados — é o
   único jeito de saber.
2. **Professor sem nome** — quem não aparecer no `users?term=` fica com UUID. A tela mostra
   o UUID, não "—", senão parece defeito.
3. **Crescimento do banco** — um MB ≈ um curso médio, e são 387. Mitigado por coletar sob
   demanda e pelo `tipo` no `--listar`.

## Fora de escopo (explicitamente)

- **Comparação entre professores da mesma disciplina** — ciclo próprio, muito mais fácil de
  desenhar com MB real na mão (referência de formato: `Compilado_Relatorios_Guardioes/`).
- **Regras de qualidade sobre MB** — o motor funcionaria, mas a Q2 sozinha já gerou 108 mil
  pendências sobre cursos; 387 MBs estouram a base antes de sabermos o que acionar num MB.
  Puramente aditivo depois: a coleta guarda tudo que a regra precisaria.
- **Ler os 111 capítulos ocultos** — o endpoint não os entrega; investigar depois se há
  parâmetro.
- **Vincular ou editar qualquer coisa no MB** — o sistema é e continua somente leitura.
