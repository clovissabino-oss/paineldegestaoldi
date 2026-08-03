# CLI de exclusão local + compactação — design

_Data: 03/08/2026 · **substitui a entrega 1b** do roadmap
`docs/superpowers/specs/2026-07-30-exclusao-coletas-e-selecao-multipla-roadmap.md`_

## Por que a 1b mudou de lugar

O roadmap justificava o `VACUUM` assim: *"o `conteudo.db` já está em **242 MB**"*. Esse número
era do banco **deste notebook**. O banco que a 1b compactaria é o **do VPS**, e medi os dois em
03/08:

| | VPS (`/opt/extrator-ldi`) | Notebook |
|---|---|---|
| Tamanho do `conteudo.db` | **41,2 MB** | 231 MB |
| Espaço recuperável (freelist) | 0 MB | 0 MB |
| Disco livre na partição | **88 GB** (9% usado) | 156 GB |
| Extrações | 7 | 4 |

**O `VACUUM` no VPS devolveria uma dezena de MB num disco com 88 GB livres** — em troca de um
lock exclusivo de minutos e de código novo no worker. Trabalho real, ganho irrelevante.

O problema de disco existe, mas **no notebook**: as duas extrações do BACEN são idênticas
(64.838 blocos cada) e somam **129.676 dos 182.858 blocos — 71% do banco**. E a exclusão pela
web **não as alcança**: o worker só enxerga o disco do VPS.

Isso inverte a ordem do roadmap. O CLI, que estava listado como item pequeno de backlog, é
**pré-requisito** para o `VACUUM` ter o que compactar. Compactar sem apagar não recupera nada
(freelist zero — nunca se apagou nada localmente).

## O que se entrega

Uma interface de linha de comando em `exclusao_coleta.py`, que hoje é só um módulo importado
pelo worker. **A lógica destrutiva já existe, testada e revisada** (as 6 garantias da 1a,
incluindo a transação atômica com `extracoes` por último). Falta a porta de entrada para quem
opera na própria máquina.

```
py exclusao_coleta.py --listar
py exclusao_coleta.py --excluir 1 [--compactar]
py exclusao_coleta.py --compactar
```

## Decisões

| Assunto | Decisão |
|---|---|
| Supabase | **Não é tocado** — o CLI mexe só no arquivo local |
| Confirmação | Digitar o termo, como na web |
| Banco em uso | Recusa **antes** de qualquer DELETE |
| Checagem de espaço | **1,5×** o tamanho do banco (medido), não 1× |
| `wal_checkpoint` | Antes **e depois** do `VACUUM` |
| `tipo='vacuum'` na fila | **Fora de escopo** (o VPS não precisa) |

---

## O que o CLI não faz: tocar no Supabase

Diferença deliberada em relação à exclusão pela web. Se um comando rodado no notebook apagasse
o snapshot da nuvem, ele mudaria **o que o time inteiro vê** — e a web já tem tela própria para
isso, com trava e confirmação.

Consequência que o `--listar` precisa deixar explícita: apagar uma extração local **não** tira
nada do ar. O snapshot continua publicado e é autossuficiente (o payload já vai agregado). Daí a
coluna **"publicada?"** na listagem — ela responde a pergunta que decide o risco.

Medido em 03/08, cruzando `extracoes.iniciada_em` com `snapshot.iniciada_em`:

| Extração local | Publicada? |
|---|---|
| #1 BACEN 06/07 18:30 | **não** — apagar não afeta a web |
| #2 BACEN 06/07 23:56 | sim (a web depende dela) |
| #3 PRF 20/07 16:07 | sim |
| #5 Coromandel 20/07 20:57 | não |

**A #1 é a duplicata a remover:** mesmo conteúdo da #2, mais antiga, e não publicada. O CLI não
escolhe por ninguém — mas mostra o que basta para escolher certo.

A checagem consulta o Supabase; **sem rede ou sem credencial, a listagem não pode quebrar** —
mostra "?" na coluna e segue. Listar é operação de leitura e tem de funcionar offline.

---

## Travas

Herda as da 1a (`conferir_extracao` com termo + data, `apagar_extracao` na transação única) e
acrescenta o que é próprio de CLI:

- **Confirmação digitando o termo.** Mesma regra da web, sem "depende". Vale também quando
  `--excluir` é chamado direto, sem `--listar` antes: mostra as contagens do alvo e só então
  pede a confirmação.
