# Automatyczne przetwarzanie zamówień z maila `zamowienia@b2bnetwork.pl` — raport ukończenia

Data: 2026-09-02 · PR: #1337 (jeden PR na cały ticket, decyzja właściciela) · poprzedza go #1336 (rejestr polityk, zmergowany).

## Co zostało dowiezione

| Faza | Zakres | Stan |
|---|---|---|
| P1a | Rejestr polityk odczytu PDF (`order_policies/registry.py`) zamiast if-chaina w routerze | ✅ #1336 |
| P1b | Parser: tryb all-rows, okres per wiersz, flaga obcięcia, prompt v4 z trzema pułapkami z korpusu | ✅ |
| P2 | Rozpoznanie klienta: numery rejestrowe ∩ `clients.nip` → markery → domena; tekst zamówienia z metadanymi (re-ekstrakcja przy literowaniu spacjami, cap OCR); harness korpusu | ✅ 20/20 na realnych PDF-ach |
| P1c | Polityki: PKO BP, KIR, mLeasing, VeloBank, Alior, Cardif (+ warstwy układu pdfplumber dla Nordea/Bank Pocztowy/Credit Agricole, naprawa Erste: dzień, nie godzina) | ✅ |
| P3 | Ingest Graph → `order_mail_documents` (dedup po SHA, drabina wyników), `M365Connection.purpose`, sloty 08:00/15:00 Europe/Warsaw, admin API, health, migracja 0264 | ✅ |
| P4 | Bramka auto-zapisu (8 warunków, TRYB CIENIA), resolver (roster klienta), planer, writer (jeden dla automatu i „Zastosuj"), kolejka API + ekran `/order-mail`, alerty `dl_alerts` (typ `order_mail_review`, migracja 0265) | ✅ |

## Pliki (najważniejsze)

Backend: `app/services/order_policies/{registry,_shared,alior,bank_pocztowy,cardif,credit_agricole,kir,mleasing,nordea,pko_bp,velobank,known_clients}.py`, `app/services/order_client_identity.py`, `app/services/order_document_text.py`, `app/services/order_mail_{ingest,resolver,planner,gate,apply}.py`, `app/tasks/order_mail_ingest.py`, `app/api/{admin_order_mail,order_mail_queue}.py`, `app/models/order_mail.py`, `alembic/versions/0264_order_mail_ingest.py`, `0265_dl_alert_order_mail_review.py`, lustra DDL w `entrypoint.sh`, `scripts/order_corpus_harness.py`.
Frontend: `src/app/order-mail/page.tsx`, `src/components/order-mail/OrderMailQueue.tsx`, `src/lib/api/orderMail.ts`, `src/app/preview/order-mail/page.tsx`, wpisy w sidebarze / middleware / capabilities.

## Nowe endpointy

- `POST /api/admin/order-mail/sync` (`since_days`), `GET /api/admin/order-mail/status`, `GET /api/admin/order-mail/documents` — admin.
- `POST /api/order-mail/sync` (admin / finance / delivery_lead) i `GET /api/order-mail/sync/status` (każda rola kolejki) — „Pobierz zamówienia z maila" i pasek „ostatnie sprawdzenie" w `/order-mail` (03.09.2026, patrz sekcja niżej).
- `GET /api/order-mail/queue`, `GET /api/order-mail/queue/{id}`, `GET …/{id}/file`, `POST …/{id}/apply`, `POST …/{id}/dismiss` — zakres portfela; „Zastosuj" = admin lub przypisany DL.

## Zmienne środowiskowe (Coolify, workflow „Coolify set env")

| Zmienna | Domyślnie | Znaczenie |
|---|---|---|
| `ORDER_MAIL_INGEST_ENABLED` | `false` | kill-switch pętli pobierania |
| `ORDER_MAIL_UPN` | `""` | UPN skrzynki kopii w M365 (połączenie dostaje `purpose=orders`) |
| `ORDER_MAIL_POLL_INTERVAL_MINUTES` | `60` | odstęp między sprawdzeniami skrzynki (od końca ostatniego biegu; podłoga 5). Zastąpił `ORDER_MAIL_SLOTS_LOCAL` 03.09.2026 |
| `ORDER_MAIL_INITIAL_LOOKBACK_DAYS` / `ORDER_MAIL_OVERLAP_HOURS` | `7` / `2` | pierwszy bieg / nakładka watermarku |
| `ORDER_MAIL_SENDER_ALLOWLIST` | `""` (wszyscy) | CSV domen nadawców |
| `ORDER_MAIL_AUTOAPPLY_ENABLED` | `false` | **tryb cienia** — werdykt w dzienniku, zero zapisów; flip po ~2 tyg. danych |
| `ORDER_MAIL_AUTOAPPLY_EXCLUDE_CLIENT_IDS` | `""` | CSV klientów wyłączonych z automatu (pusta = nikt) |
| `<KLIENT>_ORDER_EXTRACTION_CLIENT_IDS` | `""` | bramki polityk: `PKO_BP_`, `KIR_`, `MLEASING_`, `VELOBANK_`, `ALIOR_`, `CARDIF_` (+ istniejące Nordea/BP/CA/BNP/Erste/Orlen/PFRON) — pusta = fail-closed |

## Co musi zrobić właściciel (bez tego nic nie ruszy)

1. ~~Reguła na hostingu~~ **NIEPOTRZEBNA** (ustalone 02.09): `zamowienia@` to lista dystrybucyjna w Exchange Online; kopię robi członkostwo skrzynki współdzielonej `nexus-zamowienia@b2bnetwork.pl` w tej liście (zrobione).
2. ~~Dedykowany user + OAuth~~ **ZASTĄPIONE trybem app-only** (`ORDER_MAIL_AUTH_MODE=app`): APPLICATION `Mail.Read` + Application Access Policy na grupę `NEXUS-OrderMail-Scope` (zrobione 02.09, patrz sekcja w `CLAUDE.md`). Zostaje env: `ORDER_MAIL_UPN`, `M365_MAIL_TENANT_ID`, potem `ORDER_MAIL_INGEST_ENABLED=true`.
3. **NIP-y w `clients.nip`** dla klientów zamówieniowych — seed w `order_policies/known_clients.py` (19 pozycji z korpusu; BNP to DWA podmioty; NIP Autenti celowo pominięty). Bez tego warunek 1 bramki zatrzymuje automat na zawsze.
4. **Env polityk** per klient (`*_ORDER_EXTRACTION_CLIENT_IDS`) — dopiero wtedy odczyt danego klienta ma proweniencję deterministyczną.
5. **Reguły okresu** dla BIK / Cyfrowy Polsat / Polkomtel (dokumenty nie mają okresu) i MD vs kosztowe (próbka Polsata ma obie kolumny) — do tego czasu ci klienci zostają w kolejce.
6. Na który podmiot BNP wskazuje `BNP_ORDER_EXTRACTION_CLIENT_IDS` (istniejąca polityka nie pasuje do żadnego z dwóch dokumentów w korpusie).
7. Po dwóch tygodniach cienia: przegląd `GET /api/admin/order-mail/documents` (werdykt vs decyzja człowieka) → `ORDER_MAIL_AUTOAPPLY_ENABLED=true`.

## Znane ograniczenia

- Writer v1 obsługuje zamówienia SAMODZIELNE (fill_draft / future / new); linie grup (BIK/Polkomtel/BNP) trafiają do kolejki z opisem — zakładane istniejącym UI grup.
- Klienci recognize-only (EY/Fieldglass, ERGO, RITS, Nationale-Nederlanden): rozpoznanie tak, polityka nie → kolejka.
- Harness korpusu mierzy warstwę deterministyczną (`--no-llm`); pełny pomiar z modelem wymaga `ANTHROPIC_API_KEY` lokalnie.
- Alior: nazwiska rozsypane po liniach tabeli — pieniądze pewne deterministycznie, tożsamość potwierdza model + roster.
- Jeden test endpointu (`test_extract_order_pdf_admin_sees_finance`) bywa zależny od kolejności w współdzielonej bazie testowej; przechodzi solo i w CI.

## Weryfikacja

Backend: 342+ testów z modułu zamówień/M365/health zielone lokalnie (obraz `nexus-verify:img`, własny Postgres), w tym 30 nowych P3/P4 i 34 polityk na fixture'ach syntetycznych; harness na 20 realnych PDF-ach: klient 20/20, numer/okres/stawka zgodne dla klientów z polityką. Frontend: type-check, eslint, vitest (order-mail 3, capabilities 255, shell 109); harness `/preview/order-mail` sprawdzony w Chrome. Instrukcja zamówień przestemplowana.

## Aktualizacja 2026-09-03 — sprawdzanie co godzinę + „Pobierz zamówienia z maila"

Ticket: skrzynka `nexus-zamowienia@` sprawdzana co godzinę, przycisk ręcznego
sprawdzenia w module, wynik po każdym sprawdzeniu, a czekające w skrzynce
zamówienie pobrane od razu po wdrożeniu.

**Co było naprawdę.** Czytnik (P3) działał już od 02.09, ale w DWÓCH slotach
dobowych (08:00/15:00), a jedyny ręczny start to `POST /api/admin/order-mail/sync`
(admin, bez UI, bez wyniku). Czekające zamówienie (VeloBank, `3/09/2026/BL`,
8 osób) przyszło 03.09 o 08:37 — 35 min PO porannym slocie — i bez zmiany
czekałoby do 15:00. Zostało pobrane ręcznym biegiem w trakcie diagnozy
(09:06 UTC) i jest w kolejce jako `needs_review` (osoba bez żywego kontraktu →
poprawnie do weryfikacji, tryb cienia).

**Ten ręczny bieg ujawnił drugą usterkę:** dokument trafił do kolejki, ale stan
biegu został na `running` bez końca (health `order_mail=degraded`). Bieg z
requestu startował gołym `asyncio.create_task` bez referencji, a każdy wyjątek
po padniętym zapytaniu (np. powiadomienie DL) zostawiał sesję bez rollbacku —
zapis końca padał na `PendingRollbackError`. Deploy #1352 wystartował o 09:00,
więc równie dobrze mogło to być przerwanie restartem; obie ścieżki są
domknięte (rejestr zadań, rollback + wpis w `errors`, `interrupted` w projekcji).

**Zmiany.** Pętla: odstęp `ORDER_MAIL_POLL_INTERVAL_MINUTES` (60) liczony od
końca ostatniego biegu zamiast slotów; tick co 60 s. Serwis: liczniki
`new_messages` / `auto_applied`, `reason` biegu, rekord ostatniego zakończonego
biegu w `stats`, `sync_snapshot` (wspólna projekcja admin + kolejka),
`start_ingest_task`, watermark bez cofania. API kolejki: `POST /sync`,
`GET /sync/status`. Health: próg 3 odstępy (min. 3 h), `running` ≠ awaria.
Front: `MailboxCheckPanel` w `/order-mail` (przycisk + „ostatnie sprawdzenie:
N nowych · A zapisanych automatycznie · R do weryfikacji"), `lib/order-mail-sync.ts`
(koniec biegu po zmianie znaczników z serwera, nie po zegarze przeglądarki),
harness `/preview/order-mail`.

**Dlaczego nie webhooki Graph.** Subskrypcje zmian dałyby sekundy zamiast
godziny, ale kosztują publiczny endpoint walidacyjny za Cloudflare, tabelę
subskrypcji, pętlę odnawiania (wygasają), sekret `clientState` i — zgodnie
z zaleceniem Microsoftu — i tak okresowy poll jako siatkę na zgubione
powiadomienia. Przy kilku zamówieniach tygodniowo i przycisku „Pobierz" na
przypadek „wiem, że właśnie przyszło" godzina wystarcza; skrócenie to jedna
zmienna w Coolify (`ORDER_MAIL_POLL_INTERVAL_MINUTES=15`).
