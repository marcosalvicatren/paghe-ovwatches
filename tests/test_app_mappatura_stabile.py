"""Regressione per il bug segnalato: righe della mappatura duplicate, righe
cancellate che ricomparivano, valori D/A scambiati. Causa: la tabella veniva
rigenerata dal PDF ad ogni rerun della pagina invece che una sola volta per
estrazione, confondendo lo stato interno di st.data_editor."""

import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

FIXTURE = str(Path(__file__).parent / "fixtures" / "esempio_ovwatches.pdf")


def _app_con_pdf_estratto() -> AppTest:
    at = AppTest.from_file(str(Path(__file__).parent.parent / "app.py"), default_timeout=60)
    at.session_state["pdf_path"] = FIXTURE
    at.session_state["pdf_name"] = "esempio_ovwatches.pdf"
    at.run()
    at.sidebar.radio[0].set_value("Buste paga").run()
    next(b for b in at.button if "Estrai voci" in b.label).click().run()
    return at


def test_rivisitare_la_pagina_regole_non_duplica_le_righe():
    at = _app_con_pdf_estratto()
    at.sidebar.radio[0].set_value("Regole").run()
    n1 = len(at.session_state["regole_bp"])

    at.sidebar.radio[0].set_value("Buste paga").run()
    at.sidebar.radio[0].set_value("Regole").run()
    n2 = len(at.session_state["regole_bp"])

    assert n1 == n2 == 15
    assert not at.exception


def test_una_riga_rimossa_non_ricompare_al_rerun_successivo():
    at = _app_con_pdf_estratto()
    at.sidebar.radio[0].set_value("Regole").run()
    ridotte = at.session_state["regole_bp"][:-1]
    at.session_state["regole_bp"] = ridotte
    at.run()
    at.sidebar.radio[0].set_value("Regole").run()

    assert len(at.session_state["regole_bp"]) == len(ridotte)


def test_anteprima_scrittura_e_modificabile_e_stabile_tra_i_rerun():
    """Righe aggiunte/modificate a mano nell'Anteprima non devono sparire
    né essere sovrascritte da un rerun che non comporti una nuova estrazione."""
    at = _app_con_pdf_estratto()
    assert at.session_state["bp_movimenti"] == []  # nessuna mappatura ancora fatta

    movimenti = list(at.session_state["bp_movimenti"])
    movimenti.append({"Conto": "6801", "Descrizione": "Riga aggiunta a mano", "Importo": 500.0, "D/A": "D"})
    movimenti.append({"Conto": "4501", "Descrizione": "Contropartita a mano", "Importo": 500.0, "D/A": "A"})
    at.session_state["bp_movimenti"] = movimenti
    at.run()

    metriche = {m.label: m.value for m in at.metric}
    assert metriche["Totale Dare"] == "€ 500.00"
    assert metriche["Totale Avere"] == "€ 500.00"
    assert metriche["Quadratura"] == "✅ OK"

    # cambio pagina e torno, senza ri-estrarre: le righe a mano restano
    at.sidebar.radio[0].set_value("F24").run()
    at.sidebar.radio[0].set_value("Buste paga").run()
    assert len(at.session_state["bp_movimenti"]) == 2
    assert not at.exception
