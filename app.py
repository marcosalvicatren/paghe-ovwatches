#!/usr/bin/env python3
"""Prima Nota Paghe & F24 — GB Software / Wolters Kluwer.

Due funzionalità indipendenti (registrazione paghe, registrazione F24), a
partire da un unico PDF multipagina. Le pagine vengono classificate
automaticamente; le regole di contabilizzazione sono in config/rules_*.json
(sincronizzabili su GitHub se GITHUB_TOKEN/GITHUB_REPO sono configurati nei
secrets di Streamlit, altrimenti gestite in locale).
"""

import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

import streamlit as st
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent / "src"))

from models import TipoPagina, DareAvere  # noqa: E402
from pdf_classifier import classifica_pdf  # noqa: E402
from payroll_parser import estrai_bilancino  # noqa: E402
from f24_parser import estrai_f24  # noqa: E402
from rule_engine import carica_regole, salva_regole, genera_mappatura_da_voci  # noqa: E402
from accounting_builder import (  # noqa: E402
    costruisci_registrazione_paghe, costruisci_registrazione_f24, verifica_quadratura,
)
from xml_generator import genera_xml  # noqa: E402
from xml_validator import valida_contro_xsd  # noqa: E402

st.set_page_config(page_title="Prima Nota Paghe & F24", page_icon="📋", layout="wide")

st.markdown("""
<style>
.stButton > button { border-radius: 4px; font-weight: 500; }
.section-header { border-left: 3px solid #0f1923; padding: 6px 0 6px 14px; margin: 20px 0 10px 0; font-weight: 600; }
</style>
""", unsafe_allow_html=True)


def _gh_config():
    # st.secrets solleva un'eccezione (non restituisce un dict vuoto) quando
    # non esiste affatto un secrets.toml — capita per chi esegue l'app in
    # locale senza aver configurato la sync GitHub, quindi va gestito, non
    # lasciato propagare.
    try:
        return (
            st.secrets.get("GITHUB_TOKEN", "") or None,
            st.secrets.get("GITHUB_REPO", "") or None,
            st.secrets.get("GITHUB_BRANCH", "main"),
        )
    except Exception:
        return None, None, "main"


def _sezione(titolo):
    st.markdown(f'<div class="section-header">{titolo}</div>', unsafe_allow_html=True)


for chiave, default in [
    ("pdf_path", None), ("pdf_name", None), ("classificazione", None),
    ("bp_righe", None), ("bp_mese", ""), ("bp_azienda", ""),
    ("f24_righe", None), ("f24_saldo", None),
    ("regole_bp", None), ("regole_f24", None),
]:
    if chiave not in st.session_state:
        st.session_state[chiave] = default


# ─────────────────────────────────────────────────────────────────────────
# SIDEBAR — caricamento PDF + navigazione
# ─────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("### 📋 Prima Nota Paghe & F24")
    st.caption("GB Software · Wolters Kluwer")
    st.divider()

    pdf_file = st.file_uploader("PDF multipagina", type=["pdf"])
    if pdf_file is not None and pdf_file.name != st.session_state.pdf_name:
        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        tmp.write(pdf_file.read())
        tmp.close()
        st.session_state.pdf_path = tmp.name
        st.session_state.pdf_name = pdf_file.name
        st.session_state.classificazione = None  # forza ri-classificazione
        st.session_state.bp_righe = None
        st.session_state.f24_righe = None

    azienda_input = st.text_input("Azienda / cliente (per regole specifiche)", value=st.session_state.bp_azienda)
    st.session_state.bp_azienda = azienda_input

    st.divider()
    pagina_scelta = st.radio(
        "Sezione", ["Analisi pagine", "Buste paga", "F24", "Regole"], label_visibility="collapsed"
    )

    st.divider()
    token, repo, branch = _gh_config()
    if repo:
        st.caption(f"Regole sincronizzate su GitHub: `{repo}` ({branch})")
    else:
        st.caption("GitHub non configurato — le regole sono salvate in `config/rules_*.json` in locale.")


if st.session_state.pdf_path is None:
    st.info("Carica un PDF dalla barra laterale per iniziare.")
    st.stop()


# ─────────────────────────────────────────────────────────────────────────
# SEZIONE — ANALISI PAGINE
# ─────────────────────────────────────────────────────────────────────────

