# Exclusão de coletas + busca com seleção múltipla

## Context

O Painel de Conteúdo do LDI é **append-only por design**: nenhuma rotina de exclusão ou retenção
existe hoje em lugar nenhum do código. Cada coleta empilha uma extração nova no `conteudo.db`, que
já está em **242 MB** — e o banco local tem duas extrações do BACEN com contagens idênticas
(64.838 blocos cada), ou seja, uma recoleta duplicada que ninguém consegue remover.

Ao mesmo tempo, o disparo por termo é cego: o usuário digita "Área Fiscal" e o worker colhe
**tudo** que casar, sem que ninguém veja antes o que vai ser coletado nem possa escolher um
subconjunto.

Duas entregas resolvem isso, e há uma dependência entre elas: a seleção múltipla **multiplica**
extrações (30 onde antes havia 1). Construir o ralo antes da torneira torna cada teste da seleção
reversível, em vez de irreversível.

### Restrições que moldaram o desenho

- **O `conteudo.db` vive no VPS** (`/opt/extrator-ldi`); a Vercel não alcança o disco de lá. Toda
  exclusão local tem de passar pelo **worker**, como as coletas passam.
- **O SQLite não tem FK nenhuma** (`banco_conteudo.py:12-64`). Apagar uma extração exige `DELETE`
  em 6 tabelas; um delete parcial deixa órfão silencioso.
- **Sem `auto_vacuum`** (só `PRAGMA journal_mode=WAL`, `banco_conteudo.py:80`): `DELETE` não
  encolhe o arquivo. Só `VACUUM` devolve disco — com lock exclusivo e ~242 MB temporários.
- **O app web já fala com o LDI** (`web/lib/ldi.ts`, cookie do `config_ldi` via service_role), mas
  só por ID único — não há busca por termo do lado web.

### Decisões do Clovis (tomadas nesta sessão)

1. A exclusão apaga **nas duas camadas**: `snapshot` no Supabase (cascade cuida dos filhos) **e** a
   extração no `conteudo.db` do VPS. `pendencias`/`acionamentos` são **preservadas**.
2. O **`VACUUM` roda logo após a exclusão**, como pedido na fila — para serializar contra coletas.
3. Na seleção múltipla, o usuário **escolhe na hora** entre "coletar juntos" (1 rótulo, 1 snapshot)
   e "coletar separados" (1 pedido por curso).
4. Ordem: **1a → 2a → 1b → 2b**.

---

## Sequência

| # | Entrega | Por que separada |
|---|---|---|
| **1a** | Exclusão lógica (sem VACUUM) | O ralo. Risco destrutivo concentrado, sem o lock longo |
| **2a** | Buscar + selecionar + "coletar juntos" | O valor. Não muda o worker, não multiplica snapshots |
| **1b** | VACUUM + checagem de espaço | Lock exclusivo por minutos: merece janela combinada |
| **2b** | "Separados" + rótulos + selos de reincidência | Onde moram as duas armadilhas sérias |

Cada uma vira spec + plano próprios, no ritual do projeto (`docs/superpowers/`), branch `feat/*` →
PR → merge do Clovis.

---

## Entrega 1a — Exclusão lógica

### Modelagem: reusar `coleta_pedido` com `tipo='excluir'`

A fila, o polling de 5s, o `mudarStatus` atômico (`web/lib/coleta.ts:100-115`), cancelar/retentar e
a reconciliação na subida já existem e são testados — e, o que mais importa, o worker é **único e
serial**, o que serializa a exclusão contra coletas de graça. Tabela nova exigiria um segundo laço
e abriria a porta para um VACUUM rodando durante uma coleta.

Migração idempotente em `supabase/schema_coleta_exclusao.sql`:

```sql
alter table coleta_pedido drop constraint if exists coleta_pedido_tipo_check;
alter table coleta_pedido add  constraint coleta_pedido_tipo_check
  check (tipo in ('termo','ids','excluir'));
```

**O `alvo` é um JSON**, nunca um termo legível — e isso é uma defesa, não um detalhe:

```json
{"termo":"BACEN","extracao_local":37,"snapshot_id":12,"vacuum":false}
```

