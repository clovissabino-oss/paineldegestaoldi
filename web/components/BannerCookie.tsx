import { criarClienteServidor } from "../lib/supabase/servidor";
import { estadoCookie } from "../lib/ldi";

// Aviso de status do cookie do LDI (publicado por cookie_status, id=1).
// Nunca lê config_ldi — só os campos derivados que o worker publica.
export async function BannerCookie() {
  const supabase = await criarClienteServidor();
  const { data: status } = await supabase
    .from("cookie_status")
    .select("dias_restantes, valido")
    .eq("id", 1)
    .maybeSingle<{ dias_restantes: number | null; valido: boolean }>();

  if (!status) return null;
  const estado = estadoCookie(status);

  if (estado === "derrubado" || estado === "vencido") {
    return (
      <p
        style={{
          fontSize: 13, margin: "0 0 16px", padding: "9px 13px",
          borderRadius: 8, background: "#fbe9e8", color: "#c0392b",
          border: "1px solid #f0c4c1",
        }}
      >
        {estado === "derrubado"
          ? "🍪 A sessão do cookie do LDI foi derrubada pelo servidor — coletas estão paradas. Renove na tela de coleta."
          : "🍪 Cookie do LDI vencido — coletas estão paradas. Renove na tela de coleta."}
      </p>
    );
  }

  if (status.dias_restantes != null && status.dias_restantes <= 3) {
    return (
      <p
        style={{
          fontSize: 13, margin: "0 0 16px", padding: "9px 13px",
          borderRadius: 8, background: "#fdf3dc", color: "#b9770e",
          border: "1px solid #eeddb0",
        }}
      >
        🍪 Cookie do LDI vence em {Math.round(status.dias_restantes)} dia(s) — renove na tela de coleta.
      </p>
    );
  }

  return null;
}