def pagina_analisi():
    st.title("Analisi pagine")

    if st.session_state.classificazione is None or st.button("🔄 Ri-classifica pagine"):
        with st.spinner("Analisi del PDF..."):
            st.session_state.classificazione = classifica_pdf(st.session_state.pdf_path)

    classificate = st.session_state.classificazione
    df = pd.DataFrame([{
        "Pagina": p.numero,
        "Tipo": p.tipo.value,
        "Affidabilità": p.affidabilita,
        "Motivo": p.motivo,
    } for p in classificate])

    st.caption(
        "Classificazione automatica. Le pagine 'duplicato' sono copie identiche (o quasi) di un'altra "
        "pagina già classificata — es. le copie multiple dell'F24, o un bilancino ristampato con gli "
        "stessi importi — e non vengono usate per evitare doppi conteggi."
    )
    edited = st.data_editor(
        df,
        column_config={
            "Tipo": st.column_config.SelectboxColumn(
                "Tipo", options=[t.value for t in TipoPagina], width="medium"
            ),
            "Affidabilità": st.column_config.ProgressColumn("Affidabilità", min_value=0, max_value=1, format="%.2f"),
        },
        disabled=["Pagina", "Motivo"],
        width='stretch', hide_index=True, key="editor_pagine",
    )

    n_bp = (edited["Tipo"] == TipoPagina.BILANCINO_PAGHE.value).sum()
    n_f24 = (edited["Tipo"] == TipoPagina.F24.value).sum()
    c1, c2, c3 = st.columns(3)
    c1.metric("Pagine bilancino paga", int(n_bp))
    c2.metric("Pagine F24", int(n_f24))
    c3.metric("Pagine totali", len(edited))

    if st.button("💾 Applica riclassificazione manuale"):
        tipi_per_pagina = dict(zip(edited["Pagina"], edited["Tipo"]))
        for p in st.session_state.classificazione:
            p.tipo = TipoPagina(tipi_per_pagina[p.numero])
        st.success("Classificazione aggiornata.")
        st.rerun()


def _pagine_disponibili(tipo: TipoPagina) -> list[int]:
    if not st.session_state.classificazione:
        return []
    return [p.numero for p in st.session_state.classificazione if p.tipo == tipo]


# ─────────────────────────────────────────────────────────────────────────
# SEZIONE — BUSTE PAGA
# ─────────────────────────────────────────────────────────────────────────

def _gestisci_eccezioni(eccezioni, tipo_documento, regole, key_prefix):
    if not eccezioni:
        st.success("Nessuna eccezione: tutte le righe hanno trovato una regola.")
        return
    st.warning(f"{len(eccezioni)} riga/e senza regola attiva — richiedono una decisione.")
    for i, ecc in enumerate(eccezioni):
        r = ecc.riga_originale
        etichetta = getattr(r, "descrizione", None) or getattr(r, "codice", "?")
        with st.expander(f"⚠ {etichetta}  —  {ecc.motivo}", expanded=False):
            st.write(f"**Testo originale:** `{r.testo_originale}`")
            st.write(f"**Pagina:** {r.pagina}")
            if hasattr(r, "importo"):
                st.write(f"**Importo:** € {r.importo:.2f}")
            if ecc.regole_candidate:
                st.info(f"Regole candidate in conflitto: {', '.join(ecc.regole_candidate)}")

            c1, c2, c3 = st.columns(3)
            conto = c1.text_input("Conto nel gestionale", key=f"{key_prefix}_conto_{i}")
            da = c2.selectbox("Dare/Avere", ["D", "A"], key=f"{key_prefix}_da_{i}")
            ambito = c3.selectbox(
                "Applica a",
                ["Solo questa registrazione", "Stessa descrizione (regola generale)",
                 f"Stessa descrizione, solo per '{st.session_state.bp_azienda}'" if st.session_state.bp_azienda else "Stessa descrizione, solo questa azienda"],
                key=f"{key_prefix}_ambito_{i}",
            )
            if st.button("✅ Applica e salva come regola", key=f"{key_prefix}_salva_{i}") and conto:
                pattern = getattr(r, "descrizione", None) or getattr(r, "codice", "")
                nuova_regola = {
                    "id": f"{key_prefix}-{abs(hash(pattern)) % 100000}",
                    "tipo_documento": tipo_documento,
                    "descrizione_regola": pattern,
                    "contiene": [pattern.lower()[:40]],
                    "non_contiene": [],
                    "segno_atteso": da,
                    "conto_override": conto,
                    "priorita": 100,
                    "scope_azienda": st.session_state.bp_azienda if "azienda" in ambito.lower() and "solo" in ambito.lower() else None,
                    "origine": "utente",
                    "attiva": True,
                    "creata_il": datetime.now().isoformat(timespec="seconds"),
                    "note": "" if ambito.startswith("Solo questa") else "regola persistente creata da risoluzione eccezione",
                }
                if ambito.startswith("Solo questa"):
                    st.info("Applicata solo a questa registrazione (non salvata come regola persistente). "
                            "Rigenera l'XML per includerla.")
                else:
                    regole.append(nuova_regola)
                    token, repo, branch = _gh_config()
                    ok, msg = salva_regole(tipo_documento, regole, token, repo, branch,
                                            f"Nuova regola: {pattern}")
                    (st.success if ok else st.error)(msg)
                    st.rerun()


