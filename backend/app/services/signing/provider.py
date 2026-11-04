"""Wynik walidacji podpisu PAdES — wspólny dla walidatorów DSS i pyHanko.

Zostało z toru „in-house QES” z czerwca 2026 (usunięty 21.10.2026): tylko
:class:`ValidationReport` i pomocnicze porównania tożsamości podpisujących,
których używa podpis umowy B2B w NEXUSIE (``app.services.b2b_esign``).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Optional


# Wynik pojedynczego podpisu, który uznajemy za POZYTYWNY (SIG-01). DSS zwraca
# ``TOTAL_PASSED`` (czasem z myślnikiem), a lokalny pyHanko — nasz odpowiednik
# ``PRE_CHECK_PASSED`` (podpis nienaruszony i kryptograficznie ważny; zaufania
# do listy EU lokalnie nie sprawdzamy, od tego jest DSS).
POSITIVE_INDICATIONS = frozenset({"TOTAL_PASSED", "PRE_CHECK_PASSED"})

_UNKNOWN_SIGNER_MARKERS = ("nieznany sygnatariusz",)


def normalize_person_text(value: str | None) -> str:
    """Małe litery, bez polskich znaków i interpunkcji — do porównań nazwisk."""
    if not value:
        return ""
    text = value.replace("ł", "l").replace("Ł", "L")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^0-9a-zA-Z]+", " ", text).lower()
    return " ".join(text.split())


def signer_identity(raw: str | None) -> str:
    """Tożsamość podpisującego z podmiotu certyfikatu (CN), znormalizowana.

    pyHanko daje ``Common Name: Jan Kowalski, Country: PL, …``, DSS zwykle samo
    ``Jan Kowalski`` albo ``CN=Jan Kowalski,…``. Pusty napis = tożsamość
    nieznana — taki podpis nie liczy się jako osobna strona.
    """
    if not raw:
        return ""
    text = str(raw)
    if any(marker in text.lower() for marker in _UNKNOWN_SIGNER_MARKERS):
        return ""
    match = re.search(r"common name:\s*([^,;]+)", text, flags=re.IGNORECASE)
    if match is None:
        match = re.search(r"(?:^|[,/;\s])cn=([^,;/]+)", text, flags=re.IGNORECASE)
    value = match.group(1) if match else text
    return normalize_person_text(value)


def is_positive_indication(indication: str | None) -> bool:
    """Czy wynik walidacji podpisu jest jawnie pozytywny (``TOTAL_PASSED``)."""
    if not indication:
        return False
    return indication.strip().upper().replace("-", "_") in POSITIVE_INDICATIONS


@dataclass(frozen=True)
class ValidationReport:
    """Outcome of validating a PAdES signature against the EU Trusted List."""

    is_qes: bool
    signature_level: Optional[str] = None
    signed_by: Optional[str] = None
    indication: Optional[str] = None
    sub_indication: Optional[str] = None
    # Number of *approval* signatures embedded in the PDF (document timestamps
    # excluded). ``None`` when the validator could not determine it — callers
    # MUST treat ``None`` conservatively (i.e. not "both parties signed").
    signature_count: Optional[int] = None
    # Human-friendly signer names (one per approval signature), best-effort.
    signers: list[str] = field(default_factory=list)
    # Wynik KAŻDEGO podpisu zatwierdzającego: ``{"signer", "indication"}``
    # (SIG-01). Pusta lista = walidator nie rozstrzygnął żadnego podpisu, więc
    # dokumentu nie wolno zakończyć.
    signature_results: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def all_signatures_passed(self) -> bool:
        """True tylko, gdy KAŻDY podpis ma jawnie pozytywny wynik (SIG-01).

        Liczba wyników musi się zgadzać z liczbą podpisów — podpis, którego
        walidator nie ocenił, nie może przejść „przy okazji" innych.
        """
        results = self.signature_results
        if not results:
            return False
        if self.signature_count is not None and self.signature_count != len(results):
            return False
        return all(is_positive_indication(r.get("indication")) for r in results)

    @property
    def positive_signer_identities(self) -> list[str]:
        """Różne, znane tożsamości z pozytywnym wynikiem (kolejność zachowana)."""
        seen: list[str] = []
        for result in self.signature_results:
            if not is_positive_indication(result.get("indication")):
                continue
            identity = signer_identity(result.get("signer"))
            if identity and identity not in seen:
                seen.append(identity)
        return seen

    def as_db_report(self) -> dict[str, Any]:
        """Shape persisted to ``b2b_signing_requests.validation`` JSONB."""
        return {
            "is_qes": self.is_qes,
            "signature_level": self.signature_level,
            "signed_by": self.signed_by,
            "indication": self.indication,
            "sub_indication": self.sub_indication,
            "signature_count": self.signature_count,
            "signers": self.signers,
            "signature_results": self.signature_results,
            "raw": self.raw,
        }
