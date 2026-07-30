# Relatório HTML compartilhável da Avaliação — plano de implementação

> **Para workers agênticos:** SUB-SKILL OBRIGATÓRIA: use superpowers:subagent-driven-development
> ou superpowers:executing-plans para implementar tarefa a tarefa. Os passos usam checkbox
> (`- [ ]`) para acompanhamento.

**Goal:** Um botão que baixa a avaliação da disciplina como **um arquivo HTML autossuficiente**,
com os capítulos expansíveis e zero JavaScript, para compartilhar com quem não tem login.

**Architecture:** O arquivo é montado **no navegador**, a partir do `D` que já está em memória, e
baixado via Blob — mesmo padrão do `gerarRelatorioArvore` do `ui.html:1690-1744`. O relatório usa
**CSS grid** (não `<table>`) porque `<details>`/`<summary>` não podem envolver `<tr>`.

**Tech Stack:** JS vanilla inline, HTML/CSS. Nenhuma dependência, nenhum endpoint novo.

**Spec:** `docs/superpowers/specs/2026-07-30-relatorio-html-avaliacao-design.md`

**Branch:** `feat/relatorio-html-avaliacao` (já criada, já contém o commit do spec).

## Global Constraints

- Idioma do projeto: **pt-BR** em código, comentários, UI e mensagens.
- **Sem dependências novas.** JS vanilla inline, como o resto do arquivo. Nada de framework, CDN
  ou `<script>` no arquivo gerado.
- **Não** tocar em `painel.py`, `painel.html`, `ui.html`, `estoque.html`, nem em qualquer arquivo
  Python ou `.ts`/`.tsx`. O gerador só consome o `D` que já existe.
- O arquivo gerado é **autossuficiente**: CSS inline, **zero `<script>`**, nenhuma referência
  externa.
- **Paleta clara fixa** no arquivo gerado (cores literais), **não** as variáveis de tema
  (`--ink`, `--surface`…) — o arquivo é para compartilhar e imprimir.
- Nome do arquivo com **data local**, nunca `toISOString` (armadilha registrada do projeto).
- As duas telas (`avaliacao.html` e `web/telas/avaliacao.html`) precisam terminar com o gerador
  **byte-idêntico**; `git diff --no-index` entre elas tem de fechar nas mesmas 5 edições próprias
  da cópia web.
- O build da web tem de ficar limpo: `cd web; npm run build`.
- A suíte Python tem de continuar verde: `py -m unittest discover -s tests` (o comando é `py`).
- Commits em pt-BR, formato `<tipo>: <descrição>`.

## Estrutura de arquivos

| Arquivo | Responsabilidade | Ação |
|---|---|---|
| `avaliacao.html` | `valoresLinha` (compartilhada), `gerarRelatorioHtml`, botão, CSS do relatório | Modificar |
| `web/telas/avaliacao.html` | as mesmas mudanças (cópia por convenção do projeto) | Modificar |
| `PROXIMA-SESSAO.md` | registro da entrega | Modificar |

Não há teste automatizado: JS em HTML single-file não tem harness neste projeto. A verificação é
manual e está detalhada na Task 3 — **é o portão de aceite da entrega**.

---

### Task 1: Extrair os valores de linha compartilhados

**Files:**
- Modify: `avaliacao.html` (nova função antes de `linhaHtml`; `linhaHtml` passa a usá-la)

**Interfaces:**
- Produces: `valoresLinha(c) -> {totQ, alvo, bancasTxt, banca}` — os valores derivados que tanto
  a tela quanto o relatório exibem. `banca` é a banca-alvo corrente (string vazia se não houver);
  `alvo` é a contagem da banca-alvo (`null` quando não há banca selecionada); `bancasTxt` é o
  texto das 3 bancas mais frequentes já formatado com `<br>`, ou `"—"`.

**Por que esta tarefa existe:** o relatório precisa **exatamente** dos mesmos valores derivados
que a tela mostra. Sem extrair, as duas cópias da aritmética divergem no dia em que uma coluna
mudar — e o relatório passa a mentir em silêncio. A extração é pequena e não muda comportamento
nenhum.

- [ ] **Step 1: Criar a função**

Em `avaliacao.html`, inserir **imediatamente antes** de `function linhaHtml(` :

