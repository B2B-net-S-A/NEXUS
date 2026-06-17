[← powrót do docs/](./README.md)

# In-house QES e-signature — raport postępu (Faza 0 + Faza 1)

**Data:** 2026-06-16 (zaktualizowano 2026-06-17) · **Status:** Faza 0 ✅, Faza 1 ✅, **Faza 2 + 3 ścieżki podpisu (link / oznacz wysłaną / wgraj podpisaną) WDROŻONE NA PRODZIE ✅** — patrz sekcja „WDROŻONE NA PRODZIE" na końcu. Fazy 3–5 (Szafir/mSzafir KIR, B-LTA) ⏳ gated na onboarding KIR — upload-validate ich nie wymaga.

Plan referencyjny: [in-house-qes-signature-plan.md](./in-house-qes-signature-plan.md).

---

## Kontekst granic

Dwa twarde ograniczenia kształtowały zakres tej sesji:

1. **KIR (zewnętrzne, biznesowe):** realny podpis QES (Fazy 3–5) wymaga umowy z KIR, licencji Szafir SDK, dostępu do mSzafir API i sandboxa. Bez tego integracja z podpisem to kod do wymyślonego API — celowo **NIE** budowany na ślepo; punkty styku z KIR są jawnymi stubami.
2. **Środowisko (lokalne):** sandbox bez `docker`/Postgresa → nie dało się lokalnie odpalić `alembic upgrade head` ani `pytest`. **Weryfikacja migracji odbywa się w CI** (`alembic upgrade head` na testowej bazie + pytest — per `CLAUDE.md`). Dlatego praca jest na branchu + PR, **bez merge'a do `main`** (niezweryfikowana migracja nie dotyka proda; deploy zostaje świadomą decyzją po zielonym CI + przeglądzie).

---

## 🔑 AKTUALIZACJA — ścieżka BEZ KIR potwierdzona (open-source)

Po pytaniu „może nic nie potrzebujemy od KIR" — **research + lokalny proof potwierdziły: dla ścieżki upload-and-validate (Option B) NIE potrzebujemy NIC od KIR.**

