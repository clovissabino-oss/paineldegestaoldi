"use server";

import { redirect } from "next/navigation";
import { criarClienteAdmin } from "../../lib/supabase/admin";
import { exigirAdmin, exigirOperador } from "../../lib/papeis";
import { extrairIds, enfileirar, mudarStatus } from "../../lib/coleta";

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
