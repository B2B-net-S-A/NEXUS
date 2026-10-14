"""Strony CV jako PDF z pliku Word (Edytor CV 3, decyzja J2, 14.10.2026).

Prawdziwego LibreOffice nie ma w CI ani lokalnie — testy podstawiają skrypt
udający `soffice` (zapisuje PDF do `--outdir`). Pilnują: wyniku i pamięci po
skrócie pliku, limitu czasu (proces ginie), braku programu, odpowiedzi, która
nie jest PDF-em, i limitu rozmiaru — każda awaria to `PdfPreviewUnavailable`,
nigdy wyjątek, który wywróciłby trasę.
"""

import os
import stat
import textwrap
from pathlib import Path

import pytest

from app.services import cv_pdf_preview as service

FAKE = textwrap.dedent(
    """\
    #!/bin/sh
    # Udaje `soffice --convert-to pdf … --outdir DIR FILE`.
    echo run >> "{counter}"
    {extra}
    out=""
    prev=""
    for arg in "$@"; do
      if [ "$prev" = "--outdir" ]; then out="$arg"; fi
      prev="$arg"
    done
    printf '%s' '{body}' > "$out/cv.pdf"
    """
)


def _fake(tmp_path: Path, *, body: str = "%PDF-1.7 fake", extra: str = "") -> Path:
    counter = tmp_path / "runs.txt"
    script = tmp_path / "soffice"
    script.write_text(FAKE.format(counter=counter, extra=extra, body=body))
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


@pytest.fixture(autouse=True)
def _clean_cache():
    service.clear_cache()
    yield
    service.clear_cache()


def _runs(tmp_path: Path) -> int:
    path = tmp_path / "runs.txt"
    return len(path.read_text().splitlines()) if path.exists() else 0


def test_converts_and_remembers_the_same_file(tmp_path, monkeypatch):
    monkeypatch.setenv(service.SOFFICE_ENV, str(_fake(tmp_path)))
    first = service.docx_to_pdf(b"PK docx")
    second = service.docx_to_pdf(b"PK docx")
    assert first.startswith(b"%PDF") and second == first
    assert _runs(tmp_path) == 1
    service.docx_to_pdf(b"PK inny docx")
    assert _runs(tmp_path) == 2


def test_remembered_pdf_expires(tmp_path, monkeypatch):
    monkeypatch.setenv(service.SOFFICE_ENV, str(_fake(tmp_path)))
    now = [1000.0]
    service.docx_to_pdf(b"PK docx", clock=lambda: now[0])
    now[0] += service.TTL_S + 1
    service.docx_to_pdf(b"PK docx", clock=lambda: now[0])
    assert _runs(tmp_path) == 2


def test_timeout_kills_the_process_and_reports_unavailable(tmp_path, monkeypatch):
    monkeypatch.setenv(service.SOFFICE_ENV, str(_fake(tmp_path, extra="sleep 30")))
    monkeypatch.setattr(service, "TIMEOUT_S", 1)
    with pytest.raises(service.PdfPreviewUnavailable, match="timeout"):
        service.docx_to_pdf(b"PK docx")


def test_missing_libreoffice_is_unavailable(monkeypatch):
    monkeypatch.setenv(service.SOFFICE_ENV, "/nie/ma/takiego/soffice")
    with pytest.raises(service.PdfPreviewUnavailable, match="no soffice"):
        service.docx_to_pdf(b"PK docx")


def test_output_that_is_not_a_pdf_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv(service.SOFFICE_ENV, str(_fake(tmp_path, body="<html>")))
    with pytest.raises(service.PdfPreviewUnavailable, match="not a pdf"):
        service.docx_to_pdf(b"PK docx")


