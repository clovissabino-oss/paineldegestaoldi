"use server";

import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { buscarPorEmail, criarClienteAdmin } from "../../lib/supabase/admin";
import { criarClienteServidor } from "../../lib/supabase/servidor";

const DOMINIO_APROVADO = "@estrategia.com";

// Regra de acesso (spec 2026-07-19):
//   @estrategia.com  -> pré-aprovado: cria/confirma o usuário e envia o link
//   externo          -> só por convite (existente e confirmado)
export async function enviarLink(formData: FormData) {
  const email = String(formData.get("email") ?? "").trim().toLowerCase();
  if (!email || !email.includes("@")) redirect("/login?msg=email");

  const admin = criarClienteAdmin();
  const usuario = await buscarPorEmail(admin, email);

  if (email.endsWith(DOMINIO_APROVADO)) {
    if (!usuario) {
      const { error } = await admin.auth.admin.createUser({ email, email_confirm: true });
      if (error) {
        console.error("[login] criar usuário do domínio:", error.message);
        redirect("/login?msg=erro");
      }
    } else if (!usuario.email_confirmed_at) {
      const { error } = await admin.auth.admin.updateUserById(usuario.id, {
        email_confirm: true,
      });
      if (error) {
        console.error("[login] confirmar usuário do domínio:", error.message);
        redirect("/login?msg=erro");
      }
    }
  } else {
    if (!usuario) redirect("/login?msg=convite");
    if (!usuario.email_confirmed_at) {
      redirect(`/login?msg=convite-pendente&email=${encodeURIComponent(email)}`);
    }
  }

  // Aqui o usuário existe e está confirmado -> magic link normal.
  const h = await headers();
  const origem = `${h.get("x-forwarded-proto") ?? "http"}://${h.get("host")}`;
  const supabase = await criarClienteServidor();
  const { error } = await supabase.auth.signInWithOtp({
    email,
    options: { shouldCreateUser: false, emailRedirectTo: `${origem}/auth/confirm` },
  });
  if (error) {
    console.error("[login] enviar magic link:", error.message);
    redirect("/login?msg=erro");
  }
  redirect("/login?msg=enviado");
}

// Reenvia o convite APENAS para convidado pendente (existe e não confirmou) —
// não vira reenviador arbitrário de convites.
export async function reenviarConvite(formData: FormData) {
  const email = String(formData.get("email") ?? "").trim().toLowerCase();
  if (!email) redirect("/login?msg=email");

  const admin = criarClienteAdmin();
  const usuario = await buscarPorEmail(admin, email);
  if (!usuario || usuario.email_confirmed_at) redirect("/login?msg=convite");

  const { error } = await admin.auth.admin.inviteUserByEmail(email);
  if (error) {
    console.error("[login] reenviar convite:", error.message);
    redirect("/login?msg=erro");
  }
  redirect("/login?msg=convite-reenviado");
}
