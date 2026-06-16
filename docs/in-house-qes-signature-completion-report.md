[← powrót do docs/](./README.md)

# In-house QES e-signature — raport postępu (Faza 0 + Faza 1)

**Data:** 2026-06-16 · **Branch:** `claude/cranky-nightingale-b7c730` · **Status:** Faza 0 ✅, Faza 1 ✅ (kod, do weryfikacji bazą w CI), Fazy 2–5 ⏳ (gated na KIR)

Plan referencyjny: [in-house-qes-signature-plan.md](./in-house-qes-signature-plan.md).

---

## Kontekst granic

Dwa twarde ograniczenia kształtowały zakres tej sesji:

1. **KIR (zewnętrzne, biznesowe):** realny podpis QES (Fazy 3–5) wymaga umowy z KIR, licencji Szafir SDK, dostępu do mSzafir API i sandboxa. Bez tego integracja z podpisem to kod do wymyślonego API — celowo **NIE** budowany na ślepo; punkty styku z KIR są jawnymi stubami.
2. **Środowisko (lokalne):** sandbox bez `docker`/Postgresa → nie dało się lokalnie odpalić `alembic upgrade head` ani `pytest`. **Weryfikacja migracji odbywa się w CI** (`alembic upgrade head` na testowej bazie + pytest — per `CLAUDE.md`). Dlatego praca jest na branchu + PR, **bez merge'a do `main`** (niezweryfikowana migracja nie dotyka proda; deploy zostaje świadomą decyzją po zielonym CI + przeglądzie).

---

## ✅ Faza 0 — onboarding (gotowe do wysłania)

- [docs/qes-faza0-kir-outreach.md](./qes-faza0-kir-outreach.md) — zapytanie ofertowo-techniczne do KIR (25 pytań: Szafir SDK Web Module + Szafir Host, mSzafir One Shot API, PAdES/TSA, cennik, onboarding, sandbox). Do uzupełnienia: dane spółki w stopce.
- [docs/qes-faza0-legal-questions.md](./qes-faza0-legal-questions.md) — 8 pytań do prawnika (forma pisemna + IP, reprezentacja spółki, JDG vs spółka, pieczęć vs podpis osoby, obcokrajowiec, retencja B-LT/B-LTA, One Shot = QES?, RODO/DPA) z uzasadnieniem każdego.

**Działanie po stronie Artura:** wysłać oba dokumenty — to odblokowuje Fazy 3–5 (najdłuższy lead-time).

## ✅ Faza 1 — provider abstraction + migracja (kod kompletny)

Czysty refactor czyniący szynę podpisów provider-agnostyczną; Autenti dalej działa pod `provider='autenti'` (zero zmiany zachowania).

**Migracja** `backend/alembic/versions/0133_signing_provider_refactor.py` (od single-head `0132_b2b_render_payload`):
- RENAME `document_signatures.autenti_process_id` → `provider_ref`, `autenti_signature_type` → `signature_type` (guarded `DO $$ IF EXISTS`).
- ADD `provider` (backfill `'autenti'`), `signing_session_id`, `identity_provider`, `signature_level`, `validation_report` JSONB (wszystkie `IF NOT EXISTS`).
- CREATE `signature_links` (single-use tokeny `/sign`) + index.
- `chk_signature_target_xor` **nietknięte**; **bez** `ALTER TYPE` na enumie notyfikacji.

**Model/schema:**
- `models/document_signature.py` — nowe kolumny + **property+setter aliasy** `autenti_process_id`/`autenti_signature_type` (utrzymują kod Autenti bez zmian).
- `models/signature_link.py` (nowy) + rejestracja w `models/__init__.py`.
- `schemas/document_signature.py` — nowe pola + `@computed_field` aliasy (FE nie pęka) + `SignForSignatureRequest`.