```js
  // Valores derivados de uma linha (capítulo ou item). Compartilhado entre a tela e o
  // relatório HTML — se divergirem, o relatório mente sem ninguém notar.
  function valoresLinha(c) {
    const banca = document.getElementById("selBanca").value;
    return {
      banca,
      totQ: c.q_emb + c.q_txt,
      alvo: banca ? (c.bancas[banca] || 0) : null,
      bancasTxt: Object.entries(c.bancas).sort((x, y) => y[1] - x[1]).slice(0, 3)
        .map(([b, n]) => `${b.replace(" (CEBRASPE)", "")}: ${n}`).join("<br>") || "—",
    };
  }
```

- [ ] **Step 2: Usar a função em `linhaHtml`**

Em `linhaHtml`, substituir as quatro primeiras linhas do corpo:

```js
    const totQ = c.q_emb + c.q_txt;
    const alvo = alvoDe(c);
    const banca = document.getElementById("selBanca").value;
    const bancasTxt = Object.entries(c.bancas).sort((x, y) => y[1] - x[1]).slice(0, 3)
      .map(([b, n]) => `${b.replace(" (CEBRASPE)", "")}: ${n}`).join("<br>") || "—";
```

por:

```js
    const { banca, totQ, alvo, bancasTxt } = valoresLinha(c);
```

⚠ **Não** apague a função `alvoDe` — ela continua sendo usada em outro lugar do arquivo. O resto
do corpo de `linhaHtml` (as 8 células) **não muda**.

- [ ] **Step 3: Verificar que a tela não mudou**

```powershell
py painel.py --sem-navegador
```

Em `http://127.0.0.1:8766/avaliacao`, escolher uma disciplina e conferir:
1. A tabela renderiza igual a antes — mesmos números, mesmas 3 bancas por linha.
2. Trocar a banca-alvo: as colunas "Qtd. banca-alvo / outras · %" aparecem e os números batem.
3. Expandir um capítulo: as linhas de item também mostram bancas corretamente.
4. Console do DevTools **sem erro**.

Encerrar com Ctrl+C. (Armadilha: a porta 8766 aceita bind duplo no Windows; se servir código
velho, matar instâncias antigas de `python`/`PainelLDI` — **não** tocar no python de
`src\backend\app.py`, que é outro app.)

- [ ] **Step 4: Rodar a suíte**

Run: `py -m unittest discover -s tests`
Expected: OK (nada de Python mudou; é a checagem de que não houve dano colateral)

- [ ] **Step 5: Commit**

```bash
git add avaliacao.html
git commit -m "refactor: extrai valoresLinha compartilhado entre tela e relatorio

Os valores derivados de uma linha (total de questoes, banca-alvo, texto das
3 bancas) passam a sair de uma funcao so. Sem isso, a aritmetica ficaria
duplicada entre a tela e o relatorio HTML e divergiria na primeira mudanca
de coluna."
```

---

### Task 2: O gerador do relatório

**Files:**
- Modify: `avaliacao.html` (botão na barra + `gerarRelatorioHtml` no script)

**Interfaces:**
- Consumes: `valoresLinha(c)` (Task 1); `fmt`, `dur`, `pc` (helpers já existentes no arquivo);
  `D` (payload); `payloadAntigo` (a mesma expressão usada no `render()`).
- Produces: `gerarRelatorioHtml()` — monta a string e baixa via Blob. A Task 3 replica isto na
  cópia web, byte-idêntico.

- [ ] **Step 1: Acrescentar o botão**

Em `avaliacao.html`, na `<div class="barra">`, **entre** o botão de CSV e o de imprimir:

```html
    <button class="btn" onclick="gerarRelatorioHtml()">📄 HTML (compartilhar)</button>
```

A barra fica: Disciplina · Banca-alvo · ⊕ Expandir tudo · ⬇ CSV (Excel) · 📄 HTML (compartilhar) ·
🖨 Imprimir / PDF.

- [ ] **Step 2: Escrever o gerador**

Inserir **no fim do `<script>`**, imediatamente antes da linha `carregarCursos();` :

