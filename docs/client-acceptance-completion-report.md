# „Klient zaakceptował” — raport ukończenia (16.10.2026)

Zgłoszenie Delivery Leada: dostał akceptację kandydata od klienta i nie
wiedział, gdzie ją zaznaczyć, żeby rekruter i Head of Recruitment dostali
informację. Makiety „teraz → propozycja” z decyzjami D1–D6:
https://claude.ai/artifact/DNz7EMuABGztLH81xGtzTc — Artur przyjął wszystkie
rekomendacje.

## Stan przed zmianą (produkcja, odczyt 16.10.2026)

- Akceptacja = ruch na etap „Akceptacja”, który na Tablicy jest kolumną
  „Umowa” z podpisem „Podpis umowy” i małą plakietką „Akceptacja”.
- Dzwonek tylko z reguły etapu (prowadzący + rekruter kandydata), do
  wyciszenia; Head of Recruitment i Delivery Lead — nic.
- 14 wejść na „Akceptację” w 60 dni, dzwonek przy 2. Cztery ostatnie
  (12–16.10) przyszły z etapu szablonu Traffita „Po Interview” (order 11)
  i resolver wziął je za cofnięcie (porównanie `order` z dwóch szablonów) —
  0 dzwonków.

## Co zmienione

| Decyzja | Zmiana |
| --- | --- |
| D1 | Przycisk „Klient zaakceptował” na karcie w „Rozmowie u klienta” i w panelu osoby, werdykt „Akceptuje”; strzałka, przeciągnięcie i „Następny etap” z rozmowy na akceptację też otwierają to okno. Okno: data akceptacji, planowany start, co powiedział klient, kto dostanie dzwonek. |
| D2 | Kolumna „Akceptacja i umowa”, podpis „Klient zaakceptował → umowa → podpis”, liczniki kroków w nagłówku; zielony wiersz „✓ Klient zaakceptował · data · kto” na karcie i w panelu. |
| D3 | Debrief zostaje bramką serwera; okno pokazuje jego brak i otwiera okno debriefu na wierzchu. |
| D4 | Dzwonek: rekruter kandydata, prowadzący, Delivery Lead rekrutacji, wszyscy aktywni Head of Recruitment (bez osoby, która zaznacza). |
| D5 | Typ `client_accepted`, kategoria „Akceptacje klienta” — obowiązkowa, bez maila. |
| D6 | Werdykt „Dalej” → „Akceptuje”; zapisuje się razem z ruchem i nie dubluje dzwonka „Klient idzie dalej”. |
| Błąd | `is_backward_move`: kierunek między szablonami po kolumnach Tablicy. |

Migracja 0451 (enum `client_accepted`, `candidate_stages.client_accepted_on`,
`planned_start_on`) z lustrem w `entrypoint.sh`. Reguły:
`docs/claude/rekrutacja-tablica/rekrutacja-v5-8-kolumn-strzalka-przesun-dalej-qc-cv.md`
(„Akceptacja klienta”) i `…/dzwonek-przy-przekazaniu-karty-qc-dl-cv-wyslane.md`.

## Testy

- Backend bez bazy (lokalnie): `test_client_acceptance.py` (część jednostkowa),
  `test_client_acceptance_migration.py`, `test_stage_handoff_notifications.py`,
  `test_notification_categories.py`, `test_interview_phase_next_action.py`,
  `test_authz_guard_matrix.py`, przewodniki Jarvisa.
- Backend z Postgresem (CI): ruch z etapu Traffita na „Akceptację” dzwoni do
  rekrutera, prowadzącego i HoR, nie do DL, który przesuwa; data i start na
  wierszu etapu i na karcie Tablicy; „Cofnij” gasi dzwonki; 422 dla pól przy
  innym etapie i dla daty z przyszłości; podgląd odbiorców bez patrzącego.
- Frontend: `client-acceptance.test.ts`, `ClientAcceptedDialog.test.tsx`,
  `KanbanBoardV2.test.tsx` (przycisk, strzałka, zielony wiersz, liczniki,
  ruch z datą, werdykt, dymek), `JobInterviewsTab.test.tsx` („Akceptuje”).
- Przeklikane w `/preview/job-detail` przy 1280×720: Tablica, okno,
  zapis, panel osoby z paskiem i „Cofnij akceptację klienta”.

## Po wdrożeniu (okno 19:00–07:00)

- `/api/health` → SHA z maina z tą zmianą; deep health — migracja 0451.
- Na produkcji: akceptacja jednej karty z Traffita i sprawdzenie dzwonków
  u rekrutera i HoR (odczyt `notifications` typu `client_accepted`).
