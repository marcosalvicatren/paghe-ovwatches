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


def test_righe_ambigue_senza_regola_diventano_eccezioni_non_indovinate():
    _, _, righe = estrai_bilancino(FIXTURE, 6)
    reg, eccezioni = costruisci_registrazione_paghe(righe, regole=[], data_documento=date(2026, 1, 31))
    assert len(eccezioni) == 3
    assert len(reg.movimenti) == 13  # solo le righe con D/A esplicito sul documento


def test_regola_attiva_risolve_la_riga_ambigua():
    _, _, righe = estrai_bilancino(FIXTURE, 6)
    regole = [{
        "id": "t", "contiene": ["netto in busta"], "non_contiene": [],
        "segno_atteso": "A", "conto_override": "52/05/055", "attiva": True,
        "priorita": 100, "scope_azienda": None,
    }]
    reg, eccezioni = costruisci_registrazione_paghe(righe, regole, date(2026, 1, 31))
    assert any(m.descrizione == "NETTO IN BUSTA" for m in reg.movimenti)
    assert not any(getattr(e.riga_originale, "descrizione", "") == "NETTO IN BUSTA" for e in eccezioni)


def test_f24_senza_regole_non_genera_movimenti_arbitrari():
    righe, _ = estrai_f24(FIXTURE, 2)
    reg, eccezioni = costruisci_registrazione_f24(righe, regole=[], conto_contropartita="18100",
                                                   data_pagamento=date(2026, 2, 16))
    assert len(reg.movimenti) == 0
    assert len(eccezioni) == 4


def test_verifica_quadratura_segnala_scrittura_sbilanciata():
    _, _, righe = estrai_bilancino(FIXTURE, 6)
    reg, eccezioni = costruisci_registrazione_paghe(righe, regole=[], data_documento=date(2026, 1, 31))
    esito = verifica_quadratura(reg, eccezioni)
    assert esito.valido is False
    assert any("non quadrata" in e for e in esito.errori)
