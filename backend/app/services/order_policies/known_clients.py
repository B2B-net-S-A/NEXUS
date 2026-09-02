"""Znani klienci zamówień: numery rejestrowe, markery, domeny — SEED i harness.

**To NIE jest bramka produkcyjna.** Na produkcji rozpoznanie idzie po
``clients.nip`` z bazy (adapter w P3); ten moduł jest:

1. **listą do wgrania** — wartości zweryfikowane na realnym korpusie 20 PDF-ów
   (09.2026), które Artur wpisuje do ``clients.nip``;
2. **rejestrem dla harnessu korpusu i testów** — działa bez bazy;
3. **markerami** dla klientów bez numeru rejestrowego w treści (Cardif, RITS,
   dokument w kształcie PFRON) — te żyją w kodzie także na produkcji, bo są
   regexami, nie danymi.

Numery rejestrowe spółek są danymi publicznymi (KRS). Nazwisk tu nie ma.

Klucze = ``OrderClientPolicy.key`` z rejestru polityk (tam, gdzie polityka
istnieje); klienci recognize-only mają klucze bez polityki — ``policy_by_key``
rzuca dla nich ``KeyError`` i harness to obsługuje.
"""

from __future__ import annotations

from app.services.order_client_identity import ClientMarkers, ClientRegistry

#: klucz klienta → numery rejestrowe potwierdzone w korpusie.
#: BNP to DWA podmioty z dwoma NIP-ami (patrz ``GET /api/admin/client-mixups``);
#: ``7831693251`` z dokumentu BNP Bank Polska to Autenti (dostawca podpisu),
#: nie bank — celowo NIEobecny.
KNOWN_REGISTRY_IDS: dict[str, tuple[str, ...]] = {
    "kir": ("5260300517",),
    "velobank": ("7011105189",),
    "credit_agricole": ("6570082274",),
    "erste": ("8960005673",),
    "bnp_oddzial": ("1070002909",),
    "bnp_bank_polska": ("5261008546",),
    "ergo": ("5851007625",),
    "bank_pocztowy": ("5540314271",),
    "polkomtel": ("5271037727",),
    "pko_bp": ("5250007738",),
    "mleasing": ("5260212925",),
    "alior": ("1070010731",),
    "bik": ("9511778633",),
    "cyfrowy_polsat": ("7961810732",),
    "ey": ("5252314195",),
    "nationale_nederlanden": ("5260305006",),
}

#: Markery dla klientów bez polskiego NIP-u w treści albo jako drugi szczebel.
#: Regexy po tekście z usuniętymi diakrytykami, case-insensitive.
KNOWN_MARKERS: dict[str, ClientMarkers] = {
    "nordea": ClientMarkers(
        all_of=(r"call off agreement", r"\bnordea\b"),
        foreign_registry_ids=frozenset({"FI28583949"}),
    ),
    "cardif": ClientMarkers(
        all_of=(r"zamowienie z dnia", r"umowy ramowej z dnia 3 lipca 2017"),
    ),
    "rits": ClientMarkers(all_of=(r"rits professional services",)),
    "pfron": ClientMarkers(
        all_of=(r"zlecenie na uslugi outsourcing specjalistow it",),
        any_of=(r"\bpfron\b", r"umowy nr \d{4}/\d{6}/pzp"),
    ),
    "ey": ClientMarkers(all_of=(r"work order", r"ernst\s*&\s*young")),
    "cyfrowy_polsat": ClientMarkers(
        all_of=(r"zlecenie wykonawcze", r"cyfrow(y|ym) polsat")
    ),
    "polkomtel": ClientMarkers(all_of=(r"zlecenie wykonawcze", r"\bpolkomtel\b")),
}

#: Domena nadawcy → klucz (najsłabszy szczebel; NIGDY nie autozapisuje).
KNOWN_SENDER_DOMAINS: dict[str, str] = {
    "bik.pl": "bik",
    "nordea.com": "nordea",
    "alior.pl": "alior",
    "pkobp.pl": "pko_bp",
    "velobank.pl": "velobank",
    "bankpocztowy.pl": "bank_pocztowy",
    "erstebank.pl": "erste",
    "mleasing.pl": "mleasing",
    "kir.pl": "kir",
    "plus.pl": "polkomtel",
    "cyfrowypolsat.pl": "cyfrowy_polsat",
    "credit-agricole.pl": "credit_agricole",
    "pfron.org.pl": "pfron",
    "nn.pl": "nationale_nederlanden",
    "nn-group.com": "nationale_nederlanden",
}


def build_registry_from_known_clients() -> ClientRegistry:
    by_id = {nip: key for key, nips in KNOWN_REGISTRY_IDS.items() for nip in nips}
    return ClientRegistry(
        by_registry_id=by_id, markers=KNOWN_MARKERS, sender_domains=KNOWN_SENDER_DOMAINS
    )
