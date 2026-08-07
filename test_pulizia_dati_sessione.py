"""Regressione/requisito di riservatezza: il PDF caricato veniva scritto in
un file temporaneo con delete=False e non veniva mai cancellato dal disco
del server, né al caricamento di un nuovo file né su richiesta esplicita —
in contrasto con il requisito 'non conservare i PDF dopo l'elaborazione'."""

import os
import shutil
import sys
import tempfile
from pathlib import Path

from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

FIXTURE = str(Path(__file__).parent / "fixtures" / "esempio_ovwatches.pdf")


def test_pulsante_cancella_rimuove_il_pdf_dal_disco():
    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    shutil.copyfile(FIXTURE, tmp.name)
    tmp.close()
    assert os.path.exists(tmp.name)

    at = AppTest.from_file(str(Path(__file__).parent.parent / "app.py"), default_timeout=60)
    at.session_state["pdf_path"] = tmp.name
    at.session_state["pdf_name"] = "esempio_ovwatches.pdf"
    at.run()

    btn = next(b for b in at.button if "Cancella PDF" in b.label)
    btn.click().run()

    assert not os.path.exists(tmp.name)
    assert at.session_state["pdf_path"] is None
    assert not at.exception