- **Banco em uso por outro processo → recusa.** O `painel.py` aberto ou uma coleta rodando
  seguram o arquivo; um `BEGIN IMMEDIATE` de teste detecta isso **antes** de qualquer DELETE.
  Sem essa trava o erro apareceria no meio da transação — que reverteria, mas depois de o
  usuário achar que já tinha apagado.
- **Sem `--sim`/`--forcar`.** Automatizar exclusão irreversível não é caso de uso: quem apaga
  está olhando a tela. Não construir a porta evita que alguém a use por engano num agendamento.

---

## A compactação

`--compactar` roda `VACUUM`. O desenho vem de medições feitas em 03/08, não de suposição:

### 1. `wal_checkpoint(TRUNCATE)` antes **e depois**

Medido: logo após o `VACUUM`, o conjunto de arquivos ainda ocupava **41,5 MB**; só depois do
checkpoint final caiu para **20,7 MB**. Em WAL o `VACUUM` escreve o resultado no WAL, e o ganho
só materializa no consolidado.

**É o passo que faz a entrega parecer quebrada se for esquecido** — o comando diz "compactado" e
o `ls` mostra o arquivo do mesmo tamanho.

### 2. Espaço livre exigido: 1,5× o banco

O roadmap estimava "~242 MB temporários", ou seja, 1× o arquivo. **Medi o pico real: 62,1 MB
para um banco de 41,3 MB — 1,50×**, porque o WAL cresce até o tamanho dos dados vivos enquanto
o `VACUUM` roda.

Faltando espaço → **recusa antes de apagar qualquer coisa**. Falha limpa e retentável é mais
previsível que "apagou mas não compactou".

### 3. `VACUUM` fora de transação, com a conexão do projeto

Verifiquei que `VACUUM` roda com `isolation_level=''` (o default que `banco_conteudo.abrir` usa)
sem erro — **não é preciso mexer em `banco_conteudo.py`**. Isso importa porque aquele módulo é
compartilhado com o coletor e o painel.

### 4. `freelist_count` não serve de métrica

Descoberta que corrigiu o próprio desenho: num teste em que apaguei **metade** dos dados, o
`freelist_count` reportou **0 MB livres** e o `VACUUM` ainda assim reduziu o arquivo de 41,2 para
20,6 MB. As páginas ficam fragmentadas internamente, não na lista livre.

**Consequência prática:** o CLI **não promete** um ganho antes de compactar. Relata tamanho
antes → depois, medido no arquivo. Prometer com base no freelist seria prometer errado.

---

## Arquivos

**Modificar:** `exclusao_coleta.py` (bloco `main()` + `argparse`, no padrão de
`coletor_ldi.py:295-320`), `tests/test_exclusao_coleta.py`

**Não mudam:** `banco_conteudo.py`, `worker_coleta.py`, nada em `web/`. A entrega é local.

---

## Testes

Reusam o padrão dos 19 que já existem em `tests/test_exclusao_coleta.py` (banco em memória,
`unittest`). Suíte atual: **143 verdes** — nenhum pode ficar vermelho.

1. **Publicada ou não** — `--listar` marca certo com o Supabase mockado; **e não quebra** quando
   ele está indisponível (mostra "?").
2. **Confirmação errada** → nada apagado, código de saída ≠ 0.
3. **Banco em uso** por outra conexão → recusa **antes** de apagar.
4. **Espaço insuficiente** → recusa sem apagar nada.
5. **`VACUUM` de verdade** num banco temporário: enche, apaga metade, compacta, e o arquivo
   **encolhe de fato** — com o checkpoint depois.
   *É o teste que prova a entrega inteira; sem ele, "compactado" é só uma mensagem na tela.*
6. **Sem `--compactar`, o arquivo não encolhe** — prova que a compactação é opt-in e que o teste
   5 mede o que diz medir.

---

## Verificação

1. `py -m unittest discover -s tests` — 143 + os novos, verde.
2. `py exclusao_coleta.py --listar` na base real: 4 extrações, com #2 e #3 marcadas "publicada".
3. `py exclusao_coleta.py --excluir 1 --compactar`, digitando `BACEN` — o alvo é a duplicata não
   publicada. **Conferir com `ls` que o arquivo encolheu de fato** (231 MB → ~100 MB esperado).
4. Abrir o painel local e confirmar que PRF, Coromandel e o BACEN #2 continuam íntegros.
5. Conferir na web que **nada mudou** — é o ponto do "não toca no Supabase".

**Deploy:** nenhum. Não há worker, web nem migração envolvidos.
