import { NextResponse } from "next/server";
import { listarTermos } from "../../../lib/dados";
import { criarClienteServidor } from "../../../lib/supabase/servidor";

export const dynamic = "force-dynamic";

// Concursos (termos) publicados, para o seletor das telas.
export async function GET() {
  const supabase = await criarClienteServidor();
  try {
    const termos = await listarTermos(supabase);
    return NextResponse.json({ data: termos });
  } catch (e) {
    const erro = e instanceof Error ? e.message : String(e);
    return NextResponse.json({ data: null, erro }, { status: 500 });
  }
}
