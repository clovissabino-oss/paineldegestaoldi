# Painel de Conteúdo do BO — Fundação (coletor + base)

**Data:** 05/07/2026 · **Status:** aprovado em conversa (design validado seção a seção com o Luiz)

## Contexto e objetivo

O Extrator LDI hoje audita apenas **vídeos** (migração velho×novo). A sondagem real da API
do BO (05/07/2026, cursos BACEN: 128 cursos, 10.545 aulas) mostrou que os blocos de cada
aula carregam muito mais: **115.526 questões**, 55.690 textos (tiptap), 3.048 PDFs, além
dos 10.264 vídeos. O objetivo amplo é um **painel de gestão/auditoria de conteúdo do novo
BO** que responda quatro famílias de pergunta:

1. **Inventário e completude** — o que cada curso/aula tem (contagens por tipo, vazios).
2. **Qualidade e consistência** — questão sem solução, aula sem bloco ativo, rascunhos etc.
3. **Auditoria de migração** — estender o velho×novo para além dos vídeos.
4. **Evolução no tempo** — o que mudou entre duas extrações.

Este spec cobre a **fundação (fase 1): coletor + base SQLite**. As fases 2-5 ficam em
contorno no final e ganharão specs próprios.

## Decisões de escopo (respostas do Luiz, 05/07/2026)

| Decisão | Escolha |
|---|---|
| Cobertura | **Por concurso, acumulando** numa base única local (BACEN + PRF + ...). Não é a carga do sistema inteiro (~123 mil cursos). |
| Hospedagem | Local primeiro; **hospedável no servidor do infosab**; possível entrega futura à Estratégia. |
| Profundidade | **Metadados + referência** (ID, tipo, banca, tópicos, tem-solução...). O conteúdo em si (enunciado, texto integral) fica no BO. |
| Relação com o app atual | **App novo ao lado.** O fluxo de vídeos/propostas (extrator + VisualizadorLDI) continua intacto; o extrator vira motor comum. |
| Scraping (Playwright) | **Descartado por ora** — a API `/bo/ldi` entrega tudo que a tela mostra, em JSON. Fica como plano B documentado se surgir dado que só exista na tela. |
| Abordagem | **B**: SQLite + coletor ampliado + painel Flask novo (vs. A: seguir em JSONs — quebra evolução/acúmulo; vs. C: stack completa Postgres+frontend — prematuro). |

## Arquitetura

```
                API do BO (api.estrategia.com/bo/ldi)
                cookie __Secure-SID + x-vertical  —  GET somente leitura
                                 │
                    coletor_ldi.py  (fase 1, novo)
                    varre TODOS os blocos de um concurso
                     │                          │
        (inalterado) │                          │ (novo)
   saida\videos_*.json/csv              saida\conteudo.db (SQLite)
             │                                  │
   VisualizadorLDI (hoje)              painel.py (fases 2-4, porta 8766)
   vídeos + propostas + de→para        inventário / qualidade / evolução
```

- `coletor_ldi.py` **importa** `extrator_ldi` (sessão, cookie, config, `listar_cursos`,
  `get_json`, `linha`, `id_sistema_antigo`) — mesmo padrão do `visualizador.py`.
  O extrator atual não muda em nada.
- Mesma varredura do extrator (cursos → `content_tree_cache` → `/bo/ldi/blocks` por aula),
  com duas diferenças: baixa blocos de **todas** as aulas (não só as com vídeo) e grava
  metadados de **todos os tipos** de bloco.
- **Cada execução = 1 snapshot** datado por termo. Nada é sobrescrito; rodar "BACEN" de
  novo cria outro snapshot (habilita a fase 4).
- `painel.py` é um Flask separado (single-file + HTML embutido, padrão da casa), porta
  8766, lendo **apenas** o SQLite — nunca a API.

## Modelo de dados (`saida\conteudo.db`)

Princípio: **snapshot é a unidade**. Cada rodada grava suas próprias linhas com
`extracao_id`. Alternativa descartada: histórico de versões por entidade (SCD) —
economiza espaço mas complica toda consulta e gravação.

Tabelas (SQLite, modo WAL):

- **`extracoes`** — `id` (PK autoincrement), `termo`, `vertical`, `iniciada_em`,
  `concluida_em`, `status` (`em_andamento` / `completa` / `parcial`),
  `total_cursos`, `total_aulas`, `total_blocos`, `erros_json`.
- **`cursos`** — PK `(extracao_id, curso_id)`: `nome`, `autores`, `criado_em_bo` e demais
  campos da listagem.
- **`capitulos`** — PK `(extracao_id, curso_id, capitulo_id)`: `nome`, `ordem`.
- **`aulas`** — PK `(extracao_id, curso_id, capitulo_id, item_id)`: `nome`, `path`,
  `ordem` e **contagens por tipo** vindas de graça do `content_tree_cache`
  (`qtd_videos`, `qtd_questoes`, `qtd_textos`, `qtd_pdfs`, `qtd_casts`, `qtd_outros`).
  A mesma aula (`item_id`) aparece em vários cursos: esta tabela registra o **vínculo**.
