"""Estrazione dati dal modello F24 usando le coordinate delle parole.

Perché non un semplice regex su testo lineare
-----------------------------------------------
`pdfplumber.extract_text()` appiattisce la tabella F24 in una sequenza di
numeri che perde la colonna di provenienza. Su un F24 reale verificato in
questo progetto, la riga "1701 12 2025 15781" corrisponde in realtà a un
IMPORTO A CREDITO COMPENSATO (non a debito): un parser basato solo su
regex testuale classificherebbe questo importo come debito, sbagliando
saldo e segno contabile.

Qui invece si usa `extract_words()` (che restituisce x0/x1/top per ogni
parola) per individuare dinamicamente, sulla pagina stessa, la posizione
delle colonne "importi a debito versati" e "importi a credito compensati"
(le etichette si ripetono identiche per ogni sezione del modulo), e si
classifica ogni importo numerico in base alla sua posizione orizzontale
rispetto a quelle colonne — non in base all'ordine in cui compare nel testo.

Limiti noti di questo prototipo (Fase 2)
-----------------------------------------
Il campo "codice"/identificativo di ogni riga viene estratto come blocco
grezzo (tutti i token a sinistra della colonna importi), non ancora
scomposto in codice sede / causale / matricola / periodo da-a separati:
nell'unico F24 di esempio disponibile solo le sezioni Erario e INPS sono
valorizzate, quindi non è ancora possibile validare una scomposizione
più fine per Regioni/IMU/Altri enti senza rischiare di indovinare un
layout non verificato.
"""

from __future__ import annotations

import re

import pdfplumber

from models import RigaF24

_RE_SEZIONE = re.compile(r"^SEZIONE$")
_RE_AMOUNT_TOKEN = re.compile(r"^[\d.]+-?$")

_SEZIONI_ATTESE = {
    "ERARIO": "erario",
    "INPS": "inps",
    "REGIONI": "regioni",
    "IMU": "imu",
    "ALTRI": "altri_enti",  # "ALTRI ENTI PREVIDENZIALI ED ASSICURATIVI"
}

# soglia minima di x0 sotto la quale un token numerico è quasi certamente
# un identificativo (codice tributo/mese/anno) e non un importo
_X0_MIN_IMPORTO = 300.0
# margine oltre la colonna "credito compensati" oltre il quale un numero
# appartiene alla colonna SALDO (solo sulle righe TOTALE, ignorate)
_MARGINE_DESTRO_CREDITO = 60.0


def _raggruppa_per_riga(words: list[dict], tolleranza: float = 2.5) -> list[list[dict]]:
    righe: list[list[dict]] = []
    correnti: list[dict] = []
    top_rif = None
    for w in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
        if top_rif is None or abs(w["top"] - top_rif) <= tolleranza:
            correnti.append(w)
            top_rif = w["top"] if top_rif is None else top_rif
        else:
            righe.append(correnti)
            correnti = [w]
            top_rif = w["top"]
    if correnti:
        righe.append(correnti)
    return righe


def _trova_colonne_importi(words: list[dict]) -> tuple[float, float]:
    """Ritorna (confine_debito_credito, confine_destro_credito) individuati
    dinamicamente dalle etichette di colonna presenti sulla pagina."""
    deb = [w for w in words if w["text"].lower() == "debito"]
    cred = [w for w in words if w["text"].lower() == "credito"]
    compensati = [w for w in words if w["text"].lower() == "compensati"]
    if not deb or not cred:
        raise ValueError(
            "Non trovo le etichette di colonna 'debito'/'credito' sulla pagina: "
            "il layout potrebbe non essere un F24 standard, o l'estrazione testo "
            "nativa non è affidabile (valutare OCR)."
        )
    versati = [w for w in words if w["text"].lower() == "versati"]
    confine = ((versati[0]["x1"] if versati else deb[0]["x1"]) + cred[0]["x0"]) / 2
    destro = (compensati[0]["x1"] if compensati else cred[0]["x1"]) + _MARGINE_DESTRO_CREDITO
    return confine, destro


def _classifica_importo(x0: float, confine: float, destro: float) -> str | None:
    if x0 < _X0_MIN_IMPORTO:
        return None
    if x0 < confine:
        return "debito"
    if x0 < destro:
        return "credito"
    return "saldo"  # colonna SALDO/TOTALE, non un importo di riga


