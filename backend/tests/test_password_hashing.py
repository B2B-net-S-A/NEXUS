"""Kontrakt hash/verify po migracji passlib → bezpośredni pyca/bcrypt.

bcrypt 5 usunął ciche ucinanie haseł >72 bajtów (rzuca ValueError), a passlib
1.7.4 (ostatnie wydanie 2020) właśnie takim hasłem testowym inicjalizuje swój
backend — z bcryptem 5 KAŻDE verify()/hash() wybuchało na starcie. Stąd
przejście na bezpośrednie ``bcrypt.hashpw``/``checkpw`` w ``app.core.security``.

Ten plik pinuje zachowania, na których wisi logowanie:

- hashe wybite passlibem na bcrypt 4.x nadal przechodzą — stałe poniżej
  zostały wygenerowane ``CryptContext(schemes=["bcrypt"])`` z passlib 1.7.4
  + bcrypt 4.0.1, czyli dokładnie tym, co produkowało hashe do tej migracji;
- placeholder kont z importu Traffita zwraca ``False`` i NIE rzuca (passlib
  rzucał ``UnknownHashError``, więc logowanie na takie konto kończyło się
  nieobsłużonym wyjątkiem w ``auth.py`` — 500 zamiast 401);
- semantyka >72 bajtów identyczna z passlibem: liczy się pierwsze 72 bajty.
"""

from app.core.security import hash_password, verify_password

# passlib 1.7.4 + bcrypt 4.0.1: ctx.hash("tajnehaslo123")
_PASSLIB_ERA_HASH = "$2b$12$EQy5GyXpOQt4ohIg28WfK.Ebp599SgSrDSMrtP5YM4ub0kYYIHmCC"
# passlib 1.7.4 + bcrypt 4.0.1: ctx.hash("y" * 100) — passlib uciął do 72 B
_PASSLIB_ERA_LONG_HASH = "$2b$12$.jZUP/laUFCzUwrRLJ996ubywEpghlObdoDlDNmLFmhsNni.aBVgW"

# Wartość wpisywana przez importer Traffita (app/services/traffit/mappers.py)
# w ``users.password_hash`` kont, które nie mają się logować hasłem.
_TRAFFIT_PLACEHOLDER = "!imported-from-traffit-no-login!"


def test_passlib_era_hash_still_verifies() -> None:
    """Istniejące hashe z proda (passlib + bcrypt 4.x) muszą przechodzić."""
    assert verify_password("tajnehaslo123", _PASSLIB_ERA_HASH) is True


def test_wrong_password_is_rejected() -> None:
    assert verify_password("zlehaslo", _PASSLIB_ERA_HASH) is False


def test_traffit_placeholder_returns_false_not_raises() -> None:
    """Nie-bcryptowy hash → False, nigdy wyjątek.

    ``auth.py`` woła ``verify_password`` bez try/except; passlib rzucał tu
    ``UnknownHashError``, więc próba logowania na konto z importu kończyła
    się 500. Kontrakt: złe poświadczenia to zawsze ``False`` → czyste 401.
    """
    assert verify_password("cokolwiek", _TRAFFIT_PLACEHOLDER) is False


def test_malformed_hashes_return_false() -> None:
    assert verify_password("cokolwiek", "") is False
    assert verify_password("cokolwiek", "notahash") is False


def test_roundtrip_keeps_format() -> None:
    """Nowe hashe zostają $2b$12$ — ten sam koszt i format co za passliba."""
    hashed = hash_password("nowehaslo456")
    assert hashed.startswith("$2b$12$")
    assert verify_password("nowehaslo456", hashed) is True
    assert verify_password("innehaslo", hashed) is False


def test_long_password_matches_passlib_truncation() -> None:
    """Hasła >72 bajty: liczy się pierwsze 72 — jak w passlibie.

    Bez jawnego ucięcia bcrypt 5 rzuciłby ValueError i użytkownik z takim
    hasłem (hash wybity jeszcze passlibem) nie zalogowałby się już nigdy.
    """
    assert verify_password("y" * 100, _PASSLIB_ERA_LONG_HASH) is True
    # Pierwsze 72 bajty identyczne → passlib uznawał za to samo hasło.
    assert verify_password("y" * 72, _PASSLIB_ERA_LONG_HASH) is True
    # Różnica WEWNĄTRZ okna 72 bajtów → odrzucone.
    assert verify_password("y" * 71 + "z", _PASSLIB_ERA_LONG_HASH) is False

    fresh = hash_password("x" * 100)
    assert verify_password("x" * 100, fresh) is True
    assert verify_password("x" * 72, fresh) is True


def test_unicode_password_roundtrip() -> None:
    """Wielobajtowe znaki (PL + emoji) przechodzą przez encode/ucięcie."""
    password = "zażółć-gęślą-jaźń-🔑"
    hashed = hash_password(password)
    assert verify_password(password, hashed) is True
    assert verify_password("zażółć-gęślą-jaźń-x", hashed) is False