```js
  // Relatório HTML autossuficiente: CSS inline, ZERO <script>, paleta clara fixa (o arquivo
  // circula por e-mail e vira PDF no Ctrl+P — herdar o tema escuro daria fundo preto).
  // Usa CSS grid, não <table>: <details>/<summary> não podem envolver <tr>.
  function gerarRelatorioHtml() {
    if (!D) return;
    const esc = s => String(s ?? "").replace(/[&<>"]/g,
      m => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[m]));
    const banca = document.getElementById("selBanca").value;
    const payloadAntigo = D.capitulos.length > 0 && !("itens" in D.capitulos[0]);
    const agora = new Date();
    // o selo de frescor só existe na cópia web; local vem vazio e a linha é omitida
    const frescor = (document.getElementById("frescor")?.textContent || "").trim();

    const faixa = (a, b, c, tot) => tot
      ? `<span class="nums">${pc(a, tot)} · ${pc(b, tot)} · ${pc(c, tot)}</span>
         <span class="barra-pct"><i style="flex:${a || 0};background:#b23230"></i
         ><i style="flex:${b || 0};background:#a06b00"></i
         ><i style="flex:${c || 0};background:#1c6e38"></i></span>`
      : '<span class="vaz">—</span>';

    const celulas = c => {
      const { totQ, alvo, bancasTxt } = valoresLinha(c);
      return `
        <span class="nums">${c.itens_total ? `${c.itens_mb}/${c.itens_total}` : "—"}</span>
        <span class="nums">${fmt(totQ)}<small>${c.q_emb} emb. + ${c.q_txt} texto</small></span>
        <span>${totQ === 0 ? '<span class="vaz">—</span>' : banca
          ? `${alvo} / ${totQ - alvo}<br><b>${pc(alvo, totQ)}</b>`
          : `<small>${bancasTxt}</small>`}</span>
        <span>${faixa(c.q_ate, c.q_meio, c.q_novo, c.q_com_ano)}</span>
        <span class="nums">${c.q_emb === 0 ? '<span class="vaz">—</span>'
          : `📝 ${c.sol_texto} (${pc(c.sol_texto, c.q_emb)})<br>🎬 ${c.sol_video} (${pc(c.sol_video, c.q_emb)})`}</span>
        <span class="nums">${c.vids} · ${dur(c.dur)}</span>
        <span>${faixa(c.v_ate, c.v_meio, c.v_novo, c.v_com_data)}</span>`;
    };

    const corpo = D.capitulos.map(c => {
      const nome = `${c.num ? `<span class="pos">${esc(c.num)}</span>` : ""}${esc((c.nome || "").trim())}`;
      const itens = c.itens || [];
      const cab = `<span class="nm">${nome}<small>${c.aulas} itens</small></span>${celulas(c)}`;
      if (!itens.length) return `<div class="lin cap sem">${cab}</div>`;
      return `<details class="cap"><summary class="lin"><span class="seta"></span>${cab}</summary>` +
        itens.map(it => `<div class="lin item"><span class="nm">${
          it.num ? `<span class="pos">${esc(it.num)}</span>` : ""}${esc((it.nome || "").trim())
        }</span>${celulas(it)}</div>`).join("") + `</details>`;
    }).join("");

    const tot = k => D.capitulos.reduce((s, c) => s + (c[k] || 0), 0);
    const totQ = tot("q_emb") + tot("q_txt");
    const totAlvo = banca ? D.capitulos.reduce((s, c) => s + (c.bancas[banca] || 0), 0) : null;
    const kpis = [
      [D.capitulos.length, "aulas"],
      [fmt(totQ), "questões (emb. + texto)"],
      banca ? [pc(totAlvo, totQ), "% banca-alvo"] : null,
      [pc(tot("q_novo"), tot("q_com_ano")), `% questões ${ANO - 2}-${ANO}`],
      [pc(tot("sol_texto"), tot("q_emb")), "embedadas c/ solução em texto"],
      [pc(tot("sol_video"), tot("q_emb")), "embedadas c/ vídeo-solução"],
      [fmt(tot("vids")) + " · " + dur(tot("dur")), "vídeos · tempo total"],
      [pc(tot("v_novo"), tot("v_com_data")), `% vídeos gravados ${ANO - 2}-${ANO}`],
    ].filter(Boolean).map(([n, l]) => `<div class="kpi"><b>${n}</b><span>${esc(l)}</span></div>`).join("");

    const COLS = "minmax(230px,2.2fr) 78px 110px 150px 132px 148px 104px 132px";
    const html = `<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<title>Avaliação — ${esc(D.curso.trim())} — ${agora.toLocaleDateString("pt-BR")}</title>
