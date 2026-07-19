"use server";

import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { criarClienteServidor } from "../../lib/supabase/servidor";

// Envia o magic-link. shouldCreateUser:false = convite apenas
// (e-mail não convidado não cria conta nem recebe link).
export async function enviarLink(formData: FormData) {
  const email = String(formData.get("email") ?? "").trim();
  if (!email) redirect("/login?msg=email");

  const h = await headers();
  const origem = `${h.get("x-forwarded-proto") ?? "http"}://${h.get("host")}`;

  const supabase = await criarClienteServidor();
  const { error } = await supabase.auth.signInWithOtp({
    email,
    options: {
      shouldCreateUser: false,
      emailRedirectTo: `${origem}/auth/confirm`,
    },
  });

  redirect(error ? "/login?msg=erro" : "/login?msg=enviado");
}