def test_failed_conversion_is_unavailable(tmp_path, monkeypatch):
    script = tmp_path / "soffice"
    script.write_text("#!/bin/sh\nexit 3\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv(service.SOFFICE_ENV, str(script))
    with pytest.raises(service.PdfPreviewUnavailable, match="exit 3"):
        service.docx_to_pdf(b"PK docx")


def test_libreoffice_that_cannot_start_is_unavailable_not_500(tmp_path, monkeypatch):
    """Fork bez pamięci, pełny /tmp, plik, którego nie da się uruchomić → 503, nie 500."""
    script = tmp_path / "soffice"
    script.write_text("bez shebanga\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv(service.SOFFICE_ENV, str(script))
    with pytest.raises(service.PdfPreviewUnavailable, match="os"):
        service.docx_to_pdf(b"PK docx")
    # Miejsce na zamianę wraca — następne żądanie nie czeka 30 s.
    assert service._slot.acquire(timeout=0)
    service._slot.release()


@pytest.mark.parametrize("size", [0, service.MAX_DOCX_BYTES + 1])
def test_empty_or_huge_file_is_refused_without_running(tmp_path, monkeypatch, size):
    monkeypatch.setenv(service.SOFFICE_ENV, str(_fake(tmp_path)))
    with pytest.raises(service.PdfPreviewUnavailable, match="size"):
        service.docx_to_pdf(b"x" * size)
    assert _runs(tmp_path) == 0


def test_busy_slot_is_unavailable_not_a_hang(tmp_path, monkeypatch):
    monkeypatch.setenv(service.SOFFICE_ENV, str(_fake(tmp_path)))
    monkeypatch.setattr(service, "WAIT_S", 0.1)
    assert service._slot.acquire(timeout=1)
    try:
        with pytest.raises(service.PdfPreviewUnavailable, match="busy"):
            service.docx_to_pdf(b"PK docx")
    finally:
        service._slot.release()


def test_runs_in_its_own_profile_without_a_home(tmp_path, monkeypatch):
    recorder = tmp_path / "soffice"
    log = tmp_path / "args.txt"
    recorder.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$@" > "{log}"\n'
        f'echo "HOME=$HOME" >> "{log}"\n'
        'out=""; prev=""\n'
        'for a in "$@"; do [ "$prev" = "--outdir" ] && out="$a"; prev="$a"; done\n'
        'printf "%%PDF-1.7" > "$out/cv.pdf"\n'
    )
    recorder.chmod(recorder.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv(service.SOFFICE_ENV, str(recorder))
    service.docx_to_pdf(b"PK docx")
    args = log.read_text().splitlines()
    profile = next(a for a in args if a.startswith("-env:UserInstallation=file://"))
    home = next(a for a in args if a.startswith("HOME="))[5:]
    assert profile.endswith("/profile") and profile.split("file://", 1)[1].startswith(
        home
    )
    assert "--headless" in args and "pdf:writer_pdf_Export" in args
    assert not os.path.exists(home), "katalog roboczy zamiany ma zniknąć"


def _docx(xml: bytes, *, written: tuple = (2026, 10, 14, 12, 0, 0)) -> bytes:
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(zipfile.ZipInfo("word/document.xml", written), xml)
    return buffer.getvalue()


def test_draft_rebuilt_from_the_same_content_is_remembered(tmp_path, monkeypatch):
    """Szkic składany od nowa różni się tylko czasem zapisu w ZIP-ie — bez drugiej zamiany."""
    monkeypatch.setenv(service.SOFFICE_ENV, str(_fake(tmp_path)))
    first = _docx(b"<w:p>CV</w:p>", written=(2026, 10, 14, 12, 0, 0))
    rebuilt = _docx(b"<w:p>CV</w:p>", written=(2026, 10, 14, 12, 0, 8))
    assert first != rebuilt
    service.docx_to_pdf(first)
    service.docx_to_pdf(rebuilt)
    assert _runs(tmp_path) == 1
    service.docx_to_pdf(_docx(b"<w:p>CV po zmianie</w:p>"))
    assert _runs(tmp_path) == 2


def test_cv_in_montserrat_without_the_font_in_pdf_falls_back(tmp_path, monkeypatch):
    """Obraz bez czcionki: PDF w zastępczej czcionce nie może udawać pliku klienta."""
    monkeypatch.setenv(
        service.SOFFICE_ENV, str(_fake(tmp_path, body="%PDF-1.7 LiberationSerif"))
    )
    with pytest.raises(service.PdfPreviewUnavailable, match="fonts"):
        service.docx_to_pdf(_docx(b'<w:rFonts w:ascii="Montserrat"/>'))


def test_cv_in_montserrat_with_the_font_in_pdf_passes(tmp_path, monkeypatch):
    monkeypatch.setenv(
        service.SOFFICE_ENV,
        str(_fake(tmp_path, body="%PDF-1.7 /BaseFont/AAAAAA+Montserrat-SemiBold")),
    )
    assert service.docx_to_pdf(
        _docx(b'<w:rFonts w:ascii="Montserrat SemiBold"/>')
    ).startswith(b"%PDF")


def test_word_file_in_other_fonts_is_not_judged_by_montserrat(tmp_path, monkeypatch):
    """CV z pliku Word kandydata (inne czcionki) — sprawdzenie Montserrat nie dotyczy."""
    monkeypatch.setenv(
        service.SOFFICE_ENV, str(_fake(tmp_path, body="%PDF-1.7 Calibri"))
    )
    assert service.docx_to_pdf(_docx(b'<w:rFonts w:ascii="Calibri"/>')).startswith(
        b"%PDF"
    )


def test_montserrat_fonts_for_the_image_carry_the_names_cv_files_use():
    from fontTools.ttLib import TTFont

    fonts = (
        Path(__file__).resolve().parents[1] / "app" / "assets" / "fonts" / "montserrat"
    )
    families = {TTFont(path)["name"].getDebugName(1) for path in fonts.glob("*.ttf")}
    assert {
        "Montserrat",
        "Montserrat Medium",
        "Montserrat SemiBold",
        "Montserrat ExtraLight",
    } <= families
    assert (fonts / "OFL.txt").read_text().startswith("Copyright")
    dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text()
    assert "libreoffice-writer-nogui" in dockerfile
    assert (
        "COPY app/assets/fonts/montserrat/ /usr/share/fonts/truetype/montserrat/"
        in dockerfile
    )


# ── Kolejka w pętli zdarzeń (`pdf_from_docx`) ───────────────────────────────


async def test_waiting_requests_queue_in_the_event_loop_not_in_threads(monkeypatch):
    """Czekający nie trzymają wątków wspólnej puli; ponad limit — od razu zapas."""
    import asyncio
    import threading

    from anyio import to_thread

    started = threading.Event()
    release = threading.Event()
    calls: list[bytes] = []

    def convert(docx: bytes) -> bytes:
        calls.append(docx)
        started.set()
        release.wait(5)
        return b"%PDF-1.7 " + docx

    monkeypatch.setattr(service, "docx_to_pdf", convert)
    first = asyncio.create_task(service.pdf_from_docx(b"PK 0"))
    await asyncio.to_thread(started.wait, 5)
    waiters = [
        asyncio.create_task(service.pdf_from_docx(f"PK {n}".encode()))
        for n in range(1, service.MAX_WAITING + 1)
    ]
    await asyncio.sleep(0.05)
    assert service._waiting == service.MAX_WAITING
    assert calls == [b"PK 0"], "czekający nie zaczynają zamiany"

    # Kolejka pełna: następny dostaje zapas od razu, bez czekania 30 s.
    with pytest.raises(service.PdfPreviewUnavailable, match="queue full"):
        await service.pdf_from_docx(b"PK nadmiar")
    # Pula wątków wolna mimo kolejki — inne trasy działają.
    assert await asyncio.wait_for(to_thread.run_sync(lambda: 1), timeout=1) == 1

    release.set()
    results = await asyncio.gather(first, *waiters)
    assert [r.split(b" ", 1)[1] for r in results] == [
        f"PK {n}".encode() for n in range(service.MAX_WAITING + 1)
    ]
    assert service._waiting == 0 and not service._queue.locked()


async def test_remembered_pdf_skips_the_queue(tmp_path, monkeypatch):
    monkeypatch.setenv(service.SOFFICE_ENV, str(_fake(tmp_path)))
    pdf = service.docx_to_pdf(_docx(b"<w:p>CV</w:p>"))
    await service._queue.acquire()
    try:
        assert await service.pdf_from_docx(_docx(b"<w:p>CV</w:p>")) == pdf
    finally:
        service._queue.release()


async def test_queue_wait_has_a_limit(monkeypatch):
    monkeypatch.setattr(service, "WAIT_S", 0.05)
    await service._queue.acquire()
    try:
        with pytest.raises(service.PdfPreviewUnavailable, match="busy"):
            await service.pdf_from_docx(b"PK docx")
        assert service._waiting == 0
    finally:
        service._queue.release()


def test_libreoffice_gets_no_application_secrets(tmp_path, monkeypatch):
    """Do LibreOffice idą tylko zmienne potrzebne do zamiany, bez sekretów."""
    monkeypatch.setenv("SECRET_KEY", "nie-dla-libreoffice")
    monkeypatch.setenv(
        service.SOFFICE_ENV, str(_fake(tmp_path, extra='env > "$0.env"'))
    )
    service.docx_to_pdf(b"PK docx")
    seen = (tmp_path / "soffice.env").read_text()
    assert "SECRET_KEY" not in seen and "DATABASE_URL" not in seen
    assert "PATH=" in seen
