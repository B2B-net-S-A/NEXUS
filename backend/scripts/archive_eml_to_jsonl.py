"""Archiwum skrzynki z home.pl (.eml + manifest.csv) → JSONL do importu w NEXUSIE.

Uruchamiane na laptopie, gdzie leży archiwum (``~/NEXUS-dane/archiwum-home-pl-pelne``),
tylko biblioteka standardowa — plik wynikowy idzie do kontenera backendu
i czyta go ``scripts/import_admin_mail_archive.py``. Treści załączników nie
przenosimy (tylko nazwy i rozmiary), treść maila jest przycięta do 20 000 znaków.

    python3 -I backend/scripts/archive_eml_to_jsonl.py \\
        --root ~/NEXUS-dane/archiwum-home-pl-pelne/administracja \\
        --mailbox administracja --out /tmp/administracja.jsonl

Foldery DRAFTS, TRASH, SPAM i confirmed-* są pomijane. Suma SHA-256 z manifestu
jest kluczem importu, więc ponowny bieg nie dubluje maili.
"""

from __future__ import annotations

import argparse
import csv
import email
import html
import json
import os
import re
import sys
from email import policy
from email.utils import getaddresses, parseaddr

BODY_MAX = 20_000
SKIP_FOLDERS = ("DRAFTS", "TRASH", "SPAM", "confirmed-ham", "confirmed-spam")
_TAGS = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"[ \t\f\v]+")
_BLANKS = re.compile(r"\n{3,}")


def _text(message: email.message.EmailMessage) -> str:
    try:
        part = message.get_body(preferencelist=("plain", "html"))
        content = part.get_content() if part is not None else ""
    except (KeyError, LookupError, ValueError):
        return ""
    if part is not None and part.get_content_type() == "text/html":
        content = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", content)
        content = html.unescape(_TAGS.sub(" ", content))
    content = _SPACES.sub(" ", content.replace("\r\n", "\n"))
    return _BLANKS.sub("\n\n", content).strip()[:BODY_MAX]


def _attachments(message: email.message.EmailMessage) -> list[dict]:
    out = []
    for part in message.iter_attachments():
        name = part.get_filename()
        if not name:
            continue
        payload = part.get_payload(decode=True) or b""
        out.append({"name": name[:255], "size": len(payload)})
    return out[:50]


def convert(root: str, mailbox: str, out) -> dict[str, int]:
    stats = {"written": 0, "skipped_folder": 0, "unreadable": 0}
    with open(os.path.join(root, "manifest.csv"), newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            folder = row["folder"]
            if folder.split("/")[0] in SKIP_FOLDERS:
                stats["skipped_folder"] += 1
                continue
            path = os.path.join(root, row["eml"])
            try:
                with open(path, "rb") as eml:
                    message = email.message_from_binary_file(eml, policy=policy.default)
            except OSError:
                stats["unreadable"] += 1
                continue
            sender_name, sender_email = parseaddr(str(message.get("from", "")))
            recipients = [
                addr.lower()
                for _, addr in getaddresses(
                    [str(message.get(h, "")) for h in ("to", "cc")]
                )
                if addr
            ]
            record = {
                "mailbox": mailbox,
                "folder": folder[:200],
                "sha256": row["sha256"],
                "received_at": row["internaldate_utc"],
                "message_id": (str(message.get("message-id", "")) or None),
                "sender_email": sender_email.lower() or None,
                "sender_name": sender_name[:200] or None,
                "to_emails": recipients[:50],
                "subject": str(message.get("subject", ""))[:500] or None,
                "body_text": _text(message),
                "attachments": _attachments(message),
                "eml_path": row["eml"][:500],
            }
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            stats["written"] += 1
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--root", required=True)
    parser.add_argument("--mailbox", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    with open(args.out, "w", encoding="utf-8") as out:
        stats = convert(os.path.expanduser(args.root), args.mailbox, out)
    print(json.dumps(stats), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
