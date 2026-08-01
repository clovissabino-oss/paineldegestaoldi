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
  // Desempata QUAL banco: `extracao_local` é um AUTOINCREMENT por conteudo.db,
  // e vários bancos publicam no mesmo Supabase (VPS, notebook e ao menos um
  // terceiro — constatado em 31/07 com dois "BACEN #1" distintos). Sem a data,
  // o worker apagaria a coleta errada quando os números colidem no mesmo termo.
  iniciadaEm: string | null;
  snapshotId: number | null;
  vacuum: boolean;
}

export function montarAlvoExclusao(a: AlvoExclusao): string {
  return JSON.stringify({
    termo: a.termo,
    extracao_local: a.extracaoLocal,
    iniciada_em: a.iniciadaEm,
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
      iniciadaEm: typeof o.iniciada_em === "string" ? o.iniciada_em : null,
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

// Só os pedidos que ainda dizem algo sobre o alvo. `concluida` some junto com o
// snapshot; `cancelada` volta a linha ao botão [excluir]. Sem este filtro, um
// pedido cancelado renderizaria como "⛔ falhou" — erro que ninguém cometeu.
const EXCLUSAO_VISIVEL: StatusPedido[] = ["pendente", "rodando", "erro"];

export function indexarPedidosExclusao(pedidos: Pedido[]): Map<string, Pedido> {
  const mapa = new Map<string, Pedido>();
  for (const p of pedidos) {
    if (p.tipo !== "excluir") continue;
    if (!EXCLUSAO_VISIVEL.includes(p.status)) continue;
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

// ————— Busca de cursos no LDI (entrega 2a) —————
// Spec: docs/superpowers/specs/2026-08-01-busca-selecao-cursos-design.md

// search_term vazio devolve o catálogo INTEIRO (127.309 cursos) COM as árvores
// — derrubaria a função serverless. É a trava mais importante desta entrega.
export const TERMO_MINIMO = 3;
// per_page é a ÚNICA alavanca de volume: a API ignora qualquer projeção
// (7 parâmetros testados no spike, todos devolvem o payload inteiro).
export const POR_PAGINA = 100;
export const CURSOS_NA_TELA = 30;
export const LIMITE_SELECAO = 30;

// Forma crua do curso na resposta do LDI. Só os campos que usamos —
// `authors_name` vem SEMPRE null na listagem (medido), por isso não entra
// no DTO: o nome do professor é buscado sob demanda, ao marcar o curso.
export interface CursoLdiBruto {
  id: string;
  name?: string | null;
  published?: boolean | null;
  created_at?: string | null;
  description?: string | null;
  content_tree_cache?: Array<{ items?: unknown[] | null }> | null;
}

// O DTO que vai ao navegador: ~200 bytes por curso, SEM a árvore.
export interface CursoBusca {
  id: string;
  nome: string;
  descricao: string | null;
  publicado: boolean;
  criadoEm: string | null;
  capitulos: number;
  aulas: number;
  // curso de 0 capítulos gera extração vazia (o VPS já tem uma: "Área Fiscal"
  // #11, 0 cursos/0 blocos) — aparece na lista, mas não se deixa marcar.
  selecionavel: boolean;
}

export interface ResultadoBusca {
  cursos: CursoBusca[];      // no máximo CURSOS_NA_TELA
  encontrados: number;       // total buscado (até POR_PAGINA)
  comConteudo: number;       // quantos têm árvore, entre os buscados
  podeHaverMais: boolean;
}

export function termoValido(termo: string): boolean {
  return (termo ?? "").trim().length >= TERMO_MINIMO;
}

// Lê a árvore e devolve NÚMEROS — a árvore em si é descartada aqui, no
// servidor. Capítulo sem `items` conta como capítulo com 0 aulas: acontece de
// verdade (curso em montagem com 46 capítulos e 6 aulas, visto no spike).
export function contarArvore(bruto: CursoLdiBruto): {
  capitulos: number;
  aulas: number;
} {
  const caps = Array.isArray(bruto?.content_tree_cache) ? bruto.content_tree_cache : [];
  let aulas = 0;
  for (const cap of caps) {
    aulas += Array.isArray(cap?.items) ? cap.items.length : 0;
  }
  return { capitulos: caps.length, aulas };
}

// Descrição só quando acrescenta informação: medida vazia em 27 de 30 cursos,
// e quando existe costuma repetir o nome.
function descricaoUtil(bruto: CursoLdiBruto): string | null {
  const d = (bruto?.description ?? "").trim();
  if (!d) return null;
  return d.toLowerCase() === (bruto?.name ?? "").trim().toLowerCase() ? null : d;
}

// Converte o payload cru no DTO leve. NÃO reordena: a API já entrega por
// created_at desc, e é essa ordem que a tela mostra.
export function converterCursosBusca(brutos: CursoLdiBruto[]): ResultadoBusca {
  const lista = Array.isArray(brutos) ? brutos : [];
  const cursos = lista.slice(0, CURSOS_NA_TELA).map((b): CursoBusca => {
    const { capitulos, aulas } = contarArvore(b);
    return {
      id: String(b?.id ?? ""),
      nome: (b?.name ?? "").trim() || "(sem nome)",
      descricao: descricaoUtil(b),
      publicado: b?.published === true,
      criadoEm: b?.created_at ?? null,
      capitulos,
      aulas,
      selecionavel: capitulos > 0,
    };
  });
  return {
    cursos,
    encontrados: lista.length,
    comConteudo: lista.filter((b) => contarArvore(b).capitulos > 0).length,
    // meta.total do LDI mente (127.309 sempre) — a página cheia é a única
    // pista honesta de que há mais resultados.
    podeHaverMais: lista.length >= POR_PAGINA,
  };
}
