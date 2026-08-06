"""Regressione: il campo Data registrazione veniva precompilato con il primo
giorno del mese CORRENTE (data odierna), non con l'ultimo giorno del mese di
competenza del bilancino — risultato: paghe di dicembre registrate a maggio."""

import sys
from datetime import date
from pathlib import Path

from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).parent.parent / "app.py"))

FIXTURE = str(Path(__file__).parent / "fixtures" / "esempio_ovwatches.pdf")


def test_data_registrazione_precompilata_con_ultimo_giorno_del_periodo():
    at = AppTest.from_file(str(Path(__file__).parent.parent / "app.py"), default_timeout=60)
    at.session_state["pdf_path"] = FIXTURE
    at.session_state["pdf_name"] = "esempio_ovwatches.pdf"
    at.run()
    at.sidebar.radio[0].set_value("Buste paga").run()
    next(b for b in at.button if "Estrai voci" in b.label).click().run()

    assert at.session_state["bp_mese"] == "Gennaio 2026"
    assert at.date_input[0].value == date(2026, 1, 31)
    assert not at.exception
