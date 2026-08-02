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
