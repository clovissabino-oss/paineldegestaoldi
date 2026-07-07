# Fase 2 — Avaliação de Livro/Disciplina + Controle de Qualidade

**Data:** 06/07/2026 · **Status:** aprovado em conversa (mockups v3-v6 validados pelo Luiz; formato
final da planilha aprovado: "Podemos seguir por este modelo")

## Contexto

A fundação (spec 2026-07-05) entregou coletor + base SQLite (`saida\conteudo.db`) com snapshots
de todos os blocos. A fase 2 transforma isso em ferramenta de trabalho do time de conteúdo. O
formato-alvo veio do levantamento real da PRF (`Modelo de Planilha - Dados.xlsx`): avaliação por
livro/disciplina. Após iterações de mockup, o produto principal aprovado é a **Planilha de
Avaliação 100% automática** (sem colunas de julgamento — decisão de 06/07).

## Decisões do Luiz (06/07/2026)

| Tema | Decisão |
|---|---|
| Régua de atualidade | **2/5 anos**, única, para vídeos (ano de gravação real) e questões (ano da prova): verde ≤2, amarelo 3-5, vermelho >5. Faixas exibidas: **≤2020 · 2021-23 · 2024-26** |
| Completude | Pendências: aula sem questão, aula sem texto (<1.000 caracteres). Aula sem vídeo = **informativa** (73% das aulas — desenho pedagógico, não defeito; rebaixada com aval do Luiz) |
| Ciclo da pendência | **Completo com baixa automática**: nova → enviada → resolvida/ignorada; chave determinística; próximo snapshot dá baixa no que sumiu |
| Indicador síntese | **Sem nota por curso** — só contagens por severidade |
| Planilha | **Sem** comparação com PDF (linhas = capítulos do LDI) e **sem** colunas de julgamento/matriz antiga. Banca-alvo **escolhida na geração, opcional** |
| Colunas da planilha (v6) | Capítulo · Questões (total, emb.+texto) · Banca-alvo/outras · % ano da prova (3 faixas + barra) · Soluções das embedadas (texto·vídeo) · Vídeos (qtd·tempo) · % ano de gravação (3 faixas + barra) + Dashboard |

## Produto 1 — Planilha de Avaliação por Livro/Disciplina (tela principal do painel)

Rota `/avaliacao` no `painel.py` (porta 8766):

1. **Seleção**: curso (da extração mais recente; busca por nome) + banca-alvo (opcional; sugestão
   automática = banca mais frequente nas questões do curso).
2. **Tabela por capítulo do LDI** (colunas v6 acima, células 100% automáticas):
   - Questões: embedadas (blocos `question`) + em texto (detector do coletor v1.1);
   - Banca/ano: colunas `banca`/`ano` da base (embedadas) + refs do detector (em texto);
   - Soluções: `tem_solucao` (📝) e `tem_video_solucao` (🎬) das embedadas, com %;
   - Vídeos: contagem, duração somada, % por faixa de ano de **gravação real** (join
     `video_id_antigo` × cache `saida\metabase_depara.json.gz`, carregado 1× em memória).
3. **Dashboard**: capítulos, questões totais, % banca-alvo, % questões 2024-26, % embedadas com
   solução texto/vídeo, vídeos·tempo total, % vídeos 2024-26.
4. **Exports**: ⬇ CSV (`;`, BOM utf-8, colunas do mockup v6) e impressão (Ctrl+P).
5. Percentuais sempre sobre o universo **com dado** (questões com prova identificada; vídeos com
   data casada), com o denominador exibido ("N com prova identificada").

## Produto 2 — Motor de Qualidade (regras + pendências + ciclo)

Módulo `regras_qualidade.py`, executado automaticamente **ao fim de cada coleta** (e via
`py regras_qualidade.py --extracao N` avulso):

