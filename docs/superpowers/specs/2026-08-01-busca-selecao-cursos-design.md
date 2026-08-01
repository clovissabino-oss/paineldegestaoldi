# Buscar, selecionar e coletar cursos juntos — design

_Data: 01/08/2026 · Entrega **2a** do roadmap
`docs/superpowers/specs/2026-07-30-exclusao-coletas-e-selecao-multipla-roadmap.md`_

## Problema

O disparo por termo é **cego**. O usuário digita "Área Fiscal" e o worker colhe **tudo** que
casar — 62 cursos, medidos — sem que ninguém veja antes o que vai ser coletado nem possa
escolher um subconjunto. Descobre-se o que veio depois, no painel.

A entrega **1a** (exclusão, no ar desde 31/07) é o que torna isto seguro de experimentar: uma
seleção errada agora é reversível.

## O que se entrega

Um modo novo na `/coleta`: **buscar → ver a lista → marcar → coletar juntos**. Um pedido, um
rótulo, um snapshot.

O modo "termo inteiro" **continua existindo, rebaixado**. Ele tem uma semântica que o modo novo
perde — *"tudo que casa, inclusive o que for criado depois"* — e é o caminho de menor atrito
para BACEN/PRF. Rebaixar não é depreciar.

Fora de escopo: **"coletar separados"**, rótulos automáticos e selos de reincidência são a
**2b**, onde moram as duas armadilhas sérias (o `distinct on (termo)` da `snapshot_atual` e o
custo N do `conferirIds`).

## Decisões

| Assunto | Decisão |
|---|---|
| Paginação | **Nenhuma** — uma requisição `per_page=100` |
| Projeção | Não há como reduzir (medido) — o DTO leve é montado no servidor |
| Ordem | Mais recentes primeiro (`created_at desc`), como o extrator já faz |
| Teto na tela | 30 cursos |
| Cursos sem árvore | Listados, com "0 cap" e **caixa desabilitada** |
| `published=false` | **Não filtra** — é informação, não exclusão |
| Autores | **Sob demanda**, só ao marcar o curso |
| Termo mínimo | 3 caracteres |
| Disparo | `tipo:"ids"` — **zero mudança no worker** |

---

## O spike, que mudou o desenho

O roadmap mandava gastar 10 minutos com `curl` **antes de codar**, para não inventar parâmetro.
Feito em 01/08, com o cookie válido do `config_ldi`. Três premissas caíram:

### 1. A projeção não pode ser reduzida

Sete variações testadas contra `search_term=Área Fiscal`, `per_page=100`:

| Tentativa | Resultado |
|---|---|
| `include_authors_names` (com/sem) | 2462,8 KB |
| `include_content_tree=false` | 2462,8 KB |
| `include_content_tree_cache=false` | 2462,8 KB |
| `select=id,name` · `lean=true` · `simple=true` | 2462,8 KB |
| `fields=id,name` | **HTTP 500** |

Byte-idêntico em todas. A API **ignora** qualquer tentativa de projeção, e `fields=` quebra o
servidor. **Não insistir** — quem mexer nisto depois vai repetir os mesmos 10 minutos.

### 2. Paginar era inviável, não só pesado

As árvores (`content_tree_cache`) são **~100% do payload** (2.549 KB de 2.467 KB), a 29–49 KB
por curso. O teto de 3 páginas que o roadmap propunha:

| "Direito" | Tamanho |
|---|---|
| página 1 | 4,29 MB |
| página 2 | 3,29 MB |
| página 3 | 2,30 MB |
| **total** | **9,9 MB** |

O limite de resposta de uma função no Vercel é **4,5 MB**. Paginar em série resolveria o pico de
memória — que era a preocupação do roadmap — mas **não o volume**. A única alavanca real é
`per_page` (medido: 20 → 0,86 MB · 30 → 1,23 MB · 50 → 2,93 MB · 100 → 4,29 MB).

### 3. `meta.total` mente

Devolve **127.309** em toda busca — o catálogo inteiro, ignorando o `search_term`. Não serve
para "N resultados encontrados" nem para saber se há próxima página. **A única pista honesta é
a contagem da página:** vieram 100 ⇒ pode haver mais.

