import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from models import TipoPagina
from pdf_classifier import classifica_pdf

FIXTURE = str(Path(__file__).parent / "fixtures" / "esempio_ovwatches.pdf")


def test_classifica_tutte_le_pagine():
    risultato = classifica_pdf(FIXTURE)
    assert len(risultato) == 10


def test_riconosce_il_bilancino_e_ne_scarta_il_duplicato():
    risultato = {p.numero: p for p in classifica_pdf(FIXTURE)}
    assert risultato[6].tipo == TipoPagina.BILANCINO_PAGHE
    assert risultato[7].tipo == TipoPagina.DUPLICATO
    assert risultato[7].duplicato_di == 6


def test_riconosce_f24_e_scarta_le_copie_ridondanti():
    risultato = {p.numero: p for p in classifica_pdf(FIXTURE)}
    assert risultato[2].tipo == TipoPagina.F24
    assert risultato[3].tipo == TipoPagina.DUPLICATO
    assert risultato[4].tipo == TipoPagina.DUPLICATO
    assert risultato[3].duplicato_di == 2
    assert risultato[4].duplicato_di == 2


def test_pagine_irrilevanti_non_vengono_classificate_come_documenti_utili():
    risultato = {p.numero: p for p in classifica_pdf(FIXTURE)}
    for numero in (1, 5, 8, 9, 10):
        assert risultato[numero].tipo == TipoPagina.ALTRO
