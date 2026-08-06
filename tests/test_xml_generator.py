import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from models import DareAvere, MovimentoContabile, RegistrazioneContabile
from xml_generator import genera_xml
from xml_validator import valida_contro_xsd


def _registrazione_bilanciata() -> RegistrazioneContabile:
    reg = RegistrazioneContabile(
        tipo="paghe", causale_contabile="LA", numero_documento="TEST-0001",
        data_documento=date(2026, 1, 31), data_registrazione=date(2026, 1, 31),
    )
    reg.movimenti = [
        MovimentoContabile(conto="68/05/150", descrizione="Compensi", importo=1200.00, da=DareAvere.DARE),
        MovimentoContabile(conto="50/05/010", descrizione="Contributi Inps", importo=140.16, da=DareAvere.AVERE),
        MovimentoContabile(conto="52/05/055", descrizione="Netto in busta", importo=1059.84, da=DareAvere.AVERE),
    ]
    return reg


def test_xml_generato_e_valido_contro_lo_xsd_reale():
    reg = _registrazione_bilanciata()
    xml_bytes = genera_xml(reg)
    esito = valida_contro_xsd(xml_bytes)
    assert esito.valido, esito.errori


def test_segno_dare_positivo_avere_negativo():
    """Regola non dedotta ma dichiarata esplicitamente nel docx allegato dal
    committente: ImponibileConto positivo=Dare, negativo=Avere."""
    reg = _registrazione_bilanciata()
    xml_bytes = genera_xml(reg).decode("utf-8")
    assert "<ImponibileConto>1200</ImponibileConto>" in xml_bytes
    assert "<ImponibileConto>-140.16</ImponibileConto>" in xml_bytes
    assert "<ImponibileConto>-1059.84</ImponibileConto>" in xml_bytes


def test_struttura_non_iva_conforme_al_tracciato():
    reg = _registrazione_bilanciata()
    xml_bytes = genera_xml(reg).decode("utf-8")
    for tag in ("PrimaNotaXsd", "ListaPrimaNota", "PrimaNotaImportazione",
                "PrimaNotaNonIva", "PrimaNotaDatiGenerici", "PrimaNotaSezioneConto",
                "ListaDettaglioSezioneConto", "SezioneContoDettaglioNonIva"):
        assert f"<{tag}" in xml_bytes or f"<{tag}>" in xml_bytes
