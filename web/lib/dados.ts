import type { SupabaseClient } from "@supabase/supabase-js";

// A view snapshot_atual tem 1 linha por termo (só pronto=true).
// Sem `termo`: o snapshot mais recente global. Com `termo`: o daquele concurso.
export async function snapshotAtual(supabase: SupabaseClient, termo?: string) {
  let consulta = supabase
    .from("snapshot_atual")
    .select("id, termo, resumo, sincronizado_em");
  consulta = termo
    ? consulta.eq("termo", termo)
    : consulta.order("sincronizado_em", { ascending: false });
  const { data, error } = await consulta.limit(1);
  if (error) throw new Error(`snapshot_atual: ${error.message}`);
  return data?.[0] ?? null;
}

// Lista os concursos (termos) publicados, para o seletor das telas.
export async function listarTermos(supabase: SupabaseClient): Promise<string[]> {
  const { data, error } = await supabase
    .from("snapshot_atual")
    .select("termo")
    .order("termo");
  if (error) throw new Error(`listar termos: ${error.message}`);
  return (data ?? []).map((r) => r.termo as string);
}
