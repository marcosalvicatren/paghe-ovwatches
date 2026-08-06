import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from payroll_parser import estrai_bilancino
from f24_parser import estrai_f24
from accounting_builder import (
    costruisci_registrazione_paghe, costruisci_registrazione_f24, verifica_quadratura,
)

FIXTURE = str(Path(__file__).parent / "fixtures" / "esempio_ovwatches.pdf")


def test_senza_mappatura_nessun_conto_del_pdf_viene_usato_come_ripiego():
    """Il conto scritto sul bilancino è quello del software paghe, non del
    gestionale: senza una mappatura esplicita (conto_override), NESSUNA riga
    genera un movimento, nemmeno quelle con D/A già esplicito sul documento."""
    _, _, righe = estrai_bilancino(FIXTURE, 6)
    reg, eccezioni = costruisci_registrazione_paghe(righe, regole=[], data_documento=date(2026, 1, 31))
    assert len(eccezioni) == 16
    assert len(reg.movimenti) == 0


def test_mappatura_con_conto_valorizzato_genera_il_movimento():
    _, _, righe = estrai_bilancino(FIXTURE, 6)
    regole = [{
        "id": "t", "descrizione_regola": "Compensi amministratori soci (spa-srl)",
        "contiene": [], "non_contiene": [], "segno_atteso": "",
        "conto_override": "6801", "attiva": True, "priorita": 100, "scope_azienda": None,
    }]
    reg, eccezioni = costruisci_registrazione_paghe(righe, regole, date(2026, 1, 31))
    assert any(m.conto == "6801" for m in reg.movimenti)
    assert not any(getattr(e.riga_originale, "descrizione", "") == "Compensi amministratori soci (spa-srl)" for e in eccezioni)


def test_regola_attiva_con_conto_risolve_anche_la_riga_ambigua():
    _, _, righe = estrai_bilancino(FIXTURE, 6)
    regole = [{
        "id": "t", "descrizione_regola": "NETTO IN BUSTA", "contiene": [], "non_contiene": [],
        "segno_atteso": "A", "conto_override": "5200", "attiva": True,
        "priorita": 100, "scope_azienda": None,
    }]
    reg, eccezioni = costruisci_registrazione_paghe(righe, regole, date(2026, 1, 31))
    assert any(m.descrizione == "NETTO IN BUSTA" and m.conto == "5200" for m in reg.movimenti)
    assert not any(getattr(e.riga_originale, "descrizione", "") == "NETTO IN BUSTA" for e in eccezioni)


def test_mappatura_senza_conto_non_basta_anche_se_regola_esiste():
    """Una riga di mappatura presente ma con conto_override vuoto (voce vista
    ma non ancora assegnata) deve restare un'eccezione, non passare a vuoto."""
    _, _, righe = estrai_bilancino(FIXTURE, 6)
    regole = [{
        "id": "t", "descrizione_regola": "Compensi amministratori soci (spa-srl)",
        "contiene": [], "non_contiene": [], "segno_atteso": "",
        "conto_override": "", "attiva": True, "priorita": 100, "scope_azienda": None,
    }]
    reg, eccezioni = costruisci_registrazione_paghe(righe, regole, date(2026, 1, 31))
    assert not any(m.descrizione == "Compensi amministratori soci (spa-srl)" for m in reg.movimenti)
    assert any(getattr(e.riga_originale, "descrizione", "") == "Compensi amministratori soci (spa-srl)" for e in eccezioni)


def test_f24_senza_regole_non_genera_movimenti_arbitrari():
    righe, _ = estrai_f24(FIXTURE, 2)
    reg, eccezioni = costruisci_registrazione_f24(righe, regole=[], conto_contropartita="18100",
                                                   data_pagamento=date(2026, 2, 16))
    assert len(reg.movimenti) == 0
    assert len(eccezioni) == 4


def test_verifica_quadratura_blocca_se_ci_sono_voci_non_mappate():
    _, _, righe = estrai_bilancino(FIXTURE, 6)
    reg, eccezioni = costruisci_registrazione_paghe(righe, regole=[], data_documento=date(2026, 1, 31))
    esito = verifica_quadratura(reg, eccezioni)
    assert esito.valido is False
    assert any("conto del gestionale" in e for e in esito.errori)


def test_verifica_quadratura_segnala_scrittura_sbilanciata():
    _, _, righe = estrai_bilancino(FIXTURE, 6)
    regole = [
        {"id": f"t{i}", "descrizione_regola": r.descrizione, "contiene": [], "non_contiene": [],
         "segno_atteso": "", "conto_override": f"C{i}", "attiva": True, "priorita": 100, "scope_azienda": None}
        for i, r in enumerate(righe) if r.da is not None
    ]  # mappa tutte le righe con D/A esplicito ma su conti diversi tra loro: non quadra
    reg, eccezioni = costruisci_registrazione_paghe(righe, regole, date(2026, 1, 31))
    esito = verifica_quadratura(reg, eccezioni)
    assert esito.valido is False
    assert any("non quadrata" in e for e in esito.errori)
