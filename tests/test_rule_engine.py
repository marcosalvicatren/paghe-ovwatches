import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rule_engine import trova_regola, genera_mappatura_da_voci


def test_matching_usa_la_voce_stessa_se_contiene_e_vuoto():
    """La tabella semplice di mappatura non richiede di compilare un campo
    tecnico 'contiene' separato: il testo della Voce stessa funge da pattern."""
    regole = [{
        "id": "r1", "descrizione_regola": "Compensi amministratori soci (spa-srl)",
        "contiene": [], "non_contiene": [], "conto_override": "6801", "attiva": True,
        "priorita": 100, "scope_azienda": None,
    }]
    trovata = trova_regola("Compensi amministratori soci (spa-srl)", regole)
    assert trovata is not None
    assert trovata["conto_override"] == "6801"


def test_genera_mappatura_precompila_voci_nuove_senza_duplicare_esistenti():
    esistenti = [{
        "id": "bp-1", "descrizione_regola": "Trasferte", "contiene": ["trasferte"],
        "non_contiene": [], "conto_override": "", "attiva": True, "priorita": 100,
        "scope_azienda": None, "segno_atteso": "D", "note": "",
    }]
    voci = ["Trasferte", "Compensi amministratori soci (spa-srl)", "Trasferte"]  # con duplicato
    risultato = genera_mappatura_da_voci(voci, "buste_paga", esistenti)

    descrizioni = [r["descrizione_regola"] for r in risultato]
    assert descrizioni.count("Trasferte") == 1  # non duplicata
    assert "Compensi amministratori soci (spa-srl)" in descrizioni
    assert len(risultato) == 2  # 1 esistente + 1 nuova, non 3
