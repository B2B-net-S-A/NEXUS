# Rekruter generuje umowę w rekrutacji — raport (04.10.2026)

Makiety: https://claude.ai/artifact/YJwAxv4ByNdj19Z1gPmDGj. Decyzje Artura
04.10.2026 (wg rekomendacji):

- D1 rekruter nie potwierdza podpisu — prosi Delivery Leada (uprawnienie
  „Podpis B2B” bez zmian, admin może je nadać w „Osoby i role”),
- D2 bez kroku kontroli TCM przed wysłaniem umowy Partnerowi,
- D3 umowę pod tym samym numerem poprawia autor, rekruterzy i Delivery Lead
  rekrutacji, TCM i admin,
- D4 wygenerowanie umowy nie przesuwa karty,
- D5 „Zatrudniony” z Traffita przy umowie „W trakcie” = sprawa na pulpicie,
  bez automatu.

## Czeka na Artura

- Nic do decyzji. Do rozważenia: TCM poprawia umowę tylko wtedy, gdy widzi jej
  stawki (reguła widoczności stawek z 22.09 — TCM bez wglądu w stawki nie
  dostaje „Popraw umowę”).

## Zmienione

| Część | PR | Stan | Dowód |
|---|---|---|---|
| Backend: migracja 0417, kto poprawia, `GET /prefill`, `POST …/signature-request`, stan umowy na karcie, grupa „Umowy” w `/board-tasks`, typ kontraktu przy UoP/zlecenie | #2020 | na produkcji | `alembic_version` = `0417_b2b_signature_request`; `/board-tasks` (admin): `to_confirm` 7 × `hired_unsigned` (108, 114, 123, 125–128), `to_close` 1 × `closed_signed_active` (83); karta pary umowy 127 niesie `agreement`; `/prefill` → stawka z karty rekomendacji |
| Front: formularz z ustaloną parą i podpowiedziami, znacznik na karcie, lustro w rejestrze (filtr „Wygenerowane przez rekruterów”, link do panelu osoby) | #2021 | na produkcji | `/api/health` = `b42109156` |
| Front: umowa w panelu osoby (sekcja w wąskim panelu, zakładka „Umowa” z formularzem, poprawka, podpis/prośba), przewodnik Jarvisa, inwentarz, harness | #2023 | w kolejce | harness `/preview/job-detail` przeklikany |
| Front: okno zatrudnienia i rezygnacji pytają o umowę, „Umowy” na pulpicie | #2022 | w kolejce | testy `usePipelineMove`, `RejectionV2`, `BoardTasksPanel` |

## Znalezione

- Stawka do klienta w szkicu zamówienia po podpisie (F7 z planu) — wycofane
  z #2020: `complete_order_clause` uznaje zamówienie ze stawką i startem za
  „uzupełnione”, więc wpisana stawka zdejmowałaby sprawę „uzupełnij
  zamówienie” bez numeru i PDF-u. Wymaga osobnej decyzji.
- Formularz w trybie `lockedPair` nadal pokazuje wyłączone pickery kandydata
  i rekrutacji zamiast nazwiska tekstem — działa, ale zajmuje miejsce.
- Lokalne testy frontu przy load average ~260 (inne sesje) dawały losowe limity
  czasu; te same pliki przechodzą przy normalnym obciążeniu i w CI.
- Niepotwierdzone na produkcji: prośba o podpis (nie wysyłaliśmy prawdziwego
  dzwonka) i generowanie z panelu (numer umowy jest zużywany przy każdym
  pobraniu — nie generowaliśmy prawdziwej umowy).
