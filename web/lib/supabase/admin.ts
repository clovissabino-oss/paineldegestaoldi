import { createClient, type SupabaseClient, type User } from "@supabase/supabase-js";

// Cliente com a service_role (API admin do GoTrue). SERVER-ONLY:
// importar apenas de server actions / server components — nunca de
// componente cliente (a chave não pode chegar ao navegador).
export function criarClienteAdmin(): SupabaseClient {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const chave = process.env.SUPABASE_SERVICE_KEY;
  if (!url || !chave) {
    throw new Error("SUPABASE_SERVICE_KEY ausente (env server-only do app).");
  }
  return createClient(url, chave, {
    auth: { autoRefreshToken: false, persistSession: false },
  });
}

// A API admin não tem busca por e-mail; o time é pequeno (< 1000),
// então listamos uma página cheia e filtramos localmente.
export async function buscarPorEmail(
  admin: SupabaseClient,
  email: string
): Promise<User | null> {
  const usuarios = await listarUsuarios(admin);
  return usuarios.find((u) => (u.email ?? "").toLowerCase() === email) ?? null;
}

export async function listarUsuarios(admin: SupabaseClient): Promise<User[]> {
  const { data, error } = await admin.auth.admin.listUsers({ page: 1, perPage: 1000 });
  if (error) throw new Error(`listar usuários: ${error.message}`);
  if (data.users.length === 1000) {
    console.error("[admin] listUsers devolveu a página cheia (1000) — resultado pode estar truncado.");
  }
  return data.users;
}
