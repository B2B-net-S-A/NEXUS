[← powrót do docs/](./README.md)

# In-house QES e-signature — plan implementacji (Szafir-first)

## 1. Metadane + decyzja

| Pole | Wartość |
|---|---|
| **Data** | 2026-06-16 |
| **Status** | Plan — do realizacji |
| **Zakres** | TYLKO umowy B2B z **Generatora Umów B2B** (`/contracts/b2b-generator`) |
| **Dostawca (QTSP)** | **KIR** — single-vendor (Szafir SDK + mSzafir API). Certum/EuroCert NIE są integrowane |
| **Branch migracji od** | `0132_b2b_render_payload` (aktualny single-head) |
| **Kill-switch** | `SIGNING_ENABLED` (wzorzec `AUTENTI_ENABLED`) |
| **Repo** | `artur-t-96/Nexus`, monorepo `backend/` + `frontend/` |

### Decyzja (skrót)

Budujemy **własny in-house flow podpisu kwalifikowanego (QES)** wbudowany w NEXUS i **w pełni zastępujemy Autenti** — żadnej platformy pośredniczącej. Integrujemy się **bezpośrednio z KIR** (Krajowa Izba Rozliczeniowa) jako jedynym QTSP, dwoma komplementarnymi pasami:

- **Pas główny — Szafir SDK (client-side).** Osadzamy **Szafir SDK Web Module** (biblioteka JS KIR) na naszej stronie `/sign/[token]`; podpisujący używa **własnego certyfikatu kwalifikowanego** (karta/token/mobilny) przez lokalny **Szafir Host** + rozszerzenie przeglądarki. Podpis PAdES powstaje **po stronie klienta**, wraca do NEXUSa, my go **walidujemy** i przechowujemy. Koszt: licencja SDK, **zero opłat per podpis**.
- **Pas zapasowy — mSzafir „One Shot" (chmura).** Dla konsultanta **bez** własnego certu: KIR wydaje **jednorazowy certyfikat** po weryfikacji tożsamości (bank / mObywatel / e-dowód NFC), podpis w chmurze przez **mSzafir API**. Bez karty, bez instalacji. Koszt per podpis (zwykle płaci nadawca → konsultant podpisuje za darmo).

**Strona spółki (B2B Network)** podpisuje **imienny umocowany reprezentant** swoim certyfikatem kwalifikowanym **na karcie przez ten sam komponent Szafir** (pieczęć kwalifikowana NIE jest dopuszczalnym substytutem przy klauzuli IP). Walidację „czy to faktycznie QES" robi **pyHanko** (szybki trust-chain) + **EU DSS** (`dss-validation-rest`, sidecar Java) jako autorytet. Konsultant zawsze jest rekordem `Candidate` w NEXUS. Reużywamy **~80% istniejącej szyny podpisów** (po Autenti), wymieniając tylko warstwę dostawcy.

---

## 2. Ograniczenie prawne (skrót)

Podpis kwalifikowany (QES) z mocy eIDAS może opierać się wyłącznie na **certyfikacie wydanym przez QTSP** z unijnej Trusted List — **nie da się go „self-issue"**. „Własny system" = NEXUS posiada cały portal/orkiestrację, a KIR (QTSP) dostarcza tylko **komponent podpisu (Szafir SDK)** i **certyfikaty** (Szafir SDK obsługuje cert dowolnego QTSP; mSzafir wydaje własny). KIR **nie jest platformą** typu Autenti — to wystawca certyfikatów + dostawca SDK, więc to w pełni zastępuje Autenti. Umowy przenoszą majątkowe prawa autorskie → **art. 53 pr.aut.** wymaga **formy pisemnej pod rygorem nieważności**, którą wg **art. 781 §1 k.c.** spełnia elektronicznie **tylko QES** (SES/AdES/profil zaufany → klauzula IP **nieważna**). Stronę spółki musi podpisać **imienna osoba fizyczna** (pieczęć podmiotu nie zastępuje podpisu osoby). Stąd: dwustronny QES (konsultant + reprezentant) na jednym PDF PAdES.