Se o worker antigo (ainda não atualizado) pegar esse pedido, `pedido_para_coleta`
(`worker_coleta.py:43-49`) cai no ramo genérico e trata o JSON como `search_term` → nenhum curso
encontrado → `SystemExit` → status `erro`. **Falha limpa, nada coletado, nada apagado, retentável**
depois do deploy. Usar a chave natural `(termo, extracao_local)` em vez do `snapshot_id` evita
apagar o snapshot errado se ele foi republicado entre o pedido e a execução.

**Ordem de deploy:** SQL no Supabase → `git pull` + restart do worker no VPS → merge da web.

### Fonte da lista: a tabela `snapshot`

Não a view `snapshot_atual` (precisa dos antigos e dos `pronto=false`). É a única fonte que a
Vercel alcança, e conhece também as coletas feitas por CLI, que `coleta_pedido` não conhece. O
`resumo` JSONB do próprio `snapshot` já traz os KPIs para mostrar o peso — zero join.

**Fica de fora, e a tela deve dizer isso:** extrações que existem no `conteudo.db` mas nunca foram
publicadas (sync falhou — é não-fatal, `coletor_ldi.py:285`). Elas ocupam disco e não aparecem.
Fechar essa lacuna é a **1c** (backlog): o worker publica um inventário do SQLite.

### Travas

Bloqueios duros (a action recusa): `exigirAdmin()`; já existe pedido `excluir` pendente/rodando
para o mesmo alvo; existe pedido `rodando` cujo `extracao_id` é o alvo. No worker: termo divergente
do `extracoes.termo` → `erro`, nada apagado.

**Confirmação reforçada (digitar o termo)** em dois casos, e o segundo é o perigoso:
- é o **único** snapshot do termo → o termo some do seletor (falha visível);
- é o **mais recente** de um termo com histórico → a web cai para o anterior **sem aviso**
  (`snapshot_atual` faz `distinct on (termo) ... order by extracao_local desc`). A confirmação
  mostra o destino: *"BACEN passa a exibir a coleta #33 de 04/07, 14 dias mais velha."*
  **Não bloquear** — apagar uma coleta ruim é justamente apagar a mais recente.

**Fallback do lado Python** (`painel.py:49`, `painel.py:314`, `sync_supabase.py:62` usam
`ORDER BY id DESC LIMIT 1` **global**): a web não tem como saber o maior `id` do SQLite. O worker
calcula e **relata** na mensagem final. Relatar, não bloquear.

**Pendências órfãs:** não mexer. Nenhuma query filtra por `extracao_id_criada/ultima`, e a chave de
`pendencias` é determinística e independe da extração. Mas o worker **conta e informa**: *"N
pendências foram apuradas contra esta coleta e continuarão abertas com os números antigos até a
próxima coleta deste termo."*

### O worker

Módulo novo **`exclusao_coleta.py`**, funções puras e sem HTTP (espelhando a separação que
`pedido_para_coleta` já usa): `ler_pedido_exclusao(row)`, `conferir_extracao(con, id, termo)`,
`apagar_extracao(con, id)`.

Sequência de `processar_exclusao`:
1. `rodando`. **Não provar o cookie** — a exclusão não fala com o LDI, e um cookie vencido não pode
   bloquear uma limpeza de disco. Diferença deliberada de `processar_pedido`.
2. Conferir a extração. Não existe no SQLite → seguir mesmo assim (idempotência).
3. **Apagar no Supabase primeiro**: `DELETE /rest/v1/snapshot?termo=eq.X&extracao_local=eq.N`.
   Se morrer no meio, o pior caso é "sumiu da web mas ainda ocupa disco" — retentável e inofensivo.
   O inverso deixaria a web mostrando coleta que não existe mais na origem.
4. Os 6 DELETEs **numa única transação** (`with con:`), nesta ordem:
   `blocos → aulas_coletadas → aulas → capitulos → cursos → extracoes`.
   `extracoes` **por último**: enquanto essa linha existir, o painel ainda enxerga a extração
   (visivelmente errada). Se sumisse primeiro e o processo caísse, ficariam centenas de MB de
   blocos órfãos que **nenhuma tela lista** — lixo invisível é pior que lixo visível.
