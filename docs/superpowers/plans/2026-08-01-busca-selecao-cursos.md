# Buscar, selecionar e coletar cursos juntos — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Na `/coleta`, buscar cursos por termo, ver a lista com o peso de cada um, marcar vários e disparar uma coleta só.

**Architecture:** Uma requisição `per_page=100` ao LDI no servidor (2,5–5 MB), convertida para um DTO leve (~200 bytes/curso) que descarta a árvore antes de chegar ao navegador. O disparo vira `tipo:"ids"` — zero mudança no worker.

**Tech Stack:** Next.js 15 (App Router, server actions), React 19, TypeScript 5.7, Node 22+.

**Spec:** `docs/superpowers/specs/2026-08-01-busca-selecao-cursos-design.md`

## Global Constraints

- **Idioma pt-BR** em código, comentários e UI.
- **Nada quebra:** `py -m unittest discover -s tests` (143 testes) e `checks/coleta.check.ts` (9 checagens) têm de continuar verdes; `npx tsc --noEmit` e `npm run build` limpos.
- **A árvore NUNCA vai ao navegador.** É a restrição que define o desenho: 29–49 KB por curso, ~5 MB por busca. Toda leitura de `content_tree_cache` acontece no servidor e o resultado é um número.
- **`web/lib/ldi.ts` é server-only** — nunca importar em componente cliente. Componentes cliente importam **só tipos** de `lib/coleta.ts` (`import type`).
- **Datas locais**: `toLocaleString("pt-BR", { timeZone: "America/Sao_Paulo" })`, nunca `toISOString` para exibir.
- Commits em português: `<tipo>: <descrição>`.

## Fatos medidos no spike (01/08) — não re-derivar

| Fato | Valor |
|---|---|
| Projeção reduzida | **Impossível** — 7 parâmetros, todos 2462,8 KB; `fields=` → HTTP 500 |
| Peso por curso | 29–49 KB (a árvore é ~100% do payload) |
| `meta.total` | **Mente** — 127.309 (catálogo inteiro) em toda busca |
| Única pista de "há mais" | `data.length === per_page` |
| `authors_name` na listagem | **Sempre `null`**, mesmo com `include_authors_names=true` |
| "Área Fiscal" | 62 encontrados, 43 com árvore |

---

### Task 1: As funções puras (DTO, contagem, travas)

**Files:**
- Modify: `web/lib/coleta.ts`
- Create: `web/checks/busca.check.ts`
- Já existe: `web/checks/fixtures/busca-ldi.json` (payload real do spike, 5 cursos, 5 KB)

**Interfaces:**
- Consumes: nada de tasks anteriores.
- Produces:
  - `TERMO_MINIMO = 3`, `LIMITE_SELECAO = 30`, `CURSOS_NA_TELA = 30`, `POR_PAGINA = 100`
  - `interface CursoLdiBruto` — a forma crua vinda da API
  - `interface CursoBusca` — o DTO leve
  - `interface ResultadoBusca { cursos: CursoBusca[]; encontrados: number; comConteudo: number; podeHaverMais: boolean }`
  - `contarArvore(bruto) => { capitulos: number; aulas: number }`
  - `termoValido(termo) => boolean`
  - `converterCursosBusca(brutos) => ResultadoBusca`

- [ ] **Step 1: Escrever a checagem que falha**

Criar `web/checks/busca.check.ts`:

