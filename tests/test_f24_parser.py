import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from f24_parser import estrai_f24

FIXTURE = str(Path(__file__).parent / "fixtures" / "esempio_ovwatches.pdf")


def test_distingue_correttamente_debito_da_credito():
    """Regressione: un parser basato su regex testuale lineare classificava
    come 'a debito' anche importi che sul modulo sono in realtà 'a credito
    compensato' (perse le colonne durante l'estrazione testo). Qui la
    distinzione si basa sulle coordinate x delle parole."""
    righe, _ = estrai_f24(FIXTURE, 2)
    per_codice = {(r.codice, r.testo_originale.split()[1] if False else None): r for r in righe}
    # riga codice 1701 col periodo 12/2025 -> a credito, non a debito
    riga_1701_dic = next(r for r in righe if r.codice == "1701" and "12" in r.testo_originale and "2025" in r.testo_originale)
    assert riga_1701_dic.importo_credito == 157.81
    assert riga_1701_dic.importo_debito == 0.0

    riga_1001 = next(r for r in righe if r.codice == "1001")
    assert riga_1001.importo_debito == 108.54
    assert riga_1001.importo_credito == 0.0


def test_saldo_ricostruito_coincide_col_saldo_dichiarato_sul_modulo():
    righe, saldo_dichiarato = estrai_f24(FIXTURE, 2)
    totale_debito = sum(r.importo_debito for r in righe)
    totale_credito = sum(r.importo_credito for r in righe)
    assert saldo_dichiarato == 479.81
    assert round(totale_debito - totale_credito, 2) == saldo_dichiarato


def test_ignora_cifre_sparse_nel_testo_libero_come_il_numero_civico():
    """Regressione: il civico '3' di un indirizzo in colonna 'credito' veniva
    scambiato per un importo di 0,03 perché privo di un codice tributo/sede
    plausibile sulla stessa riga."""
    righe, _ = estrai_f24(FIXTURE, 2)
    assert all(r.importo_credito != 0.03 for r in righe)
    assert len(righe) == 4
