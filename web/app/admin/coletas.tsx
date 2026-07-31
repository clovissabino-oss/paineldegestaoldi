"use client";

import { useState, type CSSProperties } from "react";
import type { ColetaListada } from "../../lib/coleta";
import { pedirExclusaoColeta, retentarExclusao } from "./actions";

const celula: CSSProperties = { padding: "8px 10px", borderBottom: "1px solid #e3e2dd" };

// Data local do projeto: pt-BR com fuso explícito (servidor do Vercel é UTC).
const dataLocal = (iso: string | null) =>
  iso
    ? new Date(iso).toLocaleString("pt-BR", {
        day: "2-digit", month: "2-digit", year: "2-digit",
        hour: "2-digit", minute: "2-digit", timeZone: "America/Sao_Paulo",
      })
    : "—";

const numero = (n: number | null) => (n === null ? "—" : n.toLocaleString("pt-BR"));

function Confirmacao({ coleta, aoFechar }: { coleta: ColetaListada; aoFechar: () => void }) {
  const [digitado, setDigitado] = useState("");
  const confere = digitado.trim() === coleta.termo;

  return (
    <form action={pedirExclusaoColeta} style={{
      border: "1px solid #e0b4ae", background: "#fdf6f5", borderRadius: 8,
      padding: "12px 14px", margin: "8px 0",
    }}>
      <input type="hidden" name="termo" value={coleta.termo} />
      <input type="hidden" name="extracaoLocal" value={coleta.extracaoLocal} />
      <input type="hidden" name="snapshotId" value={coleta.snapshotId} />

      <p style={{ margin: "0 0 8px", fontWeight: 600 }}>
        Excluir a coleta #{coleta.extracaoLocal} de {coleta.termo}
      </p>
      <p style={{ margin: "0 0 8px", fontSize: 12.5, color: "#52514e" }}>
        {numero(coleta.cursos)} cursos · {numero(coleta.blocos)} blocos ·{" "}
        {dataLocal(coleta.iniciadaEm)}. Apaga o snapshot na web <strong>e</strong> a
        extração no conteudo.db do VPS. Não tem volta.
      </p>

      {coleta.ehUnicoDoTermo && (
        <p style={{ margin: "0 0 8px", fontSize: 12.5, color: "#b9770e" }}>
          ⚠ É a única coleta de {coleta.termo} — o termo some do seletor da web.
        </p>
      )}
      {!coleta.ehUnicoDoTermo && coleta.ehMaisRecenteDoTermo && coleta.destino && (
        <p style={{ margin: "0 0 8px", fontSize: 12.5, color: "#b9770e" }}>
          ⚠ É a coleta mais recente de {coleta.termo} — a web passa a exibir a
          #{coleta.destino.extracaoLocal} de {dataLocal(coleta.destino.iniciadaEm)}.
        </p>
      )}

      <label style={{ fontSize: 12.5, display: "block", marginBottom: 6 }}>
        Digite <strong>{coleta.termo}</strong> para confirmar:
      </label>
      <input
        name="confirmacao" value={digitado} autoComplete="off"
        onChange={(e) => setDigitado(e.target.value)}
        style={{
          font: "inherit", padding: "6px 10px", border: "1px solid #e3e2dd",
          borderRadius: 6, width: 220, marginRight: 8,
        }}
      />
      <button type="button" onClick={aoFechar} style={{
        font: "inherit", fontSize: 13, cursor: "pointer", background: "transparent",
        border: "1px solid #cfceca", borderRadius: 6, padding: "5px 12px", marginRight: 6,
      }}>
        Cancelar
      </button>
      <button type="submit" disabled={!confere} style={{
        font: "inherit", fontSize: 13, fontWeight: 600,
        cursor: confere ? "pointer" : "not-allowed",
        background: confere ? "#c0392b" : "#e3e2dd",
        color: confere ? "#fff" : "#8a897f",
        border: 0, borderRadius: 6, padding: "6px 14px",
      }}>
        Excluir
      </button>
    </form>
  );
}

function EstadoDoPedido({ coleta }: { coleta: ColetaListada }) {
  const p = coleta.pedido;
  if (!p) return null;
  if (p.status === "pendente") return <span style={{ color: "#b9770e" }}>⏳ exclusão pedida</span>;
  if (p.status === "rodando") return <span style={{ color: "#2a5fa8" }}>⏳ exclusão rodando</span>;
  return (
    <form action={retentarExclusao} style={{ display: "inline" }}>
      <input type="hidden" name="id" value={p.id} />
      <span style={{ color: "#c0392b" }} title={p.mensagem ?? ""}>
        ⛔ falhou: {(p.mensagem ?? "erro").slice(0, 60)}
      </span>{" "}
      <button type="submit" style={{
        font: "inherit", fontSize: 12, cursor: "pointer", background: "transparent",
        border: "1px solid #cfceca", borderRadius: 6, padding: "2px 8px",
      }}>
        Retentar
      </button>
    </form>
  );
}

export function ListaColetas({ coletas }: { coletas: ColetaListada[] }) {
  const [abertaEm, setAbertaEm] = useState<string | null>(null);

  if (coletas.length === 0) {
    return <p style={{ color: "#8a897f", fontSize: 13 }}>Nenhuma coleta publicada ainda.</p>;
  }

  return (
    <>
      <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 13 }}>
        <thead>
          <tr>
            {["Termo", "#", "Quando", "Cursos", "Blocos", ""].map((t) => (
              <th key={t} style={{
                textAlign: "left", padding: "8px 10px", color: "#52514e",
                fontSize: 11, letterSpacing: ".07em", textTransform: "uppercase",
                borderBottom: "1px solid #e3e2dd",
              }}>{t}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {coletas.map((c) => {
            const chave = `${c.termo}#${c.extracaoLocal}`;
            return (
              <tr key={chave}>
                <td style={celula}>
                  {c.termo}
                  {!c.pronto && (
                    <span style={{ color: "#b9770e", fontSize: 11 }}> (incompleta)</span>
                  )}
                </td>
                <td style={celula}>{c.extracaoLocal}</td>
                <td style={celula}>{dataLocal(c.iniciadaEm)}</td>
                <td style={celula}>{numero(c.cursos)}</td>
                <td style={celula}>{numero(c.blocos)}</td>
                <td style={{ ...celula, whiteSpace: "nowrap" }}>
                  {c.pedido ? (
                    <EstadoDoPedido coleta={c} />
                  ) : (
                    <button
                      type="button"
                      onClick={() => setAbertaEm(abertaEm === chave ? null : chave)}
                      style={{
                        font: "inherit", fontSize: 12, cursor: "pointer",
                        background: "transparent", color: "#c0392b",
                        border: "1px solid #e0b4ae", borderRadius: 6, padding: "2px 8px",
                      }}
                    >
                      Excluir
                    </button>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {coletas
        .filter((c) => `${c.termo}#${c.extracaoLocal}` === abertaEm)
        .map((c) => (
          <Confirmacao
            key={`${c.termo}#${c.extracaoLocal}`}
            coleta={c}
            aoFechar={() => setAbertaEm(null)}
          />
        ))}

      <p style={{ color: "#8a897f", fontSize: 12, marginTop: 10 }}>
        Esta lista mostra o que está publicado na web. Coletas que ficaram só no
        conteudo.db do VPS (quando o sync falhou) ocupam disco e <strong>não
        aparecem aqui</strong>.
      </p>
    </>
  );
}