```ts
// Checagens das puras da busca de cursos (web/lib/coleta.ts).
// Rodar: cd web && node --experimental-strip-types checks/busca.check.ts
// A fixture é payload REAL do LDI (spike de 01/08), com as árvores podadas
// para 2 capítulos × 2 itens — a FORMA é a de produção, o volume não.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  contarArvore, termoValido, converterCursosBusca,
  TERMO_MINIMO, CURSOS_NA_TELA, POR_PAGINA,
  type CursoLdiBruto,
} from "../lib/coleta.ts";

const fixture = JSON.parse(
  readFileSync(new URL("./fixtures/busca-ldi.json", import.meta.url), "utf-8")
) as { data: CursoLdiBruto[] };
const brutos = fixture.data;

// 1. DTO a partir de payload REAL (não inventado)
const r = converterCursosBusca(brutos);
assert.equal(r.cursos.length, 5);
assert.equal(r.encontrados, 5);
assert.equal(r.comConteudo, 3);          // 3 com árvore, 2 sem
assert.equal(r.podeHaverMais, false);    // 5 < POR_PAGINA

// 2. contagem de árvore: povoada, ausente, null, vazia
assert.deepEqual(contarArvore(brutos[0]), { capitulos: 2, aulas: 2 });
assert.deepEqual(contarArvore(brutos[1]), { capitulos: 2, aulas: 4 });
assert.deepEqual(contarArvore(brutos[3]), { capitulos: 0, aulas: 0 });
assert.deepEqual(contarArvore({ id: "x", name: "y" } as CursoLdiBruto),
                 { capitulos: 0, aulas: 0 });
assert.deepEqual(contarArvore({ content_tree_cache: null } as unknown as CursoLdiBruto),
                 { capitulos: 0, aulas: 0 });
assert.deepEqual(contarArvore({ content_tree_cache: [] } as unknown as CursoLdiBruto),
                 { capitulos: 0, aulas: 0 });
// capítulo sem `items` (curso em montagem — existe de verdade: um curso da
// amostra tem 46 capítulos e só 6 aulas)
assert.deepEqual(
  contarArvore({ content_tree_cache: [{ chapter_id: "c" }] } as unknown as CursoLdiBruto),
  { capitulos: 1, aulas: 0 });

// 3. A ÁRVORE NÃO VAZA — é o que impede 5 MB de atravessar para o navegador
const serializado = JSON.stringify(r);
assert.ok(!serializado.includes("content_tree_cache"), "árvore vazou no DTO!");
assert.ok(!serializado.includes("chapter_id"), "capítulo vazou no DTO!");
assert.ok(serializado.length < 4000, `DTO grande demais: ${serializado.length} bytes`);

// 4. termo mínimo
assert.equal(termoValido("PRF"), true);
assert.equal(termoValido("Área Fiscal"), true);
assert.equal(termoValido("PR"), false);
assert.equal(termoValido(""), false);
assert.equal(termoValido("   "), false);      // só espaços não vale
assert.equal(termoValido("  PRF  "), true);   // apara antes de medir
assert.equal(TERMO_MINIMO, 3);

// 5. sem árvore ⇒ não selecionável
const vazio = r.cursos.find((c) => c.capitulos === 0)!;
assert.equal(vazio.selecionavel, false);
const cheio = r.cursos.find((c) => c.capitulos > 0)!;
assert.equal(cheio.selecionavel, true);

// 6. veio cheio ⇒ podeHaverMais (meta.total do LDI mente: 127309 sempre)
const cem = Array.from({ length: POR_PAGINA }, (_, i) => ({
  id: `id-${i}`, name: `Curso ${i}`, published: true,
  created_at: "2026-07-30T00:00:00Z",
  content_tree_cache: [{ chapter_id: "c", items: [{ item_id: "i" }] }],
})) as unknown as CursoLdiBruto[];
const rCem = converterCursosBusca(cem);
assert.equal(rCem.podeHaverMais, true);
assert.equal(rCem.encontrados, POR_PAGINA);
assert.equal(rCem.cursos.length, CURSOS_NA_TELA);   // só 30 vão para a tela
// mas os totais contam TODOS os buscados, não só os exibidos
assert.equal(rCem.comConteudo, POR_PAGINA);

// 7. ordem preservada (a API já entrega por created_at desc — não reordenar)
assert.deepEqual(r.cursos.map((c) => c.id), brutos.map((b) => b.id));

// 8. descrição: só quando existir e diferente do nome
const comDesc = r.cursos.find((c) => c.id === brutos[2].id)!;
assert.equal(comDesc.descricao, null);  // a descrição REPETE o nome → descartada
const semDesc = r.cursos.find((c) => c.id === brutos[0].id)!;
assert.equal(semDesc.descricao, null);

console.log("ok — 8 checagens da busca");
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd web && node --experimental-strip-types checks/busca.check.ts`
Expected: FAIL — `does not provide an export named 'contarArvore'`

