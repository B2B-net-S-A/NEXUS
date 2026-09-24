# Praktykant — kontrakt API (0374)

Makieta: https://claude.ai/artifact/2cF9QaY3YwoezR8dU8ga7x

Wszystkie trasy pod `/api/trainee`. Kwoty stawek zawsze PLN netto B2B.

## Trasy praktykanta (rola `trainee`, tylko własna lista)

### `GET /api/trainee/today`
Pierwsze wywołanie dnia generuje listę, jeśli jej nie ma, a pustą listę próbuje
uzupełnić (pusty ranking liczony ponownie najwyżej co 10 min). Poza dniem
roboczym albo bez aktywnego programu: `items: []` i `status` mówi dlaczego.
Admin w „podglądzie jako” niczego nie zapisuje: bez programu `no_program`, bez
listy `preview_not_generated`. Ranking z rana i oddzwonienia „później” przed
wpisaniem na listę przechodzą przez twarde warunki puli (czarna lista,
„nie kontaktować”, umowa, proces w toku).

```jsonc
{
  "list_date": "2026-09-24",
  "status": "ready",            // ready | not_workday | no_program | program_finished | preview_not_generated
  "program": { "day": 12, "total_days": 40, "status": "active" },
  "counts": { "total": 70, "closed": 32, "open": 38,
              "call": 15, "noanswer": 11, "later": 3, "wrong": 2, "declined": 1 },
  "day_completed": false,
  "answered_pct": 41.0,          // null gdy brak danych
  "team_answered_pct": 35.0,     // null gdy brak danych
  "items": [ItemRow]             // otwarte (bez odłożonych) → odłożone (retry_after) → zamknięte
}
```

`ItemRow`:
```jsonc
{
  "id": 123, "candidate_id": 456, "position": 1,
  "name": "Tomasz Zieliński", "role": "Senior Java Developer", "company": "Comarch",
  "city": "Kraków", "phone": "+48 601 234 518",
  "in_base_since": 2023, "last_contact_at": "2025-07-01T10:00:00Z" | null,
  "attempts": 0, "retry_after": null, "outcome": null, "closed_at": null, "later_date": null,
  "reasons": { "fits": 6, "open_fits": 2, "stack": ["Java", "Spring", "Kafka"],
               "missing": ["rate_stale", "availability", "work_mode"] },
  "facts": {
    "min_rate_hourly": 140.0 | null, "rate_updated_at": "…" | null,
    "b2b_willingness": null, "accepts_below_min_rate": null,
    "remote_modes": ["hybrid"], "max_onsite_days": 2 | null, "accepts_more_office_days": null,
    "office_cities": ["Kraków"], "work_time_preference": null,
    "availability_status": "unknown", "availability_date": null
  }
}
```
Kody `missing`: `rate_missing`, `rate_stale`, `b2b`, `work_time`, `work_mode`,
`below_min_consent`, `office_consent`, `availability`.

### `POST /api/trainee/items/{id}/call` — zapis rozmowy
```jsonc
{
  "b2b_willingness": "b2b" | "would_switch" | "employment_only",   // wymagane
  "min_rate": { "value": 150, "unit": "hour" | "day" | "month" } | null,
  "accepts_below_min_rate": true | false | null,
  "remote_modes": ["remote" | "hybrid" | "onsite"],
  "max_onsite_days": 0..5 | null,
  "accepts_more_office_days": true | false | null,
  "office_cities": ["Kraków"],
  "work_time_preference": "full_time_only" | "also_part_time" | "part_time_only" | null,
  "availability": "now" | "within_1m" | "within_3m" | "later" | null,
  "open_to_offers": "yes" | "maybe" | "no" | null,
  "wants": "tekst ≤ 1000" | null
}
```
Przy `employment_only` pozostałe pola są ignorowane. Odpowiedź: `{ "item": ItemRow, "day_completed": bool }`.
Pozycja już zamknięta → 409 `item_closed`. Cudza pozycja → 404.

### `POST /api/trainee/items/{id}/outcome`
`{ "outcome": "noanswer" | "later" | "wrong" | "declined", "later_date": "YYYY-MM-DD" (tylko later, dzień roboczy > dziś) }`
`noanswer`: 1. próba → `attempts=1`, `retry_after = teraz + 3 h`, pozycja otwarta; 2. próba → zamknięta.
Odpowiedź jak wyżej.

### `GET /api/trainee/items/{id}/open-jobs`
`[{ "job_id": 4812, "title": "Senior Java Developer", "recruiter_name": "Marta Nowak" | null, "matched_skills": ["Java","Spring"] }]` — tylko opublikowane rekrutacje, do których kandydat pasuje; bez klienta i budżetu.
Tylko dla pozycji z dziś z wynikiem `call` — inaczej 409.

