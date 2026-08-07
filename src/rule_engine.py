"""Motore di regole contabili.

Le regole mappano una voce estratta dal PDF (per descrizione, nel bilancino;
per codice tributo/sede, nell'F24) a un conto contabile del gestionale di
destinazione. Non sono nel codice sorgente: vivono in file JSON
(`config/rules_buste_paga.json`, `config/rules_f24.json`), versionabili e
— come nel prototipo di partenza — sincronizzabili direttamente su GitHub
tramite token, per chi vuole gestirle senza toccare il filesystem locale.

Import qui sotto invariato rispetto ad app.py per compatibilità: stesso
formato di regola (contiene/non_contiene/conto/da/desc_xml), con l'aggiunta
di `priorita` (intero, più alto = valutata prima) e `attiva` (bool) per
poter disattivare una regola senza cancellarla — richiesto dalla specifica
per lo storico/audit delle regole.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import requests

_CONFIG_DIR = Path(__file__).parent.parent / "config"


AMBITO_GENERALE = "Generale (tutte le aziende)"
AMBITO_AZIENDA = "Solo questa azienda"
AMBITO_REGISTRAZIONE = "Solo questa registrazione"


def ambito_da_scope(scope_azienda: str | None, scope_periodo: str | None) -> str:
    if scope_periodo:
        return AMBITO_REGISTRAZIONE
    if scope_azienda:
        return AMBITO_AZIENDA
    return AMBITO_GENERALE


def scope_da_ambito(ambito: str, azienda_corrente: str, periodo_corrente: str) -> tuple[str | None, str | None]:
    if ambito == AMBITO_REGISTRAZIONE:
        return (azienda_corrente or None), (periodo_corrente or None)
    if ambito == AMBITO_AZIENDA:
        return (azienda_corrente or None), None
    return None, None


def _gh_headers(token: str | None):
    return {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"} if token else None


def gh_leggi(filename: str, token: str | None, repo: str | None, branch: str = "main"):
    headers = _gh_headers(token)
    if not headers or not repo:
        return None, None
    r = requests.get(f"https://api.github.com/repos/{repo}/contents/{filename}",
                      headers=headers, params={"ref": branch}, timeout=10)
    if r.status_code != 200:
        return None, None
    d = r.json()
    return json.loads(base64.b64decode(d["content"]).decode()), d["sha"]


def gh_scrivi(filename: str, contenuto, messaggio: str, token: str | None, repo: str | None,
              branch: str = "main", sha: str | None = None):
    headers = _gh_headers(token)
    if not headers or not repo:
        return False, "GitHub non configurato (impostare GITHUB_TOKEN e GITHUB_REPO)"
    url = f"https://api.github.com/repos/{repo}/contents/{filename}"
    if not sha:
        r = requests.get(url, headers=headers, params={"ref": branch}, timeout=10)
        sha = r.json().get("sha") if r.status_code == 200 else None
    payload = {
        "message": messaggio,
        "content": base64.b64encode(json.dumps(contenuto, ensure_ascii=False, indent=2).encode()).decode(),
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha
    r = requests.put(url, headers=headers, json=payload, timeout=15)
    return (True, "Salvato su GitHub") if r.status_code in (200, 201) else (False, f"Errore {r.status_code}: {r.json().get('message', '')}")


def verifica_connessione_github(token: str | None, repo: str | None, branch: str) -> tuple[bool, str]:
    """Diagnostica esplicita della configurazione GitHub: dice esattamente
    cosa non va (repo non trovato, token senza permessi di scrittura, branch
    inesistente) invece di scoprirlo solo al momento di un salvataggio fallito."""
    if not token or not repo:
        return False, "GITHUB_TOKEN o GITHUB_REPO non impostati nei secrets di Streamlit."
    headers = _gh_headers(token)
    try:
        r = requests.get(f"https://api.github.com/repos/{repo}", headers=headers, timeout=10)
    except requests.RequestException as e:
        return False, f"Impossibile contattare GitHub: {e}"

    if r.status_code == 404:
        return False, f"Repository '{repo}' non trovato (o il token non può vederlo). Controlla il nome esatto (formato: utente/nome-repo)."
    if r.status_code == 401:
        return False, "Token non valido o scaduto."
    if r.status_code != 200:
        return False, f"Errore {r.status_code} contattando GitHub: {r.json().get('message', '')}"

    permessi = r.json().get("permissions", {})
    if not permessi.get("push"):
        return False, (f"Il token vede '{repo}' ma NON ha il permesso di scrittura. Nel token fine-grained "
                        f"su GitHub, sotto 'Repository permissions', il permesso 'Contents' deve essere "
                        f"impostato su 'Read and write', non solo 'Read-only'.")

    try:
        r2 = requests.get(f"https://api.github.com/repos/{repo}/branches/{branch}", headers=headers, timeout=10)
    except requests.RequestException as e:
        return False, f"Impossibile verificare il branch: {e}"
    if r2.status_code == 404:
        return False, f"Il branch '{branch}' non esiste in '{repo}'. Controlla il nome esatto (es. 'main' oppure 'master')."

    return True, f"Connessione OK: scrittura confermata su '{repo}' (branch '{branch}')."


def carica_regole(tipo: str, token: str | None = None, repo: str | None = None, branch: str = "main") -> list[dict]:
    """Carica le regole per 'buste_paga' o 'f24'. Priorità: GitHub (se
    configurato) -> file locale in config/ come fallback per sviluppo/offline."""
    filename = f"regole/{tipo}.json"
    dati, _ = gh_leggi(filename, token, repo, branch)
    if dati is not None:
        return dati
    path_locale = _CONFIG_DIR / f"rules_{tipo}.json"
    if path_locale.exists():
        return json.loads(path_locale.read_text(encoding="utf-8"))
    return []


def salva_regole(tipo: str, regole: list[dict], token: str | None = None, repo: str | None = None,
                  branch: str = "main", messaggio: str = "Aggiornamento regole") -> tuple[bool, str]:
    if token and repo:
        ok, msg = gh_scrivi(f"regole/{tipo}.json", regole, messaggio, token, repo, branch)
        if ok:
            return True, msg
        # IMPORTANTE: se GitHub è configurato ma il salvataggio fallisce
        # (token senza permessi, nome repo sbagliato, branch inesistente...),
        # NON si deve ripiegare in silenzio su un file locale spacciandolo
        # per un successo: su Streamlit Cloud quel file sparirebbe al primo
        # riavvio del container, e l'utente non saprebbe mai che i dati non
        # sono stati salvati davvero. Meglio un errore chiaro subito.
        return False, f"Salvataggio su GitHub FALLITO: {msg}. Le regole non sono state salvate in modo permanente."
    # GitHub non è proprio configurato (nessun token/repo nei secrets): qui
    # il fallback locale è legittimo, serve per lo sviluppo/uso in locale.
    path_locale = _CONFIG_DIR / f"rules_{tipo}.json"
    path_locale.write_text(json.dumps(regole, ensure_ascii=False, indent=2), encoding="utf-8")
    return True, f"GitHub non configurato: salvato solo in locale ({path_locale})."


def _applica_pattern(testo: str, regola: dict) -> bool:
    testo_lower = testo.lower()
    if regola.get("contiene"):
        # pattern avanzato impostato esplicitamente dall'utente: match per
        # sottostringa, case-insensitive (comportamento flessibile voluto).
        for c in regola["contiene"]:
            if c.lower() not in testo_lower:
                return False
        for nc in regola.get("non_contiene", []):
            if nc.lower() in testo_lower:
                return False
        return True

    # Nessun pattern avanzato: si usa il testo della "Voce" così com'è stato
    # visto sul PDF, con corrispondenza ESATTA e sensibile alle maiuscole.
    # Necessario perché lo stesso documento può avere due righe reali e
    # DISTINTE che differiscono solo per maiuscole/minuscole (es. "Irpef
    # Collaboratori" a Dare vs "Irpef collaboratori" ad Avere, viste su
    # questo stesso bilancino): un confronto case-insensitive le fonderebbe
    # per errore in un'unica mappatura, perdendo la distinzione.
    voce = regola.get("descrizione_regola", "").strip()
    if not voce:
        return False
    if testo.strip() != voce:
        return False
    for nc in regola.get("non_contiene", []):
        if nc.lower() in testo_lower:
            return False
    return True


def trova_regola(
    testo_matching: str, regole: list[dict],
    scope_azienda: str | None = None, scope_periodo: str | None = None,
) -> dict | None:
    """Trova la regola con priorità più alta che matcha. Gerarchia (più
    specifico vince, a parità di priorità): scope per questa registrazione
    (azienda + periodo) > scope per azienda > regola generale."""
    candidate = [
        r for r in regole
        if r.get("attiva", True) and _applica_pattern(testo_matching, r)
        and (r.get("scope_azienda") in (None, "", scope_azienda))
        and (r.get("scope_periodo") in (None, "", scope_periodo))
    ]
    if not candidate:
        return None
    candidate.sort(key=lambda r: (
        0 if r.get("scope_periodo") else (1 if r.get("scope_azienda") else 2),
        -r.get("priorita", 100),
    ))
    return candidate[0]


def genera_mappatura_da_voci(
    voci: list[str], tipo_documento: str, regole_esistenti: list[dict],
) -> list[dict]:
    """Aggiunge alla lista di regole una riga vuota (conto da compilare) per
    ogni voce vista nel PDF che non ha ancora una mappatura, così la tabella
    di mappatura parte già popolata con le voci reali del documento invece
    che vuota. Non tocca le mappature già esistenti (anche se il conto è
    ancora vuoto: l'utente potrebbe averlo lasciato così apposta)."""
    # Sensibile alle maiuscole di proposito: sullo stesso documento possono
    # comparire due voci reali e distinte che differiscono solo per
    # maiuscole/minuscole (vedi nota in _applica_pattern) — fondere il
    # confronto case-insensitive le tratterebbe per errore come la stessa voce.
    esistenti = {r.get("descrizione_regola", "").strip() for r in regole_esistenti}
    nuove = list(regole_esistenti)
    for voce in dict.fromkeys(v.strip() for v in voci if v.strip()):  # dedup, ordine preservato
        if voce in esistenti:
            continue
        esistenti.add(voce)
        nuove.append({
            "id": f"{tipo_documento}-{abs(hash(voce)) % 1000000}",
            "tipo_documento": tipo_documento,
            "descrizione_regola": voce,
            "contiene": [],
            "non_contiene": [],
            "segno_atteso": "",
            "conto_override": "",
            "escludi": False,
            "priorita": 100,
            "scope_azienda": None,
            "scope_periodo": None,
            "origine": "estratta_da_pdf",
            "attiva": True,
            "note": "",
        })
    return nuove


def regole_concorrenti(
    testo_matching: str, regole: list[dict],
    scope_azienda: str | None = None, scope_periodo: str | None = None,
) -> list[dict]:
    """Tutte le regole attive che matcherebbero (per segnalare conflitti)."""
    return [
        r for r in regole
        if r.get("attiva", True) and _applica_pattern(testo_matching, r)
        and (r.get("scope_azienda") in (None, "", scope_azienda))
        and (r.get("scope_periodo") in (None, "", scope_periodo))
    ]
