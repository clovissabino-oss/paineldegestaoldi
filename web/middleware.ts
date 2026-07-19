import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

// Gate: sem sessão -> /login. Também renova o token expirado (setAll).
export async function middleware(request: NextRequest) {
  let resposta = NextResponse.next({ request });

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll();
        },
        setAll(aGravar: Array<{ name: string; value: string; options?: Record<string, unknown> }>) {
          aGravar.forEach(({ name, value }) => request.cookies.set(name, value));
          resposta = NextResponse.next({ request });
          aGravar.forEach(({ name, value, options }) =>
            resposta.cookies.set(name, value, options as Parameters<typeof resposta.cookies.set>[2])
          );
        },
      },
    }
  );

  const { data: { user } } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.redirect(new URL("/login", request.url));
  }
  return resposta;
}

export const config = {
  // Tudo passa pelo gate, exceto login, fluxo de auth e estáticos do Next.
  matcher: ["/((?!login|auth/|_next/static|_next/image|favicon.ico).*)"],
};
