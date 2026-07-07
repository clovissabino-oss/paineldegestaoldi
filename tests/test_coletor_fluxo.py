# -*- coding: utf-8 -*-
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import banco_conteudo
import coletor_ldi

CURSOS = [{
    "id": "c1", "name": "Curso A", "published": True,
    "content_tree_cache": [{
        "chapter_id": "cap1", "name": "Cap 1", "order_index": 0,
        "items": [
            {"item_id": "i1", "name": "Aula 1", "path": "1",
             "block_type_count": {"question": 1}},
            {"item_id": "i2", "name": "Aula 2", "path": "2",
             "block_type_count": {"tiptap": 1}},
        ],
    }],
}]

BLOCOS = {
    "i1": [{"id": "b1", "type": "question", "order_index": 1, "is_active": True,
            "data": {"value": "9", "resolved": {"id": "9", "answer_type": "MULTI",
                                                "solution": {"brief": "x"}}}}],
    "i2": [{"id": "b2", "type": "tiptap", "order_index": 1, "is_active": True,
            "content_length": 50, "data": {}}],
}


class RespostaFake:
    def __init__(self, status, dados=None):
        self.status_code, self._dados, self.ok = status, dados, status < 400
        self.text = ""

    def json(self):
        return {"data": self._dados}


class SessaoFake:
    """GET de /bo/ldi/blocks?item_id=X devolve BLOCOS[X]; falhas injetáveis."""
    def __init__(self, falhas=(), status_falha=404):
        self.falhas, self.status_falha = set(falhas), status_falha

    def get(self, url, timeout=0):
        if "/bo/ldi/courses/" in url:  # detalhe do curso (autores)
            cid = url.rsplit("/", 1)[1]
            if cid == "c1":
                return RespostaFake(200, {"id": cid, "structured_authors":
                                          [{"full_name": "Prof Teste"}]})
            return RespostaFake(404)
        item = url.split("item_id=")[1]
        if item in self.falhas:
            return RespostaFake(self.status_falha)
        return RespostaFake(200, BLOCOS.get(item, []))


CFG = {"vertical": "concursos", "filtro_local": "", "concorrencia": 2}


class TestColetar(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.dir.name, "conteudo.db")
        self._listar = coletor_ldi.extrator_ldi.listar_cursos
        coletor_ldi.extrator_ldi.listar_cursos = lambda s, t: CURSOS

    def tearDown(self):
        coletor_ldi.extrator_ldi.listar_cursos = self._listar
        self.dir.cleanup()

    def test_coleta_completa(self):
        eid = coletor_ldi.coletar(CFG, SessaoFake(), "BACEN", self.db)
        con = banco_conteudo.abrir(self.db)
        row = con.execute("SELECT status, total_blocos FROM extracoes WHERE id=?", (eid,)).fetchone()
        self.assertEqual((row[0], row[1]), ("completa", 2))
        con.close()

    def test_falha_de_aula_vira_parcial_e_continuar_completa(self):
        eid = coletor_ldi.coletar(CFG, SessaoFake(falhas={"i2"}), "BACEN", self.db)
        con = banco_conteudo.abrir(self.db)
        row = con.execute("SELECT status, erros_json FROM extracoes WHERE id=?", (eid,)).fetchone()
        self.assertEqual(row[0], "parcial")
        self.assertIn("i2", json.loads(row[1]))
        con.close()
        # --continuar retoma a coleta PARCIAL sem criar snapshot novo
        eid2 = coletor_ldi.coletar(CFG, SessaoFake(), "BACEN", self.db, continuar=True)
        self.assertEqual(eid2, eid)
        con = banco_conteudo.abrir(self.db)
        row = con.execute("SELECT status, total_blocos FROM extracoes WHERE id=?", (eid,)).fetchone()
        self.assertEqual((row[0], row[1]), ("completa", 2))
        con.close()

    def test_401_aborta_com_cookie_vencido(self):
        with self.assertRaises(coletor_ldi.CookieVencido):
            coletor_ldi.coletar(CFG, SessaoFake(falhas={"i1", "i2"}, status_falha=401),
                                "BACEN", self.db)

    def test_continuar_sem_coleta_aberta_falha_claro(self):
        with self.assertRaises(SystemExit):
            coletor_ldi.coletar(CFG, SessaoFake(), "BACEN", self.db, continuar=True)

    def test_coleta_preenche_autores_do_detalhe(self):
        eid = coletor_ldi.coletar(CFG, SessaoFake(), "BACEN", self.db)
        con = banco_conteudo.abrir(self.db)
        row = con.execute("SELECT autores FROM cursos WHERE extracao_id=? AND curso_id='c1'",
                          (eid,)).fetchone()
        self.assertEqual(row["autores"], "Prof Teste")
        con.close()

    def test_com_videos_emite_arquivo_classico(self):
        cfg = dict(CFG, pasta_saida=self.dir.name, incluir_url=False)
        coletor_ldi.coletar(cfg, SessaoFake(), "BACEN", self.db, com_videos=True)
        import glob
        arquivos = glob.glob(os.path.join(self.dir.name, "videos_BACEN_*.json"))
        self.assertEqual(len(arquivos), 1)
        with open(arquivos[0], encoding="utf-8") as f:
            linhas = json.load(f)
        # i1 e i2 não têm vídeo -> viram linhas "aula sem bloco de video"
        self.assertEqual(len(linhas), 2)
        self.assertTrue(all("curso_nome" in l and "video_id_antigo" in l for l in linhas))


if __name__ == "__main__":
    unittest.main()
