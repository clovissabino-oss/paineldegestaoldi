import { readFile } from "fs/promises";
import { NextResponse } from "next/server";
import path from "path";
import { snapshotAtual, listarTermos } from "../lib/dados";
import { criarClienteServidor } from "../lib/supabase/servidor";

export const dynamic = "force-dynamic";

// GET / — serve o painel com __DADOS__ injetado (mesmo mecanismo do painel.py).
export async function GET(request: Request) {
  const termo = new URL(request.url).searchParams.get("termo") ?? undefined;
  const supabase = await criarClienteServidor();
  let snap;
  let termos: string[] = [];
  try {
    snap = await snapshotAtual(supabase, termo);
    termos = await listarTermos(supabase);
  } catch (e) {
    const erro = e instanceof Error ? e.message : String(e);
    return new NextResponse(
      `<h1>Erro ao carregar os dados.</h1><p>${erro}</p>`,
      { status: 500, headers: { "content-type": "text/html; charset=utf-8" } }
    );
  }
  if (!snap) {
    return new NextResponse(
      "<h1>Nenhum snapshot publicado ainda.</h1>" +
      "<p>Assim que o coletor rodar e sincronizar, os dados aparecem aqui.</p>",
      { headers: { "content-type": "text/html; charset=utf-8" } }
    );
  }
  const html = await readFile(
    path.join(process.cwd(), "telas", "painel.html"), "utf-8"
  );
  const dados = { ...snap.resumo, sincronizado_em: snap.sincronizado_em, termos, termo_atual: snap.termo };
  // < evita fechar o <script> se algum nome de curso tiver "</"
  const json = JSON.stringify(dados).replace(/</g, "\\u003c");
  return new NextResponse(html.replace("__DADOS__", () => json), {
    headers: { "content-type": "text/html; charset=utf-8" },
  });
}