5. `concluida` com relatório: linhas apagadas por tabela, pendências afetadas, e o aviso de
   "era a mais recente" se for o caso.

**Invariante que sustenta tudo: cada passo é idempotente** — é o que torna segura a reconciliação
`rodando→pendente` da subida do worker. Documentar no docstring.

### Arquivos

**Criar:** `exclusao_coleta.py`, `tests/test_exclusao_coleta.py`,
`supabase/schema_coleta_exclusao.sql`, `web/app/admin/coletas.tsx`
**Modificar:** `worker_coleta.py` (roteamento por `tipo` + guarda de tipo desconhecido),
`web/lib/coleta.ts` (tipo `"excluir"`, montar/ler o alvo JSON), `web/app/admin/actions.ts`
(`pedirExclusaoColeta`), `web/app/admin/page.tsx`, `web/app/coleta/fila.tsx` (renderizar
`tipo="excluir"` legível — senão a coluna despeja JSON)

### Testes (`unittest`, banco em memória, padrão de `tests/test_banco_conteudo.py`)

1. **Isolamento:** duas extrações povoadas; apagar a #1; a #2 intacta nas 6 tabelas.
2. **Preservação:** `pendencias` e `acionamentos` com a mesma contagem antes/depois.
3. **Atomicidade:** monkeypatch levantando no 4º DELETE → **nada** foi apagado. *É o teste que
   prova a ausência de órfão silencioso.*
4. **Idempotência:** rodar duas vezes; a segunda devolve zeros sem levantar.
5. **Roteamento no worker:** `tipo='excluir'` não chama `coletor_ldi.coletar`; não chama
   `probar_cookie`; tipo desconhecido → `erro`.
6. **Regressão do fallback:** após apagar a mais recente, `painel.dados_do_snapshot` devolve a
   anterior (documenta o comportamento para ninguém "consertar" sem querer).

---

## Entrega 2a — Buscar e selecionar

`buscarCursosLdi(sid, termo)` em **`web/lib/ldi.ts`**, no mesmo padrão de `buscarNomeCursoLdi`
(server-only, `"sem-acesso"` em 401/403). Mesma URL de `extrator_ldi.py:137-147`.

**O ponto de desenho que mais importa:** a resposta já traz `content_tree_cache` (a árvore inteira)
por curso. Paginar **em série, nunca `Promise.all`** — converter a página em DTO leve e soltar a
referência antes da próxima; com `Promise.all` de 3 páginas o pico de memória triplica. Teto de
3 páginas, timeout de 15s, e um `spike` de 10 minutos com `curl` **antes de codar** para testar se
a API aceita reduzir a projeção (não há evidência no código de que aceite — não inventar
parâmetro).

Do DTO ficam `id`, `nome`, `publicado`, `criadoEm`, `autores` e — derivados e descartados —
`qtdCapitulos`/`qtdAulas`, que é o que deixa o usuário estimar o peso do lote antes de disparar.

**Trava real:** termo com mínimo de 3 caracteres. `search_term=` vazio devolve o catálogo inteiro
**com as árvores** — centenas de MB derrubando a função serverless.

Server action `buscarCursos` com **`exigirOperador()`** — quem já pode disparar `tipo:"termo"` (que
colhe tudo) obviamente pode listar o que colheria.

**UI:** três modos no radio, com "Buscar e escolher cursos" como padrão. O modo "termo inteiro"
**continua existindo, rebaixado** — é o caminho de menor atrito para BACEN/PRF e tem semântica que
o modo novo perde ("tudo que casa, inclusive o que for criado depois"). Quebrar
`web/app/coleta/form-disparo.tsx` (já com ~135 linhas) em casca + `busca-cursos.tsx`.

**O disparo vira `tipo:"ids"`** — o worker já sabe fazer isso via `obter_curso` por ID
(`coletor_ldi.py:224-228`), então **zero mudança no worker**, sem refazer a busca pesada no VPS, e
congela a seleção (curso criado entre o clique e a execução não entra).

---

## Entrega 1b — VACUUM

`espaco_para_vacuum(caminho)` e `rodar_vacuum(con)` em `exclusao_coleta.py`; opção na UI.

