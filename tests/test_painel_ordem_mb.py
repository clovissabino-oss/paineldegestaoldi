# -*- coding: utf-8 -*-
"""Ordem e numeração dos capítulos no universo Material Base.

No curso o `path` do item é `capítulo.item` (2.1, 2.2) e o menor path dos itens
dá o número do capítulo. No MB o path é RELATIVO ao capítulo e reinicia em 1 a
cada um (medido na API real) — usar a regra do curso lá numera todo capítulo
como "1" e ordena por nome. A posição real vem de `capitulos.ordem`.
"""
import os
import tempfile
import unittest

import banco_conteudo
import painel


def _item(item_id, path):
    return {"item_id": item_id, "name": item_id, "path": path,
            "block_type_count": {}}


class TestOrdemDosCapitulosMB(unittest.TestCase):
    def _avaliacao(self, capitulos, tipo="mb", curso_id="mb-1"):
        con = banco_conteudo.abrir(os.path.join(tempfile.mkdtemp(), "t.db"))
        try:
            ext = banco_conteudo.iniciar_extracao(
                con, "MB · Profa Fulana · Direito Constitucional", "concursos",
                tipo=tipo, professor_nome="Profa Fulana",
                disciplina="Direito Constitucional")
            banco_conteudo.gravar_arvore(con, ext, [{
                "id": curso_id, "name": "Direito Constitucional",
                "content_tree_cache": capitulos}])
            return painel.dados_avaliacao(con, curso_id, depara={})
        finally:
            con.close()

    def test_segue_a_ordem_da_api_e_nao_o_alfabeto(self):
        """Discriminante: os nomes estão em ordem alfabética INVERSA à da API e
        os itens dos dois capítulos começam em path "1". Com a regra do curso,
        os dois capítulos ficam com a chave (0,(1,)) e o desempate cai no nome:
        sai "Alfa" antes de "Zebra", ambos numerados "1"."""
        dados = self._avaliacao([
            {"chapter_id": "cap-z", "name": "Zebra", "order_index": 0,
             "items": [_item("z1", "1"), _item("z2", "1.1")]},
            {"chapter_id": "cap-a", "name": "Alfa", "order_index": 1,
             "items": [_item("a1", "1")]},
        ])
        self.assertEqual([c["nome"] for c in dados["capitulos"]], ["Zebra", "Alfa"])
        self.assertEqual([c["num"] for c in dados["capitulos"]], ["1", "2"])

    def test_capitulo_sem_ordem_conhecida_vai_para_o_fim_sem_sumir(self):
        dados = self._avaliacao([
            {"chapter_id": "cap-x", "name": "Sem posicao", "order_index": None,
             "items": [_item("x1", "1")]},
            {"chapter_id": "cap-p", "name": "Primeiro", "order_index": 0,
             "items": [_item("p1", "1")]},
        ])
        self.assertEqual([c["nome"] for c in dados["capitulos"]],
                         ["Primeiro", "Sem posicao"])
        self.assertEqual([c["num"] for c in dados["capitulos"]], ["1", ""])

    def test_nao_regride_o_curso_o_path_continua_mandando(self):
        """Trava a não regressão: num CURSO o `ordem` é ignorado. Aqui ele está
        gravado ao CONTRÁRIO do path — se algum dia dados_avaliacao passar a
        lê-lo no universo de curso, este teste acusa."""
        dados = self._avaliacao([
            {"chapter_id": "cap-1", "name": "Primeiro", "order_index": 9,
             "items": [_item("i1", "1.1"), _item("i2", "1.2")]},
            {"chapter_id": "cap-2", "name": "Segundo", "order_index": 0,
             "items": [_item("i3", "2.1")]},
        ], tipo="curso", curso_id="c-1")
        self.assertEqual([c["nome"] for c in dados["capitulos"]],
                         ["Primeiro", "Segundo"])
        self.assertEqual([c["num"] for c in dados["capitulos"]], ["1", "2"])


if __name__ == "__main__":
    unittest.main()
