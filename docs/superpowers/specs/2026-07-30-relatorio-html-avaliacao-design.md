# Relatório HTML compartilhável da Avaliação — design

_Data: 30/07/2026 · Fase 2.3 do Painel de Conteúdo_

## Problema

A tela `/avaliacao` exporta **⬇ CSV (Excel)**, que serve a quem vai cruzar dados numa
planilha. Falta o outro uso: **mandar a avaliação para alguém ler** — inclusive para quem não
tem login no app. Hoje isso obriga a tirar print ou a compartilhar a planilha, que não se
apresenta sozinha.

## O que se entrega

Um botão **📄 HTML (compartilhar)** ao lado do CSV, nas duas telas, que baixa **um arquivo
HTML autossuficiente** com a avaliação da disciplina selecionada. Convive com o CSV; não o
substitui.

## Decisões

| Assunto | Decisão |
|---|---|
| Conteúdo | Capítulos + itens, cada capítulo num `<details>` recolhido |
| Interatividade | **Zero JavaScript** — expandir/recolher pelo `<details>` nativo |
| Alcance | Painel local **e** cópia web (o time também gera) |
| Onde é gerado | **No navegador**, a partir do `D` já em memória |
| Paleta | Clara fixa, não as variáveis de tema |

### Por que gerar no navegador

O payload já está no cliente — não há dado novo a buscar. Gerar no servidor exigiria **duas**
implementações (rota Flask + rota Next), a da web acoplada ao JWT do usuário, para produzir um
arquivo estático. E é exatamente o padrão que o projeto já usa em `ui.html:1690-1744`
(`gerarRelatorioArvore`), que baixa via Blob.

O preço, nomeado: JS dentro de HTML single-file **não tem harness de teste neste projeto**, então
a verificação é manual (como nas Tasks 4 e 5 da fase anterior).

### Por que zero JavaScript

Um anexo de e-mail sem `<script>` abre em qualquer navegador, offline, e não dispara alerta de
segurança. O `<details>` nativo entrega expandir/recolher sem custo.

**Consequência aceita:** no `Ctrl+P` sai **só o que estiver aberto**. Imprimir o curso inteiro
exige abrir os capítulos antes. Ter um "abrir tudo" dentro do arquivo exigiria JS — as duas
coisas são incompatíveis, e o zero-JS vale mais, porque é o que faz o anexo abrir em qualquer
lugar.

## Estrutura do arquivo

- **Cabeçalho** — nome do curso, professores, selo de frescor do dado (`Dados de DD/MM HH:MM`),
  instante da geração e a **banca-alvo ativa**, se houver. É o que torna o arquivo auditável
  meses depois: quem recebe sabe de quando é o dado e com que filtro foi tirado.

  O selo de frescor **só existe na cópia web** (`#frescor`); o painel local não tem essa
  informação. Para a função sair **idêntica nos dois arquivos**, o gerador lê
  `document.getElementById("frescor")?.textContent` e omite a linha quando vier vazio — em vez
  de dois códigos diferentes que teriam de ser mantidos em paralelo.
- **Os 8 KPIs** do dashboard, iguais aos da tela.
- **A tabela** — um `<details>` por capítulo (recolhido), com a linha do capítulo no `<summary>`
  e os itens dentro. Mesmas 8 colunas da tela, mesma numeração (selo de posição + rótulo do
  nome).

⚠ **O relatório não usa `<table>`.** `<details>`/`<summary>` **não podem** envolver `<tr>` — o
HTML não permite essa aninhagem e o navegador expulsa os elementos da tabela, quebrando o
layout. O relatório usa **CSS grid**, com o mesmo `grid-template-columns` aplicado à linha do
`<summary>` e às linhas de item, para as colunas alinharem **entre capítulos diferentes**, não
só dentro de um. O relatório do `ui.html` já é baseado em `div`/flex pelo mesmo motivo — não é
uma invenção nova, é o padrão que existe.
- **Rodapé** identificando a origem e o uso interno.

### Três decisões técnicas

**Paleta clara fixa**, não as variáveis de tema (`--ink`, `--surface`…). O arquivo é para
compartilhar e imprimir; herdar tema escuro produziria PDF de fundo preto. É o que o `ui.html`
já faz.

**Escapa o HTML dos nomes.** A tela interpola nomes crus, o que é tolerável dentro dela; num
arquivo que vai circular, um `<` num nome de capítulo quebraria o documento. O gerador leva um
`esc()` próprio, como o do `ui.html`.

**Nome do arquivo com data local** — `avaliacao_<curso>_<data>.html`. Armadilha já registrada:
`toISOString` viraria o dia seguinte à noite.

### Payload antigo

Se o snapshot não tiver a chave `itens` (publicado antes da visão por item), o arquivo sai só
com capítulos e carrega o **mesmo aviso da tela**, em vez de fingir que a visão por item existe.
Reusa a detecção `payloadAntigo` que já está no `render()`.

## Verificação (manual, e tem de provar o que importa)

1. **Autossuficiência** — gerar, **fechar o servidor do painel**, abrir o HTML. Se depender de
   algo externo, aparece quebrado. É o teste que decide se o artefato serve.
2. **Expandir/recolher sem JS** — clicar num `<details>` e ver os itens; conferir no DevTools
   que a página não tem `<script>`.
3. **Paridade com a tela** — os 8 KPIs e os números de dois ou três capítulos batem com o que a
   tela mostra no mesmo momento.
4. **Banca-alvo** — gerar com banca selecionada; o cabeçalho registra o filtro e as colunas
   refletem a seleção.
5. **Escape e encoding** — curso com acento e apóstrofo sai correto (`charset=utf-8` no Blob).
6. **Ctrl+P** — com um capítulo aberto, a prévia sai legível, em fundo claro.
7. **Payload antigo** — num termo ainda não recoletado, sai só com capítulos e com o aviso.

## Armadilhas do projeto a respeitar

- **Data local** no nome do arquivo, nunca `toISOString`.
- Replicar na cópia `web\telas\avaliacao.html` **preservando as 5 edições próprias dela**; o
  `git diff --no-index` entre as duas telas tem de continuar fechando nos mesmos hunks.
- Se a tela servir código velho, matar instâncias antigas de `python`/`PainelLDI` — a porta 8766
  aceita bind duplo no Windows. **Não** tocar no python de `src\backend\app.py`, que é outro app.

## Worker do VPS

**Não precisa de `git pull`** — e aqui a afirmação é feita seguindo a cadeia de imports, não os
nomes dos arquivos (foi assim que um incidente nasceu em 29/07): a mudança fica confinada a
`avaliacao.html` e `web\telas\avaliacao.html`, arquivos que só os *request handlers* do
`painel.py` leem. O worker (`worker_coleta.py` → `coletor_ldi.py` → `sync_supabase.py` →
`painel.dados_avaliacao`) nunca serve requisição e não alcança esses arquivos. A **forma do
payload não muda**.

## Fora de escopo

- Mudar o CSV.
- Qualquer alteração em `painel.py` ou no backend — o gerador só consome o `D` que já existe.
- O `ui.html` do Visualizador e seu relatório de árvore.
- Um "abrir tudo" dentro do arquivo exportado (exigiria JS; ver decisão acima).
