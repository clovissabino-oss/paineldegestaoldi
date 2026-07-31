import { listarUsuarios, criarClienteAdmin } from "../../lib/supabase/admin";
import { criarClienteServidor } from "../../lib/supabase/servidor";
import { exigirAdmin } from "../../lib/papeis";
import { convidarUsuario } from "./actions";
import { FormRemover } from "./form-remover";
import { FormPapel } from "./form-papel";
import { BannerCookie } from "../../components/BannerCookie";
import { CookieLdi } from "../../components/CookieLdi";
import type { StatusCookie } from "../../lib/ldi";
import { montarListaColetas, type SnapshotLinha, type Pedido } from "../../lib/coleta";
import { ListaColetas } from "./coletas";

export const dynamic = "force-dynamic";
// o probe do cookie na action pode levar ~6s — folga na função serverless
export const maxDuration = 30;

const MENSAGENS: Record<string, (email?: string) => string> = {
  email: () => "Informe um e-mail válido.",
  dominio: () => "ℹ Esse e-mail é @estrategia.com — entra direto pelo login, sem convite.",
  erro: () => "❌ Não foi possível concluir — tente de novo.",
  proprio: () => "⚠ Você não pode remover a si mesmo.",
  "proprio-papel": () => "⚠ Você não pode alterar o próprio papel.",
  convidado: (e) => `✅ Convite enviado para ${e ?? "o e-mail"}.`,
  removido: (e) => `✅ Acesso de ${e ?? "usuário"} removido.`,
  "papel-definido": (e) => `✅ Papel de ${e ?? "usuário"} atualizado.`,
  "cookie-vazio": () => "Cole o cookie antes de salvar.",
  "cookie-erro": () => "❌ Não foi possível salvar o cookie — tente de novo.",
  "cookie-ok": () => "✅ Cookie aceito pelo LDI e salvo. O worker publica o status em instantes.",
  "cookie-recusado": () =>
    "⛔ O LDI recusou esse cookie (sessão inválida) — nada foi salvo. Copie o __Secure-SID de novo (F12 → Application → Cookies).",
  "cookie-salvo-sem-validar": () =>
    "⚠ Cookie salvo, mas não consegui validar contra o LDI agora — o worker confirma em instantes (veja o status).",
  "exclusao-enfileirada": () =>
    "✅ Exclusão enfileirada — o worker executa em até 20 segundos.",
  "exclusao-repetida": () => "⚠ Já existe um pedido de exclusão para essa coleta.",
  "exclusao-em-uso": () => "⛔ Essa extração está sendo escrita por uma coleta em andamento.",
  "exclusao-confirmacao": () => "⚠ O termo digitado não confere — nada foi excluído.",
  "exclusao-status-mudou": () => "⚠ O status do pedido mudou — recarregue a página.",
  "exclusao-retentada": () => "✅ Pedido de exclusão devolvido para a fila.",
  "exclusao-erro": () => "❌ Não foi possível concluir a exclusão — tente de novo.",
};

// Data local do projeto: pt-BR com fuso explícito (servidor do Vercel é UTC).
const dataLocal = (iso: string | undefined) =>
  iso
    ? new Date(iso).toLocaleString("pt-BR", {
        day: "2-digit", month: "2-digit", year: "2-digit",
        hour: "2-digit", minute: "2-digit", timeZone: "America/Sao_Paulo",
      })
    : "—";

