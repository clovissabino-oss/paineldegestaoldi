# Verificação com dados reais — "Itens no MB" (29/07/2026)

Portão de aceite da Task 7 do plano `2026-07-29-avaliacao-por-item`. Mede o antes/depois da
contagem de "Itens no MB" contra o `saida\conteudo.db` disponível nesta máquina e confere os
cursos de controle (Amparo/DMAE).

## ⚠ Resultado principal: a medição não é conclusiva nesta base local

O `saida\conteudo.db` desta máquina **não tem nenhuma linha com `vinculado_mb` preenchido**:

```
total linhas aulas (toda a base): 24949
vinculado_mb NOT NULL (toda a base): 0
valores distintos de vinculado_mb: [(None,)]
```

Isso vale para as 4 extrações presentes no banco:

| extracao_id | termo | status | iniciada_em | linhas em `aulas` | `vinculado_mb` não nulo |
|---|---|---|---|---|---|
| 1 | BACEN | completa | 2026-07-06T18:30:08 | 10544 | 0 |
| 2 | BACEN | completa | 2026-07-06T23:56:22 | 10544 | 0 |
| 3 | PRF | completa | 2026-07-20T16:07:40 | 3739 | 0 |
| 5 | Prefeitura de Coromandel - MG | completa | 2026-07-20T20:57:25 | 122 | 0 |

**Causa raiz identificada:** o passo que lê o vínculo com o Material Base
(`_completar_vinculo_mb`, via `GET /bo/ldi/chapters/{id}/items`) só existe no `coletor_ldi.py`
desde os commits `4ba8433` e `2e7e6b7`, ambos de **2026-07-23**. As 4 extrações desta base
são de **06/07 e 20/07** — todas anteriores à existência do passo. Não é um bug: são
snapshots que antecedem a feature, e o campo não é preenchido retroativamente (só na coleta).

**Consequência:** com `vinculado_mb` nulo em 100% das linhas, tanto a contagem "velha"
(consulta que vaza o filtro por curso) quanto a "nova" (`painel.dados_avaliacao`) dão sempre
`0/0` para "Itens no MB" — em qualquer curso. O resultado "0 cursos com diferença" abaixo é,
portanto, **um resultado degenerado desta base, não uma confirmação de que a correção está
certa**. Para uma medição real do antes/depois, é preciso rodar esta verificação contra um
`conteudo.db` com pelo menos uma extração coletada **depois** de 23/07 (ex.: a máquina do
Clovis, que tem acesso ao admin do LDI para completar o vínculo).

Adicionalmente, **nenhum curso "Amparo" nem "DMAE"** existe nesta base — os 181 cursos
distintos aqui são só de BACEN (128), PRF (52) e "Prefeitura de Coromandel - MG" (1). Os
controles do aceite anterior (Amparo 68/75, DMAE 319/345) vêm de outra coleta, feita na
máquina do Clovis, que não está presente neste `saida\conteudo.db`.

## O que foi medido mesmo assim

Rodei o comparativo do Step 1 do brief, **corrigido** para varrer os cursos de **todas as
extrações** da base (não só a mais recente — a mais recente, extração 5, tem 1 curso só e
nenhum item compartilhado, o que esconderia justamente o que a correção conserta) e usando,
para cada curso, **a mesma extração que `painel.dados_avaliacao` resolve sozinho**
(`SELECT MAX(extracao_id) FROM cursos WHERE curso_id=?`), para comparar maçã com maçã.

Script usado (`mode=ro`, só stdlib + `painel`/`sqlite3`):

```python
import sqlite3, sys
sys.path.insert(0, r"C:\Users\Clovis Sabino\Projetos\Estratégia Claude\🎬 EXTRATOR_LDI_VIDEOS")
import painel

con = sqlite3.connect(
    r"file:C:\Users\Clovis Sabino\Projetos\Estratégia Claude\🎬 EXTRATOR_LDI_VIDEOS\saida\conteudo.db?mode=ro",
    uri=True)
con.row_factory = sqlite3.Row

extracoes = {r["id"]: r["termo"] for r in con.execute("SELECT id, termo FROM extracoes")}
cursos = [dict(r) for r in con.execute("SELECT DISTINCT curso_id FROM cursos ORDER BY curso_id")]

linhas, controles = [], {}
for c in cursos:
    curso_id = c["curso_id"]
    e = con.execute("SELECT MAX(extracao_id) FROM cursos WHERE curso_id=?", (curso_id,)).fetchone()[0]
    nome = con.execute("SELECT nome FROM cursos WHERE extracao_id=? AND curso_id=?",
                        (e, curso_id)).fetchone()["nome"]

    d = painel.dados_avaliacao(con, curso_id, depara={})
    novo_t = sum(x["itens_total"] for x in d["capitulos"])
    novo_m = sum(x["itens_mb"] for x in d["capitulos"])

    # antigo: a consulta que não filtrava por curso na etapa final
    velho_t = velho_m = 0
    for cap in con.execute("SELECT capitulo_id FROM capitulos WHERE extracao_id=? AND curso_id=?",
                            (e, curso_id)):
        itens = [r[0] for r in con.execute(
            "SELECT item_id FROM aulas WHERE extracao_id=? AND curso_id=? AND capitulo_id=?",
            (e, curso_id, cap[0]))]
        if not itens:
            continue
        marks = ",".join("?" * len(itens))
        r = con.execute(
            f"SELECT COUNT(*), SUM(vinculado_mb) FROM aulas WHERE extracao_id=? "
            f"AND vinculado_mb IS NOT NULL AND item_id IN ({marks})", (e, *itens)).fetchone()
        velho_t += r[0] or 0
        velho_m += r[1] or 0

    linha = {"curso_id": curso_id, "nome": nome, "extracao_id": e, "termo": extracoes.get(e, "?"),
             "velho_m": velho_m, "velho_t": velho_t, "novo_m": novo_m, "novo_t": novo_t}
    if "amparo" in nome.lower():
        controles["Amparo"] = linha
    if "dmae" in nome.lower():
        controles["DMAE"] = linha
    if (velho_t, velho_m) != (novo_t, novo_m):
        linhas.append(linha)
```

