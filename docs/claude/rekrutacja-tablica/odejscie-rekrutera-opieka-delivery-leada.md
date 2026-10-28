# Odejście rekrutera: jego kandydatów domyka Delivery Lead rekrutacji
<!-- indeks: wyłączenie konta, `departure_care`, `pair_departure_care`, „Prowadzi” przypięte, bez Ligi/KPI/premii, „Wyłącz konto…”, kafel, filtr „Po osobach, które odeszły”, `/departed-care`, przypomnienie 5 dni, licznik HoR 10 dni -->

Prośba Artura z 28.10.2026. Na kopii produkcji z 22.10 608 żywych par
w otwartych rekrutacjach (19%) prowadziły wyłączone konta 13 osób, a żadna
nie miała sprawy odejścia: „Dezaktywuj” w Ustawieniach niczego nie
przekazywało, a przekazanie w „Ludziach” szło do jednej osoby i nie ruszało
„Prowadzi” pary. Makiety i rekomendacje:
https://claude.ai/artifact/XgaQS3c9PTRoNahBb2FuPx (wersja 4).

Decyzje Artura z 28.10.2026:

- **Każde wyłączenie konta dzieli pary po rekrutacjach.** Ustawienia (PATCH
  `is_active=false` i `DELETE /api/admin/users/{id}`), sprawa odejścia
  i M365 wołają `departure_care.hand_over_safely` (przez
  `account_deactivation.deactivate_account` albo wprost). Compass i SSO
  nadrabia pętla triggerów (`departure_care.sweep`): konta wyłączone po
  `SWEEP_SINCE` bez śladu `departure_care_assigned`. Awaria przekazania nie
  zatrzymuje wyłączenia.
- **Kto przejmuje:** Delivery Lead rekrutacji (`jobs.delivery_lead_id`,
  aktywne konto), bez niego główny DL klienta
  (`delivery_lead_client_assignments`, najpierw `is_head`), bez niego
  aktywny Head of Recruitment. Jeden rekruter u kilku DL-i = osobna część dla
  każdego. Para = żywa para osoby w otwartej rekrutacji, „Prowadzi” liczone
  jak w „Moich ludziach” (przypisanie, pierwszy weryfikujący, osoba, która
  dodała).
- **Obowiązek DL-a w ramach pensji — bez Ligi, KPI i premii.** Dlatego
  „Prowadzi” pary NIE przechodzi na DL-a: przekazanie przypina je do osoby,
  która odeszła (`candidate_job_owners`, powód „Odejście z firmy — domyka …”).
  `credited_nexus`, `kpi_panel` i `placement_bonuses.load_verifiers` liczą
  wtedy osobę, która odeszła, także gdy DL da „Zweryfikowany”. Nowe miejsce,
  które liczy zasługę z pierwszego weryfikującego, musi czytać przypisanie.
- **DL domyka sam, nie przekazuje dalej.** Nie ma „Przekaż rekruterowi”.
  Ruch i odrzucenie idą zwykłą drogą Tablicy (panel osoby, zaznaczenie wielu
  kart i „Odrzuć” z powodem dla starych „Nowych” i „Screeningu”). Admin i HoR
  dalej mogą przypisać „Prowadzi” — wtedy opieka się kończy.
- **Opieka (`pair_departure_care`)** jest otwarta, dopóki para żyje,
  rekrutacja jest otwarta, konto dalej wyłączone, a „Prowadzi” wskazuje osobę,
  która odeszła (`departure_care.open_care`). Opiekun dostaje follow-up po CV
  (`candidate_followups`) i jest pierwszy w domyślnym rekruterze rozmów
  (`interview_slots.default_recruiter_ids`).
- **Gdzie DL to widzi:** dzwonek i mail obowiązkowy `departed_pairs_care`
  (rodzaj `departed_care`, jeden na DL-a i odejście, link
  `/departed-care?from=<id>`); kafel „Po osobach, które odeszły” w „Czeka na
  Ciebie” (`DepartedCareSection`, `GET /api/board-tasks/departed-care`);
  na Tablicy znacznik „domykasz Ty” / „domyka …” (`care_*` w karcie) i pozycja
  „Po osobach, które odeszły” w „Kto dodał” (`?added_by=departed`); lista
  `/departed-care` od najbliższych klienta.
- **Przypomnienie po 5 dniach roboczych** (jedno na opiekuna i odejście,
  `reminded_at`), **po 10 dniach roboczych licznik per DL** dla Head of
  Recruitment i admina w tym samym kaflu i na liście.
- **Okno „Wyłącz konto…”** zamiast cichego „Dezaktywuj” w Osobach i rolach:
  lista DL-i z liczbą osób, klientami i etapami
  (`GET /api/admin/users/{id}/departure-preview`). Awaria podglądu nie blokuje
  wyłączenia.
- **Tylko nowe odejścia.** 608 par po osobach wyłączonych przed wdrożeniem
  zostaje bez zmian.
- **Urlopów to nie dotyczy** — przekazanie uruchamia tylko wyłączenie konta.

Dane: `pair_departure_care` (migracja 0615 + lustro w `entrypoint.sh`,
`services/departure_care_schema.py`), sonda w `/api/health/deep`.