def pagina_buste_paga():
    st.title("📋 Buste paga → Prima Nota")

    pagine_bp = _pagine_disponibili(TipoPagina.BILANCINO_PAGHE)
    if not pagine_bp:
        st.warning("Nessuna pagina classificata come bilancino paga. Controlla la sezione 'Analisi pagine'.")
        return

    _sezione("Passo 1 — Estrazione")
    pagina_num = st.selectbox("Pagina del bilancino da usare", pagine_bp)
    if st.button("▶ Estrai voci", width='stretch') or st.session_state.bp_righe is None:
        try:
            mese, az, righe = estrai_bilancino(st.session_state.pdf_path, pagina_num)
            st.session_state.bp_righe = righe
            st.session_state.bp_mese = mese
            if az and not st.session_state.bp_azienda:
                st.session_state.bp_azienda = az
        except ValueError as e:
            st.error(str(e))
            return

    righe = st.session_state.bp_righe
    if not righe:
        return

    st.caption(f"Periodo: **{st.session_state.bp_mese}**  ·  Azienda: **{st.session_state.bp_azienda or '(non specificata)'}**")

    token, repo, branch = _gh_config()
    if st.session_state.regole_bp is None:
        st.session_state.regole_bp = carica_regole("buste_paga", token, repo, branch)
    regole = st.session_state.regole_bp

    data_doc = st.date_input("Data registrazione", value=date.today().replace(day=1))

    reg, eccezioni = costruisci_registrazione_paghe(
        righe, regole, data_doc, scope_azienda=st.session_state.bp_azienda or None
    )

    _sezione("Passo 2 — Anteprima scrittura")
    df_mov = pd.DataFrame([{
        "Conto": m.conto, "Descrizione": m.descrizione, "Importo": m.importo,
        "D/A": m.da.value, "Regola": m.regola_applicata, "Pagina": m.pagina_origine,
    } for m in reg.movimenti])
    st.dataframe(df_mov, width='stretch', hide_index=True)

    c1, c2, c3 = st.columns(3)
    c1.metric("Totale Dare", f"€ {reg.totale_dare:,.2f}")
    c2.metric("Totale Avere", f"€ {reg.totale_avere:,.2f}")
    c3.metric("Quadratura", "✅ OK" if reg.quadrata else "❌ Non quadrata")

    _sezione("Passo 3 — Eccezioni")
    _gestisci_eccezioni(eccezioni, "buste_paga", regole, "bp")

    _sezione("Passo 4 — Esportazione XML")
    esito = verifica_quadratura(reg, eccezioni)
    for a in esito.avvisi:
        st.warning(a)
    for e in esito.errori:
        st.error(e)

    forza = False
    if not esito.valido:
        forza = st.checkbox("⚠ Genera comunque l'XML nonostante gli errori sopra (a mio rischio)")

    if st.button("⚡ Genera XML", disabled=not (esito.valido or forza), width='stretch'):
        xml_bytes = genera_xml(reg)
        esito_xsd = valida_contro_xsd(xml_bytes)
        if esito_xsd.valido:
            st.success("XML generato e validato contro lo schema XSD del gestionale.")
        else:
            st.error("XML generato ma NON conforme allo schema XSD:\n" + "\n".join(esito_xsd.errori))
        st.download_button(
            "⬇ Scarica prima_nota_paghe.xml", data=xml_bytes,
            file_name=f"prima_nota_paghe_{st.session_state.bp_mese.replace(' ', '_') or 'export'}.xml",
            mime="application/xml", width='stretch',
        )
        with st.expander("Anteprima XML"):
            st.code(xml_bytes.decode("utf-8"), language="xml")


