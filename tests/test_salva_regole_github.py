"""Regressione: quando GitHub è configurato (token+repo presenti) ma il
salvataggio fallisce (token senza permessi, repo/branch sbagliato...), il
codice ripiegava in silenzio su un file locale e riportava comunque
successo — su Streamlit Cloud quel file locale sparisce al riavvio del
container, quindi le regole sembravano salvate ma si perdevano davvero."""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rule_engine import salva_regole


def test_fallimento_github_viene_segnalato_non_nascosto():
    with patch("rule_engine.gh_scrivi", return_value=(False, "Errore 404: Not Found")):
        ok, msg = salva_regole("buste_paga", [{"id": "x"}], token="tok", repo="utente/repo", branch="main")
    assert ok is False
    assert "FALLITO" in msg
    assert "404" in msg


def test_successo_github_viene_riportato_correttamente():
    with patch("rule_engine.gh_scrivi", return_value=(True, "Salvato su GitHub")):
        ok, msg = salva_regole("buste_paga", [{"id": "x"}], token="tok", repo="utente/repo", branch="main")
    assert ok is True
    assert "Salvato" in msg


def test_senza_token_ripiega_in_locale_dichiarandolo_esplicitamente(tmp_path, monkeypatch):
    import rule_engine
    monkeypatch.setattr(rule_engine, "_CONFIG_DIR", tmp_path)
    ok, msg = salva_regole("buste_paga", [{"id": "x"}], token=None, repo=None, branch="main")
    assert ok is True
    assert "non configurato" in msg.lower()
    assert (tmp_path / "rules_buste_paga.json").exists()


def test_verifica_connessione_non_si_fida_del_campo_permissions():
    """Regressione: per i token fine-grained, il campo 'permissions' di
    GET /repos/{repo} riflette i permessi dell'ACCOUNT sul repository (per
    il proprietario, sempre push=true), non quelli specifici del token —
    un token senza alcun accesso reale può comunque risultare 'push: true'
    lì. L'unico test affidabile è un tentativo di scrittura vero."""
    from unittest.mock import patch, MagicMock
    from rule_engine import verifica_connessione_github

    risposta_repo = MagicMock(status_code=200)
    risposta_repo.json.return_value = {"permissions": {"push": True}}  # mente, come nel caso reale
    risposta_branch = MagicMock(status_code=200)

    with patch("rule_engine.requests.get", side_effect=[risposta_repo, risposta_branch]), \
         patch("rule_engine.gh_scrivi", return_value=(False, "Errore 403: Resource not accessible by personal access token")):
        ok, msg = verifica_connessione_github("tok", "utente/repo", "main")

    assert ok is False
    assert "403" in msg or "scrittura" in msg.lower()


def test_verifica_connessione_ok_solo_se_la_scrittura_reale_riesce():
    from unittest.mock import patch, MagicMock
    from rule_engine import verifica_connessione_github

    risposta_repo = MagicMock(status_code=200)
    risposta_repo.json.return_value = {"permissions": {"push": True}}
    risposta_branch = MagicMock(status_code=200)

    with patch("rule_engine.requests.get", side_effect=[risposta_repo, risposta_branch]), \
         patch("rule_engine.gh_scrivi", return_value=(True, "Salvato su GitHub")):
        ok, msg = verifica_connessione_github("tok", "utente/repo", "main")

    assert ok is True
