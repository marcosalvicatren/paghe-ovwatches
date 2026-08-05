"""Validazione dell'XML generato contro lo schema XSD reale del gestionale
(config/schema/SchemaImportazionePrimaNotaV2.xsd), non solo controllo di
buona formattazione sintattica."""

from __future__ import annotations

from pathlib import Path

from lxml import etree

from models import RisultatoValidazione

_XSD_PATH = Path(__file__).parent.parent / "config" / "schema" / "SchemaImportazionePrimaNotaV2.xsd"


def valida_contro_xsd(xml_bytes: bytes, xsd_path: str | Path = _XSD_PATH) -> RisultatoValidazione:
    try:
        schema_doc = etree.parse(str(xsd_path))
        schema = etree.XMLSchema(schema_doc)
    except Exception as e:
        return RisultatoValidazione(valido=False, errori=[f"Impossibile caricare lo schema XSD: {e}"])

    try:
        doc = etree.fromstring(xml_bytes)
    except etree.XMLSyntaxError as e:
        return RisultatoValidazione(valido=False, errori=[f"XML non ben formato: {e}"])

    if schema.validate(doc):
        return RisultatoValidazione(valido=True)

    errori = [f"riga {err.line}: {err.message}" for err in schema.error_log]
    return RisultatoValidazione(valido=False, errori=errori)