---

## 3. Architektura — przegląd

### Sekwencja end-to-end

1. **Generator B2B** → promocja wygenerowanej umowy do realnego `Contract(type=b2b)` przez `POST /api/b2b-generator/generate` (signer z `Candidate`).
2. `POST /api/signing/contracts/{id}/send-for-signature` → `DocumentSignature(provider=szafir_sdk, signature_type=QES, status=draft)`; bg `initiate_signing`: render PDF (WeasyPrint) → zapis niepodpisanego PDF → mint `SignatureLink` per party → e-mail z linkiem.
3. **Konsultant** otwiera `/sign/[token]` → wybiera:
   - **„Podpisz kartą (Szafir)"** → strona ładuje **Szafir SDK Web Module**, wykrywa Szafir Host, podaje PDF → konsultant podpisuje **swoją kartą** → klient zwraca **PAdES-signed PDF** → `POST /api/public/sign/{token}/submit`.
   - **„Podpisz przez mSzafir (bez karty)"** → `POST /api/public/sign/{token}/mszafir-start` → backend woła **mSzafir API** (One Shot) → redirect/widget identyfikacji (bank/mObywatel) → KIR wydaje cert + podpisuje w chmurze → backend pobiera podpisany PDF (callback/poll).
4. Backend **waliduje** PAdES (pyHanko → szybko; EU DSS → autorytatywnie „is QES") → zapis `validation_report` + `signature_level`.
5. **Reprezentant spółki** podpisuje ten sam (już raz podpisany) PDF — **kartą przez Szafir** (drugi podpis **incremental**, nie unieważnia pierwszego), `party=company`.
6. Po obu podpisach: `status=completed`, attach signed PDF jako `ContractDocument`, notyfikacja `signature_signed` do rekrutera.
7. (Faza 5) archiwalny znacznik czasu **B-LTA** (sweeper refresh) dla długoterminowej dowodliwości.

### Diagram (ASCII)

```
Generator B2B (Candidate) ──promocja──▶ Contract(type=b2b)
        │ POST /api/signing/contracts/{id}/send-for-signature (202)
        ▼
  DocumentSignature(provider=szafir_sdk, signature_type=QES, status=draft)
        │ bg initiate_signing: WeasyPrint PDF → mint SignatureLink/party → e-mail
        ▼
  Konsultant → /sign/{token}
        ├─ Pas 1: Szafir SDK Web Module (karta + Szafir Host) ──┐ podpis PAdES po stronie klienta
        └─ Pas 2: mSzafir One Shot (bank/mObywatel, chmura)  ───┤ podpis PAdES w chmurze KIR
                                                                ▼
                            POST submit / pobranie → pyHanko + EU DSS validate (is QES?)
                                                                ▼
  Reprezentant spółki → /sign (party=company) → Szafir SDK (karta) → 2. podpis incremental
                                                                ▼
                 status=completed → attach ContractDocument → notyfikacja signature_signed
                                                                ▼
                                       (Faza 5) B-LTA archival timestamp (sweeper)
```

### Abstrakcja `SignatureProvider` (Protocol)

```python
# backend/app/services/signing/provider.py
class SignatureProvider(Protocol):
    name: str  # persisted on DocumentSignature.provider
    async def initiate(self, sig: DocumentSignature, pdf: bytes) -> ProviderRef: ...
    async def finalize(self, sig: DocumentSignature, payload: dict) -> SignedArtifact: ...
    async def validate(self, signed_pdf: bytes) -> ValidationReport: ...
```

Implementacje: `SzafirSdkProvider` (pas 1 — odbiera PDF podpisany client-side + waliduje), `MszafirOneShotProvider` (pas 2 — orkiestruje sesję mSzafir API + pobiera podpisany PDF), `UploadValidateProvider` (generyczny upload + walidacja, reuse pasa 1 dla „mam własny cert offline"), `AutentiProvider` (istniejący, deprecated, tylko dla historycznych wierszy). Wiersz `DocumentSignature` samoopisujący przez `provider` + `provider_ref`.

---

## 4. Decyzje technologiczne

| Komponent | Rola | My budujemy / oni dostarczają |
|---|---|---|
| **KIR Szafir SDK (Web Module + Host)** | Pas 1: podpis QES kartą konsultanta/reprezentanta, client-side | Oni: komponent JS + Szafir Host + obsługa karty (PAdES, TSA). My: osadzenie na `/sign`, odbiór i walidacja podpisanego PDF |
| **KIR mSzafir „One Shot" (mSzafir API)** | Pas 2: jednorazowy cert dla konsultanta bez certu, chmura | Oni: wydanie certu + identyfikacja bank/mObywatel + podpis. My: klient mSzafir API + orkiestracja sesji |
| **pyHanko** | Walidacja PAdES + (Faza 5) archival timestamp B-LTA | Nowa zależność `requirements.txt`. **NIE podpisuje** (podpis robi Szafir/mSzafir); rola = `validate` + LTV/LTA |
| **EU DSS `dss-validation-rest`** | Autorytatywny „is QES" (Trusted List) | Nowy sidecar Java (Coolify). My: serwis REST + mapowanie raportu → `validation_report` |
| **WeasyPrint** (`63.0`, już jest) | HTML → PDF przed podpisem | reuse 1:1 `render_contract_pdf` (provider-agnostic) |
| **PyJWT** (centralny wrapper `app.core.jwt`) | Purpose-scoped JWT public link | reuse wzorca `actionable_messages` (`purpose=qes_signing`) |
| **httpx** (`0.28.1`, już jest) | Klient mSzafir API + DSS | reuse |

> **Certum/EuroCert/CenCert — świadomie poza zakresem.** To alternatywni QTSP; nie są nam potrzebni, bo Szafir SDK czyta certyfikat **dowolnego** QTSP z karty (jeśli reprezentant ma cert Certum — Szafir i tak go obsłuży, bez integracji). Byliby kandydatami tylko gdyby kiedyś trzeba było **serwerowego auto-podpisu** firmy (odłożone).

---

## 5. Wymagania i onboarding po stronie konsultanta

Konsultant IT (zwykle JDG) podpisuje **jako osoba fizyczna**. Co musi mieć — zależnie od pasa:

**Pas 1 — własny podpis kwalifikowany (Szafir SDK):** certyfikat kwalifikowany (dowolny QTSP, ~250–400 zł/rok, karta/token/mobilny) + czytnik PC/SC (gdy karta) + zainstalowany **Szafir Host** + rozszerzenie przeglądarki + PIN + komputer. Zero kosztu dla nas; tarcie = instalacja Szafir Host.

**Pas 2 — mSzafir One Shot (bez certu):** sposób potwierdzenia tożsamości (**logowanie do banku PL** lub **mObywatel/e-dowód NFC**) + telefon + PESEL + ważny dowód + przeglądarka. Bez karty/instalacji. **Limity One Shot: 1 PDF ≤ 20 MB, cert ważny 15 min.** Nasza umowa B2B = mały PDF (OK). Koszt per podpis — zwykle płaci nadawca.

**Co NEXUS dostarcza, by zmniejszyć tarcie:**
- `/sign/[token]` **wykrywa** obecność Szafir Host i **prowadzi za rękę** (karta vs mSzafir bez karty).
- Strona **instrukcji** (co przygotować, oba warianty).
- PDF **PAdES-ready** i mały (pilnowany limit 20 MB pod One Shot).
- **Bez konta w NEXUS** — podpis z tokenowanego linku z maila.

**Przypadki brzegowe (mają wpływ na projekt):**
- **JDG vs spółka:** jeśli konsultant działa przez sp. z o.o., podpisuje **osoba umocowana** (zarząd/pełnomocnik wg KRS), nie dowolny pracownik. Pole „kto podpisuje po stronie konsultanta" musi to uwzględnić (domyślnie = `Candidate`, ale dopuścić korektę imienia/maila signera).
- **Obcokrajowiec bez PESEL/banku PL/mObywatela** → **nie wyrobi One Shot**; musi użyć **własnego unijnego certu** (eIDAS) przez Szafir SDK. Fallback do udokumentowania; ryzyko adopcji przy zespołach międzynarodowych.
- **Zablokowany firmowy laptop** (brak praw admina na Szafir Host) → kieruj na mSzafir (chmura) lub cert mobilny.
- **Dane w umowie = dane z certyfikatu** (QES niesie imię/nazwisko; walidacja DSS wyciąga `signedBy`).

---

## 6. Zmiany w modelu danych — migracja `0133`

Branch od **single-head `0132_b2b_render_payload`** (zweryfikowane — żaden plik nie referuje `0132` jako `down_revision`). Plik: `backend/alembic/versions/0133_signing_provider_refactor.py`, `down_revision="0132_b2b_render_payload"`, pełne id (nie prefiks). Po merdżu `alembic heads`=1.

**`document_signatures`:**

| Operacja | Szczegół |
|---|---|
| RENAME `autenti_process_id` → `provider_ref` | `String(64)` null; `ALTER INDEX ix_doc_sig_autenti_process RENAME TO ix_doc_sig_provider_ref` (partial unique zostaje) |
| RENAME `autenti_signature_type` → `signature_type` | `String(16)` NOT NULL, free-form (SES/AdES/QES, NIE enum) |
| ADD `provider` | `String(32)` NOT NULL `server_default="autenti"` (backfill) — wartości `szafir_sdk \| mszafir_oneshot \| upload_validate \| autenti` |
| ADD `signing_session_id` | `String(255)` null — sesja mSzafir One Shot (pas 2) |
| ADD `identity_provider` | `String(64)` null — `card \| mobile \| bank \| mobywatel \| edowod_nfc` |
| ADD `signature_level` | `String(16)` null — `B-B \| B-T \| B-LT \| B-LTA` |
| ADD `validation_report` | `JSONB` null — raport DSS (`is_qes`, `indication`, `signatureLevel`, `signedBy`, cert serial/subject, timestamps) |
| KEEP `chk_signature_target_xor` | **nietknięte** (XOR z `0091`) |

**Nowa tabela `signature_links`** (wzorzec `CandidateInviteLink`, true single-use): `token` PK (`secrets.token_urlsafe(36)`), `signature_id` FK→`document_signatures` ON DELETE CASCADE (idx), `party` (`consultant \| company`), `purpose` (`qes_signing \| upload_signed`), `created_by` FK→`users` RESTRICT, `expires_at`, `revoked`, `used_at` (single-use), `use_count`, `last_used_at`, `created_at`.

**`NotificationType`** — **bez `ALTER TYPE`** (reuse `signature_sent/_signed/_rejected/_failed` z `0080`).

Model `backend/app/models/document_signature.py` + schemat `backend/app/schemas/document_signature.py` zsynchronizować; w `DocumentSignatureResponse` dodać **kompat-aliasy** `@computed_field` `autenti_process_id`/`autenti_signature_type` → nowe nazwy (FE nie pęka przed migracją FE).

---

## 7. Provider abstraction + nowy pakiet `backend/app/services/signing/`

```
provider.py            # SignatureProvider Protocol (§3)
registry.py            # get_provider(name) — szafir_sdk | mszafir_oneshot | upload_validate | autenti
szafir_sdk_provider.py # Pas 1: finalize=odbiór client-signed PAdES + validate
mszafir_provider.py    # Pas 2: initiate=start sesji mSzafir API; finalize=pobranie podpisanego PDF + validate
mszafir_client.py      # klient mSzafir API (httpx): start One Shot, status/poll, fetch signed
upload_validate_provider.py  # generyczny upload + validate (offline własny cert)
autenti_provider.py    # wrapper na services/autenti/* (deprecated)
pades.py               # pyHanko: validate + (Faza 5) archival timestamp B-LTA
validation.py          # ValidationService → DSS sidecar → validation_report
pdf_renderer.py        # PRZENIESIONY z services/autenti/pdf_renderer.py (+ re-export w starej ścieżce)
sender.py              # prepare_send (reuse) + initiate_signing (bg)
```

**Kroki refactoru (Faza 1):** migracja `0133` → model+schemat sync (aliasy) → pakiet `services/signing/` + Protocol + `registry` → `AutentiProvider` wrapper (bez przepisywania Autenti) → relokacja `pdf_renderer` (+ re-export) → flagi w `config.py` → grep-podmiana `sig.autenti_process_id`/`autenti_signature_type` na nowe nazwy.

> **Brak klienta CSC.** Szafir SDK podpisuje client-side (nie potrzeba serwerowego CSC); mSzafir ma własne API. pyHanko **nie podpisuje** — tylko waliduje i (później) dokłada B-LTA.

---

## 8. Backend — endpointy i serwisy

**Router `app/api/signing.py`** (mount `/api/signing`, gating `SIGNING_ENABLED` + `_require_enabled()` 503 jak `api/autenti.py`):

| Method | Path | Auth | Opis | Guard |
|---|---|---|---|---|
| POST | `/contracts/{id}/send-for-signature` | TacPlus | `prepare_send` (wiersz `draft`, `provider=szafir_sdk`, `signature_type=QES`) + bg `initiate_signing`; 202 | yes |
| GET | `/contracts/{id}/signatures` | CurrentUser | lista podpisów kontraktu | no |
| GET | `/signatures/{id}` | CurrentUser | szczegóły + status | no |
| POST | `/signatures/{id}/withdraw` | TacPlus | wycofanie | yes |
| POST | `/signatures/{id}/remind` | TacPlus | ponowny e-mail | yes |
| GET | `/health` | CurrentUser | status providera | no |

**Publiczny router** (mount `/api/public`, wzorzec `public_share.py` + `slowapi`, **no-info-leak: każdy fail tokenu → jednolite 403/404**):

| Method | Path | Limit | Opis |
|---|---|---|---|
| GET | `/api/public/sign/{token}` | `30/minute` | dane strony (tytuł umowy, signer, party, krok, dostępne pasy); JWT `purpose=qes_signing` + lookup `SignatureLink` |
| GET | `/api/public/sign/{token}/pdf` | `30/minute` | niepodpisany (lub częściowo podpisany dla company) PDF do podania komponentowi Szafir |
| POST | `/api/public/sign/{token}/submit` | `5/minute; 30/hour` | **Pas 1**: odbiór client-signed PAdES → `validate` (pyHanko+DSS) → attach + status (single-use `used_at`) |
| POST | `/api/public/sign/{token}/mszafir-start` | `10/hour` | **Pas 2**: start sesji mSzafir One Shot → `redirect_url/widget` (bank/mObywatel) |
| GET/POST | `/api/public/sign/{token}/mszafir-status` | `30/minute` | poll/callback statusu mSzafir → po `completed` backend pobiera podpisany PDF → validate → attach |

**Serwisy:**
- `services/signing/sender.py` — `prepare_send` (reuse logiki z `services/autenti/sender.py` + `provider`), `initiate_signing(sig_id)` (bg: HTML→`render_contract_pdf`→zapis→mint `SignatureLink` per party→`emit_notification(signature_sent)`+e-mail). State machine `draft→sending→sent→in_progress→completed|rejected|withdrawn|failed|expired` reuse 1:1.
- `services/signing/mszafir_client.py` — httpx: start One Shot, poll status, fetch signed PDF; `MszafirConfig.from_settings()` (RuntimeError gdy brak creds, jak `AutentiConfig`). *Dokładny kształt API z dokumentacji KIR w Fazie 0.*
- `services/signing/validation.py` — `ValidationService.validate(pdf) -> dict`: pyHanko trust-chain (szybko) + POST do `DSS_VALIDATION_URL` (autorytatywnie) → map na `validation_report` (`is_qes`, `signature_level`, `signedBy`, cert).
- `services/signing/pades.py` — pyHanko: `validate` helper; Faza 5 `add_archival_timestamp` (B-LTA) w sweeperze.

**Sweeper** `backend/app/tasks/signing_sweeper.py` (wzorzec `autenti_expiry_sweeper.py`, interval clamp `max(300,…)`, kill-switch, inner/outer try): timeout sesji mSzafir, retry attach (`signed_document_id IS NULL AND status=completed`), ekspiracja `sent/in_progress` po `expires_at` → `expired`+notyfikacja, (Faza 5) refresh B-LTA. Rejestracja w `main.py` lifespan: `"signing_sweeper": asyncio.create_task(signing_sweeper_loop())` (loop `return`uje gdy `SIGNING_ENABLED=false`).

> Szafir/mSzafir **nie mają webhooków jak Autenti** — pas 1 finalizuje się synchronicznie na `submit`; pas 2 przez poll/callback. `services/autenti/webhook_handler.py` zostaje tylko dla `AutentiProvider` (historyczne wiersze).

---

## 9. Frontend

**Akcja „Wyślij do podpisu (QES)"** — `frontend/src/components/v2/pages/B2BContractGeneratorV2.tsx` → `GeneratedContractsTab` (kolumna Akcje ~371–412). Bridge: generated record → `/api/b2b-generator/generate` (Contract) → `send-for-signature` na zwróconym `contract_id`; dialog promocji dopytuje o brakujące pola (kandydat/klient). Nowa kolumna „Status podpisu" + `signature_status?` w `B2BGeneratedContractRow` (`api.ts:1747`).

**Reuse** `AutentiSendDialog.tsx` → przemianować na `SignSendDialog` (default `signature_type=QES`, wybór pasa/`provider`, `company_signer_user_id`) i `AutentiEnvelopeCard.tsx` (`SignatureRow` badge/remind/withdraw; endpointy → `signingApi`; link „Otwórz" → backend-proxy signed PDF). Wpięcie istniejące w `CandidateDetailV2` → `UmowaTab` zostaje, ale **głównym wejściem jest B2B Generator** (zakres).

**NOWA publiczna strona** `frontend/src/app/sign/[token]/{page,layout}.tsx`:
- **CRITICAL:** prefix **`/sign/`** (NIE `/contracts/*` — PROTECTED w `middleware.ts:46`); dodać do `PUBLIC_PATHS` (`middleware.ts:58`). Publiczne endpointy hitować **raw `fetch`/`axios`**, nie auth-`api` (interceptor Bearer).
- Wzorzec `frontend/src/app/apply/[token]/page.tsx`.
- **Osadzenie Szafir SDK Web Module** (skrypt JS KIR): detekcja Szafir Host → jeśli jest: „Podpisz kartą" (komponent ładuje PDF z `/pdf`, podpisuje, zwraca PAdES → `POST submit`); jeśli brak: instrukcja instalacji **lub** „Podpisz przez mSzafir (bez karty)" → `mszafir-start` → redirect identyfikacji → powrót + poll status.
- Strona **company** (party=company) ładuje **już podpisany przez konsultanta** PDF do drugiego (incremental) podpisu kartą reprezentanta.

**`signingApi`** w `frontend/src/lib/api.ts` (wzorzec `autentiApi` ~922 / `b2bGeneratorApi` ~1673): `send`, `list`, `get`, `withdraw`, `remind`. Reuse `extractErrorMsg`, `downloadBlob`.

---

## 10. Infrastruktura / deploy

- **Sidecar `dss-validation`** w `docker-compose*.yml` (profile-gated jak Alloy — `profiles: [signing]`); obraz `dss-validation-rest` (Java; dokładny tag z Fazy 0/4). Wołany po HTTP z FastAPI (`DSS_VALIDATION_URL`).
- **Feature flagi** (`config.py`, wzorzec bloku Autenti/CloudTalk): `SIGNING_ENABLED` (killswitch), `SIGNING_PROVIDER` (default `szafir_sdk`), `SZAFIR_SDK_*` (konfiguracja/asset Web Module), `MSZAFIR_*` (creds API One Shot), `DSS_VALIDATION_URL`. Sekrety tylko w Coolify vault (runtime), zero w repo/Dockerfile ARG. (Brak `QTSP_CERTUM_*`/`CSC_*` — single-vendor KIR.)
- Nowa zależność `pyhanko` w `backend/requirements.txt`. `alembic upgrade head` na starcie (Coolify entrypoint).
- Szafir SDK Web Module + Szafir Host — assety/licencja od KIR; rozszerzenie przeglądarki instaluje **konsultant** (nie my).

---

## 11. Plan fazowy

- **Faza 0 — onboarding KIR + prawnik (CRITICAL PATH, start NATYCHMIAST; Fazy 1–2 lecą równolegle bez creds):**
  - [ ] Umowa z **KIR** na **Szafir SDK** (Web Module + Host, licencja) + środowisko integracyjne/testowe + dokumentacja + przykłady
  - [ ] Dostęp do **mSzafir API** (One Shot) + sandbox + potwierdzenie metod identyfikacji (bank/mObywatel/e-dowód) + model rozliczeń per podpis (kto płaci)
  - [ ] Prawnik (na piśmie): (a) czy szablon `umowa_b2b_{pl,en}.html` + WeasyPrint + dwustronny QES spełnia formę pisemną; (b) umocowanie reprezentanta spółki; (c) obsługa konsultanta-spółki (KRS) vs JDG; (d) retencja B-LT vs B-LTA
  - [ ] Creds sandbox → Coolify vault. **Weryfikacja:** komponent Szafir podpisuje testowy PDF w sandbox; mSzafir One Shot wystawia testowy cert.
- **Faza 1 — Provider abstraction + migracja `0133` (czysty refactor, Autenti dalej działa):** migracja, model+schemat (aliasy), pakiet `services/signing/`, `AutentiProvider` wrapper, relokacja `pdf_renderer`, flagi. **Weryfikacja:** `alembic upgrade head && alembic heads`=1; istniejące testy podpisów zielone; `GET .../signatures` zwraca `provider_ref` przezroczyście.
- **Faza 2 — In-house skeleton + tokenized signing page (UX bez realnego podpisu):** `api/signing.py` + publiczny `/api/public/sign/{token}` (+ `/pdf`), mint `SignatureLink` + e-mail, FE przycisk + bridge promocji, publiczna `/sign/[token]` (szkielet UI obu pasów), sweeper + rejestracja. **Weryfikacja:** `send-for-signature`→202; `/sign/{token}` w **Chrome MCP** pokazuje dane umowy + PDF; zły/wygasły/zużyty token → jednolite 403/404.
- **Faza 3 — Szafir SDK (pas 1) + mSzafir One Shot (pas 2):** osadzenie Szafir SDK Web Module na `/sign` + detekcja Host + `POST submit` (odbiór client-signed PAdES); `mszafir_client.py` + `MszafirOneShotProvider` (start/poll/fetch); dwustronny podpis (konsultant → reprezentant incremental); `pyhanko` w requirements. **Weryfikacja:** sandbox e2e — konsultant kartą (Szafir) + mSzafir bez karty + reprezentant kartą; pobrany PDF ma 2 podpisy PAdES; `SIGNING_ENABLED=true` na staging.
- **Faza 4 — Walidacja (DSS) + lane uploadu:** compose `dss-validation`, `validation.py` (pyHanko+DSS) + zapis `validation_report`, `UploadValidateProvider` + ścieżka „mam własny cert offline". Wpięcie walidacji do `submit`/`mszafir-status`. **Weryfikacja:** known-good PAdES → `is_qes=true`, known-bad → `false`; `validation_report` w DB (`mcp__postgres-nexus__query`).
- **Faza 5 — B-LTA archival + sprzątanie:** B-LTA timestamp w sweeperze (refresh przed wygaśnięciem), `SIGNING_PROVIDER=szafir_sdk` default + `AUTENTI_ENABLED=false`, deprecation `services/autenti/*` (read-only historii), raport `docs/in-house-qes-signature-completion-report.md`. **Weryfikacja:** signed PDF waliduje się jako B-LTA; nowy podpis idzie przez KIR; stare wiersze Autenti czytelne.

---

## 12. Ryzyka i strategia testów

| Ryzyko | Mitygacja |
|---|---|
| KIR onboarding lead time | Faza 0 start natychmiast; Fazy 1–2 równolegle bez creds |
| **Szafir Host install friction** (firmowe laptopy, Mac/Linux) | Detekcja Host na `/sign` + fallback mSzafir (chmura, bez instalacji); instrukcja |
| **Konsultant-obcokrajowiec** (brak PESEL/banku PL) | Pas 1 z własnym unijnym certem (eIDAS); udokumentować onboarding |
| One Shot limity (20 MB / 15 min) | PDF mały (pilnowany rozmiar); sesja krótka — UX bez zbędnych kroków |
| Validation correctness („is QES") | **Nie wymyślamy** — EU DSS jako autorytet; pyHanko tylko szybki pre-check |
| Dwustronny PAdES (2. podpis unieważnia 1.) | incremental update (Szafir/pyHanko); unit testy 2-sig |
| Konsultant-spółka (nie JDG) | Pole signera korygowalne (osoba umocowana wg KRS), nie sztywno z `Candidate` |
| Single-head drift | `0133` od `0132`; `alembic heads`=1 w CI |

**Testy:** sandbox Szafir SDK (podpis kartą testową) + mSzafir One Shot (sandbox); pyHanko PAdES unit (odbiór, 2-sig incremental, B-LT/B-LTA); DSS regresja `is_qes` na known-good/known-bad; E2E staging `SIGNING_ENABLED=true` przez **Chrome MCP** + screenshot (autonomous-verification §2).

---

## 13. Bezpieczeństwo / RODO

- **Token:** JWT `purpose=qes_signing` (cross-use guard jak `actionable_messages`) + opaque `SignatureLink` single-use (`used_at`) + TTL (`expires_at`); cross-check `signature_id` JWT vs wiersz.
- **Rate limiting:** `slowapi` na publicznych (`/sign` `30/minute`, `/mszafir-start` `10/hour`, `/submit` `5/minute; 30/hour`); Cloudflare pierwsza linia (`api.nexus.dynaminds.pl`).
- **No-info-leak:** każdy fail tokenu → jednolite 403/404 + identyczny PL string.
- **Signed-PDF storage:** przez `storage_service` (Object Storage / local). **Object Storage NIE MA CORS** (pamięć `cv_download_hetzner_cors`) → podgląd/pobranie zawsze **backend-proxied**, nigdy bezpośredni cross-origin XHR/iframe na bucket.
- **Audit immutability:** `DocumentSignatureEvent` (unique `event_id`, idempotencja) + `validation_report` JSONB jako trwały dowód „is QES" — append-only.
- **No secrets in repo:** `MSZAFIR_*`, `SZAFIR_SDK_*` tylko w Coolify vault (runtime); zero w Dockerfile ARG / repo `.env`; gitleaks blokuje.
- **PII signera:** snapshot (`signer_email/first_name/last_name/phone`) w modelu; dane tożsamości (bank/mObywatel) zostają u KIR — NEXUS trzyma tylko `identity_provider` (typ), nie surowe dane uwierzytelnienia; brak PII/tokenów w logach/Sentry (replay `maskAllText:true`, RODO ATS).