- [ ] **Step 3: Implementar**

Acrescentar ao fim de `web/lib/coleta.ts`:

```ts
// ————— Busca de cursos no LDI (entrega 2a) —————
// Spec: docs/superpowers/specs/2026-08-01-busca-selecao-cursos-design.md

// search_term vazio devolve o catálogo INTEIRO (127.309 cursos) COM as árvores
// — derrubaria a função serverless. É a trava mais importante desta entrega.
export const TERMO_MINIMO = 3;
// per_page é a ÚNICA alavanca de volume: a API ignora qualquer projeção
// (7 parâmetros testados no spike, todos devolvem o payload inteiro).
export const POR_PAGINA = 100;
export const CURSOS_NA_TELA = 30;
export const LIMITE_SELECAO = 30;

// Forma crua do curso na resposta do LDI. Só os campos que usamos —
// `authors_name` vem SEMPRE null na listagem (medido), por isso não entra
// no DTO: o nome do professor é buscado sob demanda, ao marcar o curso.
export interface CursoLdiBruto {
  id: string;
  name?: string | null;
  published?: boolean | null;
  created_at?: string | null;
  description?: string | null;
  content_tree_cache?: Array<{ items?: unknown[] | null }> | null;
}

// O DTO que vai ao navegador: ~200 bytes por curso, SEM a árvore.
export interface CursoBusca {
  id: string;
  nome: string;
  descricao: string | null;
  publicado: boolean;
  criadoEm: string | null;
  capitulos: number;
  aulas: number;
  // curso de 0 capítulos gera extração vazia (o VPS já tem uma: "Área Fiscal"
  // #11, 0 cursos/0 blocos) — aparece na lista, mas não se deixa marcar.
  selecionavel: boolean;
}

export interface ResultadoBusca {
  cursos: CursoBusca[];      // no máximo CURSOS_NA_TELA
  encontrados: number;       // total buscado (até POR_PAGINA)
  comConteudo: number;       // quantos têm árvore, entre os buscados
  podeHaverMais: boolean;
}

export function termoValido(termo: string): boolean {
  return (termo ?? "").trim().length >= TERMO_MINIMO;
}

// Lê a árvore e devolve NÚMEROS — a árvore em si é descartada aqui, no
// servidor. Capítulo sem `items` conta como capítulo com 0 aulas: acontece de
// verdade (curso em montagem com 46 capítulos e 6 aulas, visto no spike).
export function contarArvore(bruto: CursoLdiBruto): {
  capitulos: number;
  aulas: number;
} {
  const caps = Array.isArray(bruto?.content_tree_cache) ? bruto.content_tree_cache : [];
  let aulas = 0;
  for (const cap of caps) {
    aulas += Array.isArray(cap?.items) ? cap.items.length : 0;
  }
  return { capitulos: caps.length, aulas };
}

// Descrição só quando acrescenta informação: medida vazia em 27 de 30 cursos,
// e quando existe costuma repetir o nome.
function descricaoUtil(bruto: CursoLdiBruto): string | null {
  const d = (bruto?.description ?? "").trim();
  if (!d) return null;
  return d.toLowerCase() === (bruto?.name ?? "").trim().toLowerCase() ? null : d;
}

// Converte o payload cru no DTO leve. NÃO reordena: a API já entrega por
// created_at desc, e é essa ordem que a tela mostra.
export function converterCursosBusca(brutos: CursoLdiBruto[]): ResultadoBusca {
  const lista = Array.isArray(brutos) ? brutos : [];
  const cursos = lista.slice(0, CURSOS_NA_TELA).map((b): CursoBusca => {
    const { capitulos, aulas } = contarArvore(b);
    return {
      id: String(b?.id ?? ""),
      nome: (b?.name ?? "").trim() || "(sem nome)",
      descricao: descricaoUtil(b),
      publicado: b?.published === true,
      criadoEm: b?.created_at ?? null,
      capitulos,
      aulas,
      selecionavel: capitulos > 0,
    };
  });
  return {
    cursos,
    encontrados: lista.length,
    comConteudo: lista.filter((b) => contarArvore(b).capitulos > 0).length,
    // meta.total do LDI mente (127.309 sempre) — a página cheia é a única
    // pista honesta de que há mais resultados.
    podeHaverMais: lista.length >= POR_PAGINA,
  };
}
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd web && node --experimental-strip-types checks/busca.check.ts`
Expected: `ok — 8 checagens da busca`

