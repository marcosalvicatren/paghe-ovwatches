"""Costruzione delle registrazioni contabili.

Principio guida: il bilancino paga arriva dal software paghe già con
Cod.Conto e D/A compilati riga per riga — non è compito di questo modulo
"inventare" una contabilizzazione, ma usare direttamente quel dato quando è
presente e chiaro, e chiedere conferma solo per ciò che è davvero ambiguo o
privo di regola. Le regole servono per:

  1. rimappare un codice conto del software paghe su un codice diverso nel
     piano dei conti del gestionale di destinazione (se necessario — di
     default NON viene applicata alcuna rimappatura, il conto del documento
     passa invariato);
  2. risolvere le righe senza D/A esplicito (ambigue), solo se esiste una
     regola attiva pensata apposta;
  3. assegnare un conto alle righe F24, che di per sé non hanno un conto
     (l'F24 è una dichiarazione fiscale, non un prospetto contabile).

Ogni riga che non trova una regola attiva e non ha un dato sufficiente dal
documento diventa una Eccezione e NON entra nella registrazione: la
generazione XML resta bloccata finché l'utente non la risolve (o forza
esplicitamente, con avviso — vedi generate_xml_*).
"""

from __future__ import annotations

from datetime import date

from models import (
    DareAvere, Eccezione, MovimentoContabile, RegistrazioneContabile,
    RigaBilancino, RigaF24, RisultatoValidazione,
)
from rule_engine import trova_regola, regole_concorrenti


def costruisci_registrazione_paghe(
    righe: list[RigaBilancino],
    regole: list[dict],
    data_documento: date,
    scope_azienda: str | None = None,
    causale: str = "LA",
    numero_documento: str = "",
) -> tuple[RegistrazioneContabile, list[Eccezione]]:
    reg = RegistrazioneContabile(
        tipo="paghe", causale_contabile=causale,
        numero_documento=numero_documento or f"BP-{data_documento.isoformat().replace('-', '')}",
        data_documento=data_documento, data_registrazione=data_documento,
    )
    eccezioni: list[Eccezione] = []

    for r in righe:
        regola = trova_regola(r.descrizione, regole, scope_azienda)
        # IMPORTANTE: il conto del bilancino è quello del software paghe, non
        # necessariamente quello del gestionale di destinazione. Non lo si usa
        # mai come ripiego: senza una mappatura esplicita (conto_override
        # valorizzato) la voce resta in sospeso, in "Eccezioni".
        conto = (regola.get("conto_override") or "").strip() if regola else ""

        if r.da is not None:
            if conto:
                reg.movimenti.append(MovimentoContabile(
                    conto=conto, descrizione=r.descrizione, importo=r.importo, da=r.da,
                    causale=causale, pagina_origine=r.pagina, regola_applicata=regola["id"],
                ))
            else:
                eccezioni.append(Eccezione(
                    riga_originale=r, motivo="conto_non_mappato",
                    regole_candidate=[regola["id"]] if regola else [],
                ))
            continue

        # riga ambigua: serve una mappatura attiva con segno atteso E conto
        if regola and regola.get("segno_atteso") and regola.get("attiva", True) and conto:
            reg.movimenti.append(MovimentoContabile(
                conto=conto, descrizione=r.descrizione, importo=r.importo,
                da=DareAvere(regola["segno_atteso"]),
                causale=causale, pagina_origine=r.pagina, regola_applicata=regola["id"],
            ))
        else:
            concorrenti = regole_concorrenti(r.descrizione, regole, scope_azienda)
            eccezioni.append(Eccezione(
                riga_originale=r,
                motivo="dati_mancanti" if not concorrenti else "piu_regole",
                regole_candidate=[c["id"] for c in concorrenti],
            ))

    return reg, eccezioni


def costruisci_registrazione_f24(
    righe: list[RigaF24],
    regole: list[dict],
    conto_contropartita: str,
    data_pagamento: date,
    scope_azienda: str | None = None,
    causale: str = "LA",
    numero_documento: str = "",
) -> tuple[RegistrazioneContabile, list[Eccezione]]:
    reg = RegistrazioneContabile(
        tipo="f24", causale_contabile=causale,
        numero_documento=numero_documento or f"F24-{data_pagamento.isoformat().replace('-', '')}",
        data_documento=data_pagamento, data_registrazione=data_pagamento,
    )
    eccezioni: list[Eccezione] = []

    for r in righe:
        regola = trova_regola(r.codice, regole, scope_azienda)
        if not regola:
            concorrenti = regole_concorrenti(r.codice, regole, scope_azienda)
            eccezioni.append(Eccezione(
                riga_originale=r,
                motivo="dati_mancanti" if not concorrenti else "piu_regole",
                regole_candidate=[c["id"] for c in concorrenti],
            ))
            continue
        conto = regola.get("conto_override", "")
        desc = regola.get("descrizione_regola", r.codice)
        if r.importo_debito:
            reg.movimenti.append(MovimentoContabile(
                conto=conto, descrizione=desc, importo=r.importo_debito, da=DareAvere.DARE,
                causale=causale, pagina_origine=r.pagina, regola_applicata=regola["id"],
                codice_tributo=r.codice,
            ))
        if r.importo_credito:
            reg.movimenti.append(MovimentoContabile(
                conto=conto, descrizione=desc, importo=r.importo_credito, da=DareAvere.AVERE,
                causale=causale, pagina_origine=r.pagina, regola_applicata=regola["id"],
                codice_tributo=r.codice,
            ))

    # riga di contropartita (es. banca) per pareggiare il pagamento F24,
    # calcolata sulle sole righe già risolte — se ci sono eccezioni aperte
    # il saldo non rappresenta ancora l'F24 completo: lo segnaliamo a chi
    # chiama tramite verifica_quadratura(), non lo nascondiamo qui.
    if conto_contropartita and reg.movimenti:
        netto = reg.totale_dare - reg.totale_avere
        if abs(netto) > 0.005:
            reg.movimenti.append(MovimentoContabile(
                conto=conto_contropartita, descrizione="Pagamento F24",
                importo=abs(netto), da=(DareAvere.AVERE if netto > 0 else DareAvere.DARE),
                causale=causale,
            ))

    return reg, eccezioni


def verifica_quadratura(reg: RegistrazioneContabile, eccezioni: list[Eccezione]) -> RisultatoValidazione:
    errori, avvisi = [], []
    if eccezioni:
        # Bloccante, non solo un avviso: una voce senza conto mappato non è
        # un dettaglio opzionale, significa che l'XML sarebbe incompleto o
        # userebbe (per le altre righe) conti del software paghe non validi
        # nel gestionale. Richiede una mappatura o una forzatura esplicita.
        errori.append(
            f"{len(eccezioni)} voce/i senza conto del gestionale assegnato: "
            "vai su 'Mappatura conti' oppure risolvile qui sotto in 'Eccezioni'."
        )
    if not reg.quadrata:
        errori.append(
            f"Scrittura non quadrata: Dare {reg.totale_dare:.2f} \u2260 Avere {reg.totale_avere:.2f} "
            f"(differenza {reg.totale_dare - reg.totale_avere:.2f})"
        )
    conti_mancanti = [m.descrizione for m in reg.movimenti if not m.conto.strip()]
    if conti_mancanti:
        errori.append(f"{len(conti_mancanti)} movimento/i senza conto assegnato: " + ", ".join(conti_mancanti[:5]))
    return RisultatoValidazione(valido=not errori, errori=errori, avvisi=avvisi)
