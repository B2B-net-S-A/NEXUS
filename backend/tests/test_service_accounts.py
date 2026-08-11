"""Konta serwisowe / klucze API — format klucza, autoryzacja, CRUD, RBAC.

Podział pliku odpowiada trzem różnym rzeczom, które mogą tu pójść źle:

1. **Format i kryptografia** (bez bazy) — czy sekret jest tym, za co go
   uważamy, czy da się go odtworzyć z bazy, czy parser przepuszcza śmieci.
2. **Decyzja autoryzacyjna** — czy klucz bez scope'u naprawdę nie wchodzi,
   czy rewokacja i wygaśnięcie działają, czy da się podszyć pod użytkownika.
3. **Powierzchnia administracyjna** — czy sekret nie wycieka do listingów
   i czy kluczem nie da się rozszerzyć własnych uprawnień.

Każdy test tutaj ma czerwienieć po cofnięciu konkretnej linii implementacji —
nie po usunięciu całego modułu.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.service_account import (
    SCOPE_LABELS,
    ServiceAccount,
    ServiceAccountKey,
    ServiceScope,
)
from app.services.service_account_auth import (
    ServiceKeyError,
    default_expires_at,
    generate_api_key,
    parse_api_key,
)

ACCOUNTS_URL = "/api/settings/service-accounts"


# ── 1. Format klucza i przechowywanie sekretu ────────────────────────────────


class TestKeyFormat:
    def test_generated_key_splits_into_public_id_and_secret(self):
        wire, key_id, secret_sha256 = generate_api_key()

        assert wire.startswith("nxs_v2_"), "prefiks musi być grepowalny dla gitleaks"
        assert key_id.startswith("v2$"), "PK trzyma revoke-key w konwencji repo"
        # Jawne id na drucie i w bazie to ten sam identyfikator, inaczej
        # zapisany — audyt „którym kluczem" opiera się na tej równości.
        assert key_id[len("v2$") :] in wire

        parsed_id, secret = parse_api_key(wire)
        assert parsed_id == key_id
        assert hashlib.sha256(secret.encode()).hexdigest() == secret_sha256

    def test_stored_hash_does_not_contain_the_secret(self):
        """Z tego, co ląduje w bazie, nie da się odtworzyć klucza."""
        wire, key_id, secret_sha256 = generate_api_key()
        _, secret = parse_api_key(wire)

        assert secret not in secret_sha256
        assert secret not in key_id
        assert len(secret_sha256) == 64

    def test_keys_are_unique_across_generations(self):
        keys = {generate_api_key()[0] for _ in range(50)}
        assert len(keys) == 50

    @pytest.mark.parametrize(
        "bad",
        [
            "",
            "nxs_v2_",
            "totally-not-a-key",
            # Zła wersja — v1 nigdy nie istniało, ale odrzucenie musi być jawne,
            # żeby przyszła zmiana schematu nie przechodziła po cichu.
            "nxs_v1_0123456789abcdef01234567_" + "a" * 43,
            # Za krótkie id.
            "nxs_v2_0123_" + "a" * 43,
            # Wielkie litery w id — id jest hexem z ``token_hex``.
            "nxs_v2_0123456789ABCDEF01234567_" + "a" * 43,
            # Za krótki sekret.
            "nxs_v2_0123456789abcdef01234567_short",
            # Znaki spoza alfabetu urlsafe.
            "nxs_v2_0123456789abcdef01234567_" + "a" * 40 + "!!!",
        ],
    )
    def test_parser_rejects_malformed_keys(self, bad):
        with pytest.raises(ServiceKeyError):
            parse_api_key(bad)


class TestExpiryPolicy:
    def test_default_ttl_is_used_when_not_requested(self):
        expires = default_expires_at(None)
        expected = datetime.now(timezone.utc) + timedelta(
            days=settings.SERVICE_ACCOUNT_KEY_DEFAULT_TTL_DAYS
        )
        assert abs((expires - expected).total_seconds()) < 60

    def test_request_above_ceiling_is_clamped_not_rejected(self):
        """Sufit ma wymuszać politykę, a nie zapraszać do kolejnego strzału."""
        expires = default_expires_at(settings.SERVICE_ACCOUNT_KEY_MAX_TTL_DAYS + 5000)
        ceiling = datetime.now(timezone.utc) + timedelta(
            days=settings.SERVICE_ACCOUNT_KEY_MAX_TTL_DAYS
        )
        assert expires <= ceiling + timedelta(seconds=60)


class TestScopeVocabulary:
    def test_no_candidate_data_scope_exists(self):
        """Klucz do syncu Traffita nie ma jak sięgnąć po dane kandydatów.

        To nie jest kwestia ostrożnej konfiguracji konta — takiego uprawnienia
        po prostu nie ma w słowniku, więc nikt nie może go przyznać.
        """
        values = {scope.value for scope in ServiceScope}
        for forbidden in ("candidate:read", "candidate:write", "client:read"):
            assert forbidden not in values

    def test_every_scope_has_polish_label(self):
        for scope in ServiceScope:
            assert SCOPE_LABELS.get(scope)

    def test_granted_scopes_fails_closed_on_corrupt_row(self):
        """Uszkodzony wiersz = brak uprawnień, nie test podciągu.

        Gdyby ``scopes`` był stringiem, ``"traffit:sync" in scopes`` byłoby
        prawdą dla wartości ``"traffit:sync-cokolwiek"``.
        """
        account = ServiceAccount(slug="x", name="x", scopes="traffit:sync")
        assert account.granted_scopes() == frozenset()

        account.scopes = None
        assert account.granted_scopes() == frozenset()

        account.scopes = ["traffit:sync", 42, None]
        assert account.granted_scopes() == frozenset({"traffit:sync"})


# ── 2. Pomocnicze: zakładanie konta + klucza przez API ───────────────────────


async def _create_account(
    app_client: AsyncClient,
    headers: dict,
    scopes: list[str],
) -> dict:
    slug = f"pytest-svc-{uuid.uuid4().hex[:8]}"
    resp = await app_client.post(
        ACCOUNTS_URL,
        headers=headers,
        json={"slug": slug, "name": "Pytest konto", "scopes": scopes},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _issue_key(
    app_client: AsyncClient,
    headers: dict,
    account_id: int,
    expires_in_days: int | None = None,
) -> tuple[str, dict]:
    payload: dict = {"label": "pytest"}
    if expires_in_days is not None:
        payload["expires_in_days"] = expires_in_days
    resp = await app_client.post(
        f"{ACCOUNTS_URL}/{account_id}/keys", headers=headers, json=payload
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return body["api_key"], body["key"]


async def _account_with_key(
    app_client: AsyncClient,
    headers: dict,
    scopes: list[str],
) -> tuple[dict, str, dict]:
    account = await _create_account(app_client, headers, scopes)
    api_key, key = await _issue_key(app_client, headers, account["id"])
    return account, api_key, key


# ── 3. Decyzja autoryzacyjna na chronionym endpointcie ───────────────────────

# ``GET /api/admin/traffit/sync/status`` to konkretny przypadek użycia, który
# wywołał całą funkcję: endpoint operacyjny odpalany poza przeglądarką.
TRAFFIT_STATUS = "/api/admin/traffit/sync/status"
TRAFFIT_SYNC = "/api/admin/traffit/sync"


class TestApiKeyAuthorization:
    async def test_key_with_scope_is_accepted(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        _, api_key, _ = await _account_with_key(
            app_client, app_auth_headers, ["traffit:read"]
        )
        resp = await app_client.get(TRAFFIT_STATUS, headers={"X-API-Key": api_key})
        assert resp.status_code == 200, resp.text
        assert "states" in resp.json()

    async def test_key_without_scope_is_denied(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        """Klucz od uruchamiania syncu nie czyta statusu — scope'y są rozłączne."""
        _, api_key, _ = await _account_with_key(
            app_client, app_auth_headers, ["traffit:sync"]
        )
        resp = await app_client.get(TRAFFIT_STATUS, headers={"X-API-Key": api_key})
        assert resp.status_code == 403, resp.text
        assert resp.json()["detail"]["error"] == "insufficient_scope"

    async def test_account_with_no_scopes_is_denied(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        _, api_key, _ = await _account_with_key(app_client, app_auth_headers, [])
        resp = await app_client.get(TRAFFIT_STATUS, headers={"X-API-Key": api_key})
        assert resp.status_code == 403

    async def test_tampered_secret_is_rejected(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        """Zmiana jednego znaku sekretu przy zachowaniu poprawnego id."""
        _, api_key, _ = await _account_with_key(
            app_client, app_auth_headers, ["traffit:read"]
        )
        key_id_part, _, secret = api_key.rpartition("_")
        flipped = "b" if secret[0] != "b" else "c"
        tampered = f"{key_id_part}_{flipped}{secret[1:]}"

        resp = await app_client.get(TRAFFIT_STATUS, headers={"X-API-Key": tampered})
        assert resp.status_code == 401

    async def test_unknown_key_id_is_rejected(self, app_client: AsyncClient):
        forged = f"nxs_v2_{'a' * 24}_{'b' * 43}"
        resp = await app_client.get(TRAFFIT_STATUS, headers={"X-API-Key": forged})
        assert resp.status_code == 401

    async def test_missing_credentials_is_401_not_403(self, app_client: AsyncClient):
        """401 = nie wiemy kim jesteś. Front rozróżnia to od 403."""
        resp = await app_client.get(TRAFFIT_STATUS)
        assert resp.status_code == 401

    async def test_revoked_key_stops_working_immediately(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        account, api_key, key = await _account_with_key(
            app_client, app_auth_headers, ["traffit:read"]
        )
        assert (
            await app_client.get(TRAFFIT_STATUS, headers={"X-API-Key": api_key})
        ).status_code == 200

        revoke = await app_client.post(
            f"{ACCOUNTS_URL}/{account['id']}/keys/{key['key_id']}/revoke",
            headers=app_auth_headers,
            json={"reason": "test"},
        )
        assert revoke.status_code == 200, revoke.text

        # Bez okresu karencji — uprawnienia są czytane przy każdym requeście,
        # nie zapiekane w wystawionym tokenie.
        resp = await app_client.get(TRAFFIT_STATUS, headers={"X-API-Key": api_key})
        assert resp.status_code == 401

    async def test_expired_key_is_rejected(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        _, api_key, key = await _account_with_key(
            app_client, app_auth_headers, ["traffit:read"]
        )
        async with AsyncSessionLocal() as db:
            row = await db.scalar(
                select(ServiceAccountKey).where(
                    ServiceAccountKey.key_id == key["key_id"]
                )
            )
            row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
            await db.commit()

        resp = await app_client.get(TRAFFIT_STATUS, headers={"X-API-Key": api_key})
        assert resp.status_code == 401

    async def test_deactivating_account_kills_all_its_keys(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        """Kill-switch konta gasi klucze bez wyliczania ich po kolei."""
        account, api_key, _ = await _account_with_key(
            app_client, app_auth_headers, ["traffit:read"]
        )
        patch = await app_client.patch(
            f"{ACCOUNTS_URL}/{account['id']}",
            headers=app_auth_headers,
            json={"is_active": False},
        )
        assert patch.status_code == 200, patch.text

        resp = await app_client.get(TRAFFIT_STATUS, headers={"X-API-Key": api_key})
        assert resp.status_code == 401

    async def test_scope_change_takes_effect_without_reissuing_key(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        """Uprawnienia żyją na koncie, nie w poświadczeniu.

        Tym mechanizm różni się od ``oauth_clients``, gdzie wystawiony JWT niesie
        scope'y ze sobą i przeżywa odebranie uprawnień do końca swojej godziny.
        """
        account, api_key, _ = await _account_with_key(
            app_client, app_auth_headers, ["traffit:sync"]
        )
        assert (
            await app_client.get(TRAFFIT_STATUS, headers={"X-API-Key": api_key})
        ).status_code == 403

        await app_client.patch(
            f"{ACCOUNTS_URL}/{account['id']}",
            headers=app_auth_headers,
            json={"scopes": ["traffit:sync", "traffit:read"]},
        )
        assert (
            await app_client.get(TRAFFIT_STATUS, headers={"X-API-Key": api_key})
        ).status_code == 200

    async def test_service_key_cannot_impersonate_a_user(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        """Poświadczenie bez wygasania sesji + cudze oczy = obejście scope'ów."""
        _, api_key, _ = await _account_with_key(
            app_client, app_auth_headers, ["traffit:read"]
        )
        resp = await app_client.get(
            TRAFFIT_STATUS,
            headers={"X-API-Key": api_key, "X-Impersonate-User-Id": "1"},
        )
        assert resp.status_code == 403
        assert "podszywa" in resp.json()["detail"]

    async def test_key_is_rejected_when_mechanism_is_disabled(
        self, app_client: AsyncClient, app_auth_headers: dict, monkeypatch
    ):
        _, api_key, _ = await _account_with_key(
            app_client, app_auth_headers, ["traffit:read"]
        )
        monkeypatch.setattr(settings, "SERVICE_ACCOUNTS_ENABLED", False)
        resp = await app_client.get(TRAFFIT_STATUS, headers={"X-API-Key": api_key})
        assert resp.status_code == 503

    async def test_admin_jwt_still_works_on_the_same_endpoint(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        """Wpięcie kluczy nie jest zmianą zrywającą dla przeglądarki."""
        resp = await app_client.get(TRAFFIT_STATUS, headers=app_auth_headers)
        assert resp.status_code == 200

    async def test_invalid_key_does_not_fall_through_to_valid_jwt(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        """Przedstawione poświadczenie jest ROZSTRZYGAJĄCE, nie „jedną z prób".

        Gdyby zły klucz cicho spadał na JWT z tego samego requestu, wynik
        zależałby od tego, które poświadczenie akurat zadziała — a skrypt
        z wygasłym kluczem działałby dalej tak długo, jak długo ktoś trzyma
        obok ważną sesję admina, i nikt by się o wygaśnięciu nie dowiedział.
        """
        forged = f"nxs_v2_{'a' * 24}_{'b' * 43}"
        resp = await app_client.get(
            TRAFFIT_STATUS, headers={**app_auth_headers, "X-API-Key": forged}
        )
        assert resp.status_code == 401, resp.text

    async def test_valid_key_wins_over_non_admin_jwt(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        """Ważny klucz rozstrzyga niezależnie od tego, co siedzi w Authorization."""
        _, api_key, _ = await _account_with_key(
            app_client, app_auth_headers, ["traffit:read"]
        )
        resp = await app_client.get(
            TRAFFIT_STATUS,
            headers={"Authorization": "Bearer nonsens.nie.jwt", "X-API-Key": api_key},
        )
        assert resp.status_code == 200, resp.text

    @pytest.mark.parametrize(
        "url",
        [
            "/api/candidates",
            "/api/jobs",
            "/api/clients",
            "/api/users",
        ],
    )
    async def test_key_cannot_reach_domain_data(
        self, app_client: AsyncClient, app_auth_headers: dict, url: str
    ):
        """Klucz z KOMPLETEM scope'ów nie dosięga danych kandydatów.

        To jest właściwość całej konstrukcji, nie konfiguracji konkretnego konta:
        powierzchnie domenowe wiszą na ``get_current_user``, który czyta wyłącznie
        ``Authorization``. ``X-API-Key`` jest tam po prostu nieznanym nagłówkiem,
        więc request jest nieuwierzytelniony (401), a nie „uwierzytelniony bez
        uprawnień".
        """
        _, api_key, _ = await _account_with_key(
            app_client,
            app_auth_headers,
            [scope.value for scope in ServiceScope],
        )
        resp = await app_client.get(url, headers={"X-API-Key": api_key})
        assert resp.status_code == 401, resp.text

    async def test_last_used_is_stamped_after_a_successful_call(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        _, api_key, key = await _account_with_key(
            app_client, app_auth_headers, ["traffit:read"]
        )
        assert key["last_used_at"] is None

        await app_client.get(TRAFFIT_STATUS, headers={"X-API-Key": api_key})

        async with AsyncSessionLocal() as db:
            row = await db.scalar(
                select(ServiceAccountKey).where(
                    ServiceAccountKey.key_id == key["key_id"]
                )
            )
            assert row.last_used_at is not None, "brak sygnału 'czy klucz żyje'"

    async def test_failed_auth_does_not_stamp_usage(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        """Odrzucona próba nie może udawać żywej integracji."""
        _, api_key, key = await _account_with_key(
            app_client, app_auth_headers, ["traffit:sync"]
        )
        # 403 (brak scope'u) — uwierzytelnienie przeszło, więc stempel jest OK.
        # Tutaj sprawdzamy ścieżkę z BŁĘDNYM sekretem, gdzie stempla być nie może.
        key_id_part, _, secret = api_key.rpartition("_")
        tampered = f"{key_id_part}_{'z' * len(secret)}"
        await app_client.get(TRAFFIT_STATUS, headers={"X-API-Key": tampered})

        async with AsyncSessionLocal() as db:
            row = await db.scalar(
                select(ServiceAccountKey).where(
                    ServiceAccountKey.key_id == key["key_id"]
                )
            )
            assert row.last_used_at is None

    async def test_scope_denied_still_stamps_usage(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        """Odrzucenie za BRAK SCOPE'U stempluje — i to jest wybór, nie luka.

        `last_used_at` odpowiada na pytanie „czy ktoś jeszcze tego klucza
        używa", nie „czy używa go skutecznie". Gdyby 403 nie stemplował, klucz
        strzelający co minutę ze źle dobranym scope'em wyglądałby na
        kompletnie nieużywany — operator uznałby go za martwy i skasował,
        zamiast zobaczyć, że jakaś integracja żyje i jest źle skonfigurowana.

        Odwrotnie niż przy BŁĘDNYM SEKRECIE (test wyżej), gdzie stempla być nie
        może: tam nie wiadomo nawet, czy dzwoni właściciel klucza.

        Test istnieje po to, żeby ta różnica nie zniknęła po cichu przy
        refaktorze — sama w sobie jest niewidoczna w kodzie, bo wynika z
        KOLEJNOŚCI dwóch operacji w różnych funkcjach.
        """
        _, api_key, key = await _account_with_key(
            app_client, app_auth_headers, ["traffit:read"]
        )
        # Klucz poprawny, ale bez `traffit:sync` wymaganego przez ten endpoint.
        resp = await app_client.post(TRAFFIT_SYNC, headers={"X-API-Key": api_key})
        assert resp.status_code == 403

        async with AsyncSessionLocal() as db:
            row = await db.scalar(
                select(ServiceAccountKey).where(
                    ServiceAccountKey.key_id == key["key_id"]
                )
            )
            assert row.last_used_at is not None


# ── 4. Powierzchnia administracyjna ──────────────────────────────────────────


class TestAdminSurface:
    async def test_secret_is_returned_once_and_never_again(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        account, api_key, key = await _account_with_key(
            app_client, app_auth_headers, ["traffit:read"]
        )

        listing = await app_client.get(ACCOUNTS_URL, headers=app_auth_headers)
        assert listing.status_code == 200
        body = listing.text
        _, secret = parse_api_key(api_key)

        assert secret not in body, "sekret wyciekł do listingu kont"
        assert api_key not in body
        # Metadane muszą być widoczne — bez key_id nie da się rewokować.
        assert key["key_id"] in body

    async def test_stored_row_holds_only_the_digest(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        _, api_key, key = await _account_with_key(
            app_client, app_auth_headers, ["traffit:read"]
        )
        _, secret = parse_api_key(api_key)

        async with AsyncSessionLocal() as db:
            row = await db.scalar(
                select(ServiceAccountKey).where(
                    ServiceAccountKey.key_id == key["key_id"]
                )
            )
            assert row.secret_sha256 == hashlib.sha256(secret.encode()).hexdigest()
            # Żadna kolumna tekstowa nie trzyma sekretu.
            for column in ("key_id", "secret_sha256", "label"):
                assert secret not in (getattr(row, column) or "")

    async def test_rotation_keeps_both_keys_alive_on_one_identity(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        """Wymiana bez przestoju: wydaj drugi → wdroż → rewokuj pierwszy."""
        account, old_key, old_meta = await _account_with_key(
            app_client, app_auth_headers, ["traffit:read"]
        )
        new_key, _ = await _issue_key(app_client, app_auth_headers, account["id"])

        for key in (old_key, new_key):
            resp = await app_client.get(TRAFFIT_STATUS, headers={"X-API-Key": key})
            assert resp.status_code == 200

        await app_client.post(
            f"{ACCOUNTS_URL}/{account['id']}/keys/{old_meta['key_id']}/revoke",
            headers=app_auth_headers,
            json={"reason": "rotacja"},
        )
        assert (
            await app_client.get(TRAFFIT_STATUS, headers={"X-API-Key": old_key})
        ).status_code == 401
        assert (
            await app_client.get(TRAFFIT_STATUS, headers={"X-API-Key": new_key})
        ).status_code == 200

    async def test_service_key_cannot_manage_service_accounts(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        """Bez tego klucz o wąskim scope'ie wydałby sobie klucz szerszy.

        Konto ma tu KOMPLET scope'ów, więc odmowa nie wynika z braku uprawnienia,
        tylko z tego, że powierzchnia administracyjna w ogóle nie przyjmuje
        kluczy — wisi na ``AdminUser``, dla którego ``X-API-Key`` nie istnieje.
        """
        _, api_key, _ = await _account_with_key(
            app_client,
            app_auth_headers,
            [scope.value for scope in ServiceScope],
        )
        for method, url in (
            ("get", ACCOUNTS_URL),
            ("post", ACCOUNTS_URL),
            ("get", f"{ACCOUNTS_URL}/scopes"),
        ):
            resp = await getattr(app_client, method)(url, headers={"X-API-Key": api_key})
            assert resp.status_code == 401, f"{method} {url} -> {resp.text}"

    async def test_admin_crud_requires_authentication(self, app_client: AsyncClient):
        assert (await app_client.get(ACCOUNTS_URL)).status_code == 401

    async def test_duplicate_slug_is_409(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        account = await _create_account(app_client, app_auth_headers, [])
        resp = await app_client.post(
            ACCOUNTS_URL,
            headers=app_auth_headers,
            json={"slug": account["slug"], "name": "Duplikat", "scopes": []},
        )
        assert resp.status_code == 409

    async def test_patch_is_partial(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        """Zgaszenie konta nie może po drodze wyczyścić jego uprawnień."""
        account = await _create_account(
            app_client, app_auth_headers, ["traffit:read"]
        )
        resp = await app_client.patch(
            f"{ACCOUNTS_URL}/{account['id']}",
            headers=app_auth_headers,
            json={"is_active": False},
        )
        assert resp.status_code == 200
        assert resp.json()["scopes"] == ["traffit:read"]
        assert resp.json()["name"] == account["name"]

    async def test_unknown_scope_is_rejected_at_the_schema(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        resp = await app_client.post(
            ACCOUNTS_URL,
            headers=app_auth_headers,
            json={
                "slug": f"pytest-bad-{uuid.uuid4().hex[:8]}",
                "name": "x",
                "scopes": ["candidate:read"],
            },
        )
        assert resp.status_code == 422

    @pytest.mark.parametrize(
        "slug",
        [
            "ab",
            "ze spacja",
            "-startuje-myslnikiem",
            "konczy-myslnikiem-",
            "ma_podkreslnik",
            "x" * 65,
        ],
    )
    async def test_invalid_slug_is_rejected(
        self, app_client: AsyncClient, app_auth_headers: dict, slug: str
    ):
        resp = await app_client.post(
            ACCOUNTS_URL,
            headers=app_auth_headers,
            json={"slug": slug, "name": "x", "scopes": []},
        )
        assert resp.status_code == 422

    async def test_slug_is_normalised_to_lowercase(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        """„Traffit-Ops" i „traffit-ops" to ten sam podmiot w audycie.

        Normalizacja zamiast odrzucenia sprawia, że kolizja wielkości liter
        kończy się jawnym 409, a nie dwoma kontami nie do odróżnienia w logach.
        """
        raw = f"Pytest-CASE-{uuid.uuid4().hex[:8]}"
        resp = await app_client.post(
            ACCOUNTS_URL,
            headers=app_auth_headers,
            json={"slug": f"  {raw}  ", "name": "x", "scopes": []},
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["slug"] == raw.lower()

        collision = await app_client.post(
            ACCOUNTS_URL,
            headers=app_auth_headers,
            json={"slug": raw.upper(), "name": "x", "scopes": []},
        )
        assert collision.status_code == 409

    async def test_deleting_account_cascades_to_keys(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        account, api_key, key = await _account_with_key(
            app_client, app_auth_headers, ["traffit:read"]
        )
        resp = await app_client.delete(
            f"{ACCOUNTS_URL}/{account['id']}", headers=app_auth_headers
        )
        assert resp.status_code == 204

        async with AsyncSessionLocal() as db:
            row = await db.scalar(
                select(ServiceAccountKey).where(
                    ServiceAccountKey.key_id == key["key_id"]
                )
            )
            assert row is None
        assert (
            await app_client.get(TRAFFIT_STATUS, headers={"X-API-Key": api_key})
        ).status_code == 401

    async def test_scopes_endpoint_lists_the_vocabulary(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        resp = await app_client.get(
            f"{ACCOUNTS_URL}/scopes", headers=app_auth_headers
        )
        assert resp.status_code == 200
        values = {item["value"] for item in resp.json()}
        assert values == {scope.value for scope in ServiceScope}


class TestOpsSnapshotScope:
    """`ops:snapshot` musi realnie czegoś strzec, nie być martwym słownikiem.

    Scope, którego żaden endpoint nie sprawdza, to obietnica bez pokrycia —
    admin nadaje go wierząc, że coś robi.
    """

    SNAPSHOT = "/api/admin/snapshot"

    async def test_key_with_ops_snapshot_scope_is_accepted(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        _, api_key, _ = await _account_with_key(
            app_client, app_auth_headers, ["ops:snapshot"]
        )
        resp = await app_client.get(self.SNAPSHOT, headers={"X-API-Key": api_key})
        assert resp.status_code == 200, resp.text
        assert resp.json()["auth_mode"] == "service_account"

    async def test_key_without_ops_snapshot_scope_is_denied(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        _, api_key, _ = await _account_with_key(
            app_client, app_auth_headers, ["traffit:read"]
        )
        resp = await app_client.get(self.SNAPSHOT, headers={"X-API-Key": api_key})
        assert resp.status_code == 403

    async def test_revoked_key_cannot_read_snapshot(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        account, api_key, key = await _account_with_key(
            app_client, app_auth_headers, ["ops:snapshot"]
        )
        await app_client.post(
            f"{ACCOUNTS_URL}/{account['id']}/keys/{key['key_id']}/revoke",
            headers=app_auth_headers,
            json={"reason": "test"},
        )
        resp = await app_client.get(self.SNAPSHOT, headers={"X-API-Key": api_key})
        assert resp.status_code == 401

    async def test_legacy_token_and_admin_jwt_paths_survive(
        self, app_client: AsyncClient, app_auth_headers: dict, monkeypatch
    ):
        """Dołożenie klucza nie może zepsuć dwóch działających ścieżek."""
        monkeypatch.setattr(settings, "SNAPSHOT_TOKEN", "pytest-snapshot-token-123456")
        by_token = await app_client.get(
            self.SNAPSHOT, headers={"X-Snapshot-Token": "pytest-snapshot-token-123456"}
        )
        assert by_token.status_code == 200
        assert by_token.json()["auth_mode"] == "token"

        by_jwt = await app_client.get(self.SNAPSHOT, headers=app_auth_headers)
        assert by_jwt.status_code == 200
        assert by_jwt.json()["auth_mode"] == "jwt"


class TestRateLimit:
    async def test_key_authenticated_endpoint_is_rate_limited(
        self, app_client: AsyncClient, app_auth_headers: dict, monkeypatch
    ):
        """Powierzchnia przyjmująca klucz musi mieć sufit tempa.

        ``app_client`` globalnie wyłącza slowapi (inaczej logowanie w innych
        suitach wpadałoby w limit), więc limiter jest tu włączany celowo
        i przywracany po teście.
        """
        from app.core.rate_limit import limiter

        _, api_key, _ = await _account_with_key(
            app_client, app_auth_headers, ["traffit:read"]
        )
        monkeypatch.setattr(settings, "SERVICE_ACCOUNT_RATE_LIMIT", "2/minute")
        limiter.enabled = True
        # Kubełek jest per IP i współdzielony między testami w procesie —
        # unikalny nagłówek daje temu testowi własny.
        headers = {
            "X-API-Key": api_key,
            "X-Forwarded-For": f"203.0.113.{uuid.uuid4().int % 200 + 1}",
        }
        try:
            statuses = [
                (await app_client.get(TRAFFIT_STATUS, headers=headers)).status_code
                for _ in range(4)
            ]
        finally:
            limiter.enabled = False
            limiter.reset()

        assert 429 in statuses, f"brak limitu tempa: {statuses}"


class TestDatabaseIntegrity:
    async def test_db_rejects_non_array_scopes(self):
        """CHECK w bazie, nie tylko walidacja w API.

        Ręczny UPDATE albo import z pominięciem warstwy aplikacji nie może
        zostawić wiersza, na którym sprawdzenie uprawnień zamienia się w test
        podciągu.
        """
        from sqlalchemy import text
        from sqlalchemy.exc import IntegrityError

        async with AsyncSessionLocal() as db:
            account = ServiceAccount(
                slug=f"pytest-chk-{uuid.uuid4().hex[:8]}",
                name="check",
                scopes=[],
            )
            db.add(account)
            await db.commit()

            with pytest.raises(IntegrityError):
                await db.execute(
                    text(
                        "UPDATE service_accounts SET scopes = '\"traffit:sync\"'::jsonb "
                        "WHERE id = :id"
                    ),
                    {"id": account.id},
                )
                await db.commit()
            await db.rollback()