### O que o spike confirmou de bom

- **A busca não tem ruído:** 62/62 resultados de "Área Fiscal" e 70/70 de "PRF" trazem o termo
  **no nome**. O `search_term` já casa por nome; não é preciso filtrar de novo no nosso lado.
- **A ordem por data funciona** — contagem de cursos com árvore entre os 30 mais recentes:

| Termo | Total | Com árvore | Publicados | Com árvore nos 30 + recentes |
|---|---|---|---|---|
| Área Fiscal | 62 | 43 | 28 | 15 |
| PRF | 70 | 66 | 49 | 27 |
| BACEN | 100 | 99 | 100 | 30 |
| Direito | 100 | 98 | 96 | 28 |

---

## Arquitetura

**Uma requisição, `per_page=100`, sem paginar.** Cai em 2,5–5 MB no servidor; ao navegador vai
só o DTO leve (~200 bytes por curso). A árvore é lida para contar capítulos/aulas e
**descartada na mesma passada** — nunca serializada para o cliente.

```
/coleta ──buscarCursos(termo)──> server action (exigirOperador)
                                      │
                        GET /bo/ldi/courses?per_page=100&search_term=…
                                      │   (2,5–5 MB, server-side)
                            converte para DTO e DESCARTA a árvore
                                      │   (~6 KB para 30 cursos)
                              lista na tela → marcar → disparar
                                      │
                          coleta_pedido {tipo:"ids", rotulo}
```

Sem paginação o teto é o `per_page=100` da própria API. **Vieram 100 ⇒ a tela avisa** que pode
haver mais e pede refinamento. É o melhor que se pode afirmar com honestidade, dado que o
`meta.total` mente.

### O disparo vira `tipo:"ids"`

O worker já resolve por ID (`coletor_ldi.py:224-228`, via `obter_curso`), então: **zero mudança
no worker**, sem refazer a busca pesada no VPS, e a seleção fica **congelada** — curso criado
entre o clique e a execução não entra no lote. Um pedido, um rótulo, um snapshot.

---

## A lista

Mostra os **30 mais recentes** dos até 100 buscados.

```
Área Fiscal — 62 encontrados · 43 com conteúdo
mostrando os 30 mais recentes

☐ Tecnologia da Informação p/ Área Fiscal   46 cap · 312 aulas   30/07 · rascunho
☐ Raciocínio Lógico e Matemática p/ Área F  36 cap · 240 aulas   30/07 · rascunho
☐ Estatística p/ Área Fiscal                18 cap · 121 aulas   30/07 · rascunho
☒̶ Governança de TI p/ Área Fiscal            0 cap                30/07 · vazio
☒̶ Bizu Estratégico de Direito Civil          0 cap                28/07 · vazio
```

### Cursos sem árvore: listados, não selecionáveis