# ─────────────────────────────────────────────────────────────────────────
# SEZIONE — F24
# ─────────────────────────────────────────────────────────────────────────

def pagina_f24():
    st.title("🏦 F24 → Prima Nota")

    pagine_f24 = _pagine_disponibili(TipoPagina.F24)
    if not pagine_f24:
        st.warning("Nessuna pagina classificata come F24. Controlla la sezione 'Analisi pagine'.")
        return

    _sezione("Passo 1 — Estrazione")
    pagina_num = st.selectbox("Copia dell'F24 da usare", pagine_f24)
    if st.button("▶ Estrai voci F24", width='stretch') or st.session_state.f24_righe is None:
        try:
            righe, saldo = estrai_f24(st.session_state.pdf_path, pagina_num)
            st.session_state.f24_righe = righe
            st.session_state.f24_saldo = saldo
        except ValueError as e:
            st.error(str(e))
            return

    righe = st.session_state.f24_righe
    if not righe:
        return

    if st.session_state.f24_saldo is not None:
        st.caption(f"Saldo finale dichiarato sul modulo: **€ {st.session_state.f24_saldo:,.2f}**")

    token, repo, branch = _gh_config()
    if st.session_state.regole_f24 is None:
        st.session_state.regole_f24 = carica_regole("f24", token, repo, branch)
    regole = st.session_state.regole_f24

    c1, c2 = st.columns(2)
    data_pag = c1.date_input("Data pagamento", value=date.today())
    conto_contropartita = c2.text_input("Conto contropartita (es. banca)", value="")

    reg, eccezioni = costruisci_registrazione_f24(
        righe, regole, conto_contropartita, data_pag,
        scope_azienda=st.session_state.bp_azienda or None,
    )

    _sezione("Passo 2 — Anteprima scrittura")
    df_mov = pd.DataFrame([{
        "Conto": m.conto, "Descrizione": m.descrizione, "Codice tributo": m.codice_tributo,
        "Importo": m.importo, "D/A": m.da.value,
    } for m in reg.movimenti])
    st.dataframe(df_mov, width='stretch', hide_index=True)

    c1, c2, c3 = st.columns(3)
    c1.metric("Totale Dare", f"€ {reg.totale_dare:,.2f}")
    c2.metric("Totale Avere", f"€ {reg.totale_avere:,.2f}")
    c3.metric("Quadratura", "✅ OK" if reg.quadrata else "❌ Non quadrata")

    _sezione("Passo 3 — Eccezioni")
    _gestisci_eccezioni(eccezioni, "f24", regole, "f24")

    _sezione("Passo 4 — Esportazione XML")
    esito = verifica_quadratura(reg, eccezioni)
    for a in esito.avvisi:
        st.warning(a)
    for e in esito.errori:
        st.error(e)
    if not conto_contropartita:
        st.info("Imposta il conto contropartita (es. banca) per chiudere la scrittura.")

    forza = False
    if not esito.valido:
        forza = st.checkbox("⚠ Genera comunque l'XML nonostante gli errori sopra (a mio rischio)", key="forza_f24")

    if st.button("⚡ Genera XML", disabled=not (esito.valido or forza), width='stretch', key="genera_f24"):
        xml_bytes = genera_xml(reg)
        esito_xsd = valida_contro_xsd(xml_bytes)
        if esito_xsd.valido:
            st.success("XML generato e validato contro lo schema XSD del gestionale.")
        else:
            st.error("XML generato ma NON conforme allo schema XSD:\n" + "\n".join(esito_xsd.errori))
        st.download_button(
            "⬇ Scarica prima_nota_f24.xml", data=xml_bytes,
            file_name=f"prima_nota_f24_{data_pag.isoformat()}.xml",
            mime="application/xml", width='stretch',
        )
        with st.expander("Anteprima XML"):
            st.code(xml_bytes.decode("utf-8"), language="xml")


# ─────────────────────────────────────────────────────────────────────────
# SEZIONE — REGOLE
# ─────────────────────────────────────────────────────────────────────────

