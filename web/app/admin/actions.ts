"use server";

import { redirect } from "next/navigation";
import { criarClienteAdmin } from "../../lib/supabase/admin";
import { exigirAdmin } from "../../lib/papeis";
import { probarCookieLdi } from "../../lib/ldi";
import {
  montarAlvoExclusao, lerAlvoExclusao, chaveColeta, mudarStatus,
  type Pedido,
} from "../../lib/coleta";

const DOMINIO_APROVADO = "@estrategia.com";
const PAPEIS_VALIDOS = ["", "operador", "admin"];
// telas que podem hospedar o formulário do cookie (whitelist do redirect)
const DESTINOS_COOKIE = ["/admin", "/coleta"];
// Pedidos de exclusão que ainda podem agir sobre o alvo.
const EXCLUSAO_EM_JOGO = ["pendente", "rodando"];

export async function convidarUsuario(formData: FormData) {
  await exigirAdmin();
  const email = String(formData.get("email") ?? "").trim().toLowerCase();
  if (!email || !email.includes("@")) redirect("/admin?msg=email");
  if (email.endsWith(DOMINIO_APROVADO)) redirect("/admin?msg=dominio");

  const admin = criarClienteAdmin();
  const { error } = await admin.auth.admin.inviteUserByEmail(email);
  if (error) {
    console.error("[admin] convidar:", error.message);
    redirect("/admin?msg=erro");
  }
  redirect(`/admin?msg=convidado&email=${encodeURIComponent(email)}`);
}

export async function removerUsuario(formData: FormData) {
  const eu = await exigirAdmin();
  const id = String(formData.get("id") ?? "");
  const email = String(formData.get("email") ?? "");
  if (!id) redirect("/admin?msg=erro");
  if (id === eu.id) redirect("/admin?msg=proprio");

  const admin = criarClienteAdmin();
  const { error } = await admin.auth.admin.deleteUser(id);
  if (error) {
    console.error("[admin] remover:", error.message);
    redirect("/admin?msg=erro");
  }
  redirect(`/admin?msg=removido&email=${encodeURIComponent(email)}`);
}

export async function definirPapel(formData: FormData) {
  const eu = await exigirAdmin();
  const id = String(formData.get("id") ?? "");
  const email = String(formData.get("email") ?? "");
  const papel = String(formData.get("papel") ?? "");
  if (!id || !PAPEIS_VALIDOS.includes(papel)) redirect("/admin?msg=erro");
  if (id === eu.id) redirect("/admin?msg=proprio-papel");

  const admin = criarClienteAdmin();
  const { error } = await admin.auth.admin.updateUserById(id, {
    app_metadata: { role: papel || null },
  });
  if (error) {
    console.error("[admin] definirPapel:", error.message);
    redirect("/admin?msg=erro");
  }
  redirect(`/admin?msg=papel-definido&email=${encodeURIComponent(email)}`);
}

// Aceita o valor puro do __Secure-SID ou um trecho colado com
// "__Secure-SID=<valor>" (cookie header inteiro ou só o par) — extrai só o valor.
function sanearCookie(bruto: string): string {
  const texto = bruto.trim();
  const marcador = "__Secure-SID=";
  const posicao = texto.indexOf(marcador);
  if (posicao === -1) return texto;
  const resto = texto.slice(posicao + marcador.length);
  const fimValor = resto.indexOf(";");
  return (fimValor === -1 ? resto : resto.slice(0, fimValor)).trim();
}

export async function atualizarCookie(formData: FormData) {
  const user = await exigirAdmin();
  const destino = String(formData.get("voltar") ?? "");
  const voltar = DESTINOS_COOKIE.includes(destino) ? destino : "/admin";
  const cookie = sanearCookie(String(formData.get("cookie") ?? ""));
  if (!cookie) redirect(`${voltar}?msg=cookie-vazio`);

  // prova o cookie contra o LDI antes de salvar: recusado com certeza (401,
  // ou 403 JSON) não é salvo; inconclusivo (rede/WAF) salva mesmo assim e o
  // worker confirma em até 20s.
  const veredito = await probarCookieLdi(cookie);
  if (veredito === "recusado") redirect(`${voltar}?msg=cookie-recusado`);

  const admin = criarClienteAdmin();
  const { error } = await admin.from("config_ldi").upsert(
    {
      id: 1,
      // salva sempre o PAR completo — é o formato que o worker usa no header
      // Cookie e que o cookie_status.py decodifica (incidente 22/07: o valor
      // puro salvo aqui quebrava o decode e o probe do worker)
      cookie: `__Secure-SID=${cookie}`,
      atualizado_em: new Date().toISOString(),
      atualizado_por: user.email,
    },
    { onConflict: "id" }
  );
  if (error) {
    console.error("[admin] atualizarCookie:", error.message);
    redirect(`${voltar}?msg=cookie-erro`);
  }
  redirect(`${voltar}?msg=${veredito === "ok" ? "cookie-ok" : "cookie-salvo-sem-validar"}`);
}

