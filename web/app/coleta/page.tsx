import { criarClienteServidor } from "../../lib/supabase/servidor";
import { exigirOperador } from "../../lib/papeis";
import { listarFila } from "../../lib/coleta";
import { BannerCookie } from "../../components/BannerCookie";
import { CookieLdi } from "../../components/CookieLdi";
import type { StatusCookie } from "../../lib/ldi";
import { FormDisparo } from "./form-disparo";
import { FilaColeta } from "./fila";

export const dynamic = "force-dynamic";
// o probe do cookie na action pode levar ~6s — folga na função serverless
export const maxDuration = 30;

const MENSAGENS: Record<string, string> = {
  "termo-vazio": "Informe um termo de busca.",
  "ids-invalidos": "Não achei um ID de curso em algum dos itens colados — confira e tente de novo.",
  "rotulo-vazio": "Informe um rótulo para identificar o lote de IDs.",
  erro: "❌ Não foi possível concluir — tente de novo.",
  "status-mudou": "⚠ O status desse pedido já mudou — a lista foi atualizada.",
  disparada: "✅ Coleta adicionada à fila.",
  cancelada: "✅ Pedido cancelado.",
  retentada: "✅ Pedido reenviado para a fila.",
  cancelando: "✅ Cancelamento solicitado — o worker para em instantes.",
  "cookie-vazio": "Cole o cookie antes de salvar.",
  "cookie-erro": "❌ Não foi possível salvar o cookie — tente de novo.",
  "cookie-ok": "✅ Cookie aceito pelo LDI e salvo. O worker publica o status em instantes.",
  "cookie-recusado":
    "⛔ O LDI recusou esse cookie (sessão inválida) — nada foi salvo. Copie o __Secure-SID de novo (F12 → Application → Cookies).",
  "cookie-salvo-sem-validar":
    "⚠ Cookie salvo, mas não consegui validar contra o LDI agora — o worker confirma em instantes (veja o status).",
};

export default async function PaginaColeta({
  searchParams,
}: {
  searchParams: Promise<{ msg?: string }>;
}) {
  const { msg } = await searchParams;

  const user = await exigirOperador("notFound");
  const souAdmin = String(user.app_metadata?.role ?? "") === "admin";

  const supabase = await criarClienteServidor();
  const pedidos = await listarFila(supabase);
  // status real do cookie (publicado pelo worker) para o bloco de renovação
  const { data: statusCookie } = souAdmin
    ? await supabase
        .from("cookie_status")
        .select("*")
        .eq("id", 1)
        .maybeSingle<StatusCookie>()
    : { data: null };

  return (
    <main
      style={{
        maxWidth: 920, margin: "0 auto", padding: "32px 24px 64px",
        background: "#fcfcfb", color: "#0b0b0b", minHeight: "100vh",
        font: '14.5px/1.5 "Segoe UI", system-ui, sans-serif',
      }}
    >
      <p
        style={{
          fontSize: 11, letterSpacing: ".14em", textTransform: "uppercase",
          color: "#2a78d6", fontWeight: 600, margin: "0 0 6px",
        }}
      >
        <a href="/" style={{ color: "#8a897f", textDecoration: "none" }}>← painel</a>
        {" "}Painel de Conteúdo · coleta de concursos
        {souAdmin && (
          <>
            {" · "}
            <a href="/admin" style={{ color: "#8a897f", textDecoration: "none" }}>⚙ Admin</a>
          </>
        )}
      </p>
      <h1 style={{ fontSize: 21, fontWeight: 650, margin: "0 0 4px" }}>📥 Coleta de concursos</h1>
      <p style={{ color: "#8a897f", fontSize: 12, margin: "0 0 16px" }}>
        Conectado como {user.email}
        {souAdmin ? " · admin" : ""}
      </p>

      <BannerCookie />

      {msg && MENSAGENS[msg] && (
        <p style={{ fontSize: 13, margin: "0 0 12px" }}>{MENSAGENS[msg]}</p>
      )}

      {souAdmin && <CookieLdi statusCookie={statusCookie ?? null} voltar="/coleta" />}

      <FormDisparo />

      <h2 style={{ fontSize: 17, fontWeight: 650, margin: "0 0 4px" }}>Fila</h2>
      <p style={{ color: "#52514e", fontSize: 13, margin: "0 0 12px" }}>
        Atualiza sozinha a cada 5 segundos.
        {souAdmin ? "" : " Ações da fila são só para administradores."}
      </p>

      <FilaColeta pedidosIniciais={pedidos} souAdmin={souAdmin} />
    </main>
  );
}
