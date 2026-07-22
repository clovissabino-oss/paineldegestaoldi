// Fala com a API do admin LDI para PROVAR o cookie na hora de colar.
// SERVER-ONLY (é chamado só por server actions) — nunca importar em cliente.
// Constantes espelham o lado Python (extrator_ldi.montar_sessao + config.json
// do VPS, vertical "concursos") e o probe do worker (cookie_status.URL_PROBE).

const X_VERTICAL = "concursos";
const USER_AGENT =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36";
const URL_PROBE =
  "https://api.estrategia.com/bo/ldi/courses" +
  "?page=1&per_page=1&sort=desc&order_by=created_at";
const TIMEOUT_PROBE_MS = 6000;

export type VereditoProbe = "ok" | "recusado" | "inconclusivo";

// 401 = recusado com certeza (o código do incidente real: AUTH.USER_SESSION_NOT_FOUND).
// 403 só conta como recusa se a resposta for JSON — um 403 HTML pode ser
// challenge de WAF contra o egress do Vercel, não veredito sobre o cookie.
// Rede/timeout/5xx = inconclusivo (quem confirma é o worker, em até 20s).
export async function probarCookieLdi(sid: string): Promise<VereditoProbe> {
  try {
    const controlador = new AbortController();
    const cronometro = setTimeout(() => controlador.abort(), TIMEOUT_PROBE_MS);
    const r = await fetch(URL_PROBE, {
      headers: {
        "x-vertical": X_VERTICAL,
        Cookie: `__Secure-SID=${sid}`,
        Accept: "application/json",
        "User-Agent": USER_AGENT,
      },
      cache: "no-store",
      signal: controlador.signal,
    });
    clearTimeout(cronometro);
    if (r.status === 401) return "recusado";
    if (
      r.status === 403 &&
      (r.headers.get("content-type") ?? "").includes("application/json")
    ) {
      return "recusado";
    }
    if (r.ok) return "ok";
    return "inconclusivo";
  } catch {
    return "inconclusivo";
  }
}

// Linha de cookie_status (publicada pelo worker; RLS SELECT authenticated).
export interface StatusCookie {
  email: string | null;
  expira_em: string | null;
  dias_restantes: number | null;
  valido: boolean;
  atualizado_em: string | null;
}

export type EstadoCookie = "valido" | "derrubado" | "vencido" | "sem-info";

// Inferência central (sem coluna nova no schema): o worker publica
// valido=false quando o probe recusa; se o exp do JWT ainda está no futuro
// (dias_restantes > 0), a causa só pode ser sessão derrubada pelo servidor.
export function estadoCookie(
  s: { valido: boolean; dias_restantes: number | null } | null
): EstadoCookie {
  if (!s) return "sem-info";
  if (s.valido) return "valido";
  if (s.dias_restantes != null && s.dias_restantes > 0) return "derrubado";
  return "vencido";
}
