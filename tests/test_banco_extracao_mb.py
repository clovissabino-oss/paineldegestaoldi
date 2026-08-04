# -*- coding: utf-8 -*-
"""Colunas de Material Base em extracoes + migração idempotente."""
import os
import tempfile
import unittest

import banco_conteudo

_COLS_MB = ("tipo", "professor_id", "professor_nome", "disciplina",
            "classificacao_id", "capitulos_ocultos")


class TestExtracaoMB(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.caminho = os.path.join(self.dir, "t.db")
        self.con = banco_conteudo.abrir(self.caminho)

    def tearDown(self):
        self.con.close()

    def _cols(self):
        return {r[1] for r in self.con.execute("PRAGMA table_info(extracoes)")}

    def test_colunas_novas_existem(self):
        self.assertTrue(set(_COLS_MB) <= self._cols())

    def test_extracao_de_curso_continua_com_a_assinatura_antiga(self):
        eid = banco_conteudo.iniciar_extracao(self.con, "BACEN", "concursos")
        r = self.con.execute("SELECT tipo, termo FROM extracoes WHERE id=?", (eid,)).fetchone()
        self.assertEqual(r["tipo"], "curso")
        self.assertEqual(r["termo"], "BACEN")

    def test_extracao_de_mb_grava_os_metadados(self):
        eid = banco_conteudo.iniciar_extracao(
            self.con, "MB · Profa Fulana · Direito Constitucional", "concursos",
            tipo="mb", professor_id="prof-1", professor_nome="Profa Fulana",
            disciplina="Direito Constitucional", classificacao_id="cls-1",
            capitulos_ocultos=111)
        r = self.con.execute("SELECT * FROM extracoes WHERE id=?", (eid,)).fetchone()
        self.assertEqual(r["tipo"], "mb")
        self.assertEqual(r["professor_id"], "prof-1")
        self.assertEqual(r["professor_nome"], "Profa Fulana")
        self.assertEqual(r["disciplina"], "Direito Constitucional")
        self.assertEqual(r["classificacao_id"], "cls-1")
        self.assertEqual(r["capitulos_ocultos"], 111)

    def test_migracao_e_idempotente(self):
        """Abrir de novo o mesmo banco não pode estourar nem perder dado."""
        eid = banco_conteudo.iniciar_extracao(self.con, "PRF", "concursos")
        self.con.close()
        con2 = banco_conteudo.abrir(self.caminho)
        try:
            self.assertTrue(set(_COLS_MB) <= {r[1] for r in con2.execute(
                "PRAGMA table_info(extracoes)")})
            self.assertEqual(con2.execute(
                "SELECT termo FROM extracoes WHERE id=?", (eid,)).fetchone()[0], "PRF")
        finally:
            con2.close()
            self.con = banco_conteudo.abrir(self.caminho)

    def test_linha_antiga_sem_tipo_vale_como_curso(self):
        """Snapshot pré-migração: o default preenche 'curso' — nada de NULL solto."""
        eid = banco_conteudo.iniciar_extracao(self.con, "Antigo", "concursos")
        tipo = self.con.execute(
            "SELECT COALESCE(tipo,'curso') FROM extracoes WHERE id=?", (eid,)).fetchone()[0]
        self.assertEqual(tipo, "curso")


if __name__ == "__main__":
    unittest.main()
