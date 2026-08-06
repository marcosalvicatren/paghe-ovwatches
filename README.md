# Prima Nota Paghe & F24

Estrae i dati da un PDF multipagina (bilancino paga + modelli F24), applica
regole di contabilizzazione configurabili e genera file XML importabili nel
gestionale (tracciato `PrimaNotaXsd`, GB Software / Wolters Kluwer).

**Buste paga e F24 sono due funzionalità indipendenti**: pagine diverse dello
stesso PDF, regole separate, due file XML separati in export.

> Stato del progetto: prototipo funzionante (Fase 2 del piano di sviluppo),
> validato sui file di esempio reali in `tests/fixtures/`. Vedi
> [Limitazioni note](#limitazioni-note) prima di un uso in produzione.

## Avvio rapido

```bash
git clone <url-del-repo>
cd prima_nota_paghe
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Per eseguire i test:

```bash
pytest tests/ -v
```

Per validare rapidamente la pipeline da riga di comando (senza aprire il
browser), utile dopo aver modificato una regola o il codice:

```bash
python scripts/validate_sample_files.py
```

### Sincronizzazione delle regole su GitHub (opzionale)

Le regole vivono in `config/rules_buste_paga.json` e `config/rules_f24.json`.
Se si preferisce gestirle tramite commit automatici su un repository GitHub
(come nel prototipo di partenza), copiare `.env.example` in
`.streamlit/secrets.toml` e compilare:

```toml
GITHUB_TOKEN = "..."
GITHUB_REPO = "utente/nome-repo"
GITHUB_BRANCH = "main"
```

Senza questa configurazione l'app funziona comunque: le regole vengono
lette/scritte in locale sotto `config/`.

## Struttura del progetto

```
app.py                     interfaccia Streamlit (4 sezioni)
src/
  models.py                dataclass tipizzate condivise
  pdf_classifier.py        classificazione automatica pagine + dedup
  payroll_parser.py        estrazione righe dal bilancino paga
  f24_parser.py            estrazione righe dall'F24 (basata su coordinate)
  rule_engine.py           matching regole + persistenza (locale/GitHub)
  accounting_builder.py    costruzione scritture, eccezioni, quadratura
  xml_generator.py         generazione XML conforme al tracciato
  xml_validator.py         validazione contro lo XSD reale
config/
  rules_buste_paga.json    regole per il bilancino paga
  rules_f24.json           regole per l'F24
  settings.yaml            impostazioni generali
  schema/                  XSD e XML di esempio del gestionale (di riferimento)
tests/
  fixtures/                PDF di esempio (anonimizzato/di test)
  test_*.py                test di regressione, uno per ciascun bug trovato
scripts/
  validate_sample_files.py validazione rapida da riga di comando
```

## Come funzionano le regole

Ogni riga estratta dal PDF viene cercata in `config/rules_*.json`. Una
regola definisce un pattern (`contiene`/`non_contiene`, case-insensitive) e
un conto/segno da applicare. Regole con `scope_azienda` specifico vincono su
quelle generali; a parità di scope vince quella con `priorita` più alta.

```json
{
  "id": "bp-0001",
  "contiene": ["compensi amministratori"],
  "non_contiene": [],
  "segno_atteso": "D",
  "conto_override": "68/05/150",
  "priorita": 100,
  "scope_azienda": null,
  "attiva": true,
  "note": ""
}
```

**Importante**: per il bilancino paga, il conto e il Dare/Avere sono già
presenti riga per riga sul documento originale (il software paghe li calcola
già). Una regola serve solo per:

1. **rimappare** un codice conto del software paghe su un codice diverso nel
   piano dei conti del gestionale (senza regola, il conto passa invariato);
2. **risolvere righe ambigue** — voci senza D/A esplicito sul documento
   (es. rimborsi, trasferte): senza una regola attiva, restano in "Eccezioni"
   e non entrano nell'XML;
3. **assegnare un conto alle righe F24**, che di per sé non hanno un conto
   (l'F24 è una dichiarazione fiscale, non un prospetto contabile) — qui
   `config/rules_f24.json` parte vuoto e va popolato dall'interfaccia.

### Aggiungere una nuova regola

Dall'interfaccia, sezione "Eccezioni" di Buste paga o F24: si compila conto e
Dare/Avere per la riga non riconosciuta, si sceglie l'ambito (solo questa
registrazione, o regola persistente), e si salva. La regola diventa
immediatamente attiva per le elaborazioni successive. In alternativa si può
modificare `config/rules_*.json` a mano, o dalla tabella nella sezione
"Regole" dell'app.

### Aggiungere un nuovo formato di bilancino o F24

I parser (`payroll_parser.py`, `f24_parser.py`) si basano su pattern
strutturali del documento (codice conto `NN/NN/NNN` per il bilancino,
posizione delle colonne "debito"/"credito" per l'F24), non su coordinate
fisse pagina per pagina: dovrebbero reggere variazioni minori di layout dello
stesso tracciato. Un formato radicalmente diverso (es. bilancino di un altro
software paghe) richiede quasi certamente un nuovo parser dedicato — i
modelli in `models.py` sono già pensati per essere riusati.

### Aggiornare il tracciato XML

Sostituire `config/schema/SchemaImportazionePrimaNotaV2.xsd` con la nuova
versione e adattare `xml_generator.py` alla struttura aggiornata; il
validatore (`xml_validator.py`) userà automaticamente il nuovo schema.

## Limitazioni note

Onestamente, cosa manca rispetto a un uso professionale ricorrente completo:

- **Un solo documento reale disponibile per lo sviluppo**: le regole di
  esempio coprono solo il caso osservato (un collaboratore, sezioni Erario e
  INPS dell'F24). Le sezioni Regioni/IMU/Altri enti dell'F24 sono
  implementate strutturalmente ma **mai validate** su un caso reale.
- **Le 3 righe ambigue del bilancino** (Trasferte, Rimborsi chilometrici,
  Netto in busta) hanno una regola *proposta ma disattivata* in
  `config/rules_buste_paga.json`, dedotta per via aritmetica dalla
  quadratura — va rivista e attivata consapevolmente, non è un dato
  dichiarato sul documento.
- **Il blocco "Contributi datore di lavoro"** del bilancino (280,20 + 140,16
  + 243,76 + 1,96 €, tutti a Dare) non ha una contropartita esplicita sul
  documento: serve il piano dei conti reale o un esempio di registrazione
  corretta per sapere quale conto di debito v/INPS-Erario usare.
- **Nessuna gestione multi-reparto reale**: la deduplica delle pagine
  bilancino confronta gli importi, ma non è stata testata su un'azienda con
  più reparti con importi effettivamente diversi tra loro.
- **Nessun import del piano dei conti** (CSV/Excel) ancora implementato:
  i conti si scrivono a mano nelle regole.
- **Nessuna modalità CLI completa** (`python -m src.main --input ... `):
  esiste solo lo script di validazione rapida in `scripts/`.
- **Nessun Dockerfile** ancora.
- **OCR non implementato**: se un PDF è scansionato (senza testo nativo), i
  parser sollevano un errore esplicito invece di tentare l'estrazione.

## Sicurezza e riservatezza

- L'elaborazione è locale: nessun PDF viene inviato a servizi esterni.
- I PDF caricati vengono scritti in un file temporaneo di sistema per la
  durata della sessione; non vengono conservati automaticamente.
- `.env`/`secrets.toml` con eventuale token GitHub sono esclusi da Git
  tramite `.gitignore` — non committarli mai con valori reali.
- Evitare di caricare PDF con dati reali in un repository pubblico: usare
  `tests/fixtures/` solo per documenti già anonimizzati.
