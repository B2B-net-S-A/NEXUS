# P4 — Przepływ: wypowiedzenie umowy → domknięte zamówienia → „Zakończeni” → raporty → sprzątanie

| Pole | Wartość |
|---|---|
| Tryb | **W** — konto admina; `wyniki/LOCK` |
| Moduły | M08 → M07 → M06 → M10 → M13 |
| MUST | **tak** |
| Zależności | P2 (kontrakt P1@D1 aktywny z zamówieniem), P3; **wymaga jednej nocy** między krokiem 6 i 7 |
| Czas | ~1,5 h + noc + 1 h |
| Akcje AI | nie |
| CZŁOWIEK | krok 12 (sprzątanie — potwierdzenie listy przed DELETE) |

## Cel

Koniec współpracy musi być widoczny WSZĘDZIE i dopiero od właściwego dnia: umowa → zamówienia →
zakładka „Zakończeni” → MRR → Insights (zejścia, rezygnacje) → alerty. Potem sprzątamy po całym UAT.

## Kroki — dzień 1

| # | Akcja (admin) | Weryfikacja | Zapisz |
|---|---|---|---|
| 1 | `/contracts/{{contract_P1@D1}}` → zmień `end_date` na **wczoraj** (PATCH, bez wypowiedzenia) | `_sync_client_orders_to_contract_end`: zamówienie QA/001 dostaje `end_date` = wczoraj (skrócenie); status zamówienia `completed` (dzień nadszedł); kontrakt `_status_after_end_date_change` → `ended`? (data w przeszłości) — zapisz, co system zrobił OD RAZU vs co zostawia cronowi | zrzut |
| 2 | wyczyść `end_date` (bezterminowa) → Zapisz | kontrakt wraca na `active` (leczenie `ended → active` przez `_status_after_end_date_change`); zamówienie NIE wydłuża się z powrotem (skracanie tylko w jedną stronę — zapisz stan: zamówienie `completed` z datą wczoraj = TERAZ konsultant „Brak aktywnego zamówienia”) | — |
| 3 | zamówienie QA/001 → „Uzupełnij” → `end_date` 31.12.2026, status Aktywne → Zapisz | zamówienie znowu obowiązuje; kontrakt `client_order_end_date` = 31.12.2026 | — |
| 4 | `/contracts/{{contract_P1@D1}}` → **„Wypowiedz”** z datą **+2 dni**, powód `consultant_resigned` | kontrakt `ending`/`active` z `terminated_at`, `termination_reason`; zamówienie QA/001 `end_date` ucięte do +2 dni, status nadal `active` (dzień nie nadszedł); powiadomienie/alert DL; Activity | — |
| 5 | `/clients/{{D1}}` → Profil | konsultant P1 nadal w „Aktywnych” (do daty końca włącznie); w Zamówieniach zamówienie z datą +2; MRR nadal liczy P1 | — |
| 6 | Insights → Rada → Rok do roku → „Zejścia”/„Rezygnacje” bieżący miesiąc | JESZCZE bez P1 (data w przyszłości; `active/ending` liczą się od dnia, w którym data nadeszła) | liczby |
| 6b | zmień datę wypowiedzenia na **wczoraj** (jeśli UI pozwala edytować; inaczej: wypowiedz drugi raz z datą wczoraj) | kontrakt `ended`; zamówienie `completed`; P1 w „Zakończonych” od razu (`contract_end_date < dziś`) | — |

## Kroki — dzień 2 (po nocnym cronie `contract_alerts._promote_statuses`)

| # | Akcja | Weryfikacja | Zapisz |
|---|---|---|---|
| 7 | `/contracts/{{contract_P1@D1}}` | `ended` (jeśli 6b) — status ustabilizowany; `terminated_at` niezmienione | — |
| 8 | `/clients/{{D1}}` → Profil → „Zakończeni” | P1 obecny z End date; stawki liczone na dzień zakończenia; „Aktywne MRR” BEZ P1; Archiwum konsultantów: 3 kolumny kwot | zrzut |
| 9 | `/contractors` | P1 poza aktywnymi (filtr statusu „Zakończeni” pokazuje) | — |
| 10 | Insights → Rada → Rok do roku → „Zejścia” i „Rezygnacje” bieżący miesiąc | +1 względem kroku 6 (`consultant_resigned` ∈ rezygnacje); miesiąc oznaczony „(trwa)”, bez delty w YTD | — |
| 11 | Insights → Rekrutacja → Placementy / Hall of Fame | placement P1 (z P2 „Zatrudniony”) WIDOCZNY pod adminem — **admin jest POZA rankingiem HoF** (scope), więc w HoF go NIE MA, a w Placementach JEST; `scope.excluded` +1 | — |
| 11b | dzwonek: alerty wygasania | brak duplikatu alertu dla QA/001 (dedup po dacie końca); alert o zakończeniu kontraktu 1× | — |
| 11c | `GET /api/insights/reconciliation/placements` | placement P1 widoczny w obu rodzinach atrybucji (lub w jednej — zapisz, w której) | — |

## Kroki — sprzątanie po całym UAT (CZŁOWIEK potwierdza listę)

| # | Akcja | Weryfikacja |
|---|---|---|
| 12 | zbierz `utworzone.json` z P1–P4, M05, M08 (umowa S20), M12 (kandydat zgłoszenia) → pokaż listę człowiekowi | zgoda |
| 13 | kolejność: sprawy offboardingowe → linie i grupy zamówień (D2), zamówienia (D1) → kontrakty (`draft` u D2 — DELETE; `ended` P1@D1 — DELETE jeśli API pozwala; inaczej zostaw z prefiksem i zapisz) → umowy B2B (`DELETE …/generated/{id}` zwalnia numer) → wygenerowane CV → linki publiczne (już odwołane) → etapy → kandydaci (P1, S17 z M12; D5–D9 zostają? — **decyzja**: usuń wszystkich testowych) → rekrutacje D3, D4 → reguła CV D12, karta D11 → klienci D1, D2 | każde DELETE 200/204/404 |
| 14 | `GET /api/candidates?q=QA-E2E`, `/api/clients?q=QA-E2E`, `/api/jobs?q=QA-E2E` | puste |
| 15 | Insights → Placementy, Hall of Fame, Rada → MRR | zero śladów testowych (placement P1 znika razem z kandydatem — twarde usunięcie kasuje wiersze wyników i etapy; jeśli zostaje w `analytics_first_milestones` → zgłoś P2 „usunięty kandydat zostaje w analityce”) |
| 16 | Coolify set env: usuń ID D2 z `MULTI_CONSULTANT_ORDER_CLIENT_IDS` (`redeploy=false`) | health po następnym deployu OK |
| 17 | `GET /api/settings/ai` → `ai-po.json`; różnica vs `ai-przed.json` → raport | zużycie ≤ budżet z Fali 0 |
| 18 | usuń `wyniki/LOCK` | — |

## Kryteria PASS

Kroki 1–5, 6b, 7–8, 10 = P1 przy FAIL. Krok 11 (admin poza HoF) = P2. Krok 15 (ślady po usunięciu) = P2.
Sprzątanie niepełne (encje, których nie da się usunąć przez API) → lista w raporcie końcowym z ID.