- [ ] **Step 5: Provar que a checagem 3 discrimina**

Trocar temporariamente o `return` de `converterCursosBusca` para incluir a árvore
(`...b` no objeto do DTO) e confirmar que a checagem **falha** com "árvore vazou no DTO!".
Depois desfazer. Se passar mesmo com a árvore, a checagem não protege nada.

Run: `cd web && node --experimental-strip-types checks/busca.check.ts`
Expected: FAIL com a árvore incluída, PASS sem ela.

- [ ] **Step 6: Tipos e checagem antiga**

Run: `cd web && npx tsc --noEmit && node --experimental-strip-types checks/coleta.check.ts`
Expected: sem erro; `ok — 9 checagens`

- [ ] **Step 7: Commit**

```bash
git add web/lib/coleta.ts web/checks/busca.check.ts web/checks/fixtures/busca-ldi.json
git commit -m "feat: puras da busca de cursos (DTO leve que descarta a arvore)"
```

---

### Task 2: Falar com o LDI

**Files:**
- Modify: `web/lib/ldi.ts`

**Interfaces:**
- Consumes: `CursoLdiBruto`, `POR_PAGINA` de `lib/coleta.ts`.
- Produces: `buscarCursosLdi(sidComPrefixo, termo) => Promise<CursoLdiBruto[] | "sem-acesso" | null>`

- [ ] **Step 1: Implementar**

Acrescentar a `web/lib/ldi.ts` (o arquivo já tem o padrão: `X_VERTICAL`, `USER_AGENT`,
`AbortController` com timeout, `"sem-acesso"` em 401/403):

```ts
import { POR_PAGINA, type CursoLdiBruto } from "./coleta";

// A busca traz a árvore inteira de cada curso e não há como pedir menos: 7
// parâmetros de projeção testados no spike de 01/08 (include_content_tree=false,
// fields=, select=, lean=, simple=…) devolvem o MESMO payload byte a byte, e
// `fields=` responde HTTP 500. Não insistir — só `per_page` controla o volume.
// Uma página de 100 ≈ 2,5–5 MB; 3 páginas de "Direito" dariam 9,9 MB, acima do
// limite de 4,5 MB de resposta de uma função no Vercel. Por isso: UMA página.
const TIMEOUT_BUSCA_MS = 20000;

export async function buscarCursosLdi(
  sidComPrefixo: string,
  termo: string
): Promise<CursoLdiBruto[] | "sem-acesso" | null> {
  const url =
    `${URL_CURSO}?page=1&per_page=${POR_PAGINA}&sort=desc&order_by=created_at` +
    `&search_term=${encodeURIComponent(termo)}`;
  try {
    const controlador = new AbortController();
    const cronometro = setTimeout(() => controlador.abort(), TIMEOUT_BUSCA_MS);
    const r = await fetch(url, {
      headers: {
        "x-vertical": X_VERTICAL,
        Cookie: sidComPrefixo,
        Accept: "application/json",
        "User-Agent": USER_AGENT,
      },
      cache: "no-store",
      signal: controlador.signal,
    });
    clearTimeout(cronometro);
    if (r.status === 401 || r.status === 403) return "sem-acesso";
    if (!r.ok) return null;
    const corpo = (await r.json()) as { data?: CursoLdiBruto[] | null };
    return Array.isArray(corpo?.data) ? corpo.data : [];
  } catch {
    return null;   // rede, timeout, JSON inválido
  }
}
```

