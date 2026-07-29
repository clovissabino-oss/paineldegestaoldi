# Avaliação por item + ordem real do curso — design

_Data: 29/07/2026 · Fase 2.2 do Painel de Conteúdo_

## Problema

A tela `/avaliacao` mostra uma linha por **capítulo** (o que o LDI chama "Aula"), e duas
coisas incomodam:

1. **A ordem sai embaralhada.** O `painel.py` ordena por `capitulos.ordem`, mas essa coluna
   é **zero em todos os 2.547 capítulos** da base — o `content_tree_cache` da API devolve
   `order_index = 0` para todo mundo, e o coletor grava o que recebe. O `ORDER BY ordem`
   é, na prática, um no-op.
2. **Não dá para descer ao item.** A análise para no capítulo; para saber qual item puxa o
   número para baixo, é preciso abrir o LDI e conferir na mão.

## Decisões

| Assunto | Decisão |
|---|---|
| Colunas do item | As **mesmas 8** da linha de capítulo |
| Alcance | Painel local **e** vitrine web (Vercel/Supabase) |
| CSV | **Sempre** com itens, colunas novas `nivel` e `num` |
| Interação | Abre recolhida + botão "expandir/recolher tudo"; estado não persiste |
| Onde a ordem é calculada | **Na leitura**, derivada do `path` (abordagem A) |

### Por que derivar na leitura (e não corrigir na coleta)

Consertar o coletor só valeria para coletas **novas** — todo snapshot existente (o BACEN
são 128 cursos) continuaria embaralhado até recoletar, e exigiria migração de schema mais
atualização do worker no VPS. Derivar do `path` conserta **retroativamente todos os
snapshots**, inclusive os já publicados no Supabase, sem recoleta e sem migração.

Além disso, a ordem é uma decisão de **apresentação**, e o `path` já é a fonte autoritativa
— o `extrator_ldi.py` usa exatamente essa chave desde o começo (`chave_path`, linha 309).
Gravar numa coluna criaria uma segunda fonte de verdade, com chance de divergir.

Se um dia a API passar a mandar `order_index` de verdade, corrigir na fonte vira trivial e
esta regra sai fora.

## Ordenação

Chave = o `path` da aula convertido em **tupla de inteiros**: `"13.1"` → `(13, 1)`.
Comparação numérica, então `2` vem antes de `10`.

- **Capítulo:** herda a chave do menor `path` entre seus itens. Cada capítulo tem prefixo
  próprio (verificado: 26 de 26 num curso de 26 capítulos, zero ambiguidade), então isso
  equivale ao número do capítulo no curso.
- **Item:** ordenado pelo `path` completo dentro do capítulo.
- **Capítulo sem itens:** lê o número do próprio nome quando existir
  (`"24. Crimes contra..."` → 24); sem isso, vai para o fim em ordem alfabética.
- **Empate, `path` ausente ou malformado:** desempate por nome. Nunca lança exceção, nunca
  descarta linha — no pior caso degrada para alfabética.

A numeração (`13`, `13.1`) é **exibida** na tela e vai na coluna `num` do CSV, para a ordem
ficar auditável contra o admin do LDI.

**O `path` é relativo ao curso.** O mesmo item aparece em 6 pacotes do BACEN com `path`
`6.4`, `5.4` e `1.4`. Como a ordenação lê a linha já filtrada por `curso_id`, cada pacote
sai na ordem dele.

## Agregação por item

`dados_avaliacao` passa a agregar **por item**; o capítulo vira a **soma dos seus itens**.
Isso garante por construção que o pai bate com os filhos — é a mesma conta.

Três funções pequenas, testáveis isoladamente:

- `_metricas_zeradas()` — o dicionário de contadores
- `_acumular(m, bloco, depara)` — aplica um bloco (questão / texto com questões coladas /
  vídeo) sobre um dicionário
- `_somar(destino, origem)` — soma dois dicionários (números somam, mapa de bancas mescla)

**Custo de consulta inalterado:** continua **uma** query de blocos por capítulo — o
`item_id` entra na projeção e os baldes são separados em Python. Nada de N+1 (seriam 619
queries no maior curso da base).

### Correção: contagem de Material Base vazava o filtro de curso

A consulta atual do "Itens no MB" do capítulo é:

```sql
SELECT COUNT(*), SUM(vinculado_mb) FROM aulas
WHERE extracao_id=? AND vinculado_mb IS NOT NULL AND item_id IN (...)
```

Sem filtrar curso nem capítulo. Como `aulas` tem uma linha por **(curso, capítulo, item)**
e **1.990 dos 3.612 itens do BACEN pertencem a mais de um curso**, um item compartilhado é
contado **uma vez por curso em que aparece** — o `itens_total`/`itens_mb` infla.

Os aceites validados (Amparo 68/75, DMAE 319/345) não pegaram o defeito porque naquelas
coletas nenhum item era compartilhado (verificado: zero).

