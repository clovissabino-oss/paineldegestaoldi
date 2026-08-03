# CLI de exclusão local + compactação — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `exclusao_coleta.py` ganha linha de comando para listar, excluir e compactar extrações do `conteudo.db` local — onde a exclusão pela web não alcança.

**Architecture:** A lógica destrutiva já existe e está testada (entrega 1a). Esta entrega acrescenta `main()` + `argparse`, três funções novas (marcar publicadas, checar banco em uso, compactar) e os testes. Nada de worker, web ou migração.

**Tech Stack:** Python 3.12 (`argparse`, `sqlite3`, `unittest`, `requests`).

**Spec:** `docs/superpowers/specs/2026-08-03-cli-exclusao-local-design.md`

## Global Constraints

- **Idioma pt-BR** em código, comentários, mensagens e docstrings.
- **Suíte atual: 143 testes verdes.** Rodar `py -m unittest discover -s tests` ao fim de cada task; nenhum pode ficar vermelho.
- **O CLI NUNCA escreve no Supabase.** Só lê, e só para marcar "publicada?". A web tem tela própria para apagar snapshot.
- **Não modificar `banco_conteudo.py`, `worker_coleta.py` nem nada em `web/`.** Já verificado que o `VACUUM` roda com a conexão do projeto como está.
- **Nada de `--sim`/`--forcar`/`--agendado`** para exclusão: quem apaga está olhando a tela.
- Datas exibidas em pt-BR; commits em português (`<tipo>: <descrição>`).

## Fatos medidos (03/08) — não re-derivar

| Fato | Valor |
|---|---|
| Pico de disco durante o `VACUUM` | **1,50×** o tamanho do banco (62,1 MB para um de 41,3 MB) |
| Ganho sem `wal_checkpoint` final | **nenhum visível** (41,5 MB depois do VACUUM → 20,7 MB só após o checkpoint) |
| `freelist_count` como métrica | **não serve** — reportou 0 MB com metade dos dados apagados e o VACUUM ainda recuperou 50% |
| `VACUUM` com `isolation_level=''` | funciona, sem mexer em `banco_conteudo.abrir` |
| Base real do notebook | 4 extrações, 231 MB; #1 e #2 são BACEN idênticos (64.838 blocos cada) |

## API que já existe em `exclusao_coleta.py` (não reescrever)

| Função | Assinatura |
|---|---|
| `conferir_extracao` | `(con, extracao_id, termo, iniciada_em) -> Row \| None` — levanta se termo/data divergem |
| `apagar_extracao` | `(con, extracao_id) -> dict[str, int]` — 6 DELETEs numa transação, `extracoes` por último |
| `contar_pendencias` | `(con, extracao_id) -> int` |
| `era_a_mais_recente` | `(con, extracao_id) -> bool` |
| `relatorio` | `(termo, extracao_local, apagadas, pendencias, mais_recente, vacuum=False) -> str` |
| `_falhar` | `(msg) -> SystemExit` — a exceção **carrega** o texto |
| `TABELAS` | ordem dos DELETEs |

---

### Task 1: Listar extrações, marcando quais estão publicadas

**Files:**
- Modify: `exclusao_coleta.py`
- Modify: `tests/test_exclusao_coleta.py`

**Interfaces:**
- Consumes: `sync_supabase.esta_configurado()`, `sync_supabase._config()`, `sync_supabase._headers(key)`.
- Produces:
  - `_TAM_DATA` já existe no módulo (=19, com underscore) — **reusar, não redeclarar**
  - `publicadas_no_supabase() -> set[tuple[str, str]] | None` — `{(termo, data[:19])}`; **None** quando não deu para consultar
  - `listar_extracoes(con, publicadas) -> list[dict]` — chaves: `id`, `termo`, `iniciada_em`, `status`, `cursos`, `blocos`, `publicada`

- [ ] **Step 1: Escrever os testes que falham**

Acrescentar a `tests/test_exclusao_coleta.py` (dentro de `TestApagarExtracao`, que já tem `_nova` e `self.con`):