### `POST /api/trainee/items/{id}/handover`
`{ "job_id": 4812, "note": "≤ 1000" }` → `{ "ok": true, "reopened_dismissed": bool }`. Propozycja `source="trainee"` w „Do przejrzenia”.
Tylko pozycja z dziś z wynikiem `call` (409). Pominięta wcześniej propozycja tej pary wraca
do „Do przejrzenia” (`reopened_dismissed: true`); osoba już dodana do rekrutacji → 409.

## Trasy Head of Recruitment i admina

### `GET /api/trainee/overview`
```jsonc
{
  "trainees": [{
    "user_id": 7, "name": "Kasia Wróbel", "is_active": true,
    "program": { "start_date": "2026-09-01", "workdays": 40, "extended_days": 0,
                 "daily_list_size": 70, "status": "active",
                 "day": 40, "total_days": 40, "end_date": "2026-10-27", "decision_due": true },
    "days_with_list": 40, "days_completed": 37,
    "calls_per_day": 27.0, "answered_pct": 38.0, "complete_profiles_pct": 91.0,
    "handed_over": 11, "handed_in_process": 4,
    "quality": { "checked": 10, "issues": 0 },
    "flag_low_answer": false
  }],
  "team_answered_pct": 35.0,
  "pool": { "size": 8420, "open_fit": 1310, "by_category": [{"name": "Software development", "count": 3120}],
            "computed_at": "…" | null },
  "month": { "verified_rates": 1184, "handed_over": 18, "in_process": 6 }
}
```

### `PUT /api/trainee/programs/{user_id}` — `{ "start_date", "workdays", "daily_list_size" }` (wszystkie opcjonalne)
### `POST /api/trainee/programs/{user_id}/decision`
`{ "action": "promote" | "extend" | "end", "role": "sourcer" | "recruiter", "add_to_my_people": true, "extend_days": 20 }`
### `GET /api/trainee/quality-sample?user_id=7` → `[{ "item_id", "candidate_id", "name", "phone", "called_at", "facts": {…}, "verdict", "note" }]`
### `POST /api/trainee/quality-sample/{item_id}` — `{ "verdict": "ok" | "issue", "note": "…" }`
### `GET /api/trainee/rules`, `PUT /api/trainee/rules`, `GET /api/trainee/rules/preview`
Reguły: `{ "min_fits": 2, "window_months": 18, "rate_stale_months": 6, "verified_recently_days": 90,
"process_active_days": 30, "my_people_contact_days": 30, "trainee_recall_days": 60,
"missing_rate": true, "missing_availability": true, "missing_work_mode": true,
"missing_consents": true, "missing_b2b": true, "missing_work_time": true }`.
Podgląd: `{ "size", "open_fit", "by_category": [...] }`.

## Fakty w profilu kandydata (`GET /api/candidates/{id}`)
Nowe pola odpowiedzi: `b2b_willingness`, `accepts_below_min_rate`, `accepts_more_office_days`,
`work_time_preference`, `call_facts_verified_at`, `call_facts_verified_by_name`.
Gdy `call_facts_verified_at` jest ustawione, `expected_rate_hourly` jest minimum z rozmowy —
dopóki ktoś nie zmieni stawki (każda zmiana stawki spoza telefonu praktykanta czyści też
`accepts_below_min_rate`).

### `PATCH /api/candidates/{id}/call-facts` — korekta faktów (audyt 24.09.2026)
`{ "b2b_willingness"?, "work_time_preference"?, "accepts_below_min_rate"?, "accepts_more_office_days"? }`
— częściowy: pominięte pole bez zmian, `null` czyści („nie wiadomo”). Bramka jak pozostałe fakty
profilu (`candidate.profile_fact.manage`). Ślad: `activities.action = candidate_call_facts_corrected`
z `details.changes = {pole: {old, new}}`. Pasek faktów profilu ma akcję „Popraw”.

## Etykiety dopasowań
`rate_fit`: dodatkowo `"below_min_consented"`; `office_fit`: dodatkowo `"over_consented"`;
`work_time_fit`: `ok | part_time_only | full_time_only | unknown | not_applicable` — sprzeczny
wymiar pracy to PLAKIETKA, nie ukrycie (decyzja Artura 24.09.2026).
Nowy powód ukrycia: `employment_only` (licznik `work_time_mismatch` zostaje w `meta.hidden`
dla kształtu odpowiedzi i jest zawsze 0).
