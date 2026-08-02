"use client";

import { useState, useTransition, type CSSProperties } from "react";
import { disparar, conferirIds, type ItemConferencia } from "./actions";
import { BuscaCursos } from "./busca-cursos";

const estiloCampo: CSSProperties = {
  width: "100%", font: "inherit", padding: "8px 11px",
  border: "1px solid #e3e2dd", borderRadius: 8, boxSizing: "border-box",
};

// Data curta pt-BR (mesmo fuso do resto da tela) — só dia/mês, o suficiente
// pra "já coletado como X (pedido #N, DD/MM)".
const dataCurta = (iso: string) =>
  new Date(iso).toLocaleString("pt-BR", {
    day: "2-digit", month: "2-digit", timeZone: "America/Sao_Paulo",
  });

function ListaConferencia({ itens }: { itens: ItemConferencia[] }) {
  return (
    <ul style={{ margin: 0, padding: 0, listStyle: "none", fontSize: 12.5, display: "flex", flexDirection: "column", gap: 4 }}>
      {itens.map((item) => (
        <li key={item.id}>
          <div>
            {item.nome ? "✓" : "⚠"} {item.id.slice(0, 8)}… →{" "}
            {item.nome ?? <span style={{ color: "#b9770e" }}>curso não encontrado no LDI</span>}
          </div>
          {item.jaColetado && (
            <div style={{ color: "#b9770e", fontSize: 11.5, marginLeft: 16 }}>
              ⚠ já coletado como "{item.jaColetado.rotulo ?? "(sem rótulo)"}" (pedido #
              {item.jaColetado.pedidoId}, {dataCurta(item.jaColetado.criadoEm)})
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}

export function FormDisparo() {
  const [modo, setModo] = useState<"selecao" | "termo" | "ids">("selecao");
  const [ids, setIds] = useState("");
  const [conferindo, iniciarConferencia] = useTransition();
  const [resultado, setResultado] = useState<{ erro: string | null; itens: ItemConferencia[] } | null>(null);

  function conferir() {
    setResultado(null);
    iniciarConferencia(async () => {
      const r = await conferirIds(ids);
      setResultado(r);
    });
  }

  return (
    <div
      style={{
        display: "flex", flexDirection: "column", gap: 10,
        padding: 16, marginBottom: 24,
        border: "1px solid #e3e2dd", borderRadius: 10, background: "#fff",
      }}
    >
      <div style={{ display: "flex", gap: 18, fontSize: 13, flexWrap: "wrap" }}>
        <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
          <input
            type="radio" name="modo-seletor" value="selecao"
            checked={modo === "selecao"} onChange={() => setModo("selecao")}
          />
          Buscar e escolher cursos
        </label>
        <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
          <input
            type="radio" name="modo-seletor" value="termo"
            checked={modo === "termo"} onChange={() => setModo("termo")}
          />
          Termo inteiro — colhe tudo que casar, inclusive o que for criado depois
        </label>
        <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
          <input
            type="radio" name="modo-seletor" value="ids"
            checked={modo === "ids"} onChange={() => setModo("ids")}
          />
          Colar IDs/URLs do admin
        </label>
      </div>

      {modo === "selecao" ? (
        <BuscaCursos />
      ) : (
        <form
          action={disparar}
          style={{ display: "flex", flexDirection: "column", gap: 10 }}
        >
          <input type="hidden" name="modo" value={modo} />

          {modo === "termo" ? (
            <input
              type="text" name="termo" required placeholder="Ex.: PRF"
              style={estiloCampo}
            />
          ) : (
            <>
              <textarea
                name="ids" required rows={4}
                placeholder="Cole URLs ou UUIDs do admin, um por linha (ou separados por vírgula/espaço)"
                style={{ ...estiloCampo, resize: "vertical", font: "inherit" }}
                value={ids}
                onChange={(e) => setIds(e.target.value)}
              />
              <button
                type="button"
                onClick={conferir}
                disabled={conferindo || !ids.trim()}
                style={{
                  alignSelf: "flex-start", font: "inherit", fontSize: 12.5, fontWeight: 600,
                  cursor: conferindo || !ids.trim() ? "default" : "pointer",
                  background: "transparent", color: "#2a78d6",
                  border: "1px solid #2a78d6", borderRadius: 8, padding: "6px 12px",
                  opacity: conferindo || !ids.trim() ? 0.6 : 1,
                }}
              >
                {conferindo ? "conferindo…" : "🔍 Conferir cursos"}
              </button>

              {resultado?.erro && (
                <p style={{ color: "#c0392b", fontSize: 12.5, margin: 0 }}>{resultado.erro}</p>
              )}
              {resultado && !resultado.erro && resultado.itens.length > 0 && (
                <ListaConferencia itens={resultado.itens} />
              )}

              <input
                type="text" name="rotulo" required placeholder="Rótulo do lote (obrigatório) — ex.: Reforço PRF turma 2"
                style={estiloCampo}
              />
            </>
          )}

          <button
            type="submit"
            style={{
              alignSelf: "flex-start", font: "inherit", fontWeight: 600, cursor: "pointer",
              background: "#2a78d6", color: "#fff", border: 0, borderRadius: 8,
              padding: "8px 16px",
            }}
          >
            Disparar coleta
          </button>
        </form>
      )}
    </div>
  );
}