```python
    def test_listar_marca_publicada_e_aceita_desconhecido(self):
        """A coluna 'publicada?' é o que evita apagar a origem de uma coleta que a
        web ainda usa. Sem rede (publicadas=None) a listagem NÃO pode quebrar —
        listar é leitura e tem de funcionar offline."""
        eid1 = self._nova()
        eid2 = self._nova("PRF")
        data1 = self._data(eid1)
        linhas = exclusao_coleta.listar_extracoes(
            self.con, {("BACEN", data1[:19])})
        por_id = {l["id"]: l for l in linhas}
        self.assertIs(por_id[eid1]["publicada"], True)
        self.assertIs(por_id[eid2]["publicada"], False)
        self.assertEqual(por_id[eid1]["termo"], "BACEN")
        self.assertGreater(por_id[eid1]["blocos"], 0)
        # sem informação do Supabase: publicada = None (a tela mostra "?")
        linhas = exclusao_coleta.listar_extracoes(self.con, None)
        self.assertTrue(all(l["publicada"] is None for l in linhas))

```

E, fora da classe, uma classe nova:

```python
class TestPublicadasNoSupabase(unittest.TestCase):
    @patch("exclusao_coleta.sync_supabase.esta_configurado", return_value=False)
    def test_sem_credencial_devolve_none(self, _):
        self.assertIsNone(exclusao_coleta.publicadas_no_supabase())

    @patch("exclusao_coleta.requests.get", side_effect=Exception("rede fora"))
    @patch("exclusao_coleta.sync_supabase._config", return_value=("http://x", "k"))
    @patch("exclusao_coleta.sync_supabase.esta_configurado", return_value=True)
    def test_rede_fora_devolve_none_sem_levantar(self, *_):
        """Listar é leitura: rede fora vira '?' na coluna, nunca um traceback."""
        self.assertIsNone(exclusao_coleta.publicadas_no_supabase())

    @patch("exclusao_coleta.sync_supabase._config", return_value=("http://x", "k"))
    @patch("exclusao_coleta.sync_supabase.esta_configurado", return_value=True)
    @patch("exclusao_coleta.requests.get")
    def test_normaliza_a_data_para_19_caracteres(self, mock_get, *_):
        mock_get.return_value = MagicMock(
            raise_for_status=lambda: None,
            json=lambda: [{"termo": "BACEN", "iniciada_em": "2026-07-06T23:56:22+00:00"},
                          {"termo": "PRF", "iniciada_em": None}])
        pub = exclusao_coleta.publicadas_no_supabase()
        self.assertIn(("BACEN", "2026-07-06T23:56:22"), pub)
        self.assertEqual(len(pub), 1)   # linha sem data é descartada
```

Acrescentar `MagicMock` ao import de `unittest.mock` no topo do arquivo.

- [ ] **Step 2: Rodar e ver falhar**

Run: `py -m unittest tests.test_exclusao_coleta -v`
Expected: FAIL — `module 'exclusao_coleta' has no attribute 'listar_extracoes'`

- [ ] **Step 3: Implementar**

No topo de `exclusao_coleta.py`, acrescentar aos imports:

```python
import requests

import sync_supabase
```

E as funções (antes de `relatorio`):

```python
def publicadas_no_supabase():
    """Devolve {(termo, iniciada_em[:19])} das coletas publicadas na web.

    None quando não deu para consultar (sem credencial, sem rede, erro) — o
    chamador mostra "?" na coluna. LISTAR É LEITURA: nunca pode levantar, senão
    um blip de rede impede o Clovis de ver o que tem na própria máquina."""
    if not sync_supabase.esta_configurado():
        return None
    try:
        url, key = sync_supabase._config()
        r = requests.get(f"{url}/rest/v1/snapshot",
                         headers=sync_supabase._headers(key),
                         params={"select": "termo,iniciada_em"}, timeout=30)
        r.raise_for_status()
        return {(x["termo"], (x["iniciada_em"] or "")[:_TAM_DATA])
                for x in r.json() if x.get("iniciada_em")}
    except Exception as e:
        print(f"[aviso] não consegui consultar o Supabase ({e}); "
              "a coluna 'publicada?' fica como '?'.")
        return None


def listar_extracoes(con, publicadas):
    """Uma linha por extração do banco local, com o peso e se está publicada.

    `publicadas` = saída de publicadas_no_supabase() (None = desconhecido).
    A comparação usa os 19 primeiros caracteres da data: o SQLite grava naive
    ('2026-07-06T23:56:22') e o Supabase devolve timestamptz ('...+00:00')."""
    linhas = []
    for r in con.execute(
            "SELECT e.id, e.termo, e.iniciada_em, e.status, e.total_cursos, "
            "       (SELECT COUNT(*) FROM blocos b WHERE b.extracao_id = e.id) blocos "
            "FROM extracoes e ORDER BY e.id"):
        chave = (r["termo"], (r["iniciada_em"] or "")[:_TAM_DATA])
        linhas.append({
            "id": r["id"], "termo": r["termo"],
            "iniciada_em": (r["iniciada_em"] or "")[:16].replace("T", " "),
            "status": r["status"], "cursos": r["total_cursos"] or 0,
            "blocos": r["blocos"] or 0,
            "publicada": None if publicadas is None else (chave in publicadas),
        })
    return linhas
```