- [ ] **Step 2: Conferir tipos**

Run: `cd web && npx tsc --noEmit`
Expected: sem erro

- [ ] **Step 3: Commit**

```bash
git add web/lib/ldi.ts
git commit -m "feat: busca cursos no LDI em uma pagina so"
```

---

### Task 3: A server action

**Files:**
- Modify: `web/app/coleta/actions.ts`

**Interfaces:**
- Consumes: `exigirOperador()`; `criarClienteAdmin()`; `buscarCursosLdi`; `converterCursosBusca`, `termoValido`, `TERMO_MINIMO`, `LIMITE_SELECAO`, `enfileirar`.
- Produces: `buscarCursos(termo) => Promise<{ erro: string | null; resultado: ResultadoBusca | null }>`; modo `"selecao"` em `disparar`.

- [ ] **Step 1: Implementar a busca**

Ampliar os imports no topo de `web/app/coleta/actions.ts`:

```ts
import {
  extrairIds, enfileirar, mudarStatus,
  converterCursosBusca, termoValido, TERMO_MINIMO, LIMITE_SELECAO,
  type ResultadoBusca,
} from "../../lib/coleta";
import { buscarNomeCursoLdi, buscarCursosLdi } from "../../lib/ldi";
```

E acrescentar ao arquivo:

```ts
// Lista os cursos que um termo traria, para o operador escolher ANTES de
// disparar. exigirOperador: quem já pode disparar tipo:"termo" (que colhe
// TUDO) obviamente pode ver o que colheria.
export async function buscarCursos(
  termo: string
): Promise<{ erro: string | null; resultado: ResultadoBusca | null }> {
  await exigirOperador();

  const limpo = (termo ?? "").trim();
  if (!termoValido(limpo)) {
    return {
      erro: `Digite pelo menos ${TERMO_MINIMO} caracteres — busca vazia traria o catálogo inteiro.`,
      resultado: null,
    };
  }

  const admin = criarClienteAdmin();
  const { data: config, error: erroConfig } = await admin
    .from("config_ldi")
    .select("cookie")
    .eq("id", 1)
    .maybeSingle<{ cookie: string | null }>();
  if (erroConfig) {
    console.error("[coleta] buscarCursos (config_ldi):", erroConfig.message);
    return { erro: "Não foi possível ler o cookie do LDI — tente de novo.", resultado: null };
  }
  const cookie = config?.cookie ?? null;
  if (!cookie) return { erro: "Sem cookie do LDI configurado.", resultado: null };

  const brutos = await buscarCursosLdi(cookie, limpo);
  if (brutos === "sem-acesso") {
    return { erro: "O cookie do LDI está inválido — renove no bloco 🍪 acima.", resultado: null };
  }
  if (brutos === null) {
    return { erro: "A busca no LDI falhou (rede ou tempo esgotado) — tente de novo.", resultado: null };
  }

  return { erro: null, resultado: converterCursosBusca(brutos) };
}
```

- [ ] **Step 2: Implementar o disparo do lote**

Dentro de `disparar`, **antes** do `redirect("/coleta?msg=erro")` final:

