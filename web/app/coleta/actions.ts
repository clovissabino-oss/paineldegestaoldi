"use server";

import { redirect } from "next/navigation";
import { criarClienteAdmin } from "../../lib/supabase/admin";
import { exigirAdmin, exigirOperador } from "../../lib/papeis";
import {
  extrairIds, enfileirar, mudarStatus,
  converterCursosBusca, termoValido, TERMO_MINIMO, LIMITE_SELECAO,
  type ResultadoBusca,
} from "../../lib/coleta";
import { buscarNomeCursoLdi, buscarCursosLdi } from "../../lib/ldi";

const LIMITE_CONFERENCIA = 15;
// pedidos "em jogo" para efeito de aviso de repetição — os demais (cancelada,
// erro) não contam como "já coletado".
const STATUS_JA_COLETADO = ["pendente", "rodando", "concluida"];

export interface ItemConferencia {
  id: string;
  nome: string | null;
  jaColetado: { rotulo: string | null; pedidoId: number; criadoEm: string } | null;
}

// Resolve o NOME real de cada ID colado (contra o LDI) e avisa se aquele
// alvo já está/esteve na fila — checagem informativa ANTES de disparar
// (incidente real: UUID repetido em 2 disparos com rótulos diferentes, só
// percebido depois). NUNCA retorna nem loga o valor do cookie.
export async function conferirIds(
  texto: string
): Promise<{ erro: string | null; itens: ItemConferencia[] }> {
  await exigirOperador();

  let ids: string[];
  try {
    ids = extrairIds(texto);
  } catch (e) {
    return { erro: e instanceof Error ? e.message : "IDs inválidos.", itens: [] };
  }
  if (ids.length > LIMITE_CONFERENCIA) {
    return {
      erro: `Confira no máximo ${LIMITE_CONFERENCIA} IDs por vez (colou ${ids.length}).`,
      itens: [],
    };
  }

  const admin = criarClienteAdmin();
  const { data: config, error: erroConfig } = await admin
    .from("config_ldi")
    .select("cookie")
    .eq("id", 1)
    .maybeSingle<{ cookie: string | null }>();
  if (erroConfig) {
    console.error("[coleta] conferirIds (config_ldi):", erroConfig.message);
    return { erro: "Não foi possível ler o cookie do LDI — tente de novo.", itens: [] };
  }
  const cookie = config?.cookie ?? null;
  if (!cookie) {
    return { erro: "Sem cookie do LDI configurado.", itens: [] };
  }

  const nomes = await Promise.all(ids.map((id) => buscarNomeCursoLdi(cookie, id)));
  if (nomes.some((n) => n === "sem-acesso")) {
    return {
      erro: "O cookie do LDI está inválido — renove no bloco 🍪 acima.",
      itens: [],
    };
  }

  const itens: ItemConferencia[] = await Promise.all(
    ids.map(async (id, i) => {
      const { data: existente, error: erroExistente } = await admin
        .from("coleta_pedido")
        .select("id, rotulo, criado_em")
        .ilike("alvo", `%${id}%`)
        .in("status", STATUS_JA_COLETADO)
        .order("criado_em", { ascending: false })
        .limit(1)
        .maybeSingle<{ id: number; rotulo: string | null; criado_em: string }>();
      if (erroExistente) {
        console.error("[coleta] conferirIds (coleta_pedido):", erroExistente.message);
      }
      return {
        id,
        nome: nomes[i] as string | null,
        jaColetado: existente
          ? { rotulo: existente.rotulo, pedidoId: existente.id, criadoEm: existente.criado_em }
          : null,
      };
    })
  );

  return { erro: null, itens };
}

// Lista os cursos que um termo traria, para o operador escolher ANTES de
// disparar. exigirOperador: quem já pode disparar tipo:"termo" (que colhe
// TUDO) obviamente pode ver o que colheria.
export async function buscarCursos(
  termo: string
): Promise<{ erro: string | null; resultado: ResultadoBusca | null }> {
  await exigirOperador();

  const limpo = (termo ?? "").trim();
  if (!termoValido(limpo)) {
    return {
      erro: `Digite pelo menos ${TERMO_MINIMO} caracteres — busca vazia traria o catálogo inteiro.`,
      resultado: null,
    };
  }

  const admin = criarClienteAdmin();
  const { data: config, error: erroConfig } = await admin
    .from("config_ldi")
    .select("cookie")
    .eq("id", 1)
    .maybeSingle<{ cookie: string | null }>();
  if (erroConfig) {
    console.error("[coleta] buscarCursos (config_ldi):", erroConfig.message);
    return { erro: "Não foi possível ler o cookie do LDI — tente de novo.", resultado: null };
  }
  const cookie = config?.cookie ?? null;
  if (!cookie) return { erro: "Sem cookie do LDI configurado.", resultado: null };

  const brutos = await buscarCursosLdi(cookie, limpo);
  if (brutos === "sem-acesso") {
    return { erro: "O cookie do LDI está inválido — renove no bloco 🍪 acima.", resultado: null };
  }
  if (brutos === null) {
    return { erro: "A busca no LDI falhou (rede ou tempo esgotado) — tente de novo.", resultado: null };
  }

  return { erro: null, resultado: converterCursosBusca(brutos) };
}