### Resultado bruto

```
Extrações na base: {1: 'BACEN', 2: 'BACEN', 3: 'PRF', 5: 'Prefeitura de Coromandel - MG'}
Cursos distintos (todas as extrações): 181

cursos com diferenca: 0

--- Controles ---
Amparo: NÃO ENCONTRADO na base (busca por nome não bateu)
DMAE: NÃO ENCONTRADO na base (busca por nome não bateu)
```

**0 de 181 cursos** (das 4 extrações: BACEN ×2, PRF, Prefeitura de Coromandel-MG) tiveram
diferença entre a contagem velha e a nova — mas, como explicado acima, isso é esperado e
**não prova nada**, porque `vinculado_mb` é nulo em toda a base: as duas contagens dão
sempre `0/0`.

### Verificação conceitual do bug (fora da comparação agregada)

Para confirmar que a lógica antiga realmente vazava o filtro por curso (mesmo sem dado de
`vinculado_mb` para testar o efeito numérico), localizei um item real compartilhado entre
dois cursos na extração 1 (BACEN):

```
item_id 00098d04-f08c-4e40-838a-ddd83efbbae0
  curso 0231ab16-...  capitulo c169bf98-...  path 8.1  vinculado_mb=None
  curso 73a05b3e-...  capitulo c169bf98-...  path 4.1  vinculado_mb=None
```

A extração 1 tem **10.544 vínculos, 3.612 itens únicos, 1.990 itens em mais de um curso**
(confirmado por consulta direta). A consulta antiga (`item_id IN (...)` sem filtro de
`curso_id` na etapa final) contaria as linhas de **todos** os cursos que compartilham aquele
item_id, não só do curso do capítulo em avaliação — exatamente o vazamento descrito no plano.
Com `vinculado_mb` seria `NOT NULL` para esses itens, o efeito numérico apareceria (o "velho"
inflaria `itens_total`/`itens_mb` pelo número de cursos que compartilham cada item); nesta
base, como `vinculado_mb` é sempre nulo, o filtro `WHERE vinculado_mb IS NOT NULL` zera as
duas contagens antes que o vazamento tenha qualquer chance de se manifestar.

## Controles (Amparo/DMAE)

Não encontrados nesta base — nenhum curso com "Amparo" ou "DMAE" no nome entre os 181
cursos distintos (BACEN, PRF, Prefeitura de Coromandel-MG). Conforme o critério de parada
combinado: **isso é informação, não fracasso** — os controles vêm de uma coleta feita na
máquina do Clovis (com acesso ao admin do LDI), que não está presente neste `conteudo.db`
local. Não há, portanto, como confirmar aqui que os números de aceite (Amparo 68/75, DMAE
319/345) permanecem inalterados — essa confirmação depende de rodar esta mesma verificação
na máquina do Clovis.

## Pendências de aceite humano

- **Step 2 (controles Amparo/DMAE):** não verificável nesta máquina — pendente de rodar
  `py -m unittest` deste mesmo script (ou o `/avaliacao` do painel) no `conteudo.db` do
  Clovis, que tem os cursos Amparo/DMAE e (presumivelmente) `vinculado_mb` populado.
- **Step 3 (ordem dos capítulos contra o admin do LDI):** exige login no admin da Estratégia
  com cookie válido — aceite humano do Clovis, fora do alcance deste agente. Não tentado.
- **Antes/depois real de "Itens no MB":** só será possível medir de fato numa base com pelo
  menos uma extração coletada após 23/07/2026 (data do `_completar_vinculo_mb`). Recomendo
  rodar o script acima contra o `conteudo.db` de produção/do Clovis antes de considerar a
  correção numericamente validada.

## Suíte de testes

```
py -m unittest discover -s tests
...
Ran 119 tests in 65.453s

OK
```

Sem falhas nem erros (exit code 0). Os `ResourceWarning: unclosed database` que aparecem no
meio da saída são de conexões sqlite não fechadas em testes pré-existentes (não relacionados
a esta tarefa) e não afetam o resultado.