<style>
  body{font:13px/1.45 "Segoe UI",system-ui,sans-serif; color:#0b0b0b; background:#fff;
       max-width:1240px; margin:0 auto; padding:26px 22px}
  header{border-bottom:3px solid #2a78d6; padding-bottom:12px; margin-bottom:14px}
  header h1{font-size:19px; margin:0 0 4px}
  header .meta{color:#52514e; font-size:12px}
  .aviso{color:#a06b00; border:1px solid #a06b00; background:#fdf6e7; border-radius:8px;
         padding:9px 13px; margin:12px 0; font-size:12.5px}
  .kpis{display:flex; flex-wrap:wrap; gap:10px; margin:14px 0 16px}
  .kpi{border:1px solid #e3e2dd; border-radius:8px; padding:8px 13px}
  .kpi b{display:block; font-size:18px; color:#2a78d6; font-variant-numeric:tabular-nums}
  .kpi span{font-size:11px; color:#52514e}
  .tblcab,.lin{display:grid; grid-template-columns:${COLS}; gap:10px; align-items:start}
  .tblcab{font-size:10px; text-transform:uppercase; letter-spacing:.05em; color:#2a78d6;
          font-weight:700; padding:8px 10px; border-bottom:1px solid #e3e2dd}
  .lin{padding:9px 10px; border-bottom:1px solid #f0efec; position:relative}
  summary.lin{cursor:pointer; list-style:none; background:#f7f7f5}
  summary.lin::-webkit-details-marker{display:none}
  .seta{position:absolute; margin-left:-14px; color:#8a897f}
  .seta::before{content:"▸"}
  details[open]>summary .seta::before{content:"▾"}
  .lin.cap .nm,summary.lin .nm{font-weight:600}
  .lin.item{padding-left:34px; color:#52514e; border-bottom:1px dashed #f0efec}
  .nm{min-width:0; overflow-wrap:anywhere}
  .nm small{display:block; color:#8a897f; font-weight:400; font-size:11px}
  .nums{font-variant-numeric:tabular-nums; white-space:nowrap}
  .nums small{display:block; color:#8a897f; font-size:11px; white-space:normal}
  .pos{display:inline-block; min-width:2.2em; margin-right:7px; color:#8a897f;
       font-variant-numeric:tabular-nums; border-right:1px solid #e3e2dd; padding-right:6px}
  .barra-pct{display:flex; height:8px; border-radius:4px; overflow:hidden; margin-top:3px}
  .vaz{color:#8a897f}
  small{font-size:11px}
  footer{margin-top:20px; color:#8a897f; font-size:11px; text-align:center}
  @media print{ body{padding:0} details{break-inside:avoid} }
</style></head><body>
<header>
  <h1>📊 Avaliação — ${esc(D.curso.trim())}</h1>
  ${D.autores ? `<div class="meta">${esc(D.autores)}</div>` : ""}
  ${frescor ? `<div class="meta">${esc(frescor)}</div>` : ""}
  <div class="meta">Gerado em ${agora.toLocaleDateString("pt-BR")} às
    ${agora.toLocaleTimeString("pt-BR").slice(0, 5)}${
    banca ? ` · banca-alvo: <b>${esc(banca)}</b>` : " · sem banca-alvo"}</div>
</header>
${payloadAntigo ? '<div class="aviso">⚠ Este snapshot é anterior à visão por item — recolha o concurso para ver a ordem do curso e abrir os itens.</div>' : ""}
<div class="kpis">${kpis}</div>
<div class="tblcab"><span>Aula (LDI)</span><span>Itens no MB</span><span>Questões</span>
  <span>${banca ? "Banca-alvo" : "Bancas"}</span><span>% ano da prova ${esc(ROTULO)}</span>
  <span>Soluções 📝 · 🎬</span><span>Vídeos qtd · tempo</span>
  <span>% ano de gravação ${esc(ROTULO)}</span></div>
${corpo}
<footer>Gerado pelo Painel de Conteúdo LDI · uso interno · clique nos capítulos para abrir os itens</footer>
</body></html>`;

    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([html], { type: "text/html;charset=utf-8" }));
    const d = new Date();  // data LOCAL (convenção do projeto — toISOString viraria o dia)
    const dia = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    a.download = "avaliacao_" + (D.curso || "disciplina").trim().slice(0, 40).replace(/\W+/g, "_") + "_" + dia + ".html";
    a.click();
    URL.revokeObjectURL(a.href);
  }
```

⚠ **Duas coisas no CSS acima são obrigatórias, não estéticas:**

1. `.lin` tem `position:relative` — a seta é `position:absolute` e precisa desse contexto para
   ancorar na linha. Sem isso ela ancora no viewport e sai do lugar.
2. A seta ser `position:absolute` é o que a mantém **fora do fluxo do grid**. Filho absoluto de um
   container grid não ocupa coluna; se ela virar estática, consome a primeira coluna e **desloca
   todas as 8 colunas**, quebrando o alinhamento inteiro.

- [ ] **Step 3: Verificar (o portão desta tarefa)**

```powershell
py painel.py --sem-navegador
```

Em `http://127.0.0.1:8766/avaliacao`, escolher disciplina e clicar **📄 HTML (compartilhar)**.
Depois **encerrar o servidor (Ctrl+C)** e abrir o arquivo baixado no navegador:

1. **Autossuficiência** — a página abre completa com o servidor desligado. É o teste que decide
   se o artefato serve.
2. **Zero JS** — `Ctrl+U` (ou DevTools) e confirmar que **não existe `<script>`** no arquivo.
3. **Expandir/recolher** — clicar num capítulo abre os itens; a seta vira ▾. Capítulo sem item
   não tem seta nem é clicável.
4. **Paridade** — os 8 KPIs e os números de 2-3 capítulos batem com a tela.
5. **Colunas alinhadas** — as colunas de capítulos **diferentes** alinham entre si (é o motivo do
   grid com `grid-template-columns` compartilhado).
6. **Ctrl+P** — com um capítulo aberto, a prévia sai legível, fundo claro.

Anotar no relato o que passou e o que não passou. **Não afirmar que verificou o que não abriu.**

- [ ] **Step 4: Verificar com banca-alvo e acentuação**

Voltar à tela, selecionar uma **banca-alvo**, gerar de novo e conferir no arquivo:
1. O cabeçalho registra `banca-alvo: <nome>`.
2. A 4ª coluna vira "Banca-alvo" e mostra `alvo / outras` com o percentual.
3. Acentos e apóstrofos do nome do curso saem corretos (não `Ã©`).
4. O nome do arquivo tem a data de **hoje** (não a de amanhã, se estiver de noite).

- [ ] **Step 5: Commit**

```bash
git add avaliacao.html
git commit -m "feat: relatorio HTML compartilhavel da avaliacao

Botao ao lado do CSV baixa um arquivo autossuficiente: CSS inline, zero
<script>, capitulos em <details> recolhidos e paleta clara fixa. Usa CSS
grid, nao <table>, porque <details> nao pode envolver <tr>. Cabecalho
registra o frescor do dado, a hora da geracao e a banca-alvo ativa."
```

---

### Task 3: Replicar na cópia web, verificar e documentar

**Files:**
- Modify: `web/telas/avaliacao.html`
- Modify: `PROXIMA-SESSAO.md`

**Interfaces:**
- Consumes: `valoresLinha` (Task 1) e `gerarRelatorioHtml` (Task 2), do `avaliacao.html` **real**.

**Contexto obrigatório:** `web/telas/avaliacao.html` é cópia da tela da raiz com **5 edições
próprias** que não podem ser perdidas: (1) banner de cookie (`#banner-cookie` + script de
`/api/cookie-status`), (2) links Coleta/Admin/sair no `eyebrow`, (3) selo de frescor
(`#frescor`), (4) seletor de concurso (`#selConcurso`) + `carregarConcursos()`, (5) estado vazio
em `carregarCursos()`. Mais: URLs de fetch com `termo`, `let TERMO = "";`, `sel.onchange`, e o
bootstrap chamando `carregarConcursos()`.

⚠ **Copie do `avaliacao.html` REAL, não do texto deste plano.** Se a Task 2 tiver ajustado algo
na verificação (por exemplo o `position:relative` do Step 2), o arquivo tem a versão correta e
este plano não.

- [ ] **Step 1: Confirmar o ponto de partida**

```bash
git diff --no-index --stat avaliacao.html web/telas/avaliacao.html
```

Expected: só as 5 edições próprias (as mesmas de antes desta entrega).

- [ ] **Step 2: Replicar**

Aplicar na cópia, lendo do arquivo da raiz: o botão `📄 HTML (compartilhar)` na barra, a função
`valoresLinha`, a mudança nas 4 linhas de `linhaHtml`, e a função `gerarRelatorioHtml` inteira
(antes do bootstrap — na cópia o bootstrap é `carregarConcursos();`, não `carregarCursos();`).

- [ ] **Step 3: Prova de fidelidade**

```bash
git diff --no-index avaliacao.html web/telas/avaliacao.html
```

Expected: **as mesmas 5 diferenças de antes, nem uma a mais.** Nenhuma diferença dentro de
`valoresLinha`, `linhaHtml`, `render`, `baixarCSV` ou `gerarRelatorioHtml` — se aparecer alguma
ali, a réplica saiu torta. Colar a saída no relato.

- [ ] **Step 4: Build da web**

```powershell
cd web; npm run build
```

Expected: build limpo. Voltar com `cd ..`.

- [ ] **Step 5: Verificar o ramo do payload antigo**

Este é o único ponto que **não** dá para verificar no painel local (o local sempre serve payload
novo). Verificar pela tela, sem servidor web: em `http://127.0.0.1:8766/avaliacao`, abrir o
DevTools e rodar

```js
D.capitulos.forEach(c => { delete c.itens; delete c.num; }); gerarRelatorioHtml();
```

No arquivo baixado, conferir que aparece o aviso "⚠ Este snapshot é anterior à visão por item"
e que os capítulos saem sem seta (nenhum tem item). Recarregar a página depois, para não seguir
com o `D` mutilado.

- [ ] **Step 6: Atualizar o `PROXIMA-SESSAO.md`**

Acrescentar ao fim da seção da Sessão 10 (antes de `## 🔑 Coisas que a próxima sessão PRECISA
saber`):

```markdown
**Relatório HTML compartilhável (30/07):** a `/avaliacao` ganhou **📄 HTML (compartilhar)** ao
lado do CSV — baixa um arquivo **autossuficiente** (CSS inline, **zero `<script>`**, paleta clara
fixa) com os capítulos em `<details>` recolhidos e os itens dentro. Serve para mandar a avaliação
a quem não tem login; o CSV continua para quem vai cruzar em planilha. Cabeçalho registra o
frescor do dado, a hora da geração e a banca-alvo ativa, então o arquivo continua auditável meses
depois. Usa **CSS grid, não `<table>`** — `<details>`/`<summary>` não podem envolver `<tr>`.
Consequência aceita: no Ctrl+P sai só o que estiver aberto (um "abrir tudo" exigiria JS, e o
zero-JS é o que faz o anexo abrir em qualquer lugar). Spec:
`docs\superpowers\specs\2026-07-30-relatorio-html-avaliacao-design.md`; plano:
`docs\superpowers\plans\2026-07-30-relatorio-html-avaliacao.md`.
**Worker do VPS não precisa de `git pull`** — a mudança fica em arquivos que só os *request
handlers* leem, e a forma do payload não muda (afirmação feita seguindo a cadeia de imports, não
os nomes dos arquivos).
```

- [ ] **Step 7: Rodar a suíte e commitar**

Run: `py -m unittest discover -s tests`
Expected: OK

```bash
git add web/telas/avaliacao.html PROXIMA-SESSAO.md
git commit -m "feat: replica o relatorio HTML na tela web e documenta a entrega

As 5 edicoes proprias da copia (banner de cookie, links, selo de frescor,
seletor de concurso, estado vazio) foram preservadas."
```

- [ ] **Step 8: Entregar**

A branch fica local. Push e PR são do Clovis (o merge na `main` deploya no Vercel):

```
! git push -u origin feat/relatorio-html-avaliacao
```

O push autônomo não funciona nesta máquina (credencial não cacheada) — deixar o comando pronto,
não tentar em loop.

---

## Notas para quem executa

- Não há teste automatizado nesta entrega. A verificação manual **é** o portão — se você não
  conseguiu abrir o arquivo gerado, diga isso em vez de afirmar que passou.
- Se a tela servir código velho depois de editar o HTML, matar instâncias antigas de
  `python`/`PainelLDI` (a porta 8766 aceita bind duplo no Windows). **Não** tocar no python de
  `src\backend\app.py`, que é outro app.
- Se existir `PainelLDI.exe` empacotado, ele embute `painel.html`/`avaliacao.html`: rebuild com
  PyInstaller para o exe refletir a tela nova.
