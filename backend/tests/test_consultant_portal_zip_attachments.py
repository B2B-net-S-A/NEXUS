"""Załącznik ZIP w poczcie rozliczeń: pliki ze środka jak zwykłe załączniki.

Bez bazy. Dane fikcyjne. Próba IX–X 2026: raport Credit Agricole w ZIP-ie
z hasłem i „Dokumenty.zip” od konsultanta PKO nie trafiały do rozliczenia, bo
czytnik ZIP-ów nie rozpakowywał.
"""

from __future__ import annotations

import base64
import io
import struct
import zipfile
import zlib

from app.services.consultant_portal import zip_files
from tests.zip_crypto import encrypted_zip

FILE = "#microsoft.graph.fileAttachment"
PDF = b"%PDF-1.4 fikcyjny raport"
XLSX_LIKE = b"PK\x03\x04 fikcyjny arkusz"


def _attachment(name: str, data: bytes, *, inline: bool = False) -> dict:
    return {
        "@odata.type": FILE,
        "name": name,
        "isInline": inline,
        "contentBytes": base64.b64encode(data).decode(),
    }


def _zip(files: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return out.getvalue()


def _names(files: list[dict]) -> list[str]:
    return [f["name"] for f in files]


def _content(file: dict) -> bytes:
    return base64.b64decode(file["contentBytes"])


def test_zip_bez_hasla_daje_pliki_ze_srodka():
    archive = _zip({"TS 2610.xlsm": XLSX_LIKE, "folder/odbior.pdf": PDF, "pusty/": b""})
    files = [_attachment("faktura.pdf", PDF), _attachment("Dokumenty.zip", archive)]

    out = zip_files.expand(files, passwords=())

    assert _names(out) == ["faktura.pdf", "TS 2610.xlsm", "odbior.pdf"]
    assert _content(out[1]) == XLSX_LIKE
    assert all(f["@odata.type"] == FILE and not f["isInline"] for f in out)


def test_zip_z_haslem_otwiera_haslo_z_konfiguracji():
    archive = encrypted_zip({"1234_Raport.xlsx": XLSX_LIKE}, b"haslo-testowe")
    files = [_attachment("1234_Raport.zip", archive)]

    out = zip_files.expand(files, passwords=(b"zle", b"haslo-testowe"))

    assert _names(out) == ["1234_Raport.xlsx"]
    assert _content(out[0]) == XLSX_LIKE


def test_zip_z_haslem_bez_hasla_zostaje_zipem():
    archive = encrypted_zip({"raport.xlsx": XLSX_LIKE}, b"haslo-testowe")
    files = [_attachment("raport.zip", archive)]

    assert _names(zip_files.expand(files, passwords=())) == ["raport.zip"]
    assert _names(zip_files.expand(files, passwords=(b"inne",))) == ["raport.zip"]


def test_zip_z_haslem_deflate_otwiera_haslo_z_konfiguracji():
    archive = encrypted_zip(
        {"raport.xlsx": XLSX_LIKE * 20}, b"haslo-testowe", deflate=True
    )

    out = zip_files.expand(
        [_attachment("raport.zip", archive)], passwords=(b"haslo-testowe",)
    )

    assert _names(out) == ["raport.xlsx"]
    assert _content(out[0]) == XLSX_LIKE * 20


def _wrong_password_past_check_byte(archive: bytes) -> bytes:
    """Złe hasło, które przechodzi bajt kontrolny ZipCrypto (co 256.), a strumień
    deflate po odszyfrowaniu jest zepsuty: ``zipfile`` rzuca wtedy ``zlib.error``."""

    with zipfile.ZipFile(io.BytesIO(archive)) as opened:
        info = opened.infolist()[0]
        for n in range(200_000):
            candidate = f"zle-{n}".encode()
            try:
                with opened.open(info, pwd=candidate) as handle:
                    handle.read()
            except RuntimeError:
                continue
            except zlib.error:
                return candidate
            except zipfile.BadZipFile:
                continue
    raise AssertionError("brak hasła przechodzącego bajt kontrolny")


def test_zle_haslo_przechodzace_bajt_kontrolny_przy_deflate_nie_wywraca_czytnika():
    # zlib.error wychodził z ``expand`` i czytnik poczty stawał na tym mailu na zawsze.
    archive = encrypted_zip(
        {"raport.xlsx": XLSX_LIKE * 20}, b"haslo-testowe", deflate=True
    )
    wrong = _wrong_password_past_check_byte(archive)
    files = [_attachment("raport.zip", archive)]

    assert _names(zip_files.expand(files, passwords=(wrong,))) == ["raport.zip"]
    out = zip_files.expand(files, passwords=(wrong, b"haslo-testowe"))
    assert _names(out) == ["raport.xlsx"]
    assert _content(out[0]) == XLSX_LIKE * 20


def _corrupt_first_entry(archive: bytes) -> bytes:
    """Strumień deflate pierwszego pliku zamieniony na blok typu 3 (zarezerwowany)."""

    with zipfile.ZipFile(io.BytesIO(archive)) as opened:
        info = opened.infolist()[0]
    raw = bytearray(archive)
    name_len, extra_len = struct.unpack(
        "<HH", raw[info.header_offset + 26 : info.header_offset + 30]
    )
    start = info.header_offset + 30 + name_len + extra_len
    raw[start : start + info.compress_size] = b"\xff" * info.compress_size
    return bytes(raw)


def test_uszkodzony_deflate_pomija_plik_a_reszta_wychodzi():
    archive = _corrupt_first_entry(_zip({"zepsuty.pdf": PDF * 20, "dobry.pdf": PDF}))

    out = zip_files.expand([_attachment("Dokumenty.zip", archive)], passwords=())

    assert _names(out) == ["dobry.pdf"]


def test_sam_uszkodzony_deflate_zostaje_zipem():
    archive = _corrupt_first_entry(_zip({"zepsuty.pdf": PDF * 20}))
    files = [_attachment("Dokumenty.zip", archive)]

    assert _names(zip_files.expand(files, passwords=())) == ["Dokumenty.zip"]


def test_polskie_nazwy_z_windows_bez_flagi_utf8():
    # Archiwizator Windows zapisuje nazwy w CP852 bez flagi UTF-8 (PKO, X 2026).
    raw = _zip_with_raw_name("Odbiór usług za październik.pdf".encode("cp852"), PDF)

    out_files = zip_files.expand([_attachment("Dokumenty.zip", raw)], passwords=())

    assert _names(out_files) == ["Odbiór usług za październik.pdf"]


def _zip_with_raw_name(raw_name: bytes, data: bytes, extra: bytes = b"") -> bytes:
    """Archiwum z nazwą zapisaną bajtami (bez flagi UTF-8) i opcjonalnym polem extra."""

    import struct
    import zlib

    crc = zlib.crc32(data) & 0xFFFFFFFF
    sizes = (crc, len(data), len(data), len(raw_name), len(extra))
    local = struct.pack("<IHHHHHIIIHH", 0x04034B50, 20, 0, 0, 0, 0x21, *sizes)
    local += raw_name + extra + data
    central = struct.pack(
        "<IHHHHHHIIIHHHHHII", 0x02014B50, 20, 20, 0, 0, 0, 0x21, *sizes, 0, 0, 0, 0, 0
    )
    central += raw_name + extra
    end = struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, 1, 1, len(central), len(local), 0)
    return local + central + end


