# Exclusão de uma coleta pelo admin — design

_Data: 30/07/2026 · Entrega **1a** do roadmap
`docs/superpowers/specs/2026-07-30-exclusao-coletas-e-selecao-multipla-roadmap.md`_

## Problema

O Painel de Conteúdo é **append-only por design**: não existe rotina de exclusão nem de
retenção em lugar nenhum do código. Cada coleta empilha uma extração no `conteudo.db`, hoje
com **242 MB**, e o banco já carrega duas extrações do BACEN com contagens idênticas (64.838
blocos cada) — uma recoleta duplicada que ninguém consegue remover.

Isso não é só disco. A entrega **2a** (buscar termo → selecionar vários cursos) vai
**multiplicar** extrações: 30 onde antes havia 1. Construir o ralo antes da torneira torna
cada teste da seleção múltipla reversível, em vez de irreversível.

## O que se entrega

Uma lista das coletas publicadas na tela `/admin`, com um botão **Excluir** por linha. O
clique não apaga nada: enfileira um pedido que o worker do VPS executa, apagando **nas duas
camadas** — o `snapshot` no Supabase e a extração no `conteudo.db`.

Fora do escopo desta entrega: `VACUUM` (é a **1b** — lock exclusivo por minutos, merece
janela combinada) e o inventário das extrações não publicadas (é a **1c**, backlog).

## Decisões

| Assunto | Decisão |
|---|---|
| Transporte | Reusar `coleta_pedido` com `tipo='excluir'` |
| Formato do alvo | JSON, nunca texto legível |
| Chave de exclusão | `(termo, extracao_local)` — não o `snapshot_id` |
| Ordem das camadas | Supabase primeiro, SQLite depois |
| Ordem dos DELETEs | `extracoes` por **último** |
| `pendencias`/`acionamentos` | **Preservadas**, o worker só informa |
| Cookie do LDI | **Não é provado** — a exclusão não fala com o LDI |
| Confirmação | Digitar o termo, **sempre** |
| Onde fica a tela | `/admin`, só admin |
| Feedback | Selo de estado na própria linha |

---

## Arquitetura

O clique **não apaga nada**. Ele enfileira `coleta_pedido` com `tipo='excluir'` — a mesma fila
das coletas, o mesmo worker serial no VPS.

```
/admin ──enfileira──> coleta_pedido {tipo:"excluir", alvo:JSON}
                              │
                     worker no VPS (serial)
                              │
              1. DELETE snapshot no Supabase (cascade nos filhos)
              2. 6 DELETEs no conteudo.db, UMA transação
                              │
                      concluída + relatório
```

### Por que reusar a fila em vez de uma tabela nova

A fila, o polling de 5 s, o `mudarStatus` atômico (`web/lib/coleta.ts:100-115`),
cancelar/retentar e a reconciliação `rodando→pendente` da subida já existem e são testados. E,
o que mais importa: **o worker é único e serial**, o que serializa a exclusão contra coletas de
graça. Uma tabela própria exigiria um segundo laço e abriria a porta para um `VACUUM` (1b)
rodando durante uma coleta.

O `conteudo.db` **vive no VPS** (`/opt/extrator-ldi`); a Vercel não alcança aquele disco. Toda
exclusão local tem de passar pelo worker, como as coletas passam. Não há alternativa a isso.

### O alvo é um JSON — e isso é defesa, não estilo

```json
{"termo":"BACEN","extracao_local":37,"snapshot_id":12,"vacuum":false}
```

Se o worker antigo (ainda sem `git pull`) pegar esse pedido, `pedido_para_coleta`
(`worker_coleta.py:43-49`) cai no ramo genérico e trata o JSON inteiro como `search_term` →
nenhum curso encontrado → `SystemExit` → status `erro`. **Falha limpa: nada coletado, nada
apagado, retentável** depois do deploy. Um alvo legível como `"BACEN"` faria o worker antigo
**recoletar o BACEN** ao receber um pedido de exclusão — o oposto exato do pedido.

O campo `vacuum` já entra em `false` para a 1b não precisar de outra migração.