def estrai_f24(pdf_path: str, numero_pagina: int) -> tuple[list[RigaF24], float | None]:
    """Estrae le righe con importo dal modello F24. Ritorna (righe, saldo_finale)."""
    with pdfplumber.open(pdf_path) as pdf:
        if not (1 <= numero_pagina <= len(pdf.pages)):
            raise ValueError(f"Pagina {numero_pagina} non esiste")
        page = pdf.pages[numero_pagina - 1]
        words = page.extract_words(use_text_flow=False, keep_blank_chars=False)

    if not words:
        raise ValueError(f"Pagina {numero_pagina} vuota o non leggibile con estrazione nativa")

    confine, destro = _trova_colonne_importi(words)

    # posizioni delle etichette SEZIONE X, per assegnare ogni riga alla sezione
    marcatori_sezione: list[tuple[float, str]] = []
    parole_per_top = {}
    for w in words:
        parole_per_top.setdefault(round(w["top"]), []).append(w)
    for w in words:
        if w["text"] == "SEZIONE":
            vicine = sorted(
                (x for x in words if abs(x["top"] - w["top"]) <= 1.0 and x["x0"] > w["x0"]),
                key=lambda x: x["x0"],
            )
            etichetta = vicine[0]["text"].upper() if vicine else ""
            sezione = _SEZIONI_ATTESE.get(etichetta, etichetta.lower() or "sconosciuta")
            marcatori_sezione.append((w["top"], sezione))
    marcatori_sezione.sort()

    def sezione_di(top: float) -> str:
        corrente = "sconosciuta"
        for soglia, nome in marcatori_sezione:
            if soglia <= top + 1e-6:
                corrente = nome
            else:
                break
        return corrente

    righe_out: list[RigaF24] = []
    saldo_finale = None

    for riga_words in _raggruppa_per_riga(words):
        testi = [w["text"] for w in riga_words]
        if "TOTALE" in testi:
            # riga di controllo/subtotale: usata solo per cross-check, non come movimento
            continue
        if "SEZIONE" in testi:
            continue
        if "EURO" in testi:
            # riga SALDO FINALE: es. ["EURO", "47981"] oppure con "-" separato
            numeri = [w for w in riga_words if _RE_AMOUNT_TOKEN.match(w["text"])]
            if numeri:
                saldo_finale = int(numeri[-1]["text"].replace(".", "")) / 100
            continue

        identificativi = [w["text"] for w in riga_words if w["x0"] < _X0_MIN_IMPORTO]
        # una riga dati F24 comincia sempre con un codice numerico (codice
        # tributo, codice sede, codice regione/ente...). Senza questo, la riga
        # è testo libero (indirizzo, intestazioni) che può contenere cifre
        # sparse (es. un numero civico) da NON scambiare per un importo.
        codici_plausibili = [t for t in identificativi if re.match(r"^\d{3,}$", t)]
        if not codici_plausibili:
            continue

        importi_riga = []
        for w in riga_words:
            if not _RE_AMOUNT_TOKEN.match(w["text"]):
                continue
            colonna = _classifica_importo(w["x0"], confine, destro)
            if colonna in ("debito", "credito"):
                valore = int(w["text"].rstrip("-").replace(".", "")) / 100
                importi_riga.append((colonna, valore))

        if not importi_riga:
            continue  # riga senza importi (etichette, righe vuote, ecc.)

        codice = next((t for t in codici_plausibili if len(t) == 4), codici_plausibili[0])
        top_riga = riga_words[0]["top"]
        riga = RigaF24(
            sezione=sezione_di(top_riga),
            codice=codice,
            pagina=numero_pagina,
            testo_originale=" ".join(testi),
        )
        for colonna, valore in importi_riga:
            if colonna == "debito":
                riga.importo_debito += valore
            else:
                riga.importo_credito += valore
        righe_out.append(riga)

    if not righe_out:
        raise ValueError(
            f"Nessuna riga con importo trovata a pagina {numero_pagina}. "
            "Verificare che sia davvero la pagina del modello F24."
        )

    return righe_out, saldo_finale