def pagina_regole():
    st.title("⚙️ Mappatura voci → conti del gestionale")
    st.caption(
        "Il PDF paghe usa i codici conto del software paghe: NON sono gli stessi conti del tuo "
        "gestionale. Per ogni voce indica qui il conto corretto del gestionale — finché una voce "
        "non ha un conto, resta in 'Eccezioni' e non entra nell'XML."
    )
    token, repo, branch = _gh_config()

    tab_bp, tab_f24 = st.tabs(["Buste paga", "F24"])
    for tab, tipo, chiave, righe_chiave in [
        (tab_bp, "buste_paga", "regole_bp", "bp_righe"),
        (tab_f24, "f24", "regole_f24", "f24_righe"),
    ]:
        with tab:
            if st.session_state[chiave] is None:
                st.session_state[chiave] = carica_regole(tipo, token, repo, branch)

            # precompila con le voci reali già estratte in questa sessione,
            # così la tabella non parte vuota: mostra esattamente le voci
            # del TUO PDF, non un elenco astratto.
            righe_estratte = st.session_state.get(righe_chiave)
            if righe_estratte:
                campo = "descrizione" if tipo == "buste_paga" else "codice"
                voci = [getattr(r, campo) for r in righe_estratte]
                st.session_state[chiave] = genera_mappatura_da_voci(voci, tipo, st.session_state[chiave])

            df = pd.DataFrame(st.session_state[chiave])
            for col in ["descrizione_regola", "conto_override", "segno_atteso", "attiva",
                        "contiene", "non_contiene", "priorita", "scope_azienda", "note"]:
                if col not in df.columns:
                    df[col] = "" if col not in ("attiva", "priorita") else (True if col == "attiva" else 100)
            df["contiene"] = df["contiene"].apply(lambda x: ", ".join(x) if isinstance(x, list) else x)
            df["non_contiene"] = df["non_contiene"].apply(lambda x: ", ".join(x) if isinstance(x, list) else x)

            n_da_mappare = int((df["conto_override"].astype(str).str.strip() == "").sum())
            if n_da_mappare:
                st.warning(f"{n_da_mappare} voce/i ancora senza conto del gestionale.")
            else:
                st.success("Tutte le voci hanno un conto assegnato.")

            avanzate = st.checkbox("Mostra colonne avanzate (pattern, priorità, azienda specifica...)",
                                    key=f"avanzate_{tipo}")
            colonne_semplici = ["descrizione_regola", "conto_override", "segno_atteso", "attiva"]
            colonne_avanzate = colonne_semplici + ["contiene", "non_contiene", "priorita", "scope_azienda", "note"]

            edited = st.data_editor(
                df,
                column_order=colonne_avanzate if avanzate else colonne_semplici,
                column_config={
                    "descrizione_regola": st.column_config.TextColumn(
                        "Voce (come compare nel PDF)", width="large", disabled=(not avanzate)),
                    "conto_override": st.column_config.TextColumn(
                        "Conto nel gestionale", width="medium",
                        help="Il conto corretto nel TUO gestionale per questa voce. Lascia vuoto se non sai ancora quale usare."),
                    "segno_atteso": st.column_config.SelectboxColumn(
                        "Dare/Avere", options=["", "D", "A"],
                        help="Da compilare solo se questa voce non ha già un D/A esplicito sul PDF."),
                    "attiva": st.column_config.CheckboxColumn("Attiva"),
                    "contiene": st.column_config.TextColumn("Pattern aggiuntivo (avanzato)", width="medium"),
                    "non_contiene": st.column_config.TextColumn("NON contiene (avanzato)", width="medium"),
                    "priorita": st.column_config.NumberColumn("Priorità"),
                    "scope_azienda": st.column_config.TextColumn("Solo per azienda (vuoto = tutte)"),
                },
                num_rows="dynamic", width='stretch', key=f"editor_{tipo}",
            )
            if st.button(f"💾 Salva mappatura {tipo}", width='stretch', key=f"salva_{tipo}"):
                nuove = edited.to_dict("records")
                for r in nuove:
                    r["contiene"] = [x.strip() for x in str(r.get("contiene", "")).split(",") if x.strip()]
                    r["non_contiene"] = [x.strip() for x in str(r.get("non_contiene", "")).split(",") if x.strip()]
                st.session_state[chiave] = nuove
                ok, msg = salva_regole(tipo, nuove, token, repo, branch, f"Aggiornamento mappatura {tipo}")
                (st.success if ok else st.error)(msg)


# ─────────────────────────────────────────────────────────────────────────

{
    "Analisi pagine": pagina_analisi,
    "Buste paga": pagina_buste_paga,
    "F24": pagina_f24,
    "Regole": pagina_regole,
}[pagina_scelta]()
