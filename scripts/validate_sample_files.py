#!/usr/bin/env python3
"""Esegue l'intera pipeline (classificazione, estrazione, regole, XML) su un
PDF ed emette un report a video. Utile per il controllo rapido dopo una
modifica alle regole o al codice, senza aprire l'interfaccia Streamlit.

Uso:
    python scripts/validate_sample_files.py [percorso_pdf]

Senza argomenti usa il PDF di esempio in tests/fixtures/.
"""

from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from models import TipoPagina  # noqa: E402
from pdf_classifier import classifica_pdf  # noqa: E402
from payroll_parser import estrai_bilancino  # noqa: E402
from f24_parser import estrai_f24  # noqa: E402
from rule_engine import carica_regole  # noqa: E402
from accounting_builder import (  # noqa: E402
    costruisci_registrazione_paghe, costruisci_registrazione_f24, verifica_quadratura,
)
from xml_generator import genera_xml  # noqa: E402
from xml_validator import valida_contro_xsd  # noqa: E402

DEFAULT_PDF = Path(__file__).parent.parent / "tests" / "fixtures" / "esempio_ovwatches.pdf"


def main() -> int:
    pdf_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PDF
    if not pdf_path.exists():
        print(f"File non trovato: {pdf_path}")
        return 2

    print(f"=== {pdf_path.name} — {datetime.now():%Y-%m-%d %H:%M} ===\n")

    classificate = classifica_pdf(str(pdf_path))
    print(f"Pagine totali: {len(classificate)}")
    for p in classificate:
        extra = f" (duplicato di pag.{p.duplicato_di})" if p.duplicato_di else ""
        print(f"  pag {p.numero:2d}: {p.tipo.value:18s} affidabilità={p.affidabilita:.2f}{extra}")

    esito_finale = 0

    pagine_bp = [p.numero for p in classificate if p.tipo == TipoPagina.BILANCINO_PAGHE]
    if pagine_bp:
        print(f"\n--- Buste paga (pagina {pagine_bp[0]}) ---")
        regole_bp = carica_regole("buste_paga")
        mese, azienda, righe = estrai_bilancino(str(pdf_path), pagine_bp[0])
        reg, eccezioni = costruisci_registrazione_paghe(righe, regole_bp, date.today(), scope_azienda=azienda)
        esito = verifica_quadratura(reg, eccezioni)
        print(f"Movimenti: {len(reg.movimenti)}  Eccezioni: {len(eccezioni)}  "
              f"Dare: {reg.totale_dare:.2f}  Avere: {reg.totale_avere:.2f}  Quadrata: {reg.quadrata}")
        for e in esito.errori:
            print(f"  ERRORE: {e}")
        for a in esito.avvisi:
            print(f"  AVVISO: {a}")
        if esito.valido:
            esito_xsd = valida_contro_xsd(genera_xml(reg))
            print(f"  Validazione XSD: {'OK' if esito_xsd.valido else esito_xsd.errori}")
        else:
            esito_finale = 1
    else:
        print("\n--- Nessuna pagina bilancino paga riconosciuta ---")

    pagine_f24 = [p.numero for p in classificate if p.tipo == TipoPagina.F24]
    if pagine_f24:
        print(f"\n--- F24 (pagina {pagine_f24[0]}) ---")
        regole_f24 = carica_regole("f24")
        righe, saldo = estrai_f24(str(pdf_path), pagine_f24[0])
        print(f"Righe estratte: {len(righe)}  Saldo dichiarato sul modulo: {saldo}")
        reg, eccezioni = costruisci_registrazione_f24(righe, regole_f24, conto_contropartita="",
                                                        data_pagamento=date.today())
        print(f"Movimenti: {len(reg.movimenti)}  Eccezioni: {len(eccezioni)}")
        if eccezioni:
            print("  (nessuna regola F24 configurata: normale finché non si popola config/rules_f24.json)")
    else:
        print("\n--- Nessuna pagina F24 riconosciuta ---")

    print(f"\n=== Esito: {'OK' if esito_finale == 0 else 'DA RIVEDERE (vedi errori sopra)'} ===")
    return esito_finale


if __name__ == "__main__":
    raise SystemExit(main())
