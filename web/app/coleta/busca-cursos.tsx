"use client";

import { useState, useTransition, type CSSProperties } from "react";
import { LIMITE_SELECAO, type CursoBusca, type ResultadoBusca } from "../../lib/coleta";
import { buscarCursos, disparar } from "./actions";

const celula: CSSProperties = { padding: "7px 9px", borderBottom: "1px solid #e3e2dd" };

const dataLocal = (iso: string | null) =>
  iso
    ? new Date(iso).toLocaleDateString("pt-BR", {
        day: "2-digit", month: "2-digit", year: "2-digit",
        timeZone: "America/Sao_Paulo",
      })
    : "—";

function Linha({
  curso, marcado, aoMarcar,
}: {
  curso: CursoBusca;
  marcado: boolean;
  aoMarcar: (id: string) => void;
}) {
  return (
    <tr style={{ opacity: curso.selecionavel ? 1 : 0.55 }}>
      <td style={celula}>
        <input
          type="checkbox" checked={marcado} disabled={!curso.selecionavel}
          onChange={() => aoMarcar(curso.id)}
          title={
            curso.selecionavel
              ? `Selecionar curso ${curso.nome}`
              : "Curso sem capítulos — coletar geraria extração vazia"
          }
          aria-label={
            curso.selecionavel
              ? `Selecionar curso ${curso.nome}`
              : `Curso ${curso.nome} sem capítulos — coletar geraria extração vazia`
          }
        />
      </td>
      <td style={celula}>
        {curso.nome}
        {curso.descricao && (
          <div style={{ fontSize: 11, color: "#8a897f" }}>{curso.descricao}</div>
        )}
      </td>
      <td style={{ ...celula, whiteSpace: "nowrap" }}>
        {curso.capitulos === 0 ? (
          <span style={{ color: "#b9770e" }}>0 cap · vazio</span>
        ) : (
          `${curso.capitulos} cap · ${curso.aulas} aulas`
        )}
      </td>
      <td style={{ ...celula, whiteSpace: "nowrap" }}>
        {curso.publicado ? "publicado" : <span style={{ color: "#8a897f" }}>rascunho</span>}
      </td>
      <td style={{ ...celula, whiteSpace: "nowrap" }}>{dataLocal(curso.criadoEm)}</td>
    </tr>
  );
}

export function BuscaCursos() {
  const [termo, setTermo] = useState("");
  const [resultado, setResultado] = useState<ResultadoBusca | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [marcados, setMarcados] = useState<Set<string>>(new Set());
  const [buscando, iniciarBusca] = useTransition();

  function buscar() {
    setErro(null);
    iniciarBusca(async () => {
      const r = await buscarCursos(termo);
      setErro(r.erro);
      setResultado(r.resultado);
      setMarcados(new Set());   // resultado novo, seleção antiga não vale mais
    });
  }

  function alternar(id: string) {
    setMarcados((atual) => {
      const novo = new Set(atual);
      if (novo.has(id)) novo.delete(id);
      else if (novo.size < LIMITE_SELECAO) novo.add(id);
      return novo;
    });
  }

  const selecionaveis = (resultado?.cursos ?? []).filter((c) => c.selecionavel);
  const todosMarcados =
    selecionaveis.length > 0 && selecionaveis.every((c) => marcados.has(c.id));

  return (
    <div>
      <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
        <input
          value={termo} onChange={(e) => setTermo(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); buscar(); } }}
          placeholder="Área Fiscal, PRF, BACEN…"
          style={{
            flex: 1, font: "inherit", padding: "8px 11px",
            border: "1px solid #e3e2dd", borderRadius: 8,
          }}
        />
        <button
          type="button" onClick={buscar} disabled={buscando}
          style={{
            font: "inherit", fontWeight: 600, cursor: buscando ? "wait" : "pointer",
            background: "#2a78d6", color: "#fff", border: 0, borderRadius: 8,
            padding: "8px 16px",
          }}
        >
          {buscando ? "Buscando…" : "Buscar"}
        </button>
      </div>

      {erro && <p style={{ color: "#c0392b", fontSize: 13 }}>{erro}</p>}

      {resultado && (
        <>
          <p style={{ fontSize: 12.5, color: "#52514e", margin: "0 0 8px" }}>
            {resultado.encontrados} encontrado(s) · {resultado.comConteudo} com conteúdo
            {resultado.cursos.length < resultado.encontrados &&
              ` · mostrando os ${resultado.cursos.length} mais recentes`}
            {resultado.podeHaverMais && (
              <span style={{ color: "#b9770e" }}>
                {" "}· a busca veio cheia, pode haver mais — refine o termo
              </span>
            )}
          </p>

          {resultado.cursos.length > 0 && (
            <form action={disparar}>
              <input type="hidden" name="modo" value="selecao" />
              {[...marcados].map((id) => (
                <input key={id} type="hidden" name="ids" value={id} />
              ))}

              <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 13 }}>
                <thead>
                  <tr>
                    <th style={{ ...celula, width: 28 }}>
                      <input
                        type="checkbox" checked={todosMarcados}
                        onChange={() =>
                          setMarcados(
                            todosMarcados
                              ? new Set()
                              : new Set(selecionaveis.slice(0, LIMITE_SELECAO).map((c) => c.id))
                          )
                        }
                        title="Marcar/desmarcar todos os que têm conteúdo"
                      />
                    </th>
                    {["Curso", "Peso", "Estado", "Criado"].map((t) => (
                      <th key={t} style={{
                        ...celula, textAlign: "left", color: "#52514e", fontSize: 11,
                        letterSpacing: ".07em", textTransform: "uppercase",
                      }}>{t}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {resultado.cursos.map((c) => (
                    <Linha
                      key={c.id} curso={c} marcado={marcados.has(c.id)} aoMarcar={alternar}
                    />
                  ))}
                </tbody>
              </table>

              <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 12 }}>
                <input
                  name="rotulo" required placeholder="Rótulo do lote (ex.: Área Fiscal 2026)"
                  style={{
                    flex: 1, font: "inherit", padding: "8px 11px",
                    border: "1px solid #e3e2dd", borderRadius: 8,
                  }}
                />
                <button
                  type="submit" disabled={marcados.size === 0}
                  style={{
                    font: "inherit", fontWeight: 600,
                    cursor: marcados.size ? "pointer" : "not-allowed",
                    background: marcados.size ? "#227a3e" : "#e3e2dd",
                    color: marcados.size ? "#fff" : "#8a897f",
                    border: 0, borderRadius: 8, padding: "8px 16px", whiteSpace: "nowrap",
                  }}
                >
                  Coletar {marcados.size || ""} juntos
                </button>
              </div>
              <p style={{ fontSize: 11.5, color: "#8a897f", margin: "6px 0 0" }}>
                Vira <strong>um</strong> pedido e <strong>um</strong> snapshot com o rótulo
                acima. Cursos sem capítulos não podem ser marcados (a coleta nasceria vazia).
              </p>
            </form>
          )}
        </>
      )}
    </div>
  );
}