### Por que `(termo, extracao_local)` e não o `snapshot_id`

O `snapshot_id` é a PK do Supabase e **muda** se o snapshot for republicado entre o pedido e a
execução do worker. `(termo, extracao_local)` é a chave natural, estável, e é também o que o
worker usa para achar a extração no SQLite. O `snapshot_id` fica no alvo apenas como
informação de diagnóstico.

### Por que o Supabase primeiro

Se o processo morrer entre as duas camadas, o pior caso é *"sumiu da web mas ainda ocupa
disco"* — retentável e inofensivo. A ordem inversa deixaria a web mostrando uma coleta que não
existe mais na origem, e o `resumo` da tela apontaria para números impossíveis de reproduzir.

O `DELETE /rest/v1/snapshot?termo=eq.X&extracao_local=eq.N` basta: `avaliacao_curso` e
`pendencia_resumo` têm `on delete cascade` (`supabase/schema.sql:18,27`).

---

## O worker

Módulo novo **`exclusao_coleta.py`**, com funções puras e sem HTTP — espelhando a separação
que `pedido_para_coleta` já usa, e que é o que torna os testes possíveis sem rede:

| Função | O quê |
|---|---|
| `ler_pedido_exclusao(row)` | Valida o JSON do alvo; devolve `(termo, extracao_local, vacuum)` |
| `conferir_extracao(con, id, termo)` | Casa `extracoes.termo` com o termo do pedido |
| `apagar_extracao(con, id)` | Os 6 DELETEs numa transação; devolve linhas por tabela |
| `contar_pendencias(con, id)` | Quantas pendências foram apuradas contra a extração |

Sequência de `processar_exclusao` em `worker_coleta.py`:

1. `rodando`. **Não provar o cookie.** Diferença deliberada de `processar_pedido`: a exclusão
   não fala com o LDI, e um cookie vencido não pode bloquear uma limpeza de disco.
2. Conferir a extração. **Não existe no SQLite → seguir mesmo assim** (idempotência: o
   Supabase pode ter sobrado de uma tentativa anterior que morreu no meio).
   **Termo divergente → `erro`, nada apagado.**
3. `DELETE` do snapshot no Supabase.
4. Os 6 DELETEs numa **única transação** (`with con:`), nesta ordem:
   `blocos → aulas_coletadas → aulas → capitulos → cursos → extracoes`.
5. `concluida` com relatório.

### Por que `extracoes` por último

O SQLite **não tem FK nenhuma** (`banco_conteudo.py:12-64`), então a ordem é escolha nossa, não
imposição do banco. Enquanto a linha de `extracoes` existir, o painel ainda **enxerga** a
extração — visivelmente errada, com contagens zeradas. Se ela sumisse primeiro e o processo
caísse, ficariam centenas de MB de blocos que **nenhuma tela lista**.

**Lixo visível é melhor que lixo invisível.** É por isso que a ordem é essa, e é por isso que
o teste de atomicidade existe.

### O que não se toca: pendências

`pendencias` e `acionamentos` ficam intactas. Nenhuma query filtra por
`extracao_id_criada`/`extracao_id_ultima`, e a chave de `pendencias` é determinística e
independe da extração — apagá-las perderia o histórico de acionamento do time sem ganho algum.

Mas o worker **conta e informa** no relatório final:

> *"N pendências foram apuradas contra esta coleta e continuarão abertas com os números
> antigos até a próxima coleta deste termo."*

### O fallback que o worker relata (e não bloqueia)

`painel.py:49` e `sync_supabase.py:62` fazem `SELECT * FROM extracoes ORDER BY id DESC LIMIT 1`
— **global**, sem filtrar por termo. Apagar a extração de maior `id` muda qual snapshot o
painel local abre por padrão. A web não tem como saber o maior `id` do SQLite; o worker calcula
e **relata na mensagem final**. Relatar, não bloquear: a informação basta, e bloquear impediria
o caso de uso legítimo (apagar a coleta ruim, que é justamente a última).

### Idempotência é a invariante que sustenta tudo

