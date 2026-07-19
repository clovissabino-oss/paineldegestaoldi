"use server";

import { redirect } from "next/navigation";
import { criarClienteAdmin } from "../../lib/supabase/admin";
import { criarClienteServidor } from "../../lib/supabase/servidor";

const DOMINIO_APROVADO = "@estrategia.com";

// Toda action re-checa o papel NO SERVIDOR — nunca confiar só na página.
async function exigirAdmin() {
  const supabase = await criarClienteServidor();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user || user.app_metadata?.role !== "admin") redirect("/login");
  return user;
}

export async function convidarUsuario(formData: FormData) {
  await exigirAdmin();
  const email = String(formData.get("email") ?? "").trim().toLowerCase();
  if (!email || !email.includes("@")) redirect("/admin?msg=email");
  if (email.endsWith(DOMINIO_APROVADO)) redirect("/admin?msg=dominio");

  const admin = criarClienteAdmin();
  const { error } = await admin.auth.admin.inviteUserByEmail(email);
  if (error) {
    console.error("[admin] convidar:", error.message);
    redirect("/admin?msg=erro");
  }
  redirect(`/admin?msg=convidado&email=${encodeURIComponent(email)}`);
}

export async function removerUsuario(formData: FormData) {
  const eu = await exigirAdmin();
  const id = String(formData.get("id") ?? "");
  const email = String(formData.get("email") ?? "");
  if (!id) redirect("/admin?msg=erro");
  if (id === eu.id) redirect("/admin?msg=proprio");

  const admin = criarClienteAdmin();
  const { error } = await admin.auth.admin.deleteUser(id);
  if (error) {
    console.error("[admin] remover:", error.message);
    redirect("/admin?msg=erro");
  }
  redirect(`/admin?msg=removido&email=${encodeURIComponent(email)}`);
}
