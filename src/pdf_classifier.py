"""Classificazione automatica delle pagine di un PDF multipagina.

Riconosce, per ogni pagina:
  - bilancino paga ("RIEPILOGO PAGHE E CONTRIBUTI")
  - modello F24 ("Mod. F24" / "MODELLO DI PAGAMENTO UNIFICATO")
  - pagine irrilevanti (cedolino, distinta bonifici, costo consuntivo, ecc.)

e marca come DUPLICATO le pagine che ripetono contenuto identico o
quasi-identico a una pagina già classificata (es. le 3 copie dell'F24,
oppure un bilancino ristampato "per reparto" con gli stessi importi).

Nota: la deduplica qui è deliberatamente prudente. Se in futuro un cliente
avrà più reparti con importi DIVERSI, quelle pagine NON verranno considerate
duplicate (il confronto è sul contenuto numerico, non sulla sola etichetta)
e verranno quindi trattate come bilancini distinti da sommare — è compito
dell'utente verificarlo nella tabella "Analisi pagine" dell'interfaccia.
"""

from __future__ import annotations

import difflib
import re

import pdfplumber

from models import PaginaClassificata, TipoPagina

_RE_BILANCINO = re.compile(r"R\s*I\s*E\s*P\s*I\s*L\s*O\s*G\s*O\s*P\s*A\s*G\s*H\s*E", re.IGNORECASE)
_RE_F24 = re.compile(r"Mod\.\s*F24|MODELLO\s+DI\s+PAGAMENTO\s+UNIFICATO", re.IGNORECASE)
_RE_COD_CONTO = re.compile(r"^\d{2}/\d{2}/\d{3}\s")

# Soglia di similarità testuale sopra la quale due pagine sono considerate
# lo stesso contenuto ristampato (copie F24, bilancino ristampato identico).
_SOGLIA_DUPLICATO = 0.92


def _normalizza(testo: str) -> str:
    """Rimuove numeri di pagina/copia e spazi per confrontare solo il contenuto."""
    t = re.sub(r"\d+a\s+COPIA.*", "", testo, flags=re.IGNORECASE)
    t = re.sub(r"COPIA\s+PER.*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"Rep\d*:?", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def classifica_pdf(pdf_path: str) -> list[PaginaClassificata]:
    """Classifica ogni pagina del PDF. Ritorna una lista ordinata per numero pagina."""
    risultati: list[PaginaClassificata] = []
    testi_bilancino: dict[int, str] = {}
    testi_f24: dict[int, str] = {}

    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            testo = page.extract_text() or ""
            testo_norm = _normalizza(testo)

            if _RE_BILANCINO.search(testo):
                n_righe_conto = len(_RE_COD_CONTO.findall(testo.replace("\n", "\n")))
                # conta le righe che iniziano con un codice conto NN/NN/NNN
                n_righe_conto = sum(1 for l in testo.split("\n") if _RE_COD_CONTO.match(l.strip()))
                dup_di = _trova_duplicato(testo_norm, testi_bilancino)
                if dup_di:
                    risultati.append(PaginaClassificata(
                        numero=i, tipo=TipoPagina.DUPLICATO, affidabilita=0.9,
                        motivo=f"contenuto numerico identico alla pagina {dup_di} (bilancino)",
                        duplicato_di=dup_di))
                else:
                    testi_bilancino[i] = testo_norm
                    aff = 0.95 if n_righe_conto >= 3 else 0.6
                    motivo = f"trovate {n_righe_conto} righe con codice conto (formato NN/NN/NNN)"
                    risultati.append(PaginaClassificata(
                        numero=i, tipo=TipoPagina.BILANCINO_PAGHE,
                        affidabilita=aff, motivo=motivo))
                continue

            if _RE_F24.search(testo):
                dup_di = _trova_duplicato(testo_norm, testi_f24)
                if dup_di:
                    risultati.append(PaginaClassificata(
                        numero=i, tipo=TipoPagina.DUPLICATO, affidabilita=0.9,
                        motivo=f"copia identica del modello F24 di pagina {dup_di}",
                        duplicato_di=dup_di))
                else:
                    testi_f24[i] = testo_norm
                    risultati.append(PaginaClassificata(
                        numero=i, tipo=TipoPagina.F24, affidabilita=0.9,
                        motivo="trovata intestazione 'Mod. F24 / MODELLO DI PAGAMENTO UNIFICATO'"))
                continue

            risultati.append(PaginaClassificata(
                numero=i, tipo=TipoPagina.ALTRO, affidabilita=0.5,
                motivo="nessun marcatore di bilancino paga o F24 riconosciuto"))

    return risultati


def _trova_duplicato(testo_norm: str, gia_visti: dict[int, str]) -> int | None:
    for numero, testo_prec in gia_visti.items():
        if not testo_norm or not testo_prec:
            continue
        ratio = difflib.SequenceMatcher(None, testo_norm, testo_prec).ratio()
        if ratio >= _SOGLIA_DUPLICATO:
            return numero
    return None


def pagine_utili(classificate: list[PaginaClassificata], tipo: TipoPagina) -> list[int]:
    """Numeri delle pagine di un dato tipo, escludendo i duplicati."""
    return [p.numero for p in classificate if p.tipo == tipo]
