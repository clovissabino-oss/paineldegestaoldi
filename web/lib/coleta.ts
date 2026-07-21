import type { SupabaseClient } from "@supabase/supabase-js";

// Porta fiel de extrair_ids() (coletor_ldi.py:43-62). Aceita UUIDs soltos
// e/ou URLs do admin (…?id=<uuid>&team_id=…), separados por vírgula/espaço/
// linha. Pega SEMPRE o id= (nunca o team_id=, por causa do prefixo [?&]
// exigido antes de "id="). Devolve a lista de UUIDs em minúsculas; lança se
// algum token não tiver ID.
const UUID_FONTE =
  "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}";
const RE_ID_NA_URL = new RegExp(`[?&]id=(${UUID_FONTE})`);
const RE_UUID_COMPLETO = new RegExp(`^${UUID_FONTE}$`);

export function extrairIds(texto: string): string[] {
  const ids: string[] = [];
  for (const tok of (texto ?? "").trim().split(/[\s,]+/)) {
    if (!tok) continue;
    const m = tok.match(RE_ID_NA_URL);
    if (m) {
      ids.push(m[1].toLowerCase());
    } else if (RE_UUID_COMPLETO.test(tok)) {
      ids.push(tok.toLowerCase());
    } else {
      throw new Error(`Não achei um ID de curso em: ${tok.slice(0, 60)}`);
    }
  }
  if (ids.length === 0) {
    throw new Error("Nenhum ID de curso informado.");
  }
  return ids;
}

export type StatusPedido =
  | "pendente"
  | "rodando"
  | "cancelando"
  | "cancelada"
  | "concluida"
  | "erro"
  | "aguardando_cookie";

export interface Pedido {
  id: number;
  tipo: "termo" | "ids";
  alvo: string;
  rotulo: string | null;
  status: StatusPedido;
  progresso: string | null;
  mensagem: string | null;
  extracao_id: number | null;
  pedido_por: string | null;
  criado_em: string;
  iniciado_em: string | null;
  concluido_em: string | null;
}

// Insere um pedido na fila (status inicial "pendente"). SERVER-ONLY:
// exige o cliente admin (escrita em coleta_pedido é só via service_role).
export async function enfileirar(
  admin: SupabaseClient,
  pedido: {
    tipo: "termo" | "ids";
    alvo: string;
    rotulo: string | null;
    pedido_por: string;
  }
): Promise<void> {
  const { error } = await admin.from("coleta_pedido").insert({
    tipo: pedido.tipo,
    alvo: pedido.alvo,
    rotulo: pedido.rotulo,
    pedido_por: pedido.pedido_por,
    status: "pendente",
  });
  if (error) throw new Error(`enfileirar pedido: ${error.message}`);
}

// Lista os pedidos mais recentes da fila (para a tela de coleta).
export async function listarFila(
  supabase: SupabaseClient,
  limite = 20
): Promise<Pedido[]> {
  const { data, error } = await supabase
    .from("coleta_pedido")
    .select("*")
    .order("criado_em", { ascending: false })
    .limit(limite);
  if (error) throw new Error(`listar fila: ${error.message}`);
  return (data ?? []) as Pedido[];
}

// Atualiza o status (e outros campos) de um pedido — de forma atômica:
// o UPDATE só aplica se o status ATUAL no banco ainda estiver entre
// `esperados` (WHERE id = ... AND status IN (...), executado pelo PostgREST
// como uma única instrução SQL). Evita a corrida ler-status-depois-escrever
// (admin cancela × worker do VPS reivindica o mesmo pedido ao mesmo tempo).
// Devolve `true` se alguma linha foi de fato atualizada; `false` se o status
// já tinha mudado (ou o id não existe) — o chamador decide o que fazer.
// SERVER-ONLY: exige o cliente admin (escrita em coleta_pedido é só via
// service_role).
export async function mudarStatus(
  admin: SupabaseClient,
  id: number,
  status: StatusPedido,
  esperados: StatusPedido[],
  extra?: Record<string, unknown>
): Promise<boolean> {
  const { data, error } = await admin
    .from("coleta_pedido")
    .update({ status, ...extra })
    .eq("id", id)
    .in("status", esperados)
    .select("id");
  if (error) throw new Error(`mudar status do pedido ${id}: ${error.message}`);
  return (data ?? []).length > 0;
}
