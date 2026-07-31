// Checagem das funções puras de web/lib/coleta.ts. O web/ não tem test runner
// (package.json só tem dev/build/start) — este arquivo é o padrão da casa,
// rodado à mão: `cd web && node --experimental-strip-types checks/coleta.check.ts`
import assert from "node:assert/strict";
import {
  montarAlvoExclusao, lerAlvoExclusao, chaveColeta,
  indexarPedidosExclusao, montarListaColetas,
  type Pedido, type SnapshotLinha,
} from "../lib/coleta.ts";

// 1. round-trip do alvo
const alvo = montarAlvoExclusao({
  termo: "BACEN", extracaoLocal: 37, snapshotId: 12, vacuum: false,
});
assert.equal(alvo, '{"termo":"BACEN","extracao_local":37,"snapshot_id":12,"vacuum":false}');
assert.deepEqual(lerAlvoExclusao(alvo), {
  termo: "BACEN", extracaoLocal: 37, snapshotId: 12, vacuum: false,
});

// 2. alvo ilegível não derruba a tela
assert.equal(lerAlvoExclusao("BACEN"), null);
assert.equal(lerAlvoExclusao('{"termo":"BACEN"}'), null);
assert.equal(lerAlvoExclusao('{"extracao_local":37}'), null);

// 3. chave
assert.equal(chaveColeta("BACEN", 37), "BACEN#37");

const pedido = (id: number, status: Pedido["status"], alvoJson: string): Pedido => ({
  id, tipo: "excluir", alvo: alvoJson, rotulo: null, status,
  progresso: null, mensagem: null, extracao_id: null, pedido_por: null,
  criado_em: "2026-07-30T10:00:00Z", iniciado_em: null, concluido_em: null,
});

// 4. indexação ignora pedidos de coleta e alvos ilegíveis; fica com o 1º (mais novo)
const indice = indexarPedidosExclusao([
  pedido(3, "erro", '{"termo":"BACEN","extracao_local":37}'),
  pedido(2, "concluida", '{"termo":"BACEN","extracao_local":37}'),
  pedido(1, "pendente", "lixo"),
  { ...pedido(0, "pendente", "PRF"), tipo: "termo" },
]);
assert.equal(indice.size, 1);
assert.equal(indice.get("BACEN#37")?.id, 3);

// 5. montarListaColetas: mais recente, único e destino
const snap = (id: number, termo: string, extracaoLocal: number): SnapshotLinha => ({
  id, termo, extracao_local: extracaoLocal, status: "completa",
  iniciada_em: `2026-07-${String(extracaoLocal).padStart(2, "0")}T09:00:00`,
  resumo: { kpis: { cursos_total: 128, blocos: 64838 } },
  pronto: true, sincronizado_em: "2026-07-30T10:00:00Z",
});
const lista = montarListaColetas(
  [snap(1, "BACEN", 33), snap(2, "BACEN", 37), snap(3, "PRF", 10)],
  [pedido(9, "rodando", '{"termo":"BACEN","extracao_local":33}')]
);
const bacen37 = lista.find((c) => c.termo === "BACEN" && c.extracaoLocal === 37)!;
const bacen33 = lista.find((c) => c.termo === "BACEN" && c.extracaoLocal === 33)!;
const prf = lista.find((c) => c.termo === "PRF")!;

assert.equal(bacen37.ehMaisRecenteDoTermo, true);
assert.equal(bacen37.ehUnicoDoTermo, false);
assert.equal(bacen37.destino?.extracaoLocal, 33);   // a web cai para a #33
assert.equal(bacen33.ehMaisRecenteDoTermo, false);
assert.equal(bacen33.destino, null);
assert.equal(bacen33.pedido?.status, "rodando");    // selo na linha certa
assert.equal(bacen37.pedido, null);
assert.equal(prf.ehUnicoDoTermo, true);
assert.equal(prf.ehMaisRecenteDoTermo, true);
assert.equal(prf.destino, null);                    // não há para onde cair
assert.equal(prf.cursos, 128);
assert.equal(prf.blocos, 64838);

// 6. ordem: mais novo primeiro, agrupado por termo
assert.deepEqual(lista.map((c) => `${c.termo}#${c.extracaoLocal}`),
                 ["BACEN#37", "BACEN#33", "PRF#10"]);

console.log("ok — 6 checagens");
