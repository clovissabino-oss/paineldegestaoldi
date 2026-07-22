import { atualizarCookie } from "../app/admin/actions";
import { estadoCookie, type StatusCookie } from "../lib/ldi";

// Seção "🍪 Cookie do LDI": status real (publicado pelo worker) + formulário de
// renovação. Server component; renderizar SÓ para admin (a action re-checa).
// `voltar` decide para onde a action redireciona ("/admin" ou "/coleta").

const dataLocal = (iso: string | null | undefined) =>
  iso
    ? new Date(iso).toLocaleString("pt-BR", {
        day: "2-digit", month: "2-digit", year: "2-digit",
        hour: "2-digit", minute: "2-digit", timeZone: "America/Sao_Paulo",
      })
    : "—";

const ROTULOS: Record<string, string> = {
  valido: "✅ aceito pelo LDI",
  derrubado: "⛔ sessão derrubada pelo servidor — cole um cookie novo",
  vencido: "❌ vencido",
};

export function CookieLdi({
  statusCookie,
  voltar,
}: {
  statusCookie: StatusCookie | null;
  voltar: "/admin" | "/coleta";
}) {
  const estado = estadoCookie(statusCookie);

  return (
    <section>
      <h2 style={{ fontSize: 17, fontWeight: 650, margin: "24px 0 4px" }}>
        🍪 Cookie do LDI
      </h2>
      <p style={{ color: "#52514e", fontSize: 13, margin: "0 0 12px" }}>
        Usado pelo worker de coleta para acessar o admin do LDI. Cole aqui um
        <code style={{ margin: "0 4px" }}>__Secure-SID</code>
        novo (o valor puro ou o cookie inteiro colado) quando vencer ou a sessão cair.
      </p>

      <p style={{ fontSize: 13, margin: "0 0 16px" }}>
        {statusCookie ? (
          <>
            {ROTULOS[estado] ?? estado}
            {statusCookie.email ? ` · ${statusCookie.email}` : ""}
            {estado === "valido" && statusCookie.dias_restantes != null
              ? ` · ${Math.round(statusCookie.dias_restantes)} dia(s) restante(s)`
              : ""}
            {" · atualizado em "}
            {dataLocal(statusCookie.atualizado_em)}
          </>
        ) : (
          "Sem informação ainda (o worker publica ao rodar)."
        )}
      </p>

      <form action={atualizarCookie} style={{ display: "flex", gap: 8, marginBottom: 20 }}>
        <input type="hidden" name="voltar" value={voltar} />
        <input
          type="password" name="cookie" required placeholder="__Secure-SID=... (ou só o valor)"
          style={{
            flex: 1, font: "inherit", padding: "8px 11px",
            border: "1px solid #e3e2dd", borderRadius: 8,
          }}
        />
        <button
          type="submit"
          style={{
            font: "inherit", fontWeight: 600, cursor: "pointer",
            background: "#2a78d6", color: "#fff", border: 0, borderRadius: 8,
            padding: "8px 16px",
          }}
        >
          Atualizar cookie
        </button>
      </form>
    </section>
  );
}
