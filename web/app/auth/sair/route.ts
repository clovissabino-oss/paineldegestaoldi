import { NextResponse } from "next/server";
import { criarClienteServidor } from "../../../lib/supabase/servidor";

export async function GET(request: Request) {
  const supabase = await criarClienteServidor();
  await supabase.auth.signOut();
  return NextResponse.redirect(new URL("/login", request.url));
}