// Enfileira a exclusão de uma coleta. NÃO apaga nada aqui: o conteudo.db vive
// no disco do VPS, que a Vercel não alcança — quem apaga é o worker.
export async function pedirExclusaoColeta(formData: FormData) {
  const user = await exigirAdmin();
  const termo = String(formData.get("termo") ?? "").trim();
  const extracaoLocal = Number(formData.get("extracaoLocal"));
  const snapshotId = Number(formData.get("snapshotId"));
  const confirmacao = String(formData.get("confirmacao") ?? "").trim();

  if (!termo || !Number.isInteger(extracaoLocal) || extracaoLocal <= 0) {
    redirect("/admin?msg=exclusao-erro");
  }
  // A confirmação digitada é re-validada NO SERVIDOR — o botão desabilitado do
  // cliente é conveniência, não trava.
  if (confirmacao !== termo) redirect("/admin?msg=exclusao-confirmacao");

  const admin = criarClienteAdmin();

  // Trava 1: já existe pedido de exclusão em jogo para o mesmo alvo.
  const { data: pedidos, error: erroPedidos } = await admin
    .from("coleta_pedido")
    .select("*")
    .eq("tipo", "excluir")
    .in("status", EXCLUSAO_EM_JOGO);
  if (erroPedidos) {
    console.error("[admin] pedirExclusaoColeta (fila):", erroPedidos.message);
    redirect("/admin?msg=exclusao-erro");
  }
  const alvoChave = chaveColeta(termo, extracaoLocal);
  const jaPedido = (pedidos ?? []).some((p) => {
    const a = lerAlvoExclusao((p as Pedido).alvo);
    return a !== null && chaveColeta(a.termo, a.extracaoLocal) === alvoChave;
  });
  if (jaPedido) redirect("/admin?msg=exclusao-repetida");

  // Trava 2: não apagar o que está sendo escrito agora.
  // ATENÇÃO ao alcance real desta trava: `extracao_id` só é gravado no pedido
  // QUANDO ELE CONCLUI, então uma coleta em andamento normalmente tem
  // extracao_id nulo e não é pega aqui. Ela ainda vale para pedidos
  // reprocessados (que já têm o id de uma execução anterior), mas quem de fato
  // serializa exclusão × coleta é o WORKER SER ÚNICO E SERIAL — um pedido por
  // vez. Não remover a trava, mas também não confiar nela como se fosse a
  // garantia principal.
  const { data: rodando, error: erroRodando } = await admin
    .from("coleta_pedido")
    .select("id")
    .eq("status", "rodando")
    .eq("extracao_id", extracaoLocal)
    .limit(1);
  if (erroRodando) {
    console.error("[admin] pedirExclusaoColeta (rodando):", erroRodando.message);
    redirect("/admin?msg=exclusao-erro");
  }
  if ((rodando ?? []).length > 0) redirect("/admin?msg=exclusao-em-uso");

  const { error } = await admin.from("coleta_pedido").insert({
    tipo: "excluir",
    alvo: montarAlvoExclusao({
      termo,
      extracaoLocal,
      snapshotId: Number.isInteger(snapshotId) ? snapshotId : null,
      vacuum: false,   // VACUUM é a entrega 1b
    }),
    rotulo: null,
    pedido_por: user.email ?? "",
    status: "pendente",
  });
  if (error) {
    console.error("[admin] pedirExclusaoColeta (insert):", error.message);
    redirect("/admin?msg=exclusao-erro");
  }
  redirect("/admin?msg=exclusao-enfileirada");
}

export async function retentarExclusao(formData: FormData) {
  await exigirAdmin();
  const id = Number(formData.get("id"));
  if (!id) redirect("/admin?msg=exclusao-erro");

  const admin = criarClienteAdmin();
  let mudou: boolean;
  try {
    // Transição ATÔMICA (update condicional): se o status mudou entre o
    // render e o clique, zero linhas são atualizadas e nada é sobrescrito.
    mudou = await mudarStatus(admin, id, "pendente", ["erro"], {
      mensagem: null, progresso: null, iniciado_em: null,
      concluido_em: null, extracao_id: null,
    });
  } catch (e) {
    console.error("[admin] retentarExclusao:", e instanceof Error ? e.message : e);
    redirect("/admin?msg=exclusao-erro");
  }
  if (!mudou) redirect("/admin?msg=exclusao-status-mudou");
  redirect("/admin?msg=exclusao-retentada");
}