```ts
  if (modo === "selecao") {
    const rotulo = String(formData.get("rotulo") ?? "").trim();
    if (!rotulo) redirect("/coleta?msg=rotulo-vazio");

    // getAll: a tela manda um campo `ids` por curso marcado.
    const ids = formData.getAll("ids").map((v) => String(v)).filter(Boolean);
    if (ids.length === 0) redirect("/coleta?msg=nenhum-selecionado");
    if (ids.length > LIMITE_SELECAO) redirect("/coleta?msg=selecao-demais");

    const admin = criarClienteAdmin();
    try {
      // tipo:"ids" — o worker já resolve por ID (coletor_ldi.py:224-228), então
      // zero mudança lá, sem refazer a busca pesada no VPS, e a seleção fica
      // CONGELADA: curso criado entre o clique e a execução não entra no lote.
      await enfileirar(admin, {
        tipo: "ids", alvo: ids.join(","), rotulo, pedido_por: user.email ?? "",
      });
    } catch (e) {
      console.error("[coleta] disparar (selecao):", e instanceof Error ? e.message : e);
      redirect("/coleta?msg=erro");
    }
    redirect("/coleta?msg=disparada");
  }
```

- [ ] **Step 3: Conferir tipos**

Run: `cd web && npx tsc --noEmit`
Expected: sem erro

- [ ] **Step 4: Commit**

```bash
git add web/app/coleta/actions.ts
git commit -m "feat: action de busca e disparo do lote selecionado"
```

---

### Task 4: A tela

**Files:**
- Create: `web/app/coleta/busca-cursos.tsx`
- Modify: `web/app/coleta/form-disparo.tsx` (134 linhas — vira casca)
- Modify: `web/app/coleta/page.tsx` (mensagens novas)

**Interfaces:**
- Consumes: `buscarCursos`, `disparar` de `./actions`; tipos `CursoBusca`, `ResultadoBusca`, `LIMITE_SELECAO` de `../../lib/coleta` (**`import type` para os tipos** — `lib/ldi.ts` é server-only e não pode ser arrastado para o bundle).
- Produces: componente cliente `BuscaCursos`.

- [ ] **Step 1: Criar o componente**

Criar `web/app/coleta/busca-cursos.tsx`:

