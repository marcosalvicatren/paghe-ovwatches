"""Estrazione delle righe dal bilancino paga (RIEPILOGO PAGHE E CONTRIBUTI).

A differenza di un primo prototipo che riconosceva le righe cercando una
sequenza di 10 underscore a inizio riga (euristica che NON matcha il testo
reale estratto da pdfplumber per questo tracciato), qui il riconoscimento si
basa sul dato strutturale davvero presente sul documento: ogni riga di
dettaglio comincia con un codice conto nel formato "NN/NN/NNN"
(es. "68/05/150"), seguito da descrizione, importo e — quando presente —
il marcatore Dare/Avere.

Le righe SENZA marcatore D/A esplicito (es. "Trasferte", "Rimborsi
chilometrici", "NETTO IN BUSTA" in questo tracciato) vengono estratte con
da=None e ambigua=True: non viene assegnato un segno per deduzione
aritmetica automatica, come richiesto esplicitamente dal committente.
Il motore di regole può risolverle solo tramite una regola esplicita
attivata dall'utente (vedi config/rules_buste_paga.json).
"""

from __future__ import annotations

import re

import pdfplumber

from models import CampoEstratto, MetodoEstrazione, RigaBilancino, DareAvere

_RE_RIGA = re.compile(
    r"^(\d{2}/\d{2}/\d{3})\s+(.+?)\s+([\d.]+,\d{2})\s*([DA])?\s*$"
)
_RE_MESE_ANNO = re.compile(r"mese\s+di\s+([A-Za-zàèéìòù]+\s+\d{4})", re.IGNORECASE)
_RE_AZIENDA = re.compile(r"Azienda/Fil\.\s*\d+\s+(.+)$")

# Etichette di sezione note su questo tracciato. Una qualunque riga interamente
# maiuscola incontrata dopo l'intestazione della tabella viene comunque
# trattata come nuova sezione (fallback), per non dipendere da un elenco
# chiuso se il layout cambia leggermente in futuro.
_SEZIONI_NOTE = {
    "RETRIBUZIONI E ALTRE COMPETENZE", "CONTRIBUTI INPS", "ALTRI VERSAMENTI",
    "TRATTENUTE FISCALI (IRPEF)", "CREDITI IRPEF", "CREDITI E BONUS FISCALI",
    "CONTRIBUTI COLLABORATORI", "RITENUTE IRPEF COLLABORATORI",
    "ADDIZIONALE REGIONALE",
}


def _parse_importo(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))


def estrai_bilancino(pdf_path: str, numero_pagina: int) -> tuple[str, str, list[RigaBilancino]]:
    """Estrae mese/anno, azienda e le righe di dettaglio da una pagina bilancino.

    Ritorna (mese_anno, azienda, righe). Solleva ValueError se la pagina non
    contiene alcuna riga con codice conto riconoscibile.
    """
    with pdfplumber.open(pdf_path) as pdf:
        if not (1 <= numero_pagina <= len(pdf.pages)):
            raise ValueError(f"Pagina {numero_pagina} non esiste (il PDF ha {len(pdf.pages)} pagine)")
        testo = pdf.pages[numero_pagina - 1].extract_text() or ""

    if not testo.strip():
        raise ValueError(f"Pagina {numero_pagina} vuota o non leggibile con estrazione nativa (valutare OCR)")

    mese_anno = ""
    m = _RE_MESE_ANNO.search(testo)
    if m:
        mese_anno = m.group(1).strip()

    azienda = ""
    for riga in testo.split("\n")[:6]:
        m = _RE_AZIENDA.search(riga)
        if m:
            azienda = m.group(1).strip()
            break

    righe: list[RigaBilancino] = []
    sezione_corrente = ""
    tabella_iniziata = False

    for riga_testo in testo.split("\n"):
        riga_pulita = riga_testo.strip()
        if not riga_pulita:
            continue

        if "Cod.Conto" in riga_pulita and "Descrizione" in riga_pulita:
            tabella_iniziata = True
            continue
        if not tabella_iniziata:
            continue

        match = _RE_RIGA.match(riga_pulita)
        if match:
            conto, descrizione, importo_str, da_lettera = match.groups()
            if descrizione.strip().lower().startswith("totale"):
                # riga di subtotale di sezione che riusa (per allineamento di
                # stampa) il codice conto di una delle righe di dettaglio
                # sovrastanti: non è una registrazione a sé, la ignoriamo per
                # non contare due volte lo stesso importo.
                continue
            da = DareAvere(da_lettera) if da_lettera else None
            righe.append(RigaBilancino(
                conto=conto,
                descrizione=descrizione.strip(),
                importo=_parse_importo(importo_str),
                da=da,
                sezione=sezione_corrente,
                pagina=numero_pagina,
                testo_originale=riga_testo,
                ambigua=(da is None),
                note="" if da else "D/A non esplicito sul documento — richiede conferma o regola dedicata",
            ))
            continue

        # possibile intestazione di sezione: riga interamente maiuscola,
        # senza importi, che non è una riga di subtotale (quelle contengono
        # comunque una cifra decimale che qui NON compare da sola)
        solo_lettere = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ]", "", riga_pulita)
        if solo_lettere and riga_pulita == riga_pulita.upper() and not re.search(r"\d", riga_pulita):
            sezione_corrente = riga_pulita
            continue
        if riga_pulita.upper() in _SEZIONI_NOTE:
            sezione_corrente = riga_pulita
            continue
        # altrimenti: riga di subtotale/riepilogo sezione (es. "Salari &
        # Stipendi 1.200,00") — già rappresentata dalle righe di dettaglio
        # con codice conto sopra, la ignoriamo per non duplicare gli importi.

    if not righe:
        raise ValueError(
            f"Nessuna riga con codice conto (formato NN/NN/NNN) trovata a pagina {numero_pagina}. "
            "Verificare che sia davvero la pagina del bilancino/riepilogo paghe."
        )

    return mese_anno, azienda, righe


def righe_ambigue(righe: list[RigaBilancino]) -> list[RigaBilancino]:
    return [r for r in righe if r.ambigua]