// Dispara uma coleta: modo "termo" (busca por termo, ex. "PRF") ou modo
// "ids" (IDs/URLs colados do admin — exige rótulo para identificar o lote).
export async function disparar(formData: FormData) {
  const user = await exigirOperador();
  const modo = String(formData.get("modo") ?? "");

  if (modo === "termo") {
    const termo = String(formData.get("termo") ?? "").trim();
    if (!termo) redirect("/coleta?msg=termo-vazio");

    const admin = criarClienteAdmin();
    try {
      await enfileirar(admin, {
        tipo: "termo", alvo: termo, rotulo: null, pedido_por: user.email ?? "",
      });
    } catch (e) {
      console.error("[coleta] disparar (termo):", e instanceof Error ? e.message : e);
      redirect("/coleta?msg=erro");
    }
    redirect("/coleta?msg=disparada");
  }

  if (modo === "ids") {
    const rotulo = String(formData.get("rotulo") ?? "").trim();
    if (!rotulo) redirect("/coleta?msg=rotulo-vazio");

    let ids: string[];
    try {
      ids = extrairIds(String(formData.get("ids") ?? ""));
    } catch {
      redirect("/coleta?msg=ids-invalidos");
    }

    const admin = criarClienteAdmin();
    try {
      await enfileirar(admin, {
        tipo: "ids", alvo: ids.join(","), rotulo, pedido_por: user.email ?? "",
      });
    } catch (e) {
      console.error("[coleta] disparar (ids):", e instanceof Error ? e.message : e);
      redirect("/coleta?msg=erro");
    }
    redirect("/coleta?msg=disparada");
  }

  if (modo === "selecao") {
    const rotulo = String(formData.get("rotulo") ?? "").trim();
    if (!rotulo) redirect("/coleta?msg=rotulo-vazio");

    // getAll: a tela manda um campo `ids` por curso marcado.
    const ids = formData.getAll("ids").map((v) => String(v)).filter(Boolean);
    if (ids.length === 0) redirect("/coleta?msg=nenhum-selecionado");
    if (ids.length > LIMITE_SELECAO) redirect("/coleta?msg=selecao-demais");

    const admin = criarClienteAdmin();
    try {
      // tipo:"ids" — o worker já resolve por ID (coletor_ldi.py:224-228), então
      // zero mudança lá, sem refazer a busca pesada no VPS, e a seleção fica
      // CONGELADA: curso criado entre o clique e a execução não entra no lote.
      await enfileirar(admin, {
        tipo: "ids", alvo: ids.join(","), rotulo, pedido_por: user.email ?? "",
      });
    } catch (e) {
      console.error("[coleta] disparar (selecao):", e instanceof Error ? e.message : e);
      redirect("/coleta?msg=erro");
    }
    redirect("/coleta?msg=disparada");
  }

  redirect("/coleta?msg=erro");
}

export async function cancelar(formData: FormData) {
  await exigirAdmin();
  const id = Number(formData.get("id"));
  if (!id) redirect("/coleta?msg=erro");

  const admin = criarClienteAdmin();
  let mudou: boolean;
  try {
    mudou = await mudarStatus(admin, id, "cancelada", ["pendente"], {
      concluido_em: new Date().toISOString(),
    });
  } catch (e) {
    console.error("[coleta] cancelar:", e instanceof Error ? e.message : e);
    redirect("/coleta?msg=erro");
  }
  if (!mudou) redirect("/coleta?msg=status-mudou");
  redirect("/coleta?msg=cancelada");
}

export async function retentar(formData: FormData) {
  await exigirAdmin();
  const id = Number(formData.get("id"));
  if (!id) redirect("/coleta?msg=erro");

  const admin = criarClienteAdmin();
  let mudou: boolean;
  try {
    mudou = await mudarStatus(admin, id, "pendente", ["erro", "aguardando_cookie"], {
      mensagem: null, progresso: null, iniciado_em: null, concluido_em: null, extracao_id: null,
    });
  } catch (e) {
    console.error("[coleta] retentar:", e instanceof Error ? e.message : e);
    redirect("/coleta?msg=erro");
  }
  if (!mudou) redirect("/coleta?msg=status-mudou");
  redirect("/coleta?msg=retentada");
}

export async function cancelarEmAndamento(formData: FormData) {
  await exigirAdmin();
  const id = Number(formData.get("id"));
  if (!id) redirect("/coleta?msg=erro");

  const admin = criarClienteAdmin();
  let mudou: boolean;
  try {
    mudou = await mudarStatus(admin, id, "cancelando", ["rodando"]);
  } catch (e) {
    console.error("[coleta] cancelarEmAndamento:", e instanceof Error ? e.message : e);
    redirect("/coleta?msg=erro");
  }
  if (!mudou) redirect("/coleta?msg=status-mudou");
  redirect("/coleta?msg=cancelando");
}