- **`blocos`** — PK `(extracao_id, item_id, bloco_id)`: blocos pertencem à **aula**
  (baixados 1× por aula). Tabela única para todos os tipos:
  - comuns: `tipo`, `ordem`, `ativo`, `rascunho`, `titulo`;
  - promovidas (filtros/joins frequentes): `questao_id`, `resposta_tipo`, `tem_solucao`,
    `tem_video_solucao` (questões); `video_id_antigo`, `duracao_seg` (vídeos);
    `tamanho_texto` (tiptap);
  - `meta` (JSON): o restante por tipo (bancas/provas, tópicos, media_id do PDF...).

Índices: `extracao_id`, `tipo`, `questao_id`, `video_id_antigo` (ponte futura com o
de→para do Metabase).

**Volumetria:** BACEN ≈ 185 mil blocos/snapshot ≈ 30-50 MB. Dezenas de snapshots ≈ 1-2 GB
— confortável. Expurgo (manter N meses + 1/mês antes) só se doer; **não** construir agora.

## O coletor (`coletor_ldi.py`)

```powershell
py coletor_ldi.py                  # usa o termo_busca do config.json
py coletor_ldi.py --termo BACEN    # concurso explícito
py coletor_ldi.py --continuar      # retoma a coleta interrompida mais recente do termo
py coletor_ldi.py --com-videos     # além da base, emite o videos_*.json/csv clássico
```

Fluxo em 4 passos (mensagens de progresso no console, como o extrator):

1. **Cursos** — `listar_cursos()`; grava `extracoes` com `em_andamento` e persiste
   cursos/capítulos/aulas com contagens (inventário de alto nível garantido mesmo se o
   resto falhar).
2. **Aulas únicas** — deduplica `item_id` entre cursos; **todas** as aulas.
3. **Blocos em paralelo** — `ThreadPoolExecutor` com `concorrencia` do config.
   **Cada aula = 1 transação** (parse → metadados → insert): é o que torna a retomada segura.
4. **Fechamento** — 1 rodada de retry para aulas que falharam; o que restar vai a
   `erros_json` e o snapshot fecha `parcial` (contagem no console); sem falhas, `completa`.

Tratamento de erros:

- **401/403 → aborta imediatamente** com mensagem de cookie vencido. Snapshot fica
  `em_andamento`, retomável após renovar o cookie.
- **Falha pontual numa aula → registra e segue.** Nunca derruba a coleta.
- **Interrupção → `--continuar`** acha o snapshot `em_andamento` mais recente do termo e
  baixa só as aulas ainda sem blocos na base.

Detalhes:

- Parse "bloco da API → linha de metadados" em **funções puras por tipo** (dict → dict),
  testadas com payloads reais — a parte com maior risco quando a API mudar.
- `--com-videos` reusa `linha()` do extrator para emitir o arquivo clássico na mesma
  varredura. Opcional, desligado por padrão.
- ID antigo do vídeo: **mesma** `id_sistema_antigo()` do extrator (armadilha do ponto de
  milhar já resolvida lá; não duplicar).

## Painel e fases seguintes (contorno — specs próprios na hora certa)

- **Fase 2 — Inventário**: seletor concurso/snapshot → KPIs → tabela curso→capítulo→aula
  com contagens, ordenável/filtrável. Tela para consultas SQL simples. Reusar a linguagem
  visual do Visualizador (KPIs, filtros, ⧉ copiar TSV, 📄 relatório HTML).
- **Fase 3 — Qualidade**: cada regra = **consulta SQL nomeada + severidade** numa lista
  declarada. Tela de achados com filtro/export. Regra nova = consulta nova.
- **Fase 4 — Evolução**: dois snapshots do mesmo termo → adicionados/removidos/alterados
  por nível. O modelo foi desenhado para isso; aqui é só a tela.
- **Fase 5 — Migração de questões**: começa com **investigação** — existe fonte do
  sistema antigo para questões (como a 19885 é para vídeos)? A ponte `questao_id` já
  estará na base.

## Riscos

| Risco | Mitigação |
|---|---|
| API interna muda sem aviso | Parse puro testado com payloads reais; erro de formato derruba 1 aula, não a coleta; `parcial` explícito |
| Cookie no servidor | Coleta é CLI; no infosab roda agendada com `cookie.txt` local; renovação ~mensal (aviso proativo de vencimento é melhoria futura natural) |
| Dados da empresa fora | Só metadados, mas **combinar com a Estratégia antes de hospedar fora** |
| Base crescer demais | Rota de expurgo desenhada; implementar só se doer |
| Dado que só exista na tela | Plano B: automação de navegador (Playwright) — hoje sem caso de uso |

## Testes

- `unittest` nas funções puras (parse por tipo de bloco, contagens) com payloads reais
  capturados da sondagem.
- Integração do schema: base em memória → inserir → consultar.
- Fases de painel testarão suas consultas SQL contra fixture. Testa-se onde a API pode
  trair — sem meta de cobertura teatral.