- **pyHanko `[etsi]`** (open-source) waliduje cudzy podpis PAdES względem **unijnej Trusted List (EU LOTL — klucze bootstrap wbudowane w bibliotekę)** + ma subpakiet `qualified` (`q_status.QualifiedStatus`, `assess`, `eutl_parse`) do oceny QES wg eIDAS. [(pyHanko validation docs)](https://docs.pyhanko.eu/en/latest/lib-guide/validation.html)
- **Zweryfikowane lokalnie:** zainstalowany pyHanko, potwierdzone API (`async_validate_pdf_signature`, `EmbeddedPdfSignature`, `ValidationContext`, `qualified.q_status`). **Konflikt wersji rozwiązany:** pyHanko 0.35 wymaga `cryptography>=48`, ale `pyhanko[etsi]==0.34.1` **koegzystuje z repo-pinem `cryptography==44.0.0`** (resolver to potwierdził).
- **Autorytatywny werdykt „is QES"** = **EU DSS** (Java sidecar, też open-source) — nasz `ValidationService` już go używa (pyHanko = lokalny pre-check integralności).

**Co to znaczy:** możemy zbudować i wdrożyć **pełnoprawny, legalnie ważny przepływ QES BEZ KIR**: konsultant podpisuje umowę **własnym** podpisem kwalifikowanym (dowolnym darmowym narzędziem — ma już certyfikat), uploaduje podpisany PDF, my walidujemy (pyHanko + EU DSS). Zero dostawcy, zero opłat per podpis, ważne dla przeniesienia IP.

**Czego KIR jest potrzebny (tylko wygoda):** (a) podpis **wbudowany w aplikację** (Szafir SDK Web — licencja + wg researchu robi CAdES/XAdES, PAdES-dla-PDF do potwierdzenia), (b) **wydanie jednorazowego certu** dla konsultanta BEZ podpisu (mSzafir One Shot).

**Trade-off ścieżki bez KIR:** konsultant musi (1) **mieć już** podpis kwalifikowany i (2) podpisać offline + uploadować (krok więcej niż in-app). Wielu kontraktorów IT (JDG) ma podpis (JPK/ZUS); reszta wyrabia lub czekamy na mSzafir.

**Dodane w kodzie (ten commit):** `pyhanko[etsi]==0.34.1` w `requirements.txt` + realny `pades.validate_pades_local` (pre-check integralności + signer, na potwierdzonym API 0.34.1). CI zweryfikuje rozwiązanie zależności na Py3.12 + cryptography 44.

**Następny build bez KIR (Faza 2/4 upload-lane):** endpointy `api/signing.py` + `api/public_signing.py` (`/submit` upload), `sender.py`, strona `/sign/[token]` (download umowy → upload podpisanego PDF → werdykt), sidecar EU DSS. Wszystko KIR-niezależne i CI-weryfikowalne.

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

---

## ✅ WDROŻONE NA PRODZIE — Faza 2 + rozszerzenia (2026-06-17)

**Status:** szyna upload-validate **w pełni działa na prodzie** (`main` @ `b4ce176`, `/api/health` healthy). KIR (Szafir/mSzafir) wciąż opcjonalny — upload-validate go nie wymaga.

**Wdrożone (PR-y, wszystkie merged + deployed):**
- **#506/#511** — Faza 1+2 kod: migracja `0133`, pakiet `services/signing/`, router `api/signing.py` + publiczny `api/public_signing.py` wpięte w `main.py`, `SIGNING_ENABLED=true` w Coolify vault. E2E zweryfikowane na żywo (self-signed PAdES → `/api/public/sign/{token}/submit` → `completed`).
- **#513** — podgląd umowy w przeglądarce (blob iframe, bo backend `X-Frame-Options: DENY`); `render_unsigned_pdf`/`prepare_send` fallback do `Contract.draft_content_html`; `send-for-signature` zwraca `sign_url` synchronicznie.
- **#514** — przycisk „Wyślij do podpisu (QES)" w Generatorze Umów B2B (`generate` → `sendForSignature` → kopiowalny link).
- **#515** — pipeline: migracja `0135` dodaje etap „Umowa podpisana" (id 1032, order 10) po „Umowa wysłana" (id 753, order 9) w Default B2B (template 1); `pipeline_hook.move_candidate_for_signing` przesuwa kandydata send→„Umowa wysłana", podpisano→„Umowa podpisana".
- **#516** — **flow offline (e-mail)**: dla rekruterów, którzy wysyłają/odbierają umowę mailem zamiast publicznym linkiem, ale chcą przesuwać pipeline:
  - `POST /api/signing/contracts/{id}/mark-sent-offline` → `DocumentSignature(status=sent)` + move „Umowa wysłana".
  - `POST /api/signing/contracts/{id}/upload-signed` → walidacja wgranego PAdES (ta sama co flow konsultanta) + complete + move „Umowa podpisana".
  - Wyodrębniony `sender.finalize_signed_pdf()` (walidacja + zapis + complete + move + notyfikacja) reużywany przez publiczny `/submit` i rekruterski `/upload-signed`.
  - `prepare_send()` akceptuje też kontrakty `draft` (generator B2B tworzy `draft`) — naprawia 409 dla świeżo wygenerowanych umów (dotyczy też #514).
  - FE: dwa przyciski w generatorze („Oznacz: wysłana mailem", „Wgraj podpisaną (z maila)") + `signingApi.markSentOffline`/`uploadSigned`.

**Weryfikacja #516 na żywo (2026-06-17):**
- Deploy `b4ce176` zielony, `/api/health` healthy (version match).
- Endpointy: bez auth → 403; auth + nieistniejący kontrakt → 404 (`prepare_send` „Contract not found"); upload nie-PDF → 422 („To nie jest plik PDF").
- FE (Chrome, świeży bundle prod): oba przyciski renderują się pod istniejącymi akcjami; klik bez wybranego kandydata → guard `validate()` (banner „Uzupełnij wymagane pola…"), **żaden** request `/api/signing` nie poleciał przedwcześnie.
- DB: etapy docelowe istnieją w Default B2B (753 „Umowa wysłana", 1032 „Umowa podpisana") → `move_candidate_for_signing` rozwiązuje cele.

**Trzy ścieżki podpisu — podsumowanie (wszystkie żywe na prodzie):**
1. **Link publiczny** — „Wyślij do podpisu (QES)" → konsultant czyta w przeglądarce, podpisuje własnym narzędziem, wgrywa na `/sign/{token}` → auto-move pipeline.
2. **Offline: oznacz wysłaną** — rekruter wysłał mailem → „Oznacz: wysłana mailem" → move „Umowa wysłana".
3. **Offline: wgraj podpisaną** — rekruter dostał podpisaną z maila → „Wgraj podpisaną (z maila)" → walidacja PAdES → move „Umowa podpisana".

**„Podpisz w panelu bez pobierania" (jak Autenti)** — niewykonalne bez KIR (wbudowany QES w przeglądarce wymaga Szafir SDK/karty lub mSzafir/chmury). Upload-validate to jedyna ścieżka bez KIR; jest wdrożona i wystarcza dla obecnego zakresu.

---

## ✅ Both-parties-signed → „Zatrudniony" (2026-06-17, PR #521, main `9d2cb6e`)

Gdy wgrany podpisany PAdES jest podpisany **przez obie strony** (konsultant + nasza strona), umowa jest w pełni zawarta ⇒ kandydat przechodzi na terminalny etap **„Zatrudniony"** (hired) zamiast zatrzymywać się na „Umowa podpisana". Pojedynczy podpis (sam konsultant) ⇒ „Umowa podpisana".

**Wykrywanie:** liczba **podpisów zatwierdzających** (approval signatures) w PAdES, z **wykluczeniem** PAdES document timestamps (B-T/B-LTA). `>= 2` ⇒ obie strony ⇒ hired; nieznana liczba (błąd parsowania / DSS) ⇒ konserwatywnie „Umowa podpisana" (**nigdy** fałszywie na hired).

**Implementacja:**
- `pades.count_approval_signatures()` — bez sieci, API zweryfikowane wobec `pyhanko[etsi]==0.34.1` (`sig_object_type` `/Sig` vs `/DocTimeStamp`, `signer_cert.subject.human_friendly`); timestampy wykluczone dwojako (`/DocTimeStamp` **i** `/SubFilter==/ETSI.RFC3161`).
- `ValidationReport.{signature_count, signers, both_parties_signed}` (property `(count or 0) >= 2`, konserwatywna na `None`); `validation.py` przeprowadza liczbę przez pyHanko + (defensywnie, Faza-4 TODO) DSS.
- `pipeline_hook.STAGE_HIRED="Zatrudniony"` — „Zatrudniony" (stage_def id 10) ma `legacy_enum_value="hired"`, więc generyczny resolver daje `PipelineStage.hired`; guard wymusza hired (bo „U klienta"/placementy/KPI czytają stary enum `stage`). **Nie** powiela auto-draft-Contractu z normalnego hooka hired (kontrakt już istnieje), **nie** aktywuje kontraktu.
- `sender.finalize_signed_pdf` rozgałęzia etap docelowy; wzbogaca Activity/Notyfikację/werdykt. Współdzielone przez publiczny `/submit` i rekruterski `/upload-signed`.
- FE: werdykt „podpisana przez obie strony / Zatrudniony" w Generatorze B2B + publicznej stronie `/sign`.

**Weryfikacja:**
- **Empiryczna (decydująca):** faktyczna `count_approval_signatures` uruchomiona na prawdziwych PDF-ach 1-podpisowym i 2-podpisowym (pyHanko, self-signed w throwaway venv): `count` = 1 i 2, nazwy sygnatariuszy poprawnie wyekstrahowane; `both_parties_signed`: None/0/1→False, 2→True.
- **Przegląd adversarialny (python-reviewer):** SHIP. Timestampy poprawnie wykluczone na ścieżce pyHanko (aktywnej na prodzie); `None` zawsze konserwatywnie → „Umowa podpisana"; `finalize_signed_pdf` nie może paść; podwójny dostęp do `reader.embedded_signatures` bezpieczny (pyHanko cache `_embedded_signatures`).
- Deploy `9d2cb6e` healthy; `provider: szafir_sdk` globalnie, ale upload/submit tworzą sygnaturę `provider="upload_validate"` ⇒ walidacja pyHanko (dss=False).
- Bez nowej migracji (stage_def + enum już istnieją); `alembic heads` pojedynczy.

**Ograniczenia (udokumentowane):**
- **R2:** konsultant-spółka z reprezentacją łączną (2 podpisy zarządu) mógłby trafić `>=2` zanim my podpiszemy → fałszywe „Zatrudniony". Rzadkie (JDG dominują). Mitygacja: `signers` zapisane + zwracane (audyt); rekruter cofa. Follow-up: bramkować na dopasowaniu DN sygnatariusza do reprezentanta firmy.
- **DSS path (Faza 4, nieaktywny):** filtr timestampów w `_map_dss_report` do walidacji wobec realnej odpowiedzi DSS przed włączeniem (TODO w kodzie).
