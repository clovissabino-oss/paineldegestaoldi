# -*- coding: utf-8 -*-
"""Colunas de Material Base em extracoes + migração idempotente."""
import os
import sqlite3
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

    def test_linha_gravada_antes_da_migracao_recebe_tipo_curso(self):
        """Discrimina de verdade a migração: cria o banco no schema ANTIGO (sem as
        colunas de Material Base) com sqlite3 puro, grava uma linha ANTES de a coluna
        'tipo' existir, e só então passa pelo banco_conteudo.abrir(). A linha antiga
        tem que sobreviver com tipo='curso', não NULL."""
        caminho_antigo = os.path.join(self.dir, "antigo.db")
        con_bruta = sqlite3.connect(caminho_antigo)
        con_bruta.execute(
            "CREATE TABLE extracoes("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  termo TEXT NOT NULL, vertical TEXT NOT NULL,"
            "  iniciada_em TEXT NOT NULL, concluida_em TEXT,"
            "  status TEXT NOT NULL DEFAULT 'em_andamento',"
            "  total_cursos INTEGER DEFAULT 0, total_aulas INTEGER DEFAULT 0,"
            "  total_blocos INTEGER DEFAULT 0, erros_json TEXT DEFAULT '{}')")
        con_bruta.execute(
            "INSERT INTO extracoes(termo, vertical, iniciada_em) VALUES(?,?,?)",
            ("PreHistorico", "concursos", "2020-01-01T00:00:00"))
        con_bruta.commit()
        con_bruta.close()

        con_migrada = banco_conteudo.abrir(caminho_antigo)
        try:
            r = con_migrada.execute(
                "SELECT termo, tipo FROM extracoes WHERE termo=?",
                ("PreHistorico",)).fetchone()
            self.assertIsNotNone(r, "a linha gravada antes da migração sumiu")
            self.assertEqual(r["termo"], "PreHistorico")
            self.assertEqual(r["tipo"], "curso")
        finally:
            con_migrada.close()


if __name__ == "__main__":
    unittest.main()
