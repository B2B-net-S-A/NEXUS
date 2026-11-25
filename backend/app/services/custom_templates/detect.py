"""Wykrywanie pól we wgranym Wordzie: wzór działu → szablon docxtpl + lista pól.

Te same klocki co buildery wzorów z repo (``docx_ops``), ale zamiast reguł
pisanych pod jeden wzór — ogólne rozpoznanie:

* ``____``, ``……``, ``.....`` i ``[nr umowy]`` w tekście → pole; etykietę
  i rodzaj podpowiada tekst tuż przed luką („NIP: ____” → ``partner.nip``
  z CEIDG, „w dniu ____” → data, „kwotę ____ zł” → kwota, a luka po
  „słownie:” → ``{{ kwota_words }}`` liczone przez kod),
* akapit z samymi kreskami/kropkami pod etykietą („Agenda:”) → pole
  wielowierszowe z etykietą z akapitu wyżej; kreski przy podpisach zostają,
* formy „Panem/ią”, „Pan/Pani”, „prowadzącym/cą”, „zwany/ą” → ``{{ g.* }}``
  i pole „Płeć Partnera”,
* gotowe ``{{ pole }}`` we wgranym pliku zostają i trafiają na listę pól.

Wynik zawsze sprawdza ``sandbox.validate``; to, czego kod nie rozpoznał,
trafia do ``warnings`` (np. forma „/a”, której nie zna, albo NIP wyglądający
na dane prawdziwej osoby).
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

import docx
from docx.text.paragraph import Paragraph

from app.services.b2b_documents.company_party import COMPANY_PL
from app.services.custom_templates.base import fields_from_paths
from app.services.custom_templates.docx_ops import (
    _JINJA,
    paragraphs,
    replace_span,
    scrub_package,
    sub_para,
)
from app.services.custom_templates.fields import CustomField
from app.services.custom_templates.sandbox import check_package, discover

#: Luka do wypełnienia. Pojedynczy „…” w prozie („(…)”) to wielokropek, nie pole.
BLANK = re.compile(r"_{3,}|(?:…\s?){2,}|\.{4,}|\[(?!\s)[^\[\]{}]{2,40}\]")
_ONLY_BLANK = re.compile(r"^[\s_.…\t]+$")
_SIGNATURE = re.compile(
    r"podpis|\(\s*(zamawiając|partner|zleceniodawc|wykonawc|spółk)|"
    r"za\s+(zamawiającego|partnera)|pieczęć",
    re.I,
)

#: Formy rodzajowe wzoru → klucz ``g.*`` (kolejność: dłuższe najpierw).
GENDER_FORMS: tuple[tuple[str, str], ...] = (
    (r"Pan(?:em)?\s*/\s*(?:Panią|ią)", "g.g_pan"),
    (r"Pan\s*/\s*Pani\b", "g.g_pan_nom"),
    (r"prowadzącym\s*/\s*(?:cą|ą|prowadzącą)", "g.g_prowadzacy"),
    (r"prowadzący\s*/\s*(?:ca|a|prowadząca)\b", "g.g_prowadzacy_nom"),
    (r"zwanym\s*/\s*(?:ą|zwaną)", "g.g_zwanym"),
    (r"zwany\s*/\s*(?:a|na|zwana)\b", "g.g_zwany"),
    (r"zamieszkałym\s*/\s*(?:ą|łą)", "g.g_zamieszkaly"),
    (r"wpisanym\s*/\s*(?:ą|ną)", "g.g_wpisany"),
    (r"zapoznałem\s*/\s*(?:am|łam)", "g.g_zapoznal"),
)
_GENDER_LEFT = re.compile(r"\b\w+\s*/\s*(?:ą|ią|cą|a|i|na)\b")

#: Etykieta luki → (klucz, etykieta, rodzaj, źródło). Pierwsze trafienie wygrywa.
LABEL_RULES: tuple[tuple[re.Pattern, str, str, str, str], ...] = tuple(
    (re.compile(p, re.I), k, label, kind, source)
    for p, k, label, kind, source in (
        (r"\bNIP\b", "partner.nip", "NIP", "text", "ceidg"),
        (r"\bREGON\b", "partner.regon", "REGON", "text", "ceidg"),
        (r"\bKRS\b", "partner.krs", "KRS", "text", "ceidg"),
        (r"\bPESEL\b", "partner.pesel", "PESEL", "text", "manual"),
        (r"e-?mail", "partner.email", "E-mail Partnera", "email", "candidate"),
        (r"\btel(efon|\.)", "partner.phone", "Telefon Partnera", "text", "candidate"),
        (
            r"pod\s+firmą|\bfirm[aąy]\b",
            "partner.legal_name",
            "Firma (CEIDG)",
            "text",
            "ceidg",
        ),
        (
            r"adres|siedzib[aąy]\s*:|z\s+siedzibą",
            "partner.business_address",
            "Adres firmy",
            "text",
            "ceidg",
        ),
        (r"klient|zamawiającego\s+końcow", "client.name", "Klient", "text", "clients"),
        (
            r"\b(pan[ae]?m?|pani[ąa]?|imi[eę]\s+i\s+nazwisk)",
            "partner.name",
            "Imię i nazwisko",
            "text",
            "candidate",
        ),
    )
)
_DATE = re.compile(r"w\s+dniu|\bdnia\b|\bdata\b|\bod\b|\bdo\b|termin", re.I)
_MONEY = re.compile(r"kwot|wynagrodzeni|stawk|zł|PLN|netto|brutto|ryczałt|limit", re.I)
_WORDS = re.compile(r"słownie", re.I)
_PERSONAL = (
    (re.compile(r"\b\d{11}\b"), "numer wyglądający na PESEL"),
    (re.compile(r"\b\d{3}-?\d{3}-?\d{2}-?\d{2}\b"), "numer wyglądający na NIP"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "adres e-mail"),
)


@dataclass
class Detection:
    docx: bytes
    fields: list[CustomField]
    warnings: list[str] = field(default_factory=list)
    #: Ile luk zamieniono na pola (do opisu „pola: 11”).
    blanks: int = 0


@dataclass
class _State:
    fields: dict[str, CustomField] = field(default_factory=dict)
    counters: dict[str, int] = field(default_factory=dict)
    last_money: str | None = None
    has_document_date: bool = False
    gender: bool = False
    warnings: list[str] = field(default_factory=list)
    blanks: int = 0

    def add(self, f: CustomField) -> str:
        self.fields.setdefault(f.key, f)
        return f.key

    def next_key(self, prefix: str) -> str:
        n = self.counters.get(prefix, 0) + 1
        self.counters[prefix] = n
        return f"{prefix}_{n}"


def _label_before(text: str) -> str:
    """Kilka słów przed luką, bez znaków interpunkcji na końcu."""
    head = _JINJA.sub(" ", text)
    head = re.split(r"[;\n(]|,(?=\s)", head)[-1]
    words = re.findall(r"[\wąćęłńóśźżĄĆĘŁŃÓŚŹŻ./-]+", head)
    return " ".join(words[-6:]).strip(" :.-")


def _field_for_blank(state: _State, before: str, bracket: str | None) -> str:
    after_form = re.search(r"g\.g_pan(_nom)?\s*\}\}\s*$", before)
    if after_form and not bracket:
        # „Panem/ią ____” — narzędnik; „Pan/Pani ____” — mianownik.
        instrumental = after_form.group(1) is None
        return state.add(
            CustomField(
                key="partner.name_instrumental" if instrumental else "partner.name",
                label="Imię i nazwisko — narzędnik („z Panem …”)"
                if instrumental
                else "Imię i nazwisko",
                group="Partner",
                source="candidate",
                required=True,
            )
        )
    label_text = bracket or _label_before(before)
    if _WORDS.search(label_text[-20:]) and state.last_money:
        return state.last_money + "_words"
    for rx, key, label, kind, source in LABEL_RULES:
        if rx.search(label_text):
            sensitive = key == "partner.pesel"
            return state.add(
                CustomField(
                    key=key,
                    label=label,
                    kind=kind,
                    group="Klient" if key.startswith("client.") else "Partner",
                    source=source,
                    required=not sensitive,
                    sensitive=sensitive,
                )
            )
    if _MONEY.search(label_text) or _MONEY.search(before[-40:]):
        key = state.next_key("kwota")
        state.last_money = key
        return state.add(
            CustomField(
                key=key,
                label=(label_text or "Kwota")[:120],
                kind="money",
                group="Pieniądze",
                required=True,
            )
        )
    if _DATE.search(label_text):
        if not state.has_document_date and re.search(r"zawart|w\s+dniu", before, re.I):
            state.has_document_date = True
            return state.add(
                CustomField(
                    key="document_date",
                    label="Data zawarcia",
                    kind="date",
                    required=True,
                )
            )
        key = state.next_key("data")
        return state.add(
            CustomField(key=key, label=(label_text or "Data")[:120], kind="date")
        )
    key = state.next_key("pole")
    label = label_text or f"Pole {key.split('_')[-1]}"
    return state.add(CustomField(key=key, label=label[:120]))


def _fill_blanks(p: Paragraph, state: _State) -> None:
    text = p.text
    matches = list(BLANK.finditer(text))
    if not matches:
        return
    # Klucze od lewej (luka „słownie” zna kwotę przed sobą), podmiana od
    # prawej (pozycje wcześniejszych luk się nie przesuwają).
    keys = []
    for m in matches:
        raw = m.group(0)
        bracket = raw[1:-1] if raw.startswith("[") else None
        keys.append(_field_for_blank(state, text[: m.start()], bracket))
    for m, key in reversed(list(zip(matches, keys))):
        replace_span(p, m.start(), m.end(), "{{ " + key + " }}")
        state.blanks += 1


def _fill_gender(p: Paragraph, state: _State) -> None:
    for pattern, key in GENDER_FORMS:
        hits = sub_para(p, re.compile(pattern), "{{ " + key + " }}")
        if hits:
            state.gender = True


def detect(data: bytes, *, title: str = "Wzór własny") -> Detection:
    """Wgrany Word → szablon i lista pól. ``ValueError`` = plik nie do otwarcia."""
    check_package(data)  # zip bomb przed python-docx (``DocxTooLarge`` to ValueError)
    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001 — plik od człowieka
        raise ValueError("Nie udało się otworzyć pliku Word (.docx).") from exc
    state = _State()
    all_paragraphs = paragraphs(document)
    # Luka w pierwszym zdaniu wiąże się z poprzedzającym ją tekstem — idziemy od
    # góry, żeby „kwota … (słownie: ____)” znała swoją kwotę.
    for i, p in enumerate(all_paragraphs):
        text = p.text
        if not text.strip():
            continue
        if p.text != "".join(r.text for r in p.runs):
            state.warnings.append(
                f"Akapit z polem lub hiperłączem pominięty: „{text[:60]}”"
            )
            continue
        _fill_gender(p, state)
        if _ONLY_BLANK.match(p.text):
            near = " ".join(
                q.text for q in all_paragraphs[max(0, i - 2) : i + 3] if q is not p
            )
            if _SIGNATURE.search(near):
                continue
            label = next(
                (
                    q.text.strip()
                    for q in reversed(all_paragraphs[:i])
                    if q.text.strip() and not _ONLY_BLANK.match(q.text)
                ),
                "",
            )
            key = state.add(
                CustomField(
                    key=state.next_key("tresc"),
                    label=(_JINJA.sub("", label).strip(" :") or "Treść")[:120],
                    kind="textarea",
                )
            )
            replace_span(p, 0, len(p.text), "{{ " + key + " }}")
            state.blanks += 1
            continue
        _fill_blanks(p, state)
    for p in all_paragraphs:
        plain = _JINJA.sub("", p.text)
        for m in _GENDER_LEFT.finditer(plain):
            state.warnings.append(
                f"Forma „{m.group(0)}” nie jest rozpoznana — popraw ją w Wordzie "
                "albo opisz w poleceniu dla asystenta."
            )
        for rx, what in _PERSONAL:
            for m in rx.finditer(plain):
                if re.sub(r"\D", "", m.group(0)) == COMPANY_PL["nip"]:
                    continue
                if what == "adres e-mail" and m.group(0).endswith("b2bnetwork.pl"):
                    continue
                state.warnings.append(
                    f"W treści jest {what} — wzór nie może mieć danych osób: "
                    f"„{m.group(0)}”."
                )
    buf = io.BytesIO()
    document.save(buf)
    out = scrub_package(buf.getvalue(), title)
    # Gotowe ``{{ pole }}`` z pliku (i formy ``g.*``) → lista pól; pola
    # z rozpoznania luk wygrywają (mają lepsze etykiety i źródła).
    found = fields_from_paths(discover(out))
    merged: dict[str, CustomField] = {f.key: f for f in found}
    merged.update(state.fields)
    ordered = [
        merged[k] for k in [*state.fields, *(f.key for f in found)] if k in merged
    ]
    seen: set[str] = set()
    fields = [f for f in ordered if not (f.key in seen or seen.add(f.key))]
    return Detection(
        docx=out,
        fields=fields,
        warnings=list(dict.fromkeys(state.warnings)),
        blanks=state.blanks,
    )