export default async function PaginaAdmin({
  searchParams,
}: {
  searchParams: Promise<{ msg?: string; email?: string }>;
}) {
  const { msg, email } = await searchParams;

  const user = await exigirAdmin("notFound");

  const admin = criarClienteAdmin();
  const usuarios = await listarUsuarios(admin);
  usuarios.sort((a, b) => (a.email ?? "").localeCompare(b.email ?? "", "pt-BR"));

  // Estado do cookie do LDI vem de cookie_status (publicado pelo worker) —
  // nunca lemos config_ldi aqui (é onde o cookie de verdade fica).
  const supabase = await criarClienteServidor();
  const { data: statusCookie } = await supabase
    .from("cookie_status")
    .select("*")
    .eq("id", 1)
    .maybeSingle<StatusCookie>();

  // A fonte é a TABELA snapshot, não a view snapshot_atual: a view faz
  // `distinct on (termo)` e filtra pronto, escondendo justamente os candidatos
  // a lixo (os antigos e os incompletos).
  const { data: snapshots } = await supabase
    .from("snapshot")
    .select("id, termo, extracao_local, status, iniciada_em, resumo, pronto, sincronizado_em")
    .order("termo")
    .order("extracao_local", { ascending: false });
  const { data: pedidos } = await supabase
    .from("coleta_pedido")
    .select("*")
    .eq("tipo", "excluir")
    .in("status", ["pendente", "rodando", "erro"])
    .order("criado_em", { ascending: false })
    .limit(50);
  const coletas = montarListaColetas(
    (snapshots ?? []) as SnapshotLinha[],
    (pedidos ?? []) as Pedido[]
  );

  return (
    <main
      style={{
        maxWidth: 760, margin: "0 auto", padding: "32px 24px 64px",
        background: "#fcfcfb", color: "#0b0b0b", minHeight: "100vh",
        font: '14.5px/1.5 "Segoe UI", system-ui, sans-serif',
      }}
    >
      <p style={{
        fontSize: 11, letterSpacing: ".14em", textTransform: "uppercase",
        color: "#2a78d6", fontWeight: 600, margin: "0 0 6px",
      }}>
        <a href="/" style={{ color: "#8a897f", textDecoration: "none" }}>← painel</a>
        {" "}Painel de Conteúdo · administração de acesso
        {" · "}
        <a href="/coleta" style={{ color: "#8a897f", textDecoration: "none" }}>📥 Coleta</a>
      </p>
      <h1 style={{ fontSize: 21, fontWeight: 650, margin: "0 0 4px" }}>Usuários</h1>

      <BannerCookie />

      <p style={{ color: "#52514e", fontSize: 13, margin: "0 0 16px" }}>
        @estrategia.com entra sozinho pelo login. Convide aqui apenas e-mails externos.
      </p>

      {msg && MENSAGENS[msg] && (
        <p style={{ fontSize: 13, margin: "0 0 12px" }}>{MENSAGENS[msg](email)}</p>
      )}

      <form action={convidarUsuario} style={{ display: "flex", gap: 8, marginBottom: 20 }}>
        <input
          type="email" name="email" required placeholder="externo@dominio.com"
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
          Convidar
        </button>
      </form>

      <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 13 }}>
        <thead>
          <tr>
            {["E-mail", "Papel", "Confirmado", "Último login", ""].map((t) => (
              <th key={t} style={{
                textAlign: "left", padding: "8px 10px", color: "#52514e",
                fontSize: 11, letterSpacing: ".07em", textTransform: "uppercase",
                borderBottom: "1px solid #e3e2dd",
              }}>{t}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {usuarios.map((u) => (
            <tr key={u.id}>
              <td style={{ padding: "8px 10px", borderBottom: "1px solid #e3e2dd" }}>
                {u.email}
              </td>
              <td style={{ padding: "8px 10px", borderBottom: "1px solid #e3e2dd" }}>
                <FormPapel
                  id={u.id}
                  email={u.email ?? ""}
                  papel={String(u.app_metadata?.role ?? "")}
                  desabilitado={u.id === user.id}
                />
              </td>
              <td style={{ padding: "8px 10px", borderBottom: "1px solid #e3e2dd" }}>
                {u.email_confirmed_at ? "✅" : "📨 pendente"}
              </td>
              <td style={{ padding: "8px 10px", borderBottom: "1px solid #e3e2dd" }}>
                {dataLocal(u.last_sign_in_at)}
              </td>
              <td style={{ padding: "8px 10px", borderBottom: "1px solid #e3e2dd" }}>
                <FormRemover id={u.id} email={u.email ?? ""} desabilitado={u.id === user.id} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2 style={{ fontSize: 17, fontWeight: 650, margin: "28px 0 4px" }}>
        Coletas publicadas
      </h2>
      <p style={{ color: "#52514e", fontSize: 13, margin: "0 0 12px" }}>
        Excluir apaga o snapshot na web <strong>e</strong> a extração no conteudo.db
        do VPS. As pendências são preservadas.
      </p>
      <ListaColetas coletas={coletas} />

      <CookieLdi statusCookie={statusCookie ?? null} voltar="/admin" />
    </main>
  );
}