Cada passo tem de ser seguro para rodar duas vezes, porque a reconciliação da subida do worker
(`worker_coleta.py:196-204`) devolve pedidos presos em `rodando` para `pendente` — um pedido de
exclusão pode ser reexecutado depois de já ter apagado parte das coisas. **Documentar isso no
docstring do módulo**, senão a próxima pessoa "otimiza" um passo e quebra a garantia.

---

## A tela

Lista das coletas publicadas em `/admin`, abaixo dos usuários. **Só admin** — o operador
dispara coletas, mas não apaga nada, e nem vê o botão. Hoje só o Clovis é admin.

```
COLETAS PUBLICADAS
termo    #    quando        cursos  blocos
BACEN    37   20/07 14:32   128    64.838   [excluir]
BACEN    33   04/07 09:11   128    64.838   ⏳ exclusão rodando
Amparo   40   23/07 10:40     8     2.980   ⛔ falhou: termo divergente [retentar]
```

### A fonte é a tabela `snapshot`, não a view

`snapshot_atual` faz `distinct on (termo)` e filtra `pronto` — mostraria **um** snapshot por
termo, que é exatamente o que não serve aqui (precisamos dos antigos e dos `pronto=false`, que
são justamente os candidatos a lixo). A tabela `snapshot` é também a única fonte que a Vercel
alcança, e conhece as coletas feitas por **CLI**, que `coleta_pedido` não conhece. O `resumo`
JSONB traz os KPIs para a coluna de peso — zero join.

### O que a tela admite não mostrar

Extrações que existem no `conteudo.db` mas **nunca foram publicadas** (o sync é não-fatal,
`coletor_ldi.py:285`) ocupam disco e não aparecem nesta lista. A tela **diz isso em nota**, em
vez de fingir ser um inventário completo. Fechar a lacuna exige o worker publicar um inventário
do SQLite — é a **1c**, no backlog.

### O selo de estado

A exclusão é assíncrona (até ~20 s de espera pelo ciclo do worker). Sem sinal na tela, o admin
clica de novo. A linha mostra o estado lendo `coleta_pedido` com `tipo=excluir` e status em
`(pendente, rodando, erro)`, indexado por `(termo, extracao_local)` extraído do alvo — **o mesmo
dado que a trava já precisa ler**, custo zero.

| Status do pedido | Na linha |
|---|---|
| `pendente` | `⏳ exclusão pedida` |
| `rodando` | `⏳ exclusão rodando` |
| `erro` | `⛔ falhou: <mensagem>` + **[retentar]** |
| `concluida` | a linha some (o snapshot foi apagado) |
| `cancelada` | volta ao botão **[excluir]** |

---

## Travas

Recusa dura da server action (`pedirExclusaoColeta`):

- `exigirAdmin()`;
- já existe pedido `excluir` **pendente ou rodando** para o mesmo alvo;
- existe pedido `rodando` cujo `extracao_id` é o alvo (não apagar o que está sendo escrito).

No worker: termo divergente do `extracoes.termo` → `erro`, nada apagado.

### Confirmação: digitar o termo, sempre

Uma regra só, sem "depende". Excluir coleta é irreversível e raro — o atrito é barato, e duas
UX diferentes na mesma tela é que sairiam caro.

Em **dois casos** a caixa mostra um aviso extra, e o segundo é o perigoso:

- **é o único snapshot do termo** → o termo some do seletor da web (falha visível, o time
  percebe);
- **é o mais recente de um termo com histórico** → a web cai para o anterior **sem aviso**
  (`snapshot_atual` faz `distinct on (termo) ... order by extracao_local desc`). A confirmação
  mostra o destino: *"BACEN passa a exibir a coleta #33 de 04/07, 14 dias mais velha."*

**Não bloquear em nenhum dos dois.** Apagar uma coleta ruim é justamente apagar a mais recente.

---

## Arquivos

**Criar**