**Pakiet `services/signing/`** (provider-agnostic):
- `provider.py` — `SignatureProvider` Protocol + `ProviderRef`/`SignedArtifact`/`ValidationReport` + wyjątki (`SigningProviderNotConfigured` → 503).
- `registry.py` — `get_provider(name)`.
- `szafir_sdk_provider.py` — **pas główny**, realny: odbiera client-signed PAdES + waliduje.
- `mszafir_provider.py` + `mszafir_client.py` — **pas zapasowy**, stub KIR API (jawny `NotImplementedError` + TODO Faza 0).
- `upload_validate_provider.py` — Option B, realny (upload + walidacja).
- `autenti_provider.py` — deprecated wrapper.
- `validation.py` — `ValidationService` → DSS sidecar (z pyHanko fallback; **nigdy** nie traktuje niezweryfikowanego podpisu jako QES).
- `pades.py` — pyHanko validate/B-LTA (stub do Faz 3/5).
- `pdf_renderer.py` — re-export provider-neutralny.

**Config** (`core/config.py`): `SIGNING_ENABLED` (killswitch), `SIGNING_PROVIDER`, `SIGNING_LINK_EXPIRY_DAYS`, `SIGNING_SWEEPER_INTERVAL_SECONDS`, `QTSP_SZAFIR_SDK_*`, `QTSP_MSZAFIR_*`, `DSS_VALIDATION_URL`.

**Naprawione regresje rename** (wyrażenia klasowe SQL, które property by zepsuła):
- `tasks/autenti_expiry_sweeper.py` ×2 → `provider_ref`.
- `services/autenti/webhook_handler.py` lookup → `provider_ref`.
- Dostęp instancyjny i kwargi konstruktora działają przez property/setter (bez zmian).

**Weryfikacja statyczna (lokalna):** `python -m py_compile` ✅ wszystkie pliki · `ruff check` ✅ · `ruff format --check` ✅.
**Weryfikacja dynamiczna (CI):** `alembic upgrade head` + `pytest` na PR — **musi przejść przed merge**.

## ⏳ Fazy 2–5 — pozostałe (interfejsy gotowe)

Fundament (Protocol + schematy + kolumny + flagi) jest na miejscu, więc poniższe to dopięcie, nie projekt od zera:

- **Faza 2 (in-house, bez krypto):** `api/signing.py` (router gated `SIGNING_ENABLED`), publiczne `/api/public/sign/{token}` (+ `/pdf`, `/submit`, `/mszafir-*`), `sender.py` (`prepare_send` + `initiate_signing`: render PDF → mint `SignatureLink` → e-mail), `tasks/signing_sweeper.py` + rejestracja w `main.py`, FE: przycisk w `B2BContractGeneratorV2.tsx` + publiczna strona `frontend/src/app/sign/[token]/` + `signingApi`. **Świadomie nie wpięte w `main.py`** póki nie zweryfikowane na bazie (router import w boot = ryzyko startu).
- **Faza 3 (KIR):** osadzenie Szafir SDK Web Module na `/sign`, `mszafir_client` realne wywołania (po dokumentacji KIR), dwustronny podpis, `pyhanko` w `requirements.txt`.
- **Faza 4:** sidecar `dss-validation` (compose, profile `signing`) + `_map_dss_report` dostrojony do realnego JSON-a.
- **Faza 5:** B-LTA archival + `SIGNING_PROVIDER=szafir_sdk` default + `AUTENTI_ENABLED=false` cutover.

## Checklist weryfikacji przed merge do `main`

- [ ] CI zielone (gitleaks + ruff + `alembic upgrade head` + pytest).
- [ ] `alembic heads` = 1 (single-head zachowany).
- [ ] Na maszynie z DB: `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` (round-trip migracji).
- [ ] Smoke: istniejący flow Autenti (jeśli `AUTENTI_ENABLED`) niezmieniony — `provider_ref`/`signature_type` czytają się przez aliasy.
- [ ] Dopiero po tym Fazy 2–5 (Faza 2 równolegle do odpowiedzi KIR; Fazy 3–5 po KIR).
