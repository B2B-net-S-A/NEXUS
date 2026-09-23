"""Strona B2B.net w dokumentach umownych — JEDNO miejsce danych spółki.

Wzory działu powtarzały komparycję spółki w każdym pliku osobno (adres, KRS,
NIP, kapitał, reprezentant). Zmiana któregokolwiek z tych faktów wymagałaby
poprawienia kilkunastu plików — tu jest jedna stała, którą czyta każdy szablon
(``{{ company.* }}``). Dane są identyczne z komparycją w umowie B2B 2026
(``templates/contract/umowa_b2b_pl.html``).
"""

from __future__ import annotations

COMPANY_PL: dict[str, str] = {
    "name": "B2B.net S.A.",
    "short": "B2BNET",
    "seat": "Warszawa",
    "address": "Aleje Jerozolimskie 180, 02-486 Warszawa",
    "court": (
        "Sąd Rejonowy dla m.st. Warszawy w Warszawie, XIV Wydział Gospodarczy "
        "Krajowego Rejestru Sądowego"
    ),
    "krs": "0000387063",
    "nip": "5711707392",
    "share_capital": "1.360.000,00 zł (opłaconym)",
    "representative": "Pana Artura Twardowskiego – Prezesa Zarządu",
    "representative_nom": "Artur Twardowski – Prezes Zarządu",
    "signatory_title": "Prezes Zarządu",
    "notices_email": "administracja@b2bnetwork.pl",
    "place": "Warszawa",
}

COMPANY_EN: dict[str, str] = {
    **COMPANY_PL,
    "court": (
        "the District Court for the Capital City of Warsaw in Warsaw, 14th "
        "Commercial Division of the National Court Register"
    ),
    "share_capital": "PLN 1,360,000.00 (fully paid)",
    "representative": "Mr Artur Twardowski – President of the Management Board",
    "representative_nom": "Artur Twardowski – President of the Management Board",
    "signatory_title": "President of the Management Board",
    "place": "Warsaw",
}


def company_party(language: str) -> dict[str, str]:
    return dict(COMPANY_EN if language == "en" else COMPANY_PL)
