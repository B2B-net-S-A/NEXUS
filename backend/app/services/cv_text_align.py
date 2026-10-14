"""Wyrównanie treści CV (decyzja J1 Artura, 14.10.2026).

CV jest domyślnie wyjustowane; reguła klienta (`client_cv_rules.cv_text_align`)
może przełączyć na „do lewej”. Reguła jest zamrażana przy generacji
(`client_rule_snapshot` w payloadzie generatora i w metadanych CV etapu), więc
plik złożony później — z generatora albo z treści edytora — ma to samo
wyrównanie co pierwsza wersja. Jawne `text-align` akapitu z edytora wygrywa
(`cv_approved_docx`).

Osobny moduł, bo czytają go oba renderery, a `cv_approved_docx` importuje
`docx_renderer`.
"""

from typing import Any

TEXT_ALIGNS = ("justify", "left")
DEFAULT_TEXT_ALIGN = "justify"


def cv_text_align(metadata: Any) -> str:
    """Wyrównanie z reguły klienta zamrożonej przy generacji CV.

    Przyjmuje metadane CV (`branded_render_metadata`, `render_metadata`) albo
    payload generatora — oba trzymają regułę pod `client_rule_snapshot`. Brak
    reguły (stare CV, kopia z pliku Word, CV z innej rekrutacji) albo nieznana
    wartość = wyrównanie domyślne.
    """
    snapshot = (
        metadata.get("client_rule_snapshot") if isinstance(metadata, dict) else None
    )
    value = snapshot.get("text_align") if isinstance(snapshot, dict) else None
    return value if value in TEXT_ALIGNS else DEFAULT_TEXT_ALIGN