- [ ] **Step 4: Rodar e ver passar**

Run: `py -m unittest tests.test_exclusao_coleta -v`
Expected: PASS

- [ ] **Step 5: Suíte inteira**

Run: `py -m unittest discover -s tests`
Expected: OK (143 + novos)

- [ ] **Step 6: Commit**

```bash
git add exclusao_coleta.py tests/test_exclusao_coleta.py
git commit -m "feat: lista extracoes locais marcando as publicadas na web"
```

---

### Task 2: Banco em uso e compactação

**Files:**
- Modify: `exclusao_coleta.py`
- Modify: `tests/test_exclusao_coleta.py`

**Interfaces:**
- Consumes: `listar_extracoes` (Task 1).
- Produces:
  - `FOLGA_VACUUM = 1.5`
  - `banco_em_uso(con) -> bool`
  - `espaco_para_vacuum(caminho) -> tuple[bool, int, int]` — `(cabe, precisa_bytes, livre_bytes)`
  - `compactar(con, caminho) -> tuple[int, int]` — `(bytes_antes, bytes_depois)`

- [ ] **Step 1: Escrever os testes que falham**

Acrescentar a `tests/test_exclusao_coleta.py` uma classe nova:

```python
class TestCompactar(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.caminho = os.path.join(self.dir.name, "x", "conteudo.db")
        self.con = banco_conteudo.abrir(self.caminho)

    def tearDown(self):
        self.con.close()
        self.dir.cleanup()

    def _encher(self, n=40000):
        eid = banco_conteudo.iniciar_extracao(self.con, "BACEN", "concursos")
        with self.con:
            self.con.executemany(
                "INSERT INTO blocos(extracao_id,item_id,bloco_id,tipo,titulo,meta) "
                "VALUES(?,?,?,?,?,?)",
                [(eid, f"i{i}", f"b{i}", "question", "t" * 60, "{}" + "z" * 120)
                 for i in range(n)])
        self.con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return eid

    def _tamanho(self):
        return sum(os.path.getsize(self.caminho + s)
                   for s in ("", "-wal", "-shm")
                   if os.path.exists(self.caminho + s))

    def test_vacuum_encolhe_o_arquivo_de_verdade(self):
        """O teste que prova a entrega. Sem ele, 'compactado' é só uma mensagem.
        Inclui o checkpoint DEPOIS do VACUUM — sem ele o ganho não aparece
        (medido: 41,5 MB logo após o VACUUM, 20,7 MB só depois do checkpoint)."""
        eid = self._encher()
        exclusao_coleta.apagar_extracao(self.con, eid)
        antes, depois = exclusao_coleta.compactar(self.con, self.caminho)
        self.assertLess(depois, antes)
        self.assertLess(self._tamanho(), antes * 0.6)

    def test_sem_compactar_o_arquivo_nao_encolhe(self):
        """Discrimina o teste acima: só apagar não devolve disco. Se este falhar
        (arquivo encolheu sozinho), o teste de cima não prova nada."""
        eid = self._encher()
        antes = self._tamanho()
        exclusao_coleta.apagar_extracao(self.con, eid)
        self.con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.assertGreater(self._tamanho(), antes * 0.9)

    def test_espaco_insuficiente_recusa(self):
        self._encher(2000)
        with patch("exclusao_coleta.shutil.disk_usage") as mock_du:
            mock_du.return_value = (100, 99, 1)   # 1 byte livre
            cabe, precisa, livre = exclusao_coleta.espaco_para_vacuum(self.caminho)
        self.assertFalse(cabe)
        self.assertEqual(livre, 1)
        self.assertGreater(precisa, 0)

    def test_espaco_exige_folga_de_uma_vez_e_meia(self):
        """1,0x NÃO basta: medido, o pico real é 1,50x (o WAL cresce até o
        tamanho dos dados vivos enquanto o VACUUM roda)."""
        self._encher(2000)
        tam = os.path.getsize(self.caminho)
        with patch("exclusao_coleta.shutil.disk_usage") as mock_du:
            mock_du.return_value = (0, 0, int(tam * 1.1))
            cabe, _, _ = exclusao_coleta.espaco_para_vacuum(self.caminho)
        self.assertFalse(cabe)
        with patch("exclusao_coleta.shutil.disk_usage") as mock_du:
            mock_du.return_value = (0, 0, int(tam * 2))
            cabe, _, _ = exclusao_coleta.espaco_para_vacuum(self.caminho)
        self.assertTrue(cabe)

    def test_banco_em_uso_detecta_escrita_de_outra_conexao(self):
        """O painel.py aberto ou uma coleta rodando seguram o arquivo. Detectar
        ANTES evita o erro no meio da transação — que reverteria, mas depois de
        o usuário achar que já tinha apagado."""
        self.assertFalse(exclusao_coleta.banco_em_uso(self.con))
        outra = sqlite3.connect(self.caminho)
        try:
            outra.execute("BEGIN EXCLUSIVE")
            self.assertTrue(exclusao_coleta.banco_em_uso(self.con))
        finally:
            outra.rollback()
            outra.close()
        self.assertFalse(exclusao_coleta.banco_em_uso(self.con))
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `py -m unittest tests.test_exclusao_coleta.TestCompactar -v`
Expected: FAIL — `has no attribute 'compactar'`

- [ ] **Step 3: Implementar**

Acrescentar `import os` e `import shutil` ao topo (se `os` já não estiver), e as funções:

```python
# Pico de disco do VACUUM, MEDIDO em 03/08: 62,1 MB para um banco de 41,3 MB.
# Em WAL o VACUUM escreve o resultado no WAL antes de consolidar, então o pico é
# maior que o arquivo final — 1,0x NÃO basta.
FOLGA_VACUUM = 1.5


