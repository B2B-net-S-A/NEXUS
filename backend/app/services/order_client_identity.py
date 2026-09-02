"""Rozpoznanie klienta z treści PDF-a zamówienia.

Trzy szczeble, od najpewniejszego: **numer rejestrowy (NIP/VAT)** przecięty
z rejestrem znanych klientów → **markery tekstowe** (nazwa podmiotu, numer
umowy ramowej, charakterystyczna fraza) → **domena nadawcy** maila. Żaden
szczebel nie zgaduje: brak jednoznacznego trafienia to ``unrecognized``,
nie „najlepszy strzał".

Dlaczego przecięcie z rejestrem, a nie „znajdź NIP nabywcy": realne dokumenty
niosą NIP-y osób trzecich jako normalną cechę — dostawcy podpisu (Autenti na
karcie podpisu BNP Bank Polska), firm konsultantów (załącznik Alior z czterema
podwykonawcami), nasz własny. Heurystyka „NIP przy słowie Zamawiający" jest nie
do obrony przy dwudziestu układach; przecięcie ze znanym rejestrem jest odporne
dokładnie dlatego, że NIP-y osób trzecich w rejestrze klientów nie występują.

Suma kontrolna NIP jest tylko filtrem szumu — numer zamówienia Polkomtela
``4500724536`` też ją przechodzi. **Filtrem jest wyłącznie przecięcie.**

Skan idzie po CAŁYM tekście, nie per linia: Credit Agricole ma
``NIP: 657-008-\\n22-74`` (numer przełamany na końcu wiersza), EY ma etykietę
w linii nad numerem (``VAT\\nPL5252314195``). Numer bez etykiety też się liczy —
etykiety są zbyt różnorodne („NIP", „Nr NIP", „Numer Identyfikacji Podatkowej",
„VAT", „VAT number") i ich brak w skanie OCR jest normalny.

Moduł jest CZYSTY (bez bazy) — rejestr przychodzi jako argument. Dzięki temu
harness korpusu i testy nie potrzebują Postgresa, a adapter bazodanowy
(``clients.nip``) jest cienki.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Optional

# Nasz własny numer — strona sprzedająca, obecna w większości dokumentów.
OWN_REGISTRY_IDS: frozenset[str] = frozenset({"5711707392"})

IdentificationMethod = str  # "registry_id" | "marker" | "sender_domain"


@dataclass(frozen=True)
class ClientIdentification:
    """Wynik rozpoznania. ``client_key`` = klucz z rejestru znanych klientów."""

    client_key: Optional[str]
    method: Optional[IdentificationMethod]
    #: Numery rejestrowe znalezione w dokumencie (po normalizacji, bez naszego).
    registry_ids_found: tuple[str, ...] = ()
    #: Klucze klientów, które trafiły — >1 oznacza niejednoznaczność.
    candidates: tuple[str, ...] = ()
    #: Po polsku, do dziennika i kolejki: dlaczego (nie) rozpoznano.
    reason: str = ""

    @property
    def recognized(self) -> bool:
        return self.client_key is not None


# ── Numery rejestrowe ────────────────────────────────────────────────────────

# Kandydat na numer: ciąg cyfr z opcjonalnymi myślnikami/spacjami i ŁAMANIEM
# LINII w środku (CA), opcjonalny prefiks kraju (PL/FI). Wymagamy 9-12 cyfr po
# zdjęciu separatorów — 10 dla polskiego NIP, ale obce numery (FI 8 cyfr +
# litery) obsługujemy osobną gałęzią przez listę znanych obcych ID.
# Separator między cyframi: WYŁĄCZNIE poziomy (spacja, NBSP, wąski NBSP,
# myślnik). Nowa linia celowo poza klasą — z nią zachłanny wzorzec sklejałby
# rok z sąsiedniego wiersza z NIP-em i produkował 10-cyfrowe „numery" z dwóch
# niezwiązanych liczb. Jedyny łamany przypadek z korpusu (CA: „657-008-\\n22-74")
# jest sklejany osobno PRZED skanem, po myślniku na końcu linii.
# Dolna granica 8 cyfr — fiński Business ID Nordei (FI28583949) ma osiem;
# polskie numery krótsze niż 10 i tak odpadają na sumie kontrolnej.
_REGISTRY_NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:(PL|FI)[ \u00a0]?)?((?:\d[ \u00a0\u202f\-]*){7,12}\d)(?![0-9])",
    re.IGNORECASE,
)
# Numer przełamany myślnikiem na końcu linii: „657-008-\n22-74". Sklejamy
# PRZED skanem, żeby regex widział ciąg.
_HYPHEN_LINEBREAK_RE = re.compile(r"(\d)-\s*\n\s*(\d)")

_NIP_WEIGHTS = (6, 5, 7, 2, 3, 4, 5, 6, 7)


def normalize_registry_id(value: str) -> str:
    """„PL 526-030-05-17" → „5260300517"; „NIP: 123-456-32-18" → cyfry; „FI28583949" zostaje.

    Prefiks kraju liczy się TYLKO wtedy, gdy stoi bezpośrednio przed cyframi
    (opcjonalnie jedna spacja). Litery etykiety („NIP", „VAT number") nie są
    prefiksem — inaczej „NIP 123…" stałoby się obcym identyfikatorem „NIP123…".
    """
    raw = unicodedata.normalize("NFKC", value or "").upper()
    m = re.search(
        r"(?:^|[^A-Z])([A-Z]{2})?[ \u00a0]?(\d[\d \u00a0\u202f\-]*\d|\d)", raw
    )
    if not m:
        return "".join(ch for ch in raw if ch.isdigit())
    prefix, body = m.group(1), m.group(2)
    digits = "".join(ch for ch in body if ch.isdigit())
    if prefix and prefix != "PL":
        return f"{prefix}{digits}"
    return digits


def nip_checksum_valid(digits: str) -> bool:
    """Polski NIP: 10 cyfr, ostatnia = suma ważona mod 11 (wynik 10 = nieważny)."""
    if len(digits) != 10 or not digits.isdigit():
        return False
    control = sum(int(d) * w for d, w in zip(digits[:9], _NIP_WEIGHTS)) % 11
    return control != 10 and control == int(digits[9])


def registry_ids_in_text(
    text: str, *, exclude: Iterable[str] = OWN_REGISTRY_IDS
) -> list[str]:
    """Wszystkie poprawne numery rejestrowe z tekstu, bez duplikatów i bez naszych.

    Polskie NIP-y filtrowane sumą kontrolną; obce (z prefiksem literowym innym
    niż PL) przechodzą bez walidacji — ich poprawność potwierdza dopiero
    przecięcie z rejestrem.
    """
    joined = _HYPHEN_LINEBREAK_RE.sub(r"\1\2", text or "")
    excluded = {normalize_registry_id(x) for x in exclude}
    found: list[str] = []
    for prefix, body in _REGISTRY_NUMBER_RE.findall(joined):
        candidate = normalize_registry_id(f"{prefix}{body}")
        if candidate in excluded or candidate in found:
            continue
        if candidate.isdigit():
            if nip_checksum_valid(candidate):
                found.append(candidate)
        else:
            found.append(candidate)
    return found


# ── Markery tekstowe ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ClientMarkers:
    """Cechy dokumentu, które identyfikują klienta bez numeru rejestrowego.

    ``all_of`` — każdy wzorzec musi wystąpić; ``any_of`` — wystarczy jeden.
    Wzorce są regexami case-insensitive po tekście z usuniętymi diakrytykami
    (OCR gubi ogonki), więc pisz je bez polskich znaków.
    """

    all_of: tuple[str, ...] = ()
    any_of: tuple[str, ...] = ()
    #: Obce numery rejestrowe (VAT/Company number) — trafienie po nich liczy
    #: się jak NIP, bo to ten sam poziom pewności.
    foreign_registry_ids: frozenset[str] = field(default_factory=frozenset)


def _fold(text: str) -> str:
    folded = unicodedata.normalize("NFKD", (text or "").casefold()).replace("ł", "l")
    return "".join(ch for ch in folded if not unicodedata.combining(ch))


def markers_match(markers: ClientMarkers, folded_text: str) -> bool:
    if not markers.all_of and not markers.any_of:
        return False
    if any(not re.search(p, folded_text, re.IGNORECASE) for p in markers.all_of):
        return False
    if markers.any_of and not any(
        re.search(p, folded_text, re.IGNORECASE) for p in markers.any_of
    ):
        return False
    return True


# ── Identyfikacja ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ClientRegistry:
    """Znani klienci: numer rejestrowy → klucz, markery per klucz, domeny per klucz."""

    by_registry_id: Mapping[str, str]
    markers: Mapping[str, ClientMarkers] = field(default_factory=dict)
    sender_domains: Mapping[str, str] = field(default_factory=dict)


def identify_client(
    text: str,
    registry: ClientRegistry,
    *,
    sender_email: Optional[str] = None,
) -> ClientIdentification:
    """Drabina: numer rejestrowy → markery → domena nadawcy. Nigdy nie zgaduje."""
    found = tuple(registry_ids_in_text(text))
    normalized_registry = {
        normalize_registry_id(k): v for k, v in registry.by_registry_id.items()
    }
    hits = tuple(
        sorted({normalized_registry[x] for x in found if x in normalized_registry})
    )
    if len(hits) == 1:
        return ClientIdentification(
            client_key=hits[0],
            method="registry_id",
            registry_ids_found=found,
            candidates=hits,
            reason="Numer rejestrowy z dokumentu pasuje do jednego klienta.",
        )
    if len(hits) > 1:
        return ClientIdentification(
            client_key=None,
            method=None,
            registry_ids_found=found,
            candidates=hits,
            reason=(
                "Dokument niesie numery rejestrowe więcej niż jednego znanego "
                f"klienta: {', '.join(hits)}."
            ),
        )

    folded = _fold(text)
    marker_hits = tuple(
        sorted(key for key, mk in registry.markers.items() if markers_match(mk, folded))
    )
    # Obce ID z markerów (Nordea FI…) traktujemy jak numer rejestrowy.
    foreign_hits = tuple(
        sorted(
            key
            for key, mk in registry.markers.items()
            if mk.foreign_registry_ids
            and any(x in mk.foreign_registry_ids for x in found)
        )
    )
    if len(foreign_hits) == 1:
        return ClientIdentification(
            client_key=foreign_hits[0],
            method="registry_id",
            registry_ids_found=found,
            candidates=foreign_hits,
            reason="Obcy numer rejestrowy z dokumentu pasuje do jednego klienta.",
        )
    if len(marker_hits) == 1:
        return ClientIdentification(
            client_key=marker_hits[0],
            method="marker",
            registry_ids_found=found,
            candidates=marker_hits,
            reason="Brak numeru rejestrowego w rejestrze; rozpoznano po markerach.",
        )
    if len(marker_hits) > 1:
        return ClientIdentification(
            client_key=None,
            method=None,
            registry_ids_found=found,
            candidates=marker_hits,
            reason=f"Markery pasują do więcej niż jednego klienta: {', '.join(marker_hits)}.",
        )

    domain = (sender_email or "").rsplit("@", 1)[-1].strip().lower()
    if domain and domain in registry.sender_domains:
        key = registry.sender_domains[domain]
        return ClientIdentification(
            client_key=key,
            method="sender_domain",
            registry_ids_found=found,
            candidates=(key,),
            reason="Rozpoznano wyłącznie po domenie nadawcy — najsłabszy dowód.",
        )
    return ClientIdentification(
        client_key=None,
        method=None,
        registry_ids_found=found,
        candidates=(),
        reason="Żaden numer rejestrowy, marker ani domena nadawcy nie pasują do znanego klienta.",
    )
