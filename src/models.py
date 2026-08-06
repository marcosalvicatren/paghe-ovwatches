"""Modelli dati tipizzati per il progetto Prima Nota Paghe/F24.

Tutti i dati che attraversano la pipeline (pagina PDF, riga estratta, regola,
movimento contabile...) sono rappresentati con dataclass esplicite, così da
avere tipizzazione e da poter tracciare sempre la provenienza di ogni dato
(pagina, testo originale, metodo di estrazione, affidabilità).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum


class TipoPagina(str, Enum):
    BILANCINO_PAGHE = "bilancino_paghe"
    F24 = "f24"
    ALTRO = "altro"
    DUPLICATO = "duplicato"  # pagina identica (o quasi) a un'altra già classificata


class MetodoEstrazione(str, Enum):
    TESTO_NATIVO = "testo_nativo"
    COORDINATE = "coordinate"  # estrazione basata su posizione x/y delle parole
    OCR = "ocr"


class DareAvere(str, Enum):
    DARE = "D"
    AVERE = "A"


@dataclass
class PaginaClassificata:
    numero: int
    tipo: TipoPagina
    affidabilita: float  # 0.0 - 1.0
    motivo: str  # perché è stata classificata così (per audit/debug)
    duplicato_di: int | None = None  # numero pagina "canonica" se è un duplicato


@dataclass
class CampoEstratto:
    """Un singolo valore estratto dal PDF, con provenienza tracciata."""
    valore: str
    pagina: int
    testo_originale: str
    metodo: MetodoEstrazione
    affidabilita: float
    corretto_manualmente: bool = False


@dataclass
class RigaBilancino:
    conto: str  # es. "68/05/150"
    descrizione: str
    importo: float
    da: DareAvere | None  # None = ambiguo, non dichiarato esplicitamente sul PDF
    sezione: str  # es. "RETRIBUZIONI E ALTRE COMPETENZE"
    pagina: int
    testo_originale: str
    ambigua: bool = False  # True se il D/A non era esplicito sul documento
    note: str = ""


@dataclass
class RigaF24:
    sezione: str  # erario | inps | regioni | imu | altri_enti
    codice: str  # codice tributo / causale contributo
    codice_sede: str = ""
    rateazione_mese: str = ""
    anno_riferimento: str = ""
    importo_debito: float = 0.0
    importo_credito: float = 0.0
    pagina: int = 0
    testo_originale: str = ""
    ambigua: bool = False
    note: str = ""


@dataclass
class RegolaContabile:
    id: str
    tipo_documento: str  # "buste_paga" | "f24"
    descrizione: str
    contiene: list[str] = field(default_factory=list)
    non_contiene: list[str] = field(default_factory=list)
    codice_tributo: str = ""
    sezione_f24: str = ""
    conto_dare: str = ""
    conto_avere: str = ""
    descrizione_conto: str = ""
    priorita: int = 100
    scope_azienda: str | None = None
    scope_cliente: str | None = None
    data_decorrenza: date | None = None
    data_cessazione: date | None = None
    origine: str = "utente"  # utente | importata | default
    creata_il: datetime | None = None
    modificata_il: datetime | None = None
    attiva: bool = True


@dataclass
class Eccezione:
    riga_originale: object  # RigaBilancino o RigaF24
    motivo: str  # "nessuna_regola" | "piu_regole" | "affidabilita_bassa" | "dati_mancanti"
    regole_candidate: list[str] = field(default_factory=list)
    risolta: bool = False
    conto_scelto: str = ""
    salva_come_regola: bool = False
    ambito_regola: str = ""  # solo_questa | stesso_cliente | stessa_descrizione | ...


@dataclass
class MovimentoContabile:
    conto: str
    descrizione: str
    importo: float
    da: DareAvere
    causale: str = "LA"
    pagina_origine: int = 0
    regola_applicata: str = ""
    codice_tributo: str = ""
    note: str = ""


@dataclass
class RegistrazioneContabile:
    tipo: str  # "paghe" | "f24"
    causale_contabile: str
    numero_documento: str
    data_documento: date
    data_registrazione: date
    movimenti: list[MovimentoContabile] = field(default_factory=list)

    @property
    def totale_dare(self) -> float:
        return round(sum(m.importo for m in self.movimenti if m.da == DareAvere.DARE), 2)

    @property
    def totale_avere(self) -> float:
        return round(sum(m.importo for m in self.movimenti if m.da == DareAvere.AVERE), 2)

    @property
    def quadrata(self) -> bool:
        return abs(self.totale_dare - self.totale_avere) < 0.005


@dataclass
class RisultatoValidazione:
    valido: bool
    errori: list[str] = field(default_factory=list)
    avvisi: list[str] = field(default_factory=list)


@dataclass
class ReportElaborazione:
    nome_file: str
    data_elaborazione: datetime
    n_pagine_totali: int = 0
    pagine_bilancino: list[int] = field(default_factory=list)
    pagine_f24: list[int] = field(default_factory=list)
    pagine_ignorate: list[int] = field(default_factory=list)
    n_movimenti_paghe: int = 0
    n_movimenti_f24: int = 0
    eccezioni_aperte: int = 0
    eccezioni_risolte: int = 0
    quadratura_paghe: bool | None = None
    quadratura_f24: bool | None = None
    validazione_xml_paghe: bool | None = None
    validazione_xml_f24: bool | None = None
    avvisi: list[str] = field(default_factory=list)
    errori: list[str] = field(default_factory=list)
