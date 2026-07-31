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

export type TipoPedido = "termo" | "ids" | "excluir";

export interface Pedido {
  id: number;
  tipo: TipoPedido;
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
    tipo: TipoPedido;
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

// O alvo de um pedido de exclusão é um JSON, nunca um termo legível — se o
// worker ANTIGO (sem git pull) pegar o pedido, ele trata o JSON como
// search_term, não acha curso nenhum e falha limpo. Um alvo legível faria o
// worker antigo RECOLETAR o termo que se pediu para apagar.
export interface AlvoExclusao {
  termo: string;
  extracaoLocal: number;
  snapshotId: number | null;
  vacuum: boolean;
}

export function montarAlvoExclusao(a: AlvoExclusao): string {
  return JSON.stringify({
    termo: a.termo,
    extracao_local: a.extracaoLocal,
    snapshot_id: a.snapshotId,
    vacuum: a.vacuum,
  });
}

// null quando o alvo não é um pedido de exclusão legível — a tela ignora a
// linha em vez de quebrar (um JSON malformado não pode derrubar a /admin).
export function lerAlvoExclusao(alvo: string): AlvoExclusao | null {
  try {
    const o = JSON.parse(alvo) as Record<string, unknown>;
    const termo = typeof o.termo === "string" ? o.termo.trim() : "";
    const extracaoLocal = typeof o.extracao_local === "number" ? o.extracao_local : null;
    if (!termo || extracaoLocal === null) return null;
    return {
      termo,
      extracaoLocal,
      snapshotId: typeof o.snapshot_id === "number" ? o.snapshot_id : null,
      vacuum: o.vacuum === true,
    };
  } catch {
    return null;
  }
}

// Chave natural da coleta: (termo, extracao_local). NÃO o snapshot_id — ele
// muda se o snapshot for republicado entre o pedido e a execução do worker.
export function chaveColeta(termo: string, extracaoLocal: number): string {
  return `${termo}#${extracaoLocal}`;
}

export function indexarPedidosExclusao(pedidos: Pedido[]): Map<string, Pedido> {
  const mapa = new Map<string, Pedido>();
  for (const p of pedidos) {
    if (p.tipo !== "excluir") continue;
    const alvo = lerAlvoExclusao(p.alvo);
    if (!alvo) continue;
    const chave = chaveColeta(alvo.termo, alvo.extracaoLocal);
    // a lista vem do mais novo para o mais velho: o primeiro é o que vale
    if (!mapa.has(chave)) mapa.set(chave, p);
  }
  return mapa;
}

// Shape cru da tabela `snapshot` (supabase/schema.sql). `resumo` é o
// painel.dados_do_snapshot() serializado pelo sync.
export interface SnapshotLinha {
  id: number;
  termo: string;
  extracao_local: number;
  status: string | null;
  iniciada_em: string | null;
  resumo: { kpis?: { cursos_total?: number; blocos?: number } } | null;
  pronto: boolean;
  sincronizado_em: string;
}

export interface ColetaListada {
  termo: string;
  extracaoLocal: number;
  snapshotId: number;
  pronto: boolean;
  iniciadaEm: string | null;
  sincronizadoEm: string;
  cursos: number | null;
  blocos: number | null;
  ehMaisRecenteDoTermo: boolean;
  ehUnicoDoTermo: boolean;
  // para onde a web cai se esta for apagada (só quando é a mais recente)
  destino: { extracaoLocal: number; iniciadaEm: string | null } | null;
  pedido: Pedido | null;
}

// Deriva tudo que a tela precisa saber ANTES de mostrar o botão. Os dois casos
// de risco (único do termo / mais recente do termo) saem daqui, não da UI:
// snapshot_atual faz `distinct on (termo) ... order by extracao_local desc`,
// então apagar a mais recente troca o que o time vê, em silêncio.
export function montarListaColetas(
  snapshots: SnapshotLinha[],
  pedidos: Pedido[]
): ColetaListada[] {
  const indice = indexarPedidosExclusao(pedidos);
  const porTermo = new Map<string, SnapshotLinha[]>();
  for (const s of snapshots) {
    porTermo.set(s.termo, [...(porTermo.get(s.termo) ?? []), s]);
  }

  const lista: ColetaListada[] = [];
  for (const termo of [...porTermo.keys()].sort((a, b) => a.localeCompare(b, "pt-BR"))) {
    const doTermo = [...(porTermo.get(termo) ?? [])].sort(
      (a, b) => b.extracao_local - a.extracao_local
    );
    doTermo.forEach((s, i) => {
      const anterior = i === 0 ? doTermo[1] : undefined;
      lista.push({
        termo: s.termo,
        extracaoLocal: s.extracao_local,
        snapshotId: s.id,
        pronto: s.pronto,
        iniciadaEm: s.iniciada_em,
        sincronizadoEm: s.sincronizado_em,
        cursos: s.resumo?.kpis?.cursos_total ?? null,
        blocos: s.resumo?.kpis?.blocos ?? null,
        ehMaisRecenteDoTermo: i === 0,
        ehUnicoDoTermo: doTermo.length === 1,
        destino: anterior
          ? { extracaoLocal: anterior.extracao_local, iniciadaEm: anterior.iniciada_em }
          : null,
        pedido: indice.get(chaveColeta(s.termo, s.extracao_local)) ?? null,
      });
    });
  }
  return lista;
}
