"use server";

import { redirect } from "next/navigation";
import { criarClienteAdmin } from "../../lib/supabase/admin";
import { exigirAdmin } from "../../lib/papeis";
import { probarCookieLdi } from "../../lib/ldi";

const DOMINIO_APROVADO = "@estrategia.com";
const PAPEIS_VALIDOS = ["", "operador", "admin"];
// telas que podem hospedar o formulário do cookie (whitelist do redirect)
const DESTINOS_COOKIE = ["/admin", "/coleta"];

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

export async function definirPapel(formData: FormData) {
  const eu = await exigirAdmin();
  const id = String(formData.get("id") ?? "");
  const email = String(formData.get("email") ?? "");
  const papel = String(formData.get("papel") ?? "");
  if (!id || !PAPEIS_VALIDOS.includes(papel)) redirect("/admin?msg=erro");
  if (id === eu.id) redirect("/admin?msg=proprio-papel");

  const admin = criarClienteAdmin();
  const { error } = await admin.auth.admin.updateUserById(id, {
    app_metadata: { role: papel || null },
  });
  if (error) {
    console.error("[admin] definirPapel:", error.message);
    redirect("/admin?msg=erro");
  }
  redirect(`/admin?msg=papel-definido&email=${encodeURIComponent(email)}`);
}

// Aceita o valor puro do __Secure-SID ou um trecho colado com
// "__Secure-SID=<valor>" (cookie header inteiro ou só o par) — extrai só o valor.
function sanearCookie(bruto: string): string {
  const texto = bruto.trim();
  const marcador = "__Secure-SID=";
  const posicao = texto.indexOf(marcador);
  if (posicao === -1) return texto;
  const resto = texto.slice(posicao + marcador.length);
  const fimValor = resto.indexOf(";");
  return (fimValor === -1 ? resto : resto.slice(0, fimValor)).trim();
}

export async function atualizarCookie(formData: FormData) {
  const user = await exigirAdmin();
  const destino = String(formData.get("voltar") ?? "");
  const voltar = DESTINOS_COOKIE.includes(destino) ? destino : "/admin";
  const cookie = sanearCookie(String(formData.get("cookie") ?? ""));
  if (!cookie) redirect(`${voltar}?msg=cookie-vazio`);

  // prova o cookie contra o LDI antes de salvar: recusado com certeza (401,
  // ou 403 JSON) não é salvo; inconclusivo (rede/WAF) salva mesmo assim e o
  // worker confirma em até 20s.
  const veredito = await probarCookieLdi(cookie);
  if (veredito === "recusado") redirect(`${voltar}?msg=cookie-recusado`);

  const admin = criarClienteAdmin();
  const { error } = await admin.from("config_ldi").upsert(
    {
      id: 1,
      cookie,
      atualizado_em: new Date().toISOString(),
      atualizado_por: user.email,
    },
    { onConflict: "id" }
  );
  if (error) {
    console.error("[admin] atualizarCookie:", error.message);
    redirect(`${voltar}?msg=cookie-erro`);
  }
  redirect(`${voltar}?msg=${veredito === "ok" ? "cookie-ok" : "cookie-salvo-sem-validar"}`);
}