```tsx
"use client";

import { useState, useTransition, type CSSProperties } from "react";
import { LIMITE_SELECAO, type CursoBusca, type ResultadoBusca } from "../../lib/coleta";
import { buscarCursos, disparar } from "./actions";

const celula: CSSProperties = { padding: "7px 9px", borderBottom: "1px solid #e3e2dd" };

const dataLocal = (iso: string | null) =>
  iso
    ? new Date(iso).toLocaleDateString("pt-BR", {
        day: "2-digit", month: "2-digit", year: "2-digit",
        timeZone: "America/Sao_Paulo",
      })
    : "—";

function Linha({
  curso, marcado, aoMarcar,
}: {
  curso: CursoBusca;
  marcado: boolean;
  aoMarcar: (id: string) => void;
}) {
  return (
    <tr style={{ opacity: curso.selecionavel ? 1 : 0.55 }}>
      <td style={celula}>
        <input
          type="checkbox" checked={marcado} disabled={!curso.selecionavel}
          onChange={() => aoMarcar(curso.id)}
          title={curso.selecionavel ? "" : "Curso sem capítulos — coletar geraria extração vazia"}
        />
      </td>
      <td style={celula}>
        {curso.nome}
        {curso.descricao && (
          <div style={{ fontSize: 11, color: "#8a897f" }}>{curso.descricao}</div>
        )}
      </td>
      <td style={{ ...celula, whiteSpace: "nowrap" }}>
        {curso.capitulos === 0 ? (
          <span style={{ color: "#b9770e" }}>0 cap · vazio</span>
        ) : (
          `${curso.capitulos} cap · ${curso.aulas} aulas`
        )}
      </td>
      <td style={{ ...celula, whiteSpace: "nowrap" }}>
        {curso.publicado ? "publicado" : <span style={{ color: "#8a897f" }}>rascunho</span>}
      </td>
      <td style={{ ...celula, whiteSpace: "nowrap" }}>{dataLocal(curso.criadoEm)}</td>
    </tr>
  );
}

export function BuscaCursos() {
  const [termo, setTermo] = useState("");
  const [resultado, setResultado] = useState<ResultadoBusca | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [marcados, setMarcados] = useState<Set<string>>(new Set());
  const [buscando, iniciarBusca] = useTransition();

  function buscar() {
    setErro(null);
    iniciarBusca(async () => {
      const r = await buscarCursos(termo);
      setErro(r.erro);
      setResultado(r.resultado);
      setMarcados(new Set());   // resultado novo, seleção antiga não vale mais
    });
  }

  function alternar(id: string) {
    setMarcados((atual) => {
      const novo = new Set(atual);
      if (novo.has(id)) novo.delete(id);
      else if (novo.size < LIMITE_SELECAO) novo.add(id);
      return novo;
    });
  }

  const selecionaveis = (resultado?.cursos ?? []).filter((c) => c.selecionavel);
  const todosMarcados =
    selecionaveis.length > 0 && selecionaveis.every((c) => marcados.has(c.id));

  return (
    <div>
      <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
        <input
          value={termo} onChange={(e) => setTermo(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); buscar(); } }}
          placeholder="Área Fiscal, PRF, BACEN…"
          style={{
            flex: 1, font: "inherit", padding: "8px 11px",
            border: "1px solid #e3e2dd", borderRadius: 8,
          }}
        />
        <button
          type="button" onClick={buscar} disabled={buscando}
          style={{
            font: "inherit", fontWeight: 600, cursor: buscando ? "wait" : "pointer",
            background: "#2a78d6", color: "#fff", border: 0, borderRadius: 8,
            padding: "8px 16px",
          }}
        >
          {buscando ? "Buscando…" : "Buscar"}
        </button>
      </div>

      {erro && <p style={{ color: "#c0392b", fontSize: 13 }}>{erro}</p>}

      {resultado && (
        <>
          <p style={{ fontSize: 12.5, color: "#52514e", margin: "0 0 8px" }}>
            {resultado.encontrados} encontrado(s) · {resultado.comConteudo} com conteúdo
            {resultado.cursos.length < resultado.encontrados &&
              ` · mostrando os ${resultado.cursos.length} mais recentes`}
            {resultado.podeHaverMais && (
              <span style={{ color: "#b9770e" }}>
                {" "}· a busca veio cheia, pode haver mais — refine o termo
              </span>
            )}
          </p>

          {resultado.cursos.length > 0 && (
            <form action={disparar}>
              <input type="hidden" name="modo" value="selecao" />
              {[...marcados].map((id) => (
                <input key={id} type="hidden" name="ids" value={id} />
              ))}

              <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 13 }}>
                <thead>
                  <tr>
                    <th style={{ ...celula, width: 28 }}>
                      <input
                        type="checkbox" checked={todosMarcados}
                        onChange={() =>
                          setMarcados(
                            todosMarcados
                              ? new Set()
                              : new Set(selecionaveis.slice(0, LIMITE_SELECAO).map((c) => c.id))
                          )
                        }
                        title="Marcar/desmarcar todos os que têm conteúdo"
                      />
                    </th>
                    {["Curso", "Peso", "Estado", "Criado"].map((t) => (
                      <th key={t} style={{
                        ...celula, textAlign: "left", color: "#52514e", fontSize: 11,
                        letterSpacing: ".07em", textTransform: "uppercase",
                      }}>{t}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {resultado.cursos.map((c) => (
                    <Linha
                      key={c.id} curso={c} marcado={marcados.has(c.id)} aoMarcar={alternar}
                    />
                  ))}
                </tbody>
              </table>

              <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 12 }}>
                <input
                  name="rotulo" required placeholder="Rótulo do lote (ex.: Área Fiscal 2026)"
                  style={{
                    flex: 1, font: "inherit", padding: "8px 11px",
                    border: "1px solid #e3e2dd", borderRadius: 8,
                  }}
                />
                <button
                  type="submit" disabled={marcados.size === 0}
                  style={{
                    font: "inherit", fontWeight: 600,
                    cursor: marcados.size ? "pointer" : "not-allowed",
                    background: marcados.size ? "#227a3e" : "#e3e2dd",
                    color: marcados.size ? "#fff" : "#8a897f",
                    border: 0, borderRadius: 8, padding: "8px 16px", whiteSpace: "nowrap",
                  }}
                >
                  Coletar {marcados.size || ""} juntos
                </button>
              </div>
              <p style={{ fontSize: 11.5, color: "#8a897f", margin: "6px 0 0" }}>
                Vira <strong>um</strong> pedido e <strong>um</strong> snapshot com o rótulo
                acima. Cursos sem capítulos não podem ser marcados (a coleta nasceria vazia).
              </p>
            </form>
          )}
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Ligar no formulário existente**

Em `web/app/coleta/form-disparo.tsx`, acrescentar o modo novo ao seletor de modos, com
`"selecao"` como **padrão**, e renderizar `<BuscaCursos />` quando ativo. O modo `"termo"`
**continua existindo**, com o rótulo ajustado para deixar a diferença clara:

```tsx
import { BuscaCursos } from "./busca-cursos";

