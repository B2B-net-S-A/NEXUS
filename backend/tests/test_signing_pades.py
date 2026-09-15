"""`signing.pades` — approval-signature counting and the local pre-check.

`count_approval_signatures` decides whether a B2B contract counts as signed by
BOTH parties, so it is tested with duck-typed stand-ins for pyHanko's
``EmbeddedPdfSignature``: that pins exactly which attributes it reads and that
it degrades to ``(None, [])`` instead of raising. `validate_pades_local` is
exercised on a real, unsigned PDF produced in memory.
"""

from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace

import pytest

from app.services.signing import pades

pyhanko = pytest.importorskip("pyhanko")


class _SigObject(dict):
    """A signature dictionary: `.get('/Type')`, `.get('/SubFilter')`."""


def _emb(
    *,
    obj_type: str | None = "/Sig",
    subfilter: str | None = None,
    subject: str | None = "CN=Jan Kowalski",
    type_raises: bool = False,
    raw_type: str | None = None,
    cert_raises: bool = False,
):
    sig_object = _SigObject()
    if subfilter is not None:
        sig_object["/SubFilter"] = subfilter
    if raw_type is not None:
        sig_object["/Type"] = raw_type

    class _Emb:
        def __init__(self):
            self.sig_object = sig_object

        @property
        def sig_object_type(self):
            if type_raises:
                raise ValueError("no /Type")
            return obj_type

        @property
        def signer_cert(self):
            if cert_raises:
                raise ValueError("broken CMS")
            if subject is None:
                return SimpleNamespace()
            return SimpleNamespace(subject=SimpleNamespace(human_friendly=subject))

    return _Emb()


def _reader(*embedded):
    return SimpleNamespace(embedded_signatures=list(embedded))


def test_two_approval_signatures_are_counted_with_signers():
    count, names = pades.count_approval_signatures(
        _reader(_emb(subject="CN=Konsultant"), _emb(subject="CN=B2B Network"))
    )
    assert count == 2
    assert names == ["CN=Konsultant", "CN=B2B Network"]


def test_document_timestamps_are_not_approval_signatures():
    count, names = pades.count_approval_signatures(
        _reader(
            _emb(subject="CN=Konsultant"),
            _emb(obj_type="/DocTimeStamp"),
            _emb(obj_type="/Sig", subfilter="/ETSI.RFC3161"),
        )
    )
    assert count == 1
    assert names == ["CN=Konsultant"]


def test_unknown_subtype_is_not_counted():
    assert pades.count_approval_signatures(_reader(_emb(obj_type="/Weird"))) == (0, [])


def test_type_falls_back_to_raw_dictionary_entry():
    count, _ = pades.count_approval_signatures(
        _reader(
            _emb(type_raises=True, raw_type="/Sig"),
            _emb(type_raises=True, raw_type="/DocTimeStamp"),
            _emb(type_raises=True),  # no /Type at all → defaults to /Sig
        )
    )
    assert count == 2


def test_unreadable_signer_is_named_but_counted():
    count, names = pades.count_approval_signatures(
        _reader(_emb(cert_raises=True), _emb(subject=None))
    )
    assert count == 2
    assert names == ["<nieznany sygnatariusz>", "<nieznany sygnatariusz>"]


def test_subject_without_human_friendly_uses_str():
    class _Subject:
        human_friendly = None

        def __str__(self):
            return "CN=Fallback"

    emb = _emb()
    type(emb).signer_cert = property(lambda self: SimpleNamespace(subject=_Subject()))
    assert pades.count_approval_signatures(_reader(emb)) == (1, ["CN=Fallback"])


def test_enumeration_failure_degrades_to_none():
    class _Broken:
        @property
        def embedded_signatures(self):
            raise ValueError("hybrid xref")

    assert pades.count_approval_signatures(_Broken()) == (None, [])


def test_non_iterable_reader_never_raises():
    assert pades.count_approval_signatures(object()) == (None, [])


def test_empty_pdf_signature_list_counts_zero():
    assert pades.count_approval_signatures(_reader()) == (0, [])


def _blank_pdf() -> bytes:
    """A minimal one-page PDF with a correct xref table and no AcroForm."""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>",
    ]
    buf = BytesIO()
    buf.write(b"%PDF-1.7\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(buf.tell())
        buf.write(b"%d 0 obj\n" % number + body + b"\nendobj\n")
    xref_at = buf.tell()
    buf.write(b"xref\n0 %d\n" % (len(objects) + 1))
    buf.write(b"0000000000 65535 f \n")
    for off in offsets:
        buf.write(b"%010d 00000 n \n" % off)
    buf.write(
        b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
        % (len(objects) + 1, xref_at)
    )
    return buf.getvalue()


async def test_unsigned_pdf_reports_no_signature():
    report = await pades.validate_pades_local(_blank_pdf())
    assert report == {
        "is_qes": False,
        "valid": False,
        "intact": False,
        "trusted": False,
        "signed_by": None,
        "signature_level": None,
        "indication": "NO_SIGNATURE",
        "signature_count": 0,
        "signers": [],
    }
