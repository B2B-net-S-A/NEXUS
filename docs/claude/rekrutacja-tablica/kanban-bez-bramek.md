# Kanban bez bramek (decyzja Artura, 17.09.2026)

Tylko 0,4 % ruchów w pipeline powstawało w NEXUSIE (131 z 32 872 w 90 dniach —
reszta z nocnego importu Traffita), a bramki zniechęcały do przeciągania kart.
Decyzja: **żadna bramka nie blokuje przepływu** — ostrzeżenia i odznaki zamiast
blokad. Razem z przełącznikiem „Rekrutacja prowadzona w NEXUSIE" (sekcja
Traffit) to warunek przenoszenia zespołu z Traffita falami. Nie przywracaj
żadnej z bramek bez decyzji właściciela.

**Wyjątki świadome (Pipeline v4, decyzje Artura 23.09.2026 — sekcja niżej):**
„CV wysłane" poza Nordeą wysyła wyłącznie DL/admin ze stawką do klienta,
wyjście z „Rozmowy u klienta" dalej wymaga debriefu z pytaniami klienta,
a osoba dodana ręcznie jest 12 h zarezerwowana dla dodającego.

**Wyjątki z 04.10.2026 (decyzje Artura D1, D2):** wejście na „Zweryfikowany”
z Nowych/Screeningu wymaga arkusza screeningu (albo odpowiedzi w karcie
rekomendacji) i stawki kandydata — 409 `VERIFIED_REQUIREMENTS_MISSING`
z `pipeline_move_rules.assert_verified_requirements`, braki liczy TA SAMA
funkcja co okno „Przesuń dalej” (`move_requirements.load_pair_facts`); zwrot
DL z „QC CV” do poprawy nie jest bramkowany, „Pomiń stawkę” zostało tylko jako
„Zostaw zapisaną stawkę”. Ręczny ruch na „Zatrudniony” wymaga
`hired_signed_via` (umowa B2B poza Generatorem / UoP / zlecenie / inna z opisem,
422 `HIRED_SIGNED_VIA_REQUIRED`); umowę z Generatora potwierdza „Oznacz jako
podpisaną”. Wyłączniki `VERIFIED_GATE_ENABLED`, `HIRED_SIGNED_VIA_REQUIRED`;
w testach wyłączone autouse-fixturą, `test_verified_gate.py` włącza je jawnie.

- **Brak karty „Oczekuje".** Bramka jest USUNIĘTA z kodu (18.09.2026; do tego
  dnia wyłączała ją flaga — nazwa w raportach z 17.09.2026, #1593; stara
  zmienna w Coolify jest nieszkodliwa, `Settings` ignoruje nieznane env).
  Ruch na „Zweryfikowany" daje `active`, stawka jest
  OPCJONALNA (jej brak to 200, nie 422), a korekta stawki
  (`update_latest_expected_rate`) NIGDY nie ustawia `pending` i sama aktywuje
  stary wiersz `pending`. `budget_max_at_move` zostaje jako snapshot. Kredyt
  KPI pierwszego weryfikatora trafia od razu przy ruchu. **Tras kolejki
  akceptacji nie ma** (`/pending-verifications`, `accept-verification`,
  `reject-verification`) — pilnuje tego test czytający `app.routes`, nie HTTP
  404. Stare wiersze zalicza jednorazowo `pending_verification_promotion.py`
  (blok w `entrypoint.sh`, nie ma osobnej migracji) — idempotentny, zostaje na
  potrzeby świeżej instalacji i odtworzenia bazy. W bazie zostaje wartość
  `pending` w enumie `verificationstatus` (`ALTER TYPE … DROP VALUE`
  w Postgresie nie istnieje) i typ powiadomienia `pending_verification` —
  historycznych wierszy i powiadomień nikt nie kasuje, a `/pending-verifications`
  nadal przekierowuje na `/jobs`. Żaden writer ich już nie tworzy.
- **„Ponad budżet" to odznaka, nie stan.** Liczona na froncie
  (`lib/rate-to-hourly.ts`) ze stawki na karcie względem
  `effective_budget_hourly` rekrutacji (dzień ÷ 8, miesiąc ÷ 168, waluta ≠ PLN
  = brak porównania). Okno „Zweryfikowany" podpowiada stawkę z profilu
  kandydata (`candidate_expected_rate_hourly` w payloadzie tablicy) i ma
  „Pomiń stawkę".
- **Globalna czarna lista / weto HM = ostrzeżenie z potwierdzeniem.**
  (Konflikty z klientem — czarna lista klienta, NDA, konkurent — od #1589 nie
  blokują w ogóle, tylko plakietka; sekcja „Konflikty kandydat↔klient".)
  `check_candidate_move_eligibility` (`services/pipeline_eligibility.py`): bez
  `acknowledge_eligibility` → 409 ze strukturalnym `detail`
  (`code: "ELIGIBILITY_WARNING"`, `reason_code`, `reason`, `message`,
  `can_acknowledge`); z flagą ruch przechodzi i zostaje
  `Activity(action="eligibility_acknowledged")`. Front: okno „Przenieś mimo to"
  (`lib/pipeline-eligibility-warning.ts`; tablica i warsztat screeningu mają je
  wbudowane, „Wysyłka CV” i „Rozmowy” przez
  `components/v2/jobs/useEligibilityWarning.tsx` — każdy nowy ekran wysyłający
  `/move` musi obsłużyć to ostrzeżenie, inaczej wraca bramka w postaci toastu
  błędu). **`/bulk-move` i wejścia dodające kandydata
  (`assert_candidate_move_eligible`) zostają twarde** — nie ma tam UI do
  potwierdzenia. `moveBlockedReason` blokuje już wyłącznie `readOnly`.
- **„Zatrudniony": szkic kontraktu nie cofa ruchu.** `ensure_b2b_employment_draft`
  biegnie w savepoincie; 409/404 serwisu = zatrudnienie zostaje,
  `Activity(contract_draft_skipped)` + powiadomienie „Nie założono szkicu
  kontraktu" dla Delivery klienta (`emit`, dedup dzienny).
- **Podpis umowy offline.** `services/signing/pipeline_hook.py` usunięty —
  wysyłka, „oznacz jako wysłane" i powrót podpisanego PDF nie przesuwają kart.
  Od 23.09.2026 (Pipeline v4) `confirm-fully-signed` w Generatorze B2B ma
  `ensure_hired=True` — potwierdzony podpis przesuwa na „Zatrudniony". Kolumny
  „Umowa wysłana"/„Umowa podpisana" są ręczne.
- **Mail odrzucenia OPT-IN.** Serwer planuje wyłącznie przy
  `send_rejection_email is True`; checkbox w `RejectionV2` domyślnie odznaczony.
- **Po ruchu nie otwierają się arkusze.** Payload tablicy niesie
  `screening_done`/`scorecard_done` (`_sheet_filled` — `{"answers": []}` to NIE
  wypełniony arkusz); karta pokazuje „Uzupełnij screening" / „Scorecard".
- **Podpowiedź „komplet obsady"** idzie do `list_job_member_ids` (zespół +
  admini), nie do każdego DL/TAC w firmie.
