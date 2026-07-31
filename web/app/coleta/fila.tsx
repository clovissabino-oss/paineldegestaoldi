"use client";

import { useEffect, useState, type CSSProperties } from "react";
// Import só de tipos — apagado no build, nenhum código server-only vai
// pro bundle do cliente (ver nota no brief da Task 5).
import type { Pedido, StatusPedido } from "../../lib/coleta";
import { lerAlvoExclusao } from "../../lib/coleta";
import { cancelar, cancelarEmAndamento, retentar } from "./actions";

const INTERVALO_POLLING_MS = 5000;

const RES_STATUS: Record<StatusPedido, string> = {
  pendente: "pendente",
  rodando: "rodando",
  cancelando: "cancelando",
  cancelada: "cancelada",
  concluida: "concluída",
  erro: "erro",
  aguardando_cookie: "aguardando cookie",
};

const CORES_STATUS: Record<StatusPedido, { bg: string; cor: string }> = {
  pendente: { bg: "#eeede8", cor: "#52514e" },
  rodando: { bg: "#e3edfb", cor: "#2a5fa8" },
  cancelando: { bg: "#fdecd8", cor: "#b9770e" },
  cancelada: { bg: "#eeede8", cor: "#8a897f" },
  concluida: { bg: "#e3f3e6", cor: "#227a3e" },
  erro: { bg: "#fbe9e8", cor: "#c0392b" },
  aguardando_cookie: { bg: "#fdf3dc", cor: "#b9770e" },
};

// Data local do projeto: pt-BR com fuso explícito (mesmo helper de /admin,
// replicado aqui porque é componente cliente).
const dataLocal = (iso: string | null) =>
  iso
    ? new Date(iso).toLocaleString("pt-BR", {
        day: "2-digit", month: "2-digit", year: "2-digit",
        hour: "2-digit", minute: "2-digit", timeZone: "America/Sao_Paulo",
      })
    : "—";

const celula: CSSProperties = { padding: "8px 10px", borderBottom: "1px solid #e3e2dd" };

// Sem isto a coluna "Rótulo / alvo" despeja o JSON cru do pedido de exclusão.
function descreverAlvo(p: Pedido): string {
  if (p.tipo !== "excluir") return p.alvo;
  const alvo = lerAlvoExclusao(p.alvo);
  return alvo ? `excluir a coleta #${alvo.extracaoLocal} de ${alvo.termo}` : p.alvo;
}

function Selo({ status }: { status: StatusPedido }) {
  const { bg, cor } = CORES_STATUS[status];
  return (
    <span
      style={{
        display: "inline-block", fontSize: 11, fontWeight: 600, padding: "2px 8px",
        borderRadius: 999, background: bg, color: cor, whiteSpace: "nowrap",
        textDecoration: status === "cancelada" ? "line-through" : "none",
      }}
    >
      {RES_STATUS[status]}
    </span>
  );
}

function BotaoAcao({
  acao, id, rotulo, confirmar,
}: {
  acao: (formData: FormData) => void | Promise<void>;
  id: number;
  rotulo: string;
  confirmar: string;
}) {
  return (
    <form
      action={acao}
      onSubmit={(e) => {
        if (!confirm(confirmar)) e.preventDefault();
      }}
      style={{ display: "inline-block", marginRight: 6, marginTop: 2 }}
    >
      <input type="hidden" name="id" value={id} />
      <button
        type="submit"
        style={{
          font: "inherit", fontSize: 12, cursor: "pointer",
          background: "transparent", color: "#0b0b0b",
          border: "1px solid #cfceca", borderRadius: 6, padding: "2px 8px",
        }}
      >
        {rotulo}
      </button>
    </form>
  );
}

export function FilaColeta({
  pedidosIniciais, souAdmin,
}: {
  pedidosIniciais: Pedido[];
  souAdmin: boolean;
}) {
  const [pedidos, setPedidos] = useState<Pedido[]>(pedidosIniciais);

  useEffect(() => {
    const intervalo = setInterval(async () => {
      try {
        const resp = await fetch("/api/fila");
        if (!resp.ok) return;
        const corpo = await resp.json();
        if (Array.isArray(corpo?.data)) setPedidos(corpo.data);
      } catch {
        // Falha de rede no polling — silencioso, tenta de novo no próximo ciclo.
      }
    }, INTERVALO_POLLING_MS);
    return () => clearInterval(intervalo);
  }, []);

  if (pedidos.length === 0) {
    return <p style={{ color: "#8a897f", fontSize: 13 }}>Nenhum pedido na fila ainda.</p>;
  }

  return (
    <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 13 }}>
      <thead>
        <tr>
          {["Status", "Rótulo / alvo", "Progresso", "Pedido por", "Criado", "Iniciado", "Concluído", ""].map((t) => (
            <th
              key={t}
              style={{
                textAlign: "left", padding: "8px 10px", color: "#52514e",
                fontSize: 11, letterSpacing: ".07em", textTransform: "uppercase",
                borderBottom: "1px solid #e3e2dd",
              }}
            >
              {t}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {pedidos.map((p) => (
          <tr key={p.id}>
            <td style={celula}>
              <Selo status={p.status} />
              {p.status === "erro" && p.mensagem && (
                <div style={{ fontSize: 11, color: "#c0392b", marginTop: 4, maxWidth: 220 }}>
                  {p.mensagem}
                </div>
              )}
            </td>
            <td style={{ ...celula, maxWidth: 260 }} title={descreverAlvo(p)}>
              {p.rotulo ? <strong>{p.rotulo}</strong> : <span style={{ color: "#8a897f" }}>({p.tipo})</span>}
              <div
                style={{
                  fontSize: 11, color: "#8a897f", overflow: "hidden",
                  textOverflow: "ellipsis", whiteSpace: "nowrap",
                }}
              >
                {descreverAlvo(p)}
              </div>
            </td>
            <td style={celula}>{p.progresso ?? "—"}</td>
            <td style={celula}>{p.pedido_por ?? "—"}</td>
            <td style={celula}>{dataLocal(p.criado_em)}</td>
            <td style={celula}>{dataLocal(p.iniciado_em)}</td>
            <td style={celula}>{dataLocal(p.concluido_em)}</td>
            <td style={{ ...celula, whiteSpace: "nowrap" }}>
              {souAdmin && p.status === "pendente" && (
                <BotaoAcao
                  acao={cancelar} id={p.id} rotulo="Cancelar"
                  confirmar={`Cancelar o pedido "${p.rotulo ?? p.alvo}"?`}
                />
              )}
              {souAdmin && (p.status === "erro" || p.status === "aguardando_cookie") && (
                <BotaoAcao
                  acao={retentar} id={p.id} rotulo="Retentar"
                  confirmar={`Reenviar o pedido "${p.rotulo ?? p.alvo}" para a fila?`}
                />
              )}
              {souAdmin && p.status === "rodando" && (
                <BotaoAcao
                  acao={cancelarEmAndamento} id={p.id} rotulo="Cancelar em andamento"
                  confirmar={`Cancelar a coleta em andamento de "${p.rotulo ?? p.alvo}"?`}
                />
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