# Espera curta só para a CHECAGEM de lock. Com o busy_timeout padrão (5s), o
# BEGIN IMMEDIATE fica 5,5s parado antes de admitir que o banco está ocupado
# (medido) — o CLI pareceria travado. 300ms basta para distinguir "ocupado" de
# "livre" e é restaurado logo em seguida.
_ESPERA_CHECAGEM_MS = 300


def banco_em_uso(con):
    """True se outro processo segura o banco (painel aberto, coleta rodando).

    Testa com BEGIN IMMEDIATE e desfaz na hora — é o mesmo lock que o DELETE
    pegaria, mas checado ANTES, quando ainda não há nada a reverter."""
    anterior = con.execute("PRAGMA busy_timeout").fetchone()[0]
    con.execute(f"PRAGMA busy_timeout={_ESPERA_CHECAGEM_MS}")
    try:
        con.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError:
        return True
    else:
        con.rollback()
        return False
    finally:
        con.execute(f"PRAGMA busy_timeout={anterior}")


def espaco_para_vacuum(caminho):
    """(cabe, precisa_bytes, livre_bytes) para compactar `caminho`.

    Checar ANTES de apagar: faltando espaço, falha limpa e retentável é mais
    previsível que 'apagou mas não compactou'."""
    tamanho = os.path.getsize(caminho) if os.path.exists(caminho) else 0
    precisa = int(tamanho * FOLGA_VACUUM)
    livre = shutil.disk_usage(os.path.dirname(os.path.abspath(caminho))).free
    return livre >= precisa, precisa, livre


def compactar(con, caminho):
    """Roda VACUUM e devolve (bytes_antes, bytes_depois) do arquivo principal.

    O checkpoint DEPOIS não é opcional: medido, o conjunto ainda ocupava
    41,5 MB logo após o VACUUM e só caiu para 20,7 MB depois dele — sem esse
    passo o comando diz "compactado" e o `ls` mostra o mesmo tamanho.

    Não promete ganho antes de rodar: `freelist_count` reportou 0 MB num banco
    com metade dos dados apagados que o VACUUM ainda reduziu à metade."""
    antes = os.path.getsize(caminho)
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.execute("VACUUM")            # fora de transação (isolation_level='' do projeto)
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return antes, os.path.getsize(caminho)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `py -m unittest tests.test_exclusao_coleta.TestCompactar -v`
Expected: PASS