**Correção:** o `vinculado_mb` passa a vir na mesma consulta que já lista os itens do
capítulo — filtrada por curso **e** capítulo. Elimina a query extra e o erro junto.

**Consequência:** o "Itens no MB" de cursos com item compartilhado **cai para o número
certo**. Não é regressão. O plano inclui um passo que mostra o antes/depois por curso antes
de publicar.

### Princípio que rege todas as contagens

Toda métrica é **escopada pelo curso selecionado**, e cada capítulo/item conta **uma vez**.
Analisar "Direito Administrativo (Analista - Área 2)" mostra a realidade daquele pacote —
nunca a soma de pacotes diferentes que repetem o mesmo conteúdo. O fix do Material Base era
o único ponto que escapava dessa regra.

## Tela, CSV e web

**Tela (`avaliacao.html`).** A linha de capítulo ganha `▶`/`▼` e o número
(`13. Função Exponencial`); no topo, **⊕ Expandir tudo** / **⊖ Recolher tudo**. As linhas de
item entram abaixo do pai, recuadas, com a numeração (`13.1`) e as mesmas 8 colunas. Estado
só em memória — trocar de disciplina volta ao recolhido.

O conjunto de capítulos abertos vive numa variável à parte, consultada no `render()`. A
tabela é redesenhada inteira quando muda a banca-alvo; sem isso, trocar a banca fecharia o
que o usuário abriu.

**Dashboard e totais:** continuam somando **capítulos**, como hoje. O KPI "aulas" segue
contando aulas do LDI e não muda com a expansão.

**CSV:** ganha `nivel` (`capitulo`/`item`) e `num` (`13` / `13.1`) na frente das colunas
atuais, com uma linha por capítulo e uma por item, **sempre** — independente do que está
expandido. As colunas existentes mantêm nome e ordem, então planilhas já montadas não
quebram; só recebem linhas a mais, filtráveis por `nivel`.

Nas linhas de item, a coluna `capitulo` (mantida com esse nome por compatibilidade) carrega
o **nome do item**, e a coluna `aulas` vale `1`. Quem quiser só a visão antiga filtra
`nivel = capitulo` e tem exatamente o arquivo de hoje.

**Formato do payload.** Cada capítulo ganha `num` (a numeração exibida) e `itens`, uma
lista ordenada em que cada item tem `num`, `nome` e **os mesmos contadores do capítulo** —
mesmas chaves, mesmos tipos. Um item é uma linha de capítulo com `aulas = 1`, o que deixa a
tela e o CSV usarem a mesma função de desenho para os dois níveis.

**Web:** o payload por curso passa a trazer `itens` dentro de cada capítulo (medido: +220 KB
no pior curso da base, 619 itens; a web busca um curso por requisição). O `sync_supabase.py`
reusa o `painel.py`, então flui sem tocar no sync. **Sem mudança de schema no Supabase** (o
payload é `jsonb`).

⚠ A cópia `web\telas\avaliacao.html` recebe as mesmas mudanças e tem **3 edições próprias**
(link sair, selo de frescor, estado vazio) que não podem ser perdidas na réplica.

## Testes

Padrão da suíte atual (`py -m unittest discover -s tests`), banco em memória, fixtures de
`tests/test_painel_dados.py` e `test_painel_vinculo_mb.py`:

- **Ordenação:** capítulos e itens na ordem do `path`; `10` depois de `2`; capítulo sem item
  usa o número do nome; capítulo sem número vai para o fim sem sumir; `path` vazio ou torto
  não derruba a agregação.
- **Pai = soma dos filhos:** cada contador do capítulo igual à soma dos itens, inclusive o
  mapa de bancas. Trava a regressão mais provável.
- **Escopo por curso:** item compartilhado entre dois cursos conta uma vez em cada, nunca
  duas no mesmo. Cobre o fix do Material Base e o `path` distinto por pacote.
- **Vídeos e datas:** o de→para continua casando por `video_id_antigo` no nível do item.
- Suíte Node (`extrairIds` e afins) não é tocada.

## Falhas

A ordenação é defensiva por construção: `path` ausente, vazio ou não-numérico cai no
desempate por nome em vez de lançar. Nenhuma linha é descartada por não ter ordem — no pior
cenário a tela fica alfabética, nunca vazia. Snapshot antigo sem `vinculado_mb` continua
exibindo `—`.

## Verificação com dados reais (antes de publicar)

1. Ordem de um curso conferida contra o admin do LDI.
2. Antes/depois do "Itens no MB" por curso, para dimensionar o efeito do fix.
3. **Amparo 68/75 e DMAE 319/345 intactos** — cursos sem item compartilhado, servem de
   controle.

## Fora de escopo

- Corrigir `capitulos.ordem` no coletor/banco (abordagem B) — reavaliar se a API passar a
  mandar `order_index` real.
- Tela de Pendências (fase 2.1, backlog).
- Qualquer mudança no `extrator_ldi.py`, no `visualizador.py` ou nas telas da raiz que não
  seja a `avaliacao.html`.
