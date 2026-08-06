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


def test_ambito_round_trip():
    from rule_engine import ambito_da_scope, scope_da_ambito, AMBITO_GENERALE, AMBITO_AZIENDA, AMBITO_REGISTRAZIONE

    assert ambito_da_scope(None, None) == AMBITO_GENERALE
    assert ambito_da_scope("OVWATCHES", None) == AMBITO_AZIENDA
    assert ambito_da_scope("OVWATCHES", "Gennaio 2026") == AMBITO_REGISTRAZIONE

    assert scope_da_ambito(AMBITO_GENERALE, "OVWATCHES", "Gennaio 2026") == (None, None)
    assert scope_da_ambito(AMBITO_AZIENDA, "OVWATCHES", "Gennaio 2026") == ("OVWATCHES", None)
    assert scope_da_ambito(AMBITO_REGISTRAZIONE, "OVWATCHES", "Gennaio 2026") == ("OVWATCHES", "Gennaio 2026")


def test_regola_specifica_per_registrazione_vince_su_azienda_e_generale():
    generale = {"id": "g", "descrizione_regola": "Compensi", "contiene": [], "non_contiene": [],
                "conto_override": "1111", "attiva": True, "priorita": 100,
                "scope_azienda": None, "scope_periodo": None}
    per_azienda = {"id": "a", "descrizione_regola": "Compensi", "contiene": [], "non_contiene": [],
                    "conto_override": "2222", "attiva": True, "priorita": 100,
                    "scope_azienda": "OVWATCHES", "scope_periodo": None}
    per_registrazione = {"id": "r", "descrizione_regola": "Compensi", "contiene": [], "non_contiene": [],
                          "conto_override": "3333", "attiva": True, "priorita": 100,
                          "scope_azienda": "OVWATCHES", "scope_periodo": "Gennaio 2026"}
    regole = [generale, per_azienda, per_registrazione]

    trovata = trova_regola("Compensi", regole, scope_azienda="OVWATCHES", scope_periodo="Gennaio 2026")
    assert trovata["conto_override"] == "3333"

    # in un periodo diverso, quella per-registrazione non si applica: vince quella per azienda
    trovata2 = trova_regola("Compensi", regole, scope_azienda="OVWATCHES", scope_periodo="Febbraio 2026")
    assert trovata2["conto_override"] == "2222"
