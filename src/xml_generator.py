"""Generazione XML conforme al tracciato PrimaNotaXsd (GB Software).

Regole del tracciato (da SchemaImportazionePrimaNotaV2.xsd e dal docx
esplicativo allegato — non dedotte):
  - registrazioni non IVA => PrimaNotaNonIva, con PrimaNotaDatiGenerici e
    PrimaNotaSezioneConto/ListaDettaglioSezioneConto/SezioneContoDettaglioNonIva
  - ImponibileConto: segno POSITIVO = Dare, NEGATIVO = Avere
  - il totale di ImponibileConto in una PrimaNotaImportazione deve dare 0
"""

from __future__ import annotations

from lxml import etree

from models import DareAvere, RegistrazioneContabile

_XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"


def _fmt_importo(v: float) -> str:
    v = round(v, 2)
    return str(int(v)) if v == int(v) else f"{v:.2f}"


def genera_xml(reg: RegistrazioneContabile, xsd_filename: str = "SchemaImportazionePrimaNotaV2.xsd") -> bytes:
    root = etree.Element("PrimaNotaXsd", nsmap={"xsi": _XSI_NS})
    root.set(f"{{{_XSI_NS}}}noNamespaceSchemaLocation", xsd_filename)

    lista_pn = etree.SubElement(root, "ListaPrimaNota")
    pn_import = etree.SubElement(lista_pn, "PrimaNotaImportazione")
    non_iva = etree.SubElement(pn_import, "PrimaNotaNonIva")

    dg = etree.SubElement(non_iva, "PrimaNotaDatiGenerici")
    etree.SubElement(dg, "CausaleContabile").text = reg.causale_contabile
    etree.SubElement(dg, "NumeroDocumento").text = reg.numero_documento
    etree.SubElement(dg, "DataDocumento").text = reg.data_documento.isoformat()
    etree.SubElement(dg, "DataRegistrazione").text = reg.data_registrazione.isoformat()

    sezione_conto = etree.SubElement(non_iva, "PrimaNotaSezioneConto")
    lista_dett = etree.SubElement(sezione_conto, "ListaDettaglioSezioneConto")
    for m in reg.movimenti:
        importo_con_segno = m.importo if m.da == DareAvere.DARE else -m.importo
        dett = etree.SubElement(lista_dett, "SezioneContoDettaglioNonIva")
        etree.SubElement(dett, "Conto").text = m.conto
        etree.SubElement(dett, "ImponibileConto").text = _fmt_importo(importo_con_segno)
        etree.SubElement(dett, "Descrizione").text = (m.descrizione or "")[:255]

    xml_bytes = etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)
    # lxml scrive gli attributi xmlns:xsi e xsi:noNamespaceSchemaLocation in
    # ordine diverso da quello del file di esempio fornito: non è un problema
    # di validità XML/XSD, ma normalizziamo per confrontabilità visiva.
    return xml_bytes


def scrivi_xml(reg: RegistrazioneContabile, path: str, xsd_filename: str = "SchemaImportazionePrimaNotaV2.xsd") -> None:
    with open(path, "wb") as f:
        f.write(genera_xml(reg, xsd_filename))