- [ ] **Step 5: Provar que o teste de compactação discrimina**

Comente o `con.execute("VACUUM")` e confirme que
`test_vacuum_encolhe_o_arquivo_de_verdade` **falha**. Depois desfaça.
Se passar sem o VACUUM, o teste não prova nada — corrija antes de seguir.

- [ ] **Step 6: Suíte inteira**

Run: `py -m unittest discover -s tests`
Expected: OK

- [ ] **Step 7: Commit**

```bash
git add exclusao_coleta.py tests/test_exclusao_coleta.py
git commit -m "feat: compacta o banco com checagem de espaco e de uso"
```

---

### Task 3: A linha de comando

**Files:**
- Modify: `exclusao_coleta.py`

**Interfaces:**
- Consumes: tudo das Tasks 1 e 2, mais `conferir_extracao`, `apagar_extracao`, `contar_pendencias`, `era_a_mais_recente`, `relatorio` (já existentes).
- Produces: `main()` + bloco `if __name__ == "__main__":`.

- [ ] **Step 1: Implementar**

No topo, acrescentar `import argparse` e `import sys`. Ao fim do arquivo:

```python
def _caminho_banco():
    """Mesmo caminho que o coletor e o painel usam (respeita o config.json)."""
    import extrator_ldi as _e
    cfg = _e.carregar_config()
    return os.path.join(_e.PASTA_APP, cfg["pasta_saida"], "conteudo.db")


def _imprimir_listagem(linhas):
    if not linhas:
        print("  (nenhuma extração no banco)")
        return
    print(f"  {'#':>3}  {'termo':28}  {'quando':16}  {'cursos':>6}  {'blocos':>7}  publicada?")
    for l in linhas:
        pub = {True: "sim", False: "não", None: "?"}[l["publicada"]]
        print(f"  {l['id']:>3}  {l['termo'][:28]:28}  {l['iniciada_em']:16}  "
              f"{l['cursos']:>6}  {l['blocos']:>7}  {pub}")
    print("\n  'publicada?' = a coleta está no Supabase (o time vê na web).")
    print("  Apagar aqui NÃO tira nada do ar — a web tem tela própria para isso.")


def main():
    parser = argparse.ArgumentParser(
        description="Exclusão e compactação do conteudo.db LOCAL. "
                    "Não toca no Supabase — a web tem tela própria para isso.")
    parser.add_argument("--listar", action="store_true",
                        help="mostra as extrações do banco e quais estão publicadas")
    parser.add_argument("--excluir", type=int, metavar="N",
                        help="apaga a extração N (pede o termo por confirmação)")
    parser.add_argument("--compactar", action="store_true",
                        help="roda VACUUM e devolve o espaço ao disco")
    args = parser.parse_args()

    if not (args.listar or args.excluir or args.compactar):
        parser.print_help()
        return

    caminho = _caminho_banco()
    con = banco_conteudo.abrir(caminho)
    try:
        print("=" * 66)
        print(f" EXCLUSÃO LOCAL  |  banco: {caminho}")
        print("=" * 66)

        if args.listar or args.excluir:
            linhas = listar_extracoes(con, publicadas_no_supabase())

        if args.listar:
            _imprimir_listagem(linhas)
            if not args.excluir and not args.compactar:
                return

        if args.excluir:
            alvo = next((l for l in linhas if l["id"] == args.excluir), None)
            if alvo is None:
                raise _falhar(f"não existe extração #{args.excluir} neste banco.")
            if not args.listar:
                _imprimir_listagem([alvo])
            if banco_em_uso(con):
                raise _falhar("o banco está em uso por outro processo "
                              "(painel.py aberto? coleta rodando?). Feche e tente de novo.")
            if args.compactar:
                cabe, precisa, livre = espaco_para_vacuum(caminho)
                if not cabe:
                    raise _falhar(
                        f"espaço insuficiente para compactar: precisa de "
                        f"{precisa/1048576:.0f} MB livres, há {livre/1048576:.0f} MB. "
                        "Nada foi apagado.")
            print(f"\n  Isto apaga a extração #{alvo['id']} ({alvo['blocos']} blocos) "
                  "do banco local. NÃO tem volta.")
            if alvo["publicada"]:
                print("  ⚠ Esta coleta está publicada na web — o snapshot continua lá, "
                      "mas some a origem local (recoleta/diff futuros).")
            digitado = input(f"  Digite {alvo['termo']} para confirmar: ").strip()
            if digitado != alvo["termo"]:
                raise _falhar("o termo digitado não confere. Nada foi apagado.")

            # `conferir_extracao` não é chamada aqui de propósito: ela existe para
            # o worker, que recebe termo e data de FORA (do pedido na fila) e
            # precisa provar que batem com o banco. No CLI o alvo veio da listagem
            # do próprio banco — conferi-lo contra ele mesmo seria tautológico.
            # A proteção que vale aqui é a confirmação digitada, acima.
            pend = contar_pendencias(con, alvo["id"])
            recente = era_a_mais_recente(con, alvo["id"])
            apagadas = apagar_extracao(con, alvo["id"])
            print("\n  " + relatorio(alvo["termo"], alvo["id"], apagadas, pend, recente))

        if args.compactar:
            if banco_em_uso(con):
                raise _falhar("o banco está em uso por outro processo. "
                              "Feche o painel/coleta e tente de novo.")
            cabe, precisa, livre = espaco_para_vacuum(caminho)
            if not cabe:
                raise _falhar(f"espaço insuficiente: precisa de {precisa/1048576:.0f} MB "
                              f"livres, há {livre/1048576:.0f} MB.")
            print("\n  Compactando (o banco fica travado durante a operação)...")
            antes, depois = compactar(con, caminho)
            print(f"  {antes/1048576:.1f} MB → {depois/1048576:.1f} MB "
                  f"(devolvidos {(antes-depois)/1048576:.1f} MB)")
    finally:
        con.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Conferir que a suíte não quebrou**

Run: `py -m unittest discover -s tests`
Expected: OK

- [ ] **Step 3: Provar o CLI num banco de brinquedo (NÃO na base real)**

```bash
py -c "
import banco_conteudo, os, tempfile
d = tempfile.mkdtemp(); p = os.path.join(d, 'conteudo.db')
con = banco_conteudo.abrir(p)
eid = banco_conteudo.iniciar_extracao(con, 'TESTE', 'concursos')
con.close(); print(p)
"
```

Rode `--listar` contra esse caminho (ajustando `_caminho_banco` temporariamente OU
apontando o `config.json` de um diretório de teste) e confirme:
- a tabela sai alinhada, com a coluna `publicada?`;
- a nota "Apagar aqui NÃO tira nada do ar" aparece;
- `--excluir 99` (inexistente) devolve mensagem clara e código ≠ 0.

Desfaça qualquer ajuste temporário antes de commitar.

- [ ] **Step 4: `--help` legível**

Run: `py exclusao_coleta.py`
Expected: imprime a ajuda (sem argumentos não faz nada destrutivo)

Run: `py exclusao_coleta.py --listar`
Expected: lista as 4 extrações reais, com #2 e #3 marcadas `sim` na coluna publicada

- [ ] **Step 5: Commit**

```bash
git add exclusao_coleta.py
git commit -m "feat: linha de comando para listar, excluir e compactar"
```

---

## Verificação final (exige o Clovis, na base real)

1. `py -m unittest discover -s tests` — verde.
2. `py exclusao_coleta.py --listar` — 4 extrações; **#2 e #3 marcadas `sim`**, #1 e #5 `não`.
3. **Fechar o painel/visualizador se estiverem abertos** (a trava vai recusar, e é para recusar).
4. `py exclusao_coleta.py --excluir 1 --compactar`, digitando `BACEN`.
   - **#1 é a escolha certa:** é a duplicata mais antiga e **não está publicada**.
   - Conferir com `ls` / Explorer que o arquivo encolheu de fato (231 MB → ~100 MB esperado).
5. `py painel.py` — PRF, Coromandel e o BACEN #2 íntegros.
6. Conferir na web que **nada mudou** — é o ponto do "não toca no Supabase".

**Deploy:** nenhum. Sem worker, sem web, sem migração.
