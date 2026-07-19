import { enviarLink } from "./actions";

const MENSAGENS: Record<string, string> = {
  enviado: "✅ Link enviado! Abra seu e-mail e clique no link para entrar.",
  erro: "❌ Não foi possível enviar o link. Confira o e-mail — o acesso é por convite.",
  email: "Informe seu e-mail.",
  "link-invalido": "⚠ Link inválido ou vencido. Peça um novo abaixo.",
};

export default async function PaginaLogin({
  searchParams,
}: {
  searchParams: Promise<{ msg?: string }>;
}) {
  const { msg } = await searchParams;
  return (
    <main
      style={{
        minHeight: "100vh", display: "grid", placeItems: "center",
        background: "#fcfcfb", color: "#0b0b0b",
        font: '15px/1.5 "Segoe UI", system-ui, sans-serif',
      }}
    >
      <form
        action={enviarLink}
        style={{
          background: "#f4f4f2", border: "1px solid #e3e2dd", borderRadius: 10,
          padding: "28px 32px", width: 360, maxWidth: "90vw",
        }}
      >
        <p style={{
          fontSize: 11, letterSpacing: ".14em", textTransform: "uppercase",
          color: "#2a78d6", fontWeight: 600, margin: "0 0 6px",
        }}>
          Painel de Conteúdo
        </p>
        <h1 style={{ fontSize: 21, fontWeight: 650, margin: "0 0 4px" }}>Entrar</h1>
        <p style={{ color: "#52514e", fontSize: 13, margin: "0 0 16px" }}>
          Acesso por convite. Digite seu e-mail e receba um link de acesso.
        </p>
        {msg && MENSAGENS[msg] && (
          <p style={{ fontSize: 13, margin: "0 0 12px" }}>{MENSAGENS[msg]}</p>
        )}
        <input
          type="email" name="email" required placeholder="seu@email.com"
          style={{
            width: "100%", font: "inherit", padding: "8px 11px",
            border: "1px solid #e3e2dd", borderRadius: 8, marginBottom: 10,
          }}
        />
        <button
          type="submit"
          style={{
            width: "100%", font: "inherit", fontWeight: 600, cursor: "pointer",
            background: "#2a78d6", color: "#fff", border: 0, borderRadius: 8,
            padding: "9px 11px",
          }}
        >
          Enviar link de acesso
        </button>
      </form>
    </main>
  );
}