- **Catálogo declarativo**: lista de regras `(id, nome, severidade, escopo, funcao_sql)`.
  Catálogo v1 (contagens reais no snapshot #1 do BACEN entre parênteses):
  - `Q1` questão sem solução — crítica (12.837 únicas / 33.266 por vínculo)
  - `Q2` questão desatualizada pela régua 2/5 — atenção/crítica (requer banca/ano do v1.1)
  - `V1` vídeo com gravação envelhecida 2/5 — atenção/crítica (1.734 / 679)
  - `V2` vídeo fora do de→para — crítica (3)
  - `C1` curso sem nenhuma aula — atenção (21)
  - `A1` aula sem nenhuma questão (emb. nem texto) — atenção (1.153 só-embedadas)
  - `A2` aula sem vídeo — **informativa**, não materializa pendência (2.636 = 73%)
  - `A3` aula sem texto (<1.000 chars) — atenção (1.170)
  - `B1` bloco em rascunho há >30 dias — atenção (0; sentinela)
- **Tabelas novas** em `conteudo.db`:
  - `pendencias(chave PK, extracao_id_criada, extracao_id_ultima, regra, severidade, curso_id,
    item_id, bloco_id, descricao, status, criada_em, resolvida_em)` — `chave` determinística
    (`regra|curso_id|item_id|bloco_id`), `status ∈ {nova, enviada, resolvida, ignorada}`.
  - `acionamentos(chave_pendencia, status, observacao, registrado_em)` — histórico de mudanças.
- **Baixa automática**: ao rodar sobre o snapshot N, pendência aberta que não reaparece →
  `resolvida` (com `resolvida_em`); a que reaparece atualiza `extracao_id_ultima` e mantém status.
  `ignorada` nunca reabre.
- API no painel: `/api/pendencias` (GET com filtros; POST muda status). Tela rica de Pendências
  (mockup v3: agrupada por curso/professor + relatório/CSV de acionamento) fica para a fase 2.1 —
  nesta fase o painel home mostra contagens por severidade/regra.

## Pré-requisito — Coletor v1.1

1. **banca/ano**: `exams[0].year` + `badges` (textos: banca, órgão) → colunas promovidas
   `banca TEXT`, `ano INTEGER` em `blocos`; órgão/cargo no `meta`. (Payload real validado 06/07.)
2. **Tópicos**: `topics[].path_name` (lista) → `meta.topicos` = último nível; caminho completo em
   `meta.topicos_path` (só o principal, `is_main_classification`).
3. **Autores**: a listagem devolve `authors` = UUIDs e `authors_name = None`. Fonte correta:
   `GET /bo/ldi/courses/{id}` → `structured_authors[].full_name` (validado 06/07). O coletor busca
   o detalhe **1×/curso** (paralelo, mesmas retentativas) e grava em `cursos.autores`
   (" | " separado). Fallback: regex `Profs?\. ...` no nome do curso.
4. **Detector de questões em texto**: durante a coleta, extrair texto dos nós do tiptap e aplicar
   `\((BANCA...)\s*[/–-]\s*(\d{4})[^)]*\)` (bancas conhecidas + "Banca X"/"Instituto X"/"Inéditas")
   → colunas `qtd_questoes_texto INTEGER` no bloco tiptap + `meta.questoes_texto` =
   `[{banca, ano, resto}]`. **O texto em si continua não sendo armazenado.**
5. **Schema/migração**: `abrir()` aplica `ALTER TABLE blocos ADD COLUMN ...` tolerante (ignora
   "duplicate column") + índice novo `ix_blocos_item ON blocos(item_id)` (consultas por aula
   ficaram lentas sem ele). Snapshots antigos ficam com colunas NULL — válido.
6. **Investigação registrada** (não bloqueia): `block_type_count` da árvore conta mais que os
   blocos ativos devolvidos (ex.: 163 vs 53 no curso de Direito Penal — provável contagem de
   versões/inativos). As contagens de `aulas.qtd_*` seguem úteis como indicador, mas as telas
   derivam números **dos blocos coletados**, não do contador da árvore.
7. Re-coleta do BACEN ao final para popular os campos novos (snapshot #2).

## Fluxo de dados (resumo)

```
coletor_ldi (v1.1) ──► conteudo.db ──► regras_qualidade (pós-coleta) ──► pendencias/acionamentos
                          │
painel.py ────────────────┴──► /avaliacao (planilha viva, + cache metabase p/ gravação)
                               /api/pendencias · home com contagens
```

## Testes

- `parse_blocos`: banca/ano/tópicos com payload real do `exams`/`topics`; detector de questões em
  texto (padrões reais: "(CEBRASPE/2025/MPE CE/...)", "Inéditas"); casos sem exams/ano.
- `banco_conteudo`: migração em base existente (colunas novas + índice, idempotente).
- `regras_qualidade`: catálogo roda em fixture; chave determinística; baixa automática
  (pendência some → resolvida; persiste → mantém status; ignorada não reabre).
- `painel`: agregação da planilha por capítulo (fixture com banca/ano/soluções/gravação).
- Verificação real: re-coleta BACEN + `/avaliacao` do curso de Direito Penal ≈ mockup v6.

## Publicação (meta do Luiz: "publicar em breve")

- Commit + **push** para `github.com/clovissabino-oss/videosldi` (autorizado em 06/07).
- Executáveis: `ColetorLDI.exe` (`--onefile coletor_ldi.py`) e `PainelLDI.exe`
  (`--onefile --add-data "painel.html;." painel.py`). ExtratorLDI/VisualizadorLDI inalterados.
- Pacote de publicação = pasta com os 4 exes + `config.json` + `TUTORIAL.md` (seção nova do painel).

## Fora de escopo (registrado para depois)

- Tela rica de Pendências com acionamento por professor (mockup v3) — fase 2.1.
- Telas árvore/busca de blocos (mockups v1/v2) — apoio, quando a demanda voltar.
- Comparação LDI × PDF (decisão: desconsiderar), busca ao vivo de enunciado na ficha,
  export XLSX nativo (CSV atende), evolução entre snapshots (fase 4 do roadmap original).
