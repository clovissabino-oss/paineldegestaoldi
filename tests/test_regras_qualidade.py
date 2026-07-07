# -*- coding: utf-8 -*-
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import banco_conteudo
import regras_qualidade
from tests.test_banco_conteudo import CURSOS, B1

B_Q_SEM_SOL = dict(B1, bloco_id="bq", questao_id="222", tem_solucao=0, ano=2015)
B_TXT_CURTO = {"bloco_id": "bt", "tipo": "tiptap", "ordem": 2, "ativo": 1, "rascunho": 0,
               "titulo": "", "questao_id": "", "resposta_tipo": "", "tem_solucao": None,
               "tem_video_solucao": None, "video_id_antigo": "", "duracao_seg": None,
               "tamanho_texto": 200, "qtd_questoes_texto": 0, "banca": "", "ano": None, "meta": {}}
B_VIDEO_VELHO = {"bloco_id": "bv", "tipo": "videoMyDocuments", "ordem": 3, "ativo": 1,
                 "rascunho": 0, "titulo": "v", "questao_id": "", "resposta_tipo": "",
                 "tem_solucao": None, "tem_video_solucao": None, "video_id_antigo": "999",
                 "duracao_seg": 60, "tamanho_texto": None, "qtd_questoes_texto": None,
                 "banca": "", "ano": None, "meta": {}}
DEPARA = {"999": {"data": "2018-05-01"}}


def montar(con, com_solucao=False):
    eid = banco_conteudo.iniciar_extracao(con, "T", "concursos")
    banco_conteudo.gravar_arvore(con, eid, CURSOS)
    blocos = [B_TXT_CURTO, B_VIDEO_VELHO] + ([dict(B_Q_SEM_SOL, tem_solucao=1)] if com_solucao
                                             else [B_Q_SEM_SOL])
    banco_conteudo.gravar_blocos_da_aula(con, eid, "i1", blocos)
    banco_conteudo.gravar_blocos_da_aula(con, eid, "i2", [])
    banco_conteudo.finalizar_extracao(con, eid, {})
    return eid


class TestRegras(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.con = banco_conteudo.abrir(os.path.join(self.dir.name, "c.db"))

    def tearDown(self):
        self.con.close()
        self.dir.cleanup()

    def test_avaliar_materializa_pendencias(self):
        eid = montar(self.con)
        r = regras_qualidade.avaliar(self.con, eid, depara=DEPARA)
        self.assertGreater(r["novas"], 0)
        regras = {row[0] for row in self.con.execute("SELECT DISTINCT regra FROM pendencias")}
        # Q1 (sem solução), Q2 (2015 = crítica pela régua), V1 (gravado 2018),
        # A1 (i2 sem questão), A3 (texto curto). C1 não: todos os cursos têm aula.
        self.assertTrue({"Q1", "Q2", "V1", "A1", "A3"} <= regras)
        self.assertNotIn("C1", regras)
        st = self.con.execute("SELECT COUNT(*) FROM pendencias WHERE status='nova'").fetchone()[0]
        self.assertEqual(st, r["novas"])

    def test_baixa_automatica_e_persistencia_de_status(self):
        montar(self.con)
        regras_qualidade.avaliar(self.con, 1, depara=DEPARA)
        chave_q1 = self.con.execute(
            "SELECT chave FROM pendencias WHERE regra='Q1' LIMIT 1").fetchone()[0]
        with self.con:
            self.con.execute("UPDATE pendencias SET status='enviada' WHERE chave=?", (chave_q1,))
        # snapshot novo: questão agora COM solução -> Q1 é baixada; V1 persiste
        eid2 = montar(self.con, com_solucao=True)
        r2 = regras_qualidade.avaliar(self.con, eid2, depara=DEPARA)
        row = self.con.execute("SELECT status, resolvida_em FROM pendencias WHERE chave=?",
                               (chave_q1,)).fetchone()
        self.assertEqual(row["status"], "resolvida")
        self.assertTrue(row["resolvida_em"])
        self.assertGreaterEqual(r2["resolvidas"], 1)
        v1 = self.con.execute("SELECT status, extracao_id_ultima FROM pendencias "
                              "WHERE regra='V1' LIMIT 1").fetchone()
        self.assertEqual((v1["status"], v1["extracao_id_ultima"]), ("nova", eid2))

    def test_ignorada_nao_reabre(self):
        montar(self.con)
        regras_qualidade.avaliar(self.con, 1, depara=DEPARA)
        with self.con:
            self.con.execute("UPDATE pendencias SET status='ignorada' WHERE regra='A3'")
        eid2 = montar(self.con)
        regras_qualidade.avaliar(self.con, eid2, depara=DEPARA)
        st = {r[0] for r in self.con.execute("SELECT status FROM pendencias WHERE regra='A3'")}
        self.assertEqual(st, {"ignorada"})

    def test_resolvida_que_volta_reabre_como_nova(self):
        montar(self.con)
        regras_qualidade.avaliar(self.con, 1, depara=DEPARA)
        eid2 = montar(self.con, com_solucao=True)   # Q1 some -> resolvida
        regras_qualidade.avaliar(self.con, eid2, depara=DEPARA)
        eid3 = montar(self.con)                     # Q1 volta -> reabre
        r3 = regras_qualidade.avaliar(self.con, eid3, depara=DEPARA)
        self.assertGreaterEqual(r3["reabertas"], 1)
        row = self.con.execute("SELECT status FROM pendencias WHERE regra='Q1' LIMIT 1").fetchone()
        self.assertEqual(row["status"], "nova")

    def test_sem_depara_pula_v1_sem_estourar(self):
        eid = montar(self.con)
        r = regras_qualidade.avaliar(self.con, eid, depara=None)
        self.assertNotIn("V1", r["abertas_por_regra"])


if __name__ == "__main__":
    unittest.main()