// …no seletor de modo, "selecao" primeiro e marcado por padrão:
//   ○ Buscar e escolher cursos     (padrão)
//   ○ Termo inteiro — colhe tudo que casar, inclusive o que for criado depois
//   ○ Colar IDs/URLs do admin
```

O modo "termo inteiro" **não é depreciado**: é o caminho de menor atrito para BACEN/PRF e tem
uma semântica que a seleção perde (pega o que for criado depois).

- [ ] **Step 3: Mensagens novas**

Em `web/app/coleta/page.tsx`, importar `LIMITE_SELECAO` de `../../lib/coleta` e acrescentar ao
mapa de mensagens:

```tsx
  "nenhum-selecionado": () => "⚠ Marque pelo menos um curso antes de coletar.",
  "selecao-demais": () => `⚠ Selecione no máximo ${LIMITE_SELECAO} cursos por lote.`,
```

- [ ] **Step 4: Tipos, build e bundle**

Run: `cd web && npx tsc --noEmit && npm run build`
Expected: build limpo

Run: `cd web && grep -rl "service_role\|SUPABASE_SERVICE_KEY\|__Secure-SID" .next/static/ ; echo "vazio acima = ok"`
Expected: nenhum arquivo listado

- [ ] **Step 5: Suítes intactas**

Run: `cd web && node --experimental-strip-types checks/busca.check.ts && node --experimental-strip-types checks/coleta.check.ts && cd .. && py -m unittest discover -s tests`
Expected: `ok — 8 checagens da busca`, `ok — 9 checagens`, `OK` (143)

- [ ] **Step 6: Commit**

```bash
git add web/app/coleta/busca-cursos.tsx web/app/coleta/form-disparo.tsx web/app/coleta/page.tsx
git commit -m "feat: tela de busca com selecao multipla de cursos"
```

---

## Verificação final (exige o Clovis, no app publicado)

1. Buscar **"Área Fiscal"** e conferir contra o admin do LDI: **62 encontrados · 43 com
   conteúdo**, os de 30/07 no topo, "Governança de TI" e "Informática" com **0 cap** e caixa
   desabilitada.
2. **Aba Network do navegador:** a resposta da action tem de ser da ordem de **KB, não MB** —
   é a prova de que a árvore ficou no servidor. *Se vier MB, a checagem 3 falhou em produção.*
3. Buscar **"Direito"** e confirmar o aviso "a busca veio cheia, pode haver mais".
4. Termo de 2 caracteres: recusado **sem** chamar o LDI.
5. Marcar 2 cursos, dar um rótulo, coletar juntos → **um** pedido `ids` na fila → um snapshot
   com os dois cursos no painel.
6. Conferir que o modo "termo inteiro" continua funcionando como antes.

**Deploy:** só web (merge → Vercel). O worker **não** precisa de `git pull`: o disparo usa
`tipo:"ids"`, que ele já sabe fazer, e nenhum módulo alcançado por import do `coletor_ldi.py`
muda. (Afirmação seguindo a cadeia de imports, não os nomes dos arquivos — regra da sessão 10.)
