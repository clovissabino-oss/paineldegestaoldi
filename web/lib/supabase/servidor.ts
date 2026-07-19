import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";

// Cliente Supabase para route handlers e server actions.
// A sessão vive em cookies (@supabase/ssr) — é o que o middleware valida.
export async function criarClienteServidor() {
  const jarra = await cookies();
  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return jarra.getAll();
        },
        setAll(aGravar: Array<{ name: string; value: string; options?: Record<string, unknown> }>) {
          try {
            aGravar.forEach(({ name, value, options }) =>
              jarra.set(name, value, options as Parameters<typeof jarra.set>[2])
            );
          } catch {
            // Chamado de um Server Component: o middleware renova a sessão.
          }
        },
      },
    }
  );
}
