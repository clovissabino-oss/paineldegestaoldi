import { NextResponse } from "next/server";
import { snapshotAtual } from "../../../lib/dados";
import { criarClienteServidor } from "../../../lib/supabase/servidor";

export const dynamic = "force-dynamic";

// Mesmo shape do /api/cursos do painel.py (curso_id, nome, autores)
// + sincronizado_em para o selo de frescor da tela.
export async function GET(request: Request) {
  const termo = new URL(request.url).searchParams.get("termo") ?? undefined;
  const supabase = await criarClienteServidor();
  let snap;
  try {
    snap = await snapshotAtual(supabase, termo);
  } catch (e) {
    const erro = e instanceof Error ? e.message : String(e);
    return NextResponse.json({ data: null, erro }, { status: 500 });
  }
  if (!snap) return NextResponse.json({ data: [], sincronizado_em: null });

  const { data, error } = await supabase
    .from("avaliacao_curso")
    .select("curso_id, curso_nome, autores")
    .eq("snapshot_id", snap.id)
    .order("curso_nome");
  if (error) {
    return NextResponse.json({ data: null, erro: error.message }, { status: 500 });
  }
  const cursos = (data ?? []).map((c) => ({
    curso_id: c.curso_id,
    nome: c.curso_nome ?? "",
    autores: c.autores ?? "",
  }));
  return NextResponse.json({ data: cursos, sincronizado_em: snap.sincronizado_em });
}