- **Checar espaço ANTES de qualquer DELETE.** Faltando → `erro` sem apagar nada: falha limpa e
  retentável, mais previsível que "apagou mas não compactou".
- **`SQLITE_TMPDIR`**: o VACUUM usa o temporário do SQLite, que no VPS pode não ser a partição de
  `/opt/extrator-ldi`. Apontar para `saida/` e checar o espaço **dessa** partição — senão um `/tmp`
  pequeno faz o VACUUM falhar tarde.
- `PRAGMA wal_checkpoint(TRUNCATE)` antes e depois; VACUUM **fora** de transação.
- Falha no VACUUM **não** derruba o pedido: os dados já foram apagados → `concluida` com a
  mensagem do erro.

---

## Entrega 2b — Separados, rótulos e selos

**Herdado da 2a (01/08):** mostrar o **professor** de um curso ao marcá-lo na busca. Foi decidido
e escrito no spec da 2a, mas nenhuma task o implementou — só apareceu na revisão final da branch,
e o Clovis preferiu não atrasar o merge. O desenho está pronto em
`2026-08-01-busca-selecao-cursos-design.md` (seção "Autores sob demanda"): `authors_name` vem
**sempre null** na listagem, então o nome exige `GET /bo/ldi/courses/{id}` por curso — daí ser sob
demanda, ao marcar, e não na lista inteira. `buscarNomeCursoLdi` já existe e serve.

**A armadilha que define esta entrega:** `snapshot_atual` faz `distinct on (termo)`. Trinta pedidos
separados com o **mesmo** rótulo viram trinta snapshots dos quais a web mostra **um** — 29
invisíveis, silenciosamente. Solução: `montarRotulos(base, cursos)` (função pura, testável) gerando
`"Área Fiscal · Direito Tributário p/ ICMS-SP"` — distintos entre si e agrupáveis por prefixo.

`LIMITE_SELECAO = 30`; `enfileirarLote` com um único `insert([...])`; e
**`order=criado_em.asc,id.asc`** no `worker_coleta.main()` — 30 linhas inseridas no mesmo statement
ganham timestamps idênticos e a ordem fica indefinida.

**Selos de reincidência, com custo constante de consultas** (o `conferirIds` de hoje faz 1 consulta
por ID — inviável com 100 resultados): "já publicado" via **uma** consulta a `avaliacao_curso`
(`select curso_id, snapshot_id`, com índice novo `ix_avaliacao_curso_curso` — a PK é
`(snapshot_id, curso_id)`, então filtrar por `curso_id` seria seq scan); "já está na fila" via
**uma** consulta a `coleta_pedido` + `indexarAlvos` (função pura). O `conferirIds` sai de N
consultas para 2 e passa a avisar sobre o publicado, não só sobre a fila.

---

## Verificação

**1a**, na ordem:
1. `py -m unittest discover -s tests` — a suíte inteira verde (119 hoje + os novos).
2. Aplicar o SQL no Supabase; conferir com um `insert` de teste que `tipo='excluir'` é aceito e
   `tipo='xpto'` é recusado.
3. **Antes de atualizar o worker**, enfileirar um pedido `excluir` e confirmar que o worker antigo
   o marca `erro` sem coletar nada — é a defesa da migração, e tem de ser provada, não presumida.
4. `git pull` + restart no VPS; retentar o mesmo pedido e confirmar que agora executa.
5. Alvo do teste real: a **extração 1 ou 2 do BACEN** (64.838 blocos cada, duplicatas idênticas) —
   conferir que a outra fica intacta e que `pendencias`/`acionamentos` não mudam de contagem.
6. Conferir na web que o snapshot sumiu do seletor e que o termo caiu para a coleta anterior.

**2a:** buscar "Área Fiscal" na `/coleta` e conferir que a lista bate com o que o admin do LDI
mostra; selecionar 2 cursos, coletar juntos, e confirmar que vira **um** snapshot com os dois.

**1b:** medir `ls -la saida/conteudo.db` antes e depois; confirmar que o arquivo encolheu de fato
(é o ponto inteiro da entrega) e que nenhuma coleta rodou durante o lock.

**2b:** disparar 3 cursos separados com a mesma base e confirmar que os **três** aparecem no
seletor da web — é o teste que pega o `distinct on (termo)`.
