"""Czy wgrany plik przyjąć jako podpis strony — czyste reguły, bez bazy i sieci.

Wady toru z czerwca (audyt 21.10.2026), których tu nie ma:

* kwalifikowany musi być KAŻDY podpis (tam liczył się tylko pierwszy),
* droga nie zna podpisu zwykłego ani zaawansowanego (tam nadawca mógł go zamówić
  i dwa samopodpisane certyfikaty kończyły sprawę),
* bez autorytatywnego walidatora (EU DSS) nic nie przechodzi — lokalny pyHanko
  nie sprawdza listy zaufanych dostawców,
* wymagana tożsamość każdej strony po nazwisku z certyfikatu, a „podpisana”
  dopiero przy obu stronach.

Komunikaty idą wprost do osoby, która wgrała plik — po polsku, bez szczegółów
technicznych (szczegóły zostają w raporcie walidacji przy wniosku).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Sequence

from app.services.signing.provider import (
    ValidationReport,
    is_positive_indication,
    normalize_person_text,
    signer_identity,
)

MSG_NOT_PDF = "Wgraj podpisany plik PDF."
MSG_CHANGED = (
    "To nie jest ten sam dokument, który wysłaliśmy do podpisu. Podpisz "
    "pobrany plik bez zmian i bez zapisywania go jako nowy PDF."
)
MSG_NOT_SIGNED = "W pliku nie ma nowego podpisu."
MSG_NO_VALIDATOR = (
    "Nie możemy teraz sprawdzić podpisu kwalifikowanego. Spróbuj za kilka minut."
)
MSG_INVALID = (
    "Podpis w pliku nie przeszedł weryfikacji. Podpisz plik ponownie "
    "podpisem kwalifikowanym."
)
MSG_NOT_QUALIFIED = (
    "Ta umowa wymaga kwalifikowanego podpisu elektronicznego (przenosi prawa "
    "autorskie). Podpis zwykły, zaawansowany ani profil zaufany nie wystarczą."
)


@dataclass(frozen=True)
class Fingerprint:
    sha256: str
    size: int

    @classmethod
    def of(cls, data: bytes) -> "Fingerprint":
        return cls(hashlib.sha256(data).hexdigest(), len(data))


def builds_on(data: bytes, previous: Fingerprint) -> bool:
    """Plik zaczyna się bajtami poprzedniej wersji i coś do niej dokłada.

    Podpis PAdES dopisuje się na końcu pliku (aktualizacja przyrostowa), więc
    podpisana wersja to poprzednia + dopisek. Inna treść albo „zapisz jako”
    zmienia początek pliku."""
    if len(data) <= previous.size:
        return False
    return hashlib.sha256(data[: previous.size]).hexdigest() == previous.sha256


def upload_problem(data: bytes, previous: Fingerprint) -> str | None:
    """Powód odmowy przed walidacją albo ``None``.

    Plik bajt w bajt taki jak poprzednia wersja to ten sam dokument bez
    podpisu, nie inny dokument (Olaf 26.10.2026 dostał „To nie jest ten sam
    dokument” po wgraniu pobranego pliku)."""
    if Fingerprint.of(data) == previous:
        return MSG_NOT_SIGNED
    if not builds_on(data, previous):
        return MSG_CHANGED
    return None


def _tokens(name: str | None) -> set[str]:
    return set(normalize_person_text(name).split())


def name_matches(expected: str, certificate_subject: str | None) -> bool:
    """Imię i nazwisko z NEXUSA zawiera się w nazwie z certyfikatu.

    Kolejność słów i drugie imię w certyfikacie nie przeszkadzają
    („Kowalski Jan Piotr” pasuje do „Jan Kowalski”); brak któregoś słowa — tak."""
    wanted = _tokens(expected)
    have = set(signer_identity(certificate_subject).split())
    return bool(wanted) and wanted <= have


def _is_qualified(level: object) -> bool:
    """Tylko ``QESig`` — pieczęć (``QESeal``), poziom niepewny
    (``Indeterminate QESig``, ``QESig?``) ani podpis zaawansowany nie wystarczą."""
    return str(level or "").strip() == "QESig"


@dataclass(frozen=True)
class Verdict:
    accepted: bool
    message: str | None = None
    # Kod do raportu i testów (nie dla człowieka).
    code: str | None = None

    @classmethod
    def ok(cls) -> "Verdict":
        return cls(True)

    @classmethod
    def no(cls, code: str, message: str) -> "Verdict":
        return cls(False, message, code)


def judge(
    report: ValidationReport,
    *,
    authoritative: bool,
    required_signers: list[str],
    any_of_signers: Sequence[str] = (),
) -> Verdict:
    """Raport walidacji → przyjąć albo nie, z powodem dla człowieka.

    ``required_signers`` — imiona i nazwiska, które MUSZĄ być wśród ważnych
    podpisów kwalifikowanych (kontraktor). ``any_of_signers`` — za firmę
    wystarczy podpis JEDNEJ z tych osób (lista reprezentantów z ustawień;
    26.10.2026 plik wgrywa Olaf, a podpisuje Artur)."""
    if not authoritative:
        return Verdict.no("no_validator", MSG_NO_VALIDATOR)
    results = report.signature_results
    if not results:
        return Verdict.no("no_signature", MSG_NOT_SIGNED)
    if not report.all_signatures_passed:
        return Verdict.no("invalid", MSG_INVALID)
    if not all(_is_qualified(r.get("level")) for r in results):
        return Verdict.no("not_qualified", MSG_NOT_QUALIFIED)
    for name in required_signers:
        if not any(
            is_positive_indication(r.get("indication"))
            and name_matches(name, r.get("signer"))
            for r in results
        ):
            return Verdict.no(
                "missing_signer",
                f"W pliku nie ma podpisu kwalifikowanego osoby: {name}. "
                "Podpisuje osoba, której imię i nazwisko jest w umowie.",
            )
    if any_of_signers and not any(
        is_positive_indication(r.get("indication"))
        and any(name_matches(name, r.get("signer")) for name in any_of_signers)
        for r in results
    ):
        return Verdict.no(
            "missing_signer",
            "W pliku nie ma podpisu kwalifikowanego osoby reprezentującej "
            f"B2B Network ({', '.join(any_of_signers)}).",
        )
    expected = len(required_signers) + (1 if any_of_signers else 0)
    if expected > 1 and len(report.positive_signer_identities) < expected:
        return Verdict.no(
            "same_person",
            "Obie strony podpisała ta sama osoba — potrzebny jest podpis "
            "kontraktora i podpis za B2B Network.",
        )
    return Verdict.ok()
