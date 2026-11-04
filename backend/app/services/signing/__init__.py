"""Walidacja podpisów kwalifikowanych (PAdES) dla podpisu umowy B2B w NEXUSIE.

Tor „in-house QES” z czerwca 2026 (KIR Szafir/mSzafir, ``/api/signing``,
``/sign/{token}``) usunięto 21.10.2026. Zostały moduły, których używa
``app.services.b2b_esign``:

- :mod:`.provider` — :class:`ValidationReport` i porównanie tożsamości,
- :mod:`.validation` — :class:`ValidationService` (sidecar EU DSS),
- :mod:`.pades` — lokalna walidacja pyHanko i lista podpisów zatwierdzających.
"""
