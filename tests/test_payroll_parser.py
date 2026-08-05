import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from payroll_parser import estrai_bilancino

FIXTURE = str(Path(__file__).parent / "fixtures" / "esempio_ovwatches.pdf")


def test_estrae_le_righe_reali_del_bilancino():
    """Regressione: un primo prototipo cercava righe che iniziano con 10
    underscore, pattern assente nel testo reale estratto da pdfplumber per
    questo tracciato — restituiva zero voci. Qui deve estrarne 16."""
    _, _, righe = estrai_bilancino(FIXTURE, 6)
    assert len(righe) == 16


def test_esclude_le_righe_di_subtotale_che_riusano_un_codice_conto():
    """Regressione: righe come 'Totale contributi collaboratori' riusano il
    codice conto di una riga di dettaglio sovrastante e non vanno contate
    come registrazione separata (altrimenti l'importo verrebbe duplicato)."""
    _, _, righe = estrai_bilancino(FIXTURE, 6)
    descrizioni = [r.descrizione.lower() for r in righe]
    assert not any(d.startswith("totale") for d in descrizioni)


def test_righe_senza_da_esplicito_sono_marcate_ambigue_non_dedotte():
    _, _, righe = estrai_bilancino(FIXTURE, 6)
    ambigue = {r.descrizione for r in righe if r.ambigua}
    assert ambigue == {"Trasferte", "Rimborsi chilom. amminist. soci(spa-srl)", "NETTO IN BUSTA"}
    for r in righe:
        if r.ambigua:
            assert r.da is None  # nessun segno dedotto automaticamente


def test_mese_e_azienda_estratti_correttamente():
    mese, azienda, _ = estrai_bilancino(FIXTURE, 6)
    assert mese == "Gennaio 2026"
    assert "OVWATCHES" in azienda


def test_pagina_senza_codice_conto_solleva_errore_esplicito():
    with pytest.raises(ValueError, match="[Nn]essuna riga"):
        estrai_bilancino(FIXTURE, 1)  # pagina 1 è il cedolino, non il bilancino
