"""Stan czytnika ``rozliczenia@`` w ``last_error``: licznik i porzucone maile.

Bez bazy: sam zapis i odczyt tekstu stanu. Skróty id są fikcyjne.
"""

from types import SimpleNamespace

from app.services.consultant_portal import mailbox


def _state(error):
    return SimpleNamespace(last_error=error)


def test_licznik_i_porzucone_wracaja_z_zapisu() -> None:
    text = mailbox._failing_state("b" * 16, 2, ["a" * 16])
    assert mailbox._failing_message(_state(text)) == ("b" * 16, 2, ["a" * 16])


def test_porzucone_przetrwaja_bez_padajacego_maila() -> None:
    """Po porzuceniu licznik jest pusty, a skrót porzuconego musi zostać."""
    text = mailbox._failing_state(None, 0, ["a" * 16])
    assert mailbox._failing_message(_state(text)) == (None, 0, ["a" * 16])


def test_kod_bledu_listy_nie_kasuje_stanu() -> None:
    kept = mailbox._failing_state("b" * 16, 3, ["a" * 16])
    assert mailbox._failing_message(_state(f"http_503;{kept}")) == (
        "b" * 16,
        3,
        ["a" * 16],
    )


def test_pusty_i_obcy_stan() -> None:
    assert mailbox._failing_message(None) == (None, 0, [])
    assert mailbox._failing_message(_state("no_mailbox")) == (None, 0, [])
    assert mailbox._failing_state(None, 0, []) is None


def test_pelny_stan_miesci_sie_w_kolumnie() -> None:
    """``cp_mailbox_state.last_error`` to ``String(200)``; nadmiar porzuconych odpada."""
    many = [f"{i:016x}" for i in range(20)]
    text = mailbox._failing_state("f" * 16, mailbox.MAX_MESSAGE_ATTEMPTS, many)
    assert len(f"http_503;{text}") <= 200
    _, _, abandoned = mailbox._failing_message(_state(text))
    assert abandoned == many[-mailbox.MAX_ABANDONED_KEYS :]


def test_ekran_widzi_sam_kod_bledu() -> None:
    kept = mailbox._failing_state("b" * 16, 3, ["a" * 16])
    assert mailbox._public_error(f"http_503;{kept}") == "http_503"
    assert mailbox._public_error(kept) is None
    assert mailbox._public_error("no_mailbox") == "no_mailbox"
    assert mailbox._public_error(None) is None
