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
            return ok, msg
    # fallback: salva comunque in locale così le modifiche non si perdono
    path_locale = _CONFIG_DIR / f"rules_{tipo}.json"
    path_locale.write_text(json.dumps(regole, ensure_ascii=False, indent=2), encoding="utf-8")
    return True, f"GitHub non disponibile: salvato in locale ({path_locale})"


def _applica_pattern(testo_lower: str, regola: dict) -> bool:
    for c in regola.get("contiene", []):
        if c.lower() not in testo_lower:
            return False
    for nc in regola.get("non_contiene", []):
        if nc.lower() in testo_lower:
            return False
    return True


def trova_regola(testo_matching: str, regole: list[dict], scope_azienda: str | None = None) -> dict | None:
    """Trova la regola con priorità più alta che matcha. Le regole con
    scope specifico per azienda vincono su quelle generali a parità di
    priorità (gerarchia richiesta dalla specifica)."""
    testo_lower = testo_matching.lower()
    candidate = [
        r for r in regole
        if r.get("attiva", True) and _applica_pattern(testo_lower, r)
        and (r.get("scope_azienda") in (None, "", scope_azienda))
    ]
    if not candidate:
        return None
    candidate.sort(key=lambda r: (
        0 if r.get("scope_azienda") else 1,  # scope specifico prima di quello generale
        -r.get("priorita", 100),
    ))
    return candidate[0]


def regole_concorrenti(testo_matching: str, regole: list[dict], scope_azienda: str | None = None) -> list[dict]:
    """Tutte le regole attive che matcherebbero (per segnalare conflitti)."""
    testo_lower = testo_matching.lower()
    return [
        r for r in regole
        if r.get("attiva", True) and _applica_pattern(testo_lower, r)
        and (r.get("scope_azienda") in (None, "", scope_azienda))
    ]