def test_nazwa_z_pola_unicode_path_zostaje():
    # „Dokumenty.zip” PKO: nazwa CP437/CP852 plus pole Info-ZIP Unicode Path (0x7075)
    # z nazwą w UTF-8, którą ``zipfile`` (3.12+) bierze sam. Nie przekodowujemy jej.
    import struct
    import zlib

    raw = "Odbiór usług.msg".encode("cp852")
    unicode_name = "Odbiór usług.msg".encode()
    body = struct.pack("<BI", 1, zlib.crc32(raw) & 0xFFFFFFFF) + unicode_name
    extra = struct.pack("<HH", 0x7075, len(body)) + body
    archive = _zip_with_raw_name(raw, PDF, extra)

    out = zip_files.expand([_attachment("Dokumenty.zip", archive)], passwords=())

    assert _names(out) == ["Odbiór usług.msg"]


def test_arkusz_xlsx_to_nie_zip_do_rozpakowania():
    # XLSX jest ZIP-em w środku; rozpakowujemy tylko pliki .zip.
    archive = _zip({"[Content_Types].xml": b"<x/>", "xl/workbook.xml": b"<x/>"})
    files = [_attachment("raport.xlsx", archive)]

    assert zip_files.expand(files, passwords=()) == files


def test_zip_w_zipie_i_uszkodzony_zip_nie_rozpakowuja_sie():
    inner = _zip({"raport.pdf": PDF})
    files = [
        _attachment("paczka.zip", _zip({"srodek.zip": inner})),
        _attachment("zly.zip", b"PK\x03\x04 nie archiwum"),
    ]

    out = zip_files.expand(files, passwords=())

    # Zagnieżdżony ZIP zostaje plikiem (czytnik go nie przyjmie), uszkodzony też.
    assert _names(out) == ["srodek.zip", "zly.zip"]


def test_limit_rozmiaru_rozpakowania(monkeypatch):
    monkeypatch.setattr(zip_files, "MAX_ENTRY_BYTES", 10)
    archive = _zip({"duzy.pdf": PDF, "maly.pdf": b"%PDF-1"})

    out = zip_files.expand([_attachment("a.zip", archive)], passwords=())

    assert _names(out) == ["maly.pdf"]


def test_hasla_z_konfiguracji(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "CONSULTANT_PORTAL_ZIP_PASSWORD", " jeden , dwa ,,")
    assert zip_files.configured_passwords() == (b"jeden", b"dwa")
    monkeypatch.setattr(settings, "CONSULTANT_PORTAL_ZIP_PASSWORD", "")
    assert zip_files.configured_passwords() == ()


def test_mail_z_odbiorem_uslug_z_zipa_to_raport():
    # „Dokumenty.zip” PKO (X 2026): mail klienta z odbiorem usług szedł jako faktura.
    from app.services.consultant_portal.mailbox import classify_kind

    name = "FW Odbiór usług za październik 2026 - Jan Testowy.msg"
    assert classify_kind("Rozliczenie pazdziernik 2026", name) == "report"
    assert classify_kind("Dokumenty", "RE Odbior uslug za wrzesien.msg") == "report"