| Arquivo | O quê |
|---|---|
| `exclusao_coleta.py` | Funções puras da exclusão |
| `tests/test_exclusao_coleta.py` | Os 6 testes |
| `supabase/schema_coleta_exclusao.sql` | Migração idempotente do `check` |
| `web/app/admin/coletas.tsx` | Lista + confirmação |

**Modificar**

| Arquivo | O quê |
|---|---|
| `worker_coleta.py` | Roteamento por `tipo` + guarda de tipo desconhecido |
| `web/lib/coleta.ts` | Tipo `"excluir"`, montar/ler o alvo JSON, indexar pedidos |
| `web/app/admin/actions.ts` | `pedirExclusaoColeta` (+ retentar do pedido de exclusão) |
| `web/app/admin/page.tsx` | Consultar `snapshot` + `coleta_pedido`, montar a lista |
| `web/app/coleta/fila.tsx` | Renderizar `tipo="excluir"` legível — senão a coluna despeja JSON |

A migração:

```sql
alter table coleta_pedido drop constraint if exists coleta_pedido_tipo_check;
alter table coleta_pedido add  constraint coleta_pedido_tipo_check
  check (tipo in ('termo','ids','excluir'));
```

---

## Testes

`unittest`, banco em memória, padrão de `tests/test_banco_conteudo.py`. Suíte atual: **119
testes verdes** — nenhum pode ficar vermelho.

1. **Isolamento** — duas extrações povoadas; apagar a #1; a #2 intacta nas 6 tabelas.
2. **Preservação** — `pendencias` e `acionamentos` com a mesma contagem antes e depois.
3. **Atomicidade** — monkeypatch levantando no 4º DELETE → **nada** foi apagado.
   *É o teste que prova a ausência de órfão silencioso; sem ele, a ordem dos DELETEs é só
   uma intenção escrita num comentário.*
4. **Idempotência** — rodar duas vezes; a segunda devolve zeros sem levantar.
5. **Roteamento no worker** — `tipo='excluir'` não chama `coletor_ldi.coletar` nem
   `probar_cookie`; tipo desconhecido → `erro`.
6. **Regressão do fallback** — após apagar a mais recente, `painel.dados_do_snapshot` devolve
   a anterior (documenta o comportamento para ninguém "consertar" sem querer).

### O lado TypeScript

As funções puras novas (`montarAlvoExclusao`, `lerAlvoExclusao`, `indexarPedidosExclusao`)
ficam em `web/lib/coleta.ts`. O `web/` **não tem test runner** (`web/package.json` só tem
`dev`/`build`/`start`) — mantém-se o padrão da casa: checagem Node ad-hoc registrada no plano,
como foi feito com `extrairIds`. Os testes travados concentram-se no Python, que é onde mora o
risco destrutivo.

---

## Verificação

Na ordem — o passo 3 é o que não pode ser pulado:

1. `py -m unittest discover -s tests` — a suíte inteira verde (119 + os novos).
2. Aplicar o SQL no Supabase; conferir com um `insert` de teste que `tipo='excluir'` é aceito e
   `tipo='xpto'` é recusado.
3. **Antes de atualizar o worker**, enfileirar um pedido `excluir` e confirmar que o worker
   antigo o marca `erro` sem coletar nada. É a defesa da migração — **tem de ser provada, não
   presumida**.
4. `git pull` + `systemctl restart worker-coleta` no VPS; retentar o mesmo pedido e confirmar
   que agora executa.
5. Alvo do teste real: a **extração 1 ou 2 do BACEN** (64.838 blocos cada, duplicatas
   idênticas) — conferir que a outra fica intacta e que `pendencias`/`acionamentos` não mudam
   de contagem.
6. Conferir na web que o snapshot sumiu do seletor e que o termo caiu para a coleta anterior.

## Ordem de deploy

**SQL no Supabase → provar a falha limpa do worker antigo (passo 3) → `git pull` + restart do
worker → merge da web.**

Vale a regra da sessão 10: mexeu em qualquer módulo que o `coletor_ldi.py` alcance por import,
o worker precisa de `git pull` + restart. Aqui o `worker_coleta.py` muda diretamente, então o
restart é obrigatório de qualquer forma.