Coletar um curso de 0 capítulos gera **extração vazia** — o VPS já tem uma delas ("Área Fiscal"
#11, 0 cursos / 0 blocos, de 30/07). Esconder seria mentir sobre o acervo; permitir seria
convidar a um pedido que nasce inútil e depois dá trabalho de excluir. **Aparecem com "0 cap" e
caixa desabilitada.**

### `published=false` não filtra

Os cursos de 30/07 com 46 e 36 capítulos são **não publicados e cheios de conteúdo** — a
montagem nova do LDI, que é justamente o que interessa auditar. Filtrar por `published`
esconderia o alvo. A tela mostra "rascunho" como informação.

### Colunas

Nome, capítulos, aulas, publicado, data de criação. A **descrição** entra como segunda linha
discreta **quando não for vazia** — medida: vazia em 27 de 30 cursos, e quando existe repete o
nome. Custa zero incluir; não se deve contar com ela.

### Autores sob demanda

`authors_name` vem **`None` na listagem** mesmo com `include_authors_names=true`, e
`structured_authors` **não vem** — só `authors` com UUIDs crus. (O projeto já sabia: sessão 6,
os nomes só vêm do `GET /bo/ldi/courses/{id}`.)

Nomes na lista inteira custariam **30 requisições por busca**. Ao **marcar** um curso, a tela
busca o professor daquele — 1 requisição, reusando `buscarNomeCursoLdi`, custo proporcional à
seleção.

---

## Travas

- **Termo com no mínimo 3 caracteres.** `search_term=` vazio devolve o catálogo inteiro **com
  as árvores** — 127.309 cursos derrubariam a função serverless. É a trava mais importante.
- **`exigirOperador()`** na action de busca: quem já pode disparar `tipo:"termo"` (que colhe
  tudo) obviamente pode listar o que colheria.
- **Rótulo obrigatório** no disparo, como o modo `ids` já exige.
- Limite de seleção: **30** (o que cabe na tela). `LIMITE_SELECAO` fica nomeado — a 2b vai
  precisar dele para "coletar separados".
- 401/403 do LDI → `"sem-acesso"`, mensagem apontando para o bloco 🍪 de renovação.

---

## Arquivos

**Criar**

| Arquivo | O quê |
|---|---|
| `web/app/coleta/busca-cursos.tsx` | Busca + lista + seleção |
| `web/checks/busca.check.ts` | Checagens das puras |
| `web/checks/fixtures/busca-ldi.json` | Payload real reduzido (do spike) |

**Modificar**

| Arquivo | O quê |
|---|---|
| `web/lib/ldi.ts` | `buscarCursosLdi(sid, termo)` |
| `web/lib/coleta.ts` | `converterCursosBusca`, `contarArvore`, `TERMO_MINIMO`, `LIMITE_SELECAO` |
| `web/app/coleta/actions.ts` | `buscarCursos` + modo `selecao` no `disparar` |
| `web/app/coleta/form-disparo.tsx` | Quebrar em casca + o modo novo (já com ~135 linhas) |

---

## Testes

O `web/` não tem test runner (`package.json` só tem `dev`/`build`/`start`) — segue o padrão da
casa: `node --experimental-strip-types checks/*.check.ts`, como `coleta.check.ts` (9 checagens
verdes hoje).

As puras ficam em `web/lib/coleta.ts` para serem testáveis **sem rede**:

1. **DTO a partir de payload real** — fixture do spike, não inventado.
2. **Contagem de árvore** com `content_tree_cache` ausente, `null`, `[]` e povoada.
3. **A árvore não vaza** — `JSON.stringify(dto)` não contém `content_tree_cache`. *É o que
   garante que os 5 MB não atravessem para o navegador.*
4. **Termo curto recusado** (< 3 caracteres), inclusive só-espaços.
5. **Sem árvore ⇒ não selecionável**.
6. **Vieram 100 ⇒ `podeHaverMais`**; 62 ⇒ não.
7. **Ordem preservada** (a API já entrega por data desc; não reordenar).

O spike é que revelou os casos de borda 2, 5 e 6 — por isso ficam travados por checagem, não por
comentário.

---

## Verificação

1. `node --experimental-strip-types checks/busca.check.ts` e `checks/coleta.check.ts` verdes;
   `npx tsc --noEmit` e `npm run build` limpos; `py -m unittest discover -s tests` (143) intacta.
2. Buscar "Área Fiscal" na `/coleta` e conferir que a lista **bate com o admin do LDI** — 62
   encontrados, 43 com conteúdo, os de 30/07 no topo.
3. Conferir no navegador (aba Network) que a resposta da action é da ordem de **KB, não MB** —
   é a prova de que a árvore ficou no servidor.
4. Marcar 2 cursos, coletar juntos, e confirmar que vira **um** snapshot com os dois.
5. Termo de 2 caracteres recusado sem chamar o LDI.

**Deploy:** só web. O worker **não** precisa de `git pull` — o disparo usa `tipo:"ids"`, que ele
já sabe fazer, e nenhum módulo alcançado pelo `coletor_ldi.py` muda. (Afirmação seguindo a
cadeia de imports, não os nomes dos arquivos — a regra da sessão 10.)
