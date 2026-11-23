"""Załączniki wiadomości MIME tak, jak widzi je Graph, także zagnieżdżone.

Apple Mail i część Outlooków składa ``multipart/related`` z ``multipart/mixed``
w środku (treść + pliki) i obrazkiem stopki obok. ``iter_attachments()`` patrzy
tylko na pierwszy poziom i zwraca wtedy sam obrazek, a PDF i załączony mail
przepadają; w próbie rozliczeń IX–XI 2026 było tak z 45 plikami (23.11.2026).
"""

from __future__ import annotations

from email.message import EmailMessage

#: Granica zagnieżdżenia multipart; plik przychodzi z zewnątrz.
_MAX_DEPTH = 20


def attachment_parts(message: EmailMessage) -> list[EmailMessage]:
    """Liście wiadomości poza treścią, w kolejności z pliku.

    Załączony mail (``message/rfc822``) wraca w całości, bez schodzenia do jego
    części. Tekst bez nazwy pliku i bez ``Content-Disposition: attachment`` to
    treść, nie załącznik.
    """

    found: list[EmailMessage] = []

    def visit(part: EmailMessage, depth: int) -> None:
        if depth > 0 and part.get_content_type() == "message/rfc822":
            found.append(part)
            return
        if part.is_multipart():
            if depth < _MAX_DEPTH:
                for child in part.iter_parts():
                    visit(child, depth + 1)
            return
        if depth == 0:
            return
        if (
            part.get_content_maintype() == "text"
            and not part.get_filename()
            and part.get_content_disposition() != "attachment"
        ):
            return
        found.append(part)

    visit(message, 0)
    return found
