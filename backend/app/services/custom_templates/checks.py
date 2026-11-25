"""Sprawdzenia wzoru własnego — liczy je kod z treści wzoru, nie model.

Trzy sprawdzenia z makiety (25.11.2026):

* **art. 22 § 1 KP** — sformułowania typowe dla umowy o pracę (kierownictwo,
  czas i miejsce wyznaczone przez zamawiającego, urlop) to ryzyko
  przekwalifikowania współpracy B2B na etat,
* **art. 53 pr. aut.** — przeniesienie autorskich praw majątkowych wymaga formy
  pisemnej pod rygorem nieważności: wzór z takim postanowieniem musi mieć
  podpis na papierze albo kwalifikowany (``signature_form = written``) — inaczej
  nie da się go zgłosić do zatwierdzenia,
* **art. 13 RODO** — wzór, który zbiera dane Partnera, potrzebuje klauzuli
  informacyjnej.

Cytat sprawdzenia przechodzi przez weryfikator fundamentu asystenta
(``app.services.legal.citations``, część A planu) przez ``legal_bridge`` — póki
fundamentu nie ma w gałęzi, cytat ma stan ``unverified`` („do sprawdzenia”).
Sprawdzenia to podpowiedź, nie porada prawna.
"""

from __future__ import annotations

import io
import re
from dataclasses import asdict, dataclass

import docx

from app.services.custom_templates import legal_bridge
from app.services.custom_templates.docx_ops import _JINJA, paragraphs
from app.services.custom_templates.fields import CustomField

_EMPLOYMENT = re.compile(
    r"pod\s+kierownictwem|podporządkowani|w\s+miejscu\s+i\s+czasie\s+wyznaczony|"
    r"czas\s+pracy|urlop\w*\s+wypoczynkow|wynagrodzeni\w*\s+za\s+pracę|"
    r"stosunek\s+pracy|polecenia\s+służbow",
    re.I,
)
#: Wszystkie odmiany: „autorskie prawa majątkowe”, „praw autorskich”,
#: „przenosi … prawa”, „przeniesienie praw”.
_COPYRIGHT = re.compile(
    r"autorsk\w*\s+praw\w*|praw\w*\s+(majątkow\w*\s+)?autorsk\w*|"
    r"przen(osi|ies)\w*\s+(\w+\s+){0,2}praw",
    re.I,
)
_GDPR = re.compile(r"RODO|danych\s+osobowych|2016/679", re.I)


@dataclass(frozen=True)
class Check:
    key: str
    state: str  # ok | warn | block
    text: str
    cite: str
    cite_kind: str  # law
    #: Stan cytatu z weryfikatora fundamentu: ok / missing / mismatch / unverified.
    cite_state: str = "unverified"

    def to_public(self) -> dict:
        return asdict(self)


def document_text(docx_bytes: bytes) -> str:
    """Tekst wzoru bez znaczników pól (do sprawdzeń i do modelu)."""
    document = docx.Document(io.BytesIO(docx_bytes))
    return "\n".join(_JINJA.sub("[pole]", p.text) for p in paragraphs(document))


def run_checks(
    text: str, fields: list[CustomField], *, signature_form: str
) -> list[Check]:
    checks: list[Check] = []
    employment = _EMPLOYMENT.search(text)
    checks.append(
        Check(
            key="art22_kp",
            state="warn" if employment else "ok",
            text=(
                f"Sformułowanie „{employment.group(0)}” brzmi jak umowa o pracę — "
                "przy B2B liczy się rezultat, zastępstwo i własne narzędzia"
                if employment
                else "Bez znamion etatu: brak kierownictwa, czasu i miejsca pracy "
                "wyznaczanych przez spółkę"
            ),
            cite="art. 22 § 1 KP",
            cite_kind="law",
        )
    )
    if _COPYRIGHT.search(text):
        written = signature_form == "written"
        checks.append(
            Check(
                key="art53_pr_aut",
                state="ok" if written else "block",
                text=(
                    "Wzór przenosi prawa autorskie: podpis na papierze albo "
                    "kwalifikowany jest ustawiony"
                    if written
                    else "Wzór przenosi prawa autorskie — ustaw podpis „na papierze "
                    "albo kwalifikowany”, inaczej przeniesienie jest nieważne"
                ),
                cite="art. 53 pr. aut.",
                cite_kind="law",
            )
        )
    personal = any(f.key.startswith("partner.") for f in fields)
    if personal:
        has_clause = bool(_GDPR.search(text))
        checks.append(
            Check(
                key="art13_rodo",
                state="ok" if has_clause else "warn",
                text=(
                    "Klauzula informacyjna dla Partnera jest we wzorze"
                    if has_clause
                    else "Wzór zbiera dane Partnera, a nie ma klauzuli informacyjnej"
                ),
                cite="art. 13 RODO",
                cite_kind="law",
            )
        )
    return [
        Check(**{**asdict(c), "cite_state": legal_bridge.citation_state(c.cite)})
        for c in checks
    ]


def blocking(checks: list[dict]) -> list[str]:
    """Sprawdzenia, które blokują zgłoszenie do zatwierdzenia."""
    return [c["text"] for c in checks if c.get("state") == "block"]
