import { type EmailOtpType } from "@supabase/supabase-js";
import { NextResponse } from "next/server";
import { criarClienteServidor } from "../../../lib/supabase/servidor";

// O link do e-mail (magic-link OU convite) chega aqui com token_hash + type.
export async function GET(request: Request) {
  const url = new URL(request.url);
  const token_hash = url.searchParams.get("token_hash");
  const type = (url.searchParams.get("type") ?? "email") as EmailOtpType;

  if (token_hash) {
    const supabase = await criarClienteServidor();
    const { error } = await supabase.auth.verifyOtp({ type, token_hash });
    if (!error) return NextResponse.redirect(new URL("/", url));
  }
  return NextResponse.redirect(new URL("/login?msg=link-invalido", url));
}
