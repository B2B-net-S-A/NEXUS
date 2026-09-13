# P2 — Przepływ: zatrudnienie → umowa B2B → potwierdzenie podpisu → aktywny kontrakt → zamówienie

| Pole | Wartość |
|---|---|
| Tryb | **W** — konto admina; `wyniki/LOCK` |
| Moduły | M03 → M08 → M07 → M06 |
| MUST | **tak** (bez tego nie ma MRR ani rejestru umów) |
| Zależności | P1 zakończony (kandydat P1 na „Interview Klient” w D3) |
| Czas | ~2,5 h |
| Akcje AI | 1 odczyt PDF zamówienia |
| CZŁOWIEK | krok 8 („Potwierdź podpis” jest na stop-liście dla danych prawdziwych; tu dane testowe — agent MOŻE kliknąć, ale człowiek zatwierdza start P2) |

## Cel

Najgroźniejszy szew w systemie: „Zatrudniony” → automatyczny szkic zamówienia → umowa B2B →
potwierdzenie podpisu → kontrakt AKTYWNY (bezterminowy, bez stawki przychodowej) → zamówienie
z PDF → stawka przychodowa i okres przepisane do kontraktu → kontrakt widoczny w MRR klienta.

## Dane

Kandydat z P1 (Jan Próbny), rekrutacja D3, klient D1 (widok jednoosobowy), `zamowienie-jednoosobowe.pdf`
(zmień w fixtures nazwisko konsultanta na „Jan Próbny”, jeśli PDF ma „Anna Testowa” — albo użyj D5 w P1).

## Kroki

| # | Akcja (admin) | Weryfikacja | Co zapisać |
|---|---|---|---|
| 1 | `/jobs/{{D3}}` → kandydat P1 → przesuń na „Oferta wysłana” → „Oferta zaakceptowana” | etapy zapisane (słowo „Oferta” TUTAJ jest poprawne — etap pipeline'u) | — |
| 2 | przesuń na **„Zatrudniony”** (`hired`) | karta w kolumnie „Zatrudniony”; `analytics_first_milestones` dostanie wiersz (widoczny w Insights po odświeżeniu widoku — sprawdź jutro w M13 S24) | czas |
| 3 | `/clients/{{D1}}?tab=zamowienia` | hook zatrudnienia założył SZKIC zamówienia „(bez numeru)” dla kandydata (D1 nie jest klientem kosztowym ani wielo-konsultantowym → szkic okresowy); kontrakt w statusie `draft` u D1 | `order_id`, `contract_id` |
| 4 | `/contracts/{{contract_id}}` | `draft`; start = dziś/brak; brak stawek; alert „Kończący się” NIE dotyczy | — |
| 5 | `/contracts/b2b-generator` → Generuj: kandydat P1, klient D1, rekrutacja D3, stawka **120 PLN/h**, start **01.10.2026**, bezterminowa → Generuj | wiersz w „aktywne i w trakcie podpisu”, status podpisu „w trakcie”; numer nadany; DOCX pobiera się | `b2b_id`, numer |
| 6 | (próba negatywna) ZMIEŃ w `/contracts/{{contract_id}}` stawkę kosztową na **150 PLN/h** (PATCH, jeszcze draft) → Zapisz | zapisane; teraz kontrakt (150) ≠ dokument (120) | — |
| 7 | generator → wiersz → „Potwierdź podpis” (obustronny), data podpisu dziś → Zatwierdź | **409** z listą `conflicts` (stawka 150 vs 120) i `can_keep_existing_terms: true`; nic nie zmienione; komunikat PL | zrzut + body |
| 8 | to samo z checkboxem „Zachowaj warunki kontraktu” (`keep_existing_contract_terms: true`) → Zatwierdź | 200; umowa `signature_status = fully_signed`; kontrakt POWIĄZANY (`b2b_contract_details` z numerem umowy); stawka kontraktu ZOSTAJE 150 (nie nadpisana z dokumentu); kontrakt **AKTYWNY** (`activate_without_revenue_gate`, source `b2b_signed_agreement`) mimo braku stawki przychodowej; `end_date` PUSTA; etap kandydata „Zatrudniony” (już był); Activity `fully_signed_confirmed` z `acknowledged_conflicts` | zrzut |
| 9 | `/clients/{{D1}}?tab=zamowienia` | szkic z kroku 3 „zapewniony” (istnieje, dalej `draft`, bez numeru) — hook nie założył drugiego; `order_skipped_reason` = null (jest zamówienie) | — |
| 10 | umowa → drugi raz „Potwierdź podpis” | `already_processed` (idempotencja): 200 bez zmian, `order_id` = szkic z kroku 3 | — |
| 11 | zamówienie (szkic) → „Uzupełnij zamówienie” → wgraj `zamowienie-jednoosobowe.pdf` → odczyt (**AI 1**) | pola: numer `QA/001/2026`, 01.10–31.12.2026, 1200 PLN/MD, 60 MD; stawka kosztowa **tylko do odczytu „z kontraktu”** = 150 (kontrakt jest jedynym źródłem kosztu) — jeśli PDF nie zna nazwiska P1, karta `none` → ręcznie potwierdź osobę | — |
| 12 | Zapisz zamówienie ze statusem Aktywne | zamówienie `active`; `commit_order_write` → sync do kontraktu | — |
| 13 | `/contracts/{{contract_id}}` | `client_order_start_date = 01.10.2026`, `client_order_end_date = 31.12.2026` (w OSOBNYCH polach; `end_date` nadal PUSTA); krok `client_rate_schedule` = 1200 od 01.10.2026 z `source_order_id`; **`rate_unit` = MD** (jednostka najnowszego zamówienia; koszt 150/h przeliczony na 1200/MD = 150 × 8) | zrzut |
| 14 | `/clients/{{D1}}` → Profil → Konsultanci | wiersz P1: start 01.10.2026, stawka kosztowa 1200 PLN/MD (przeliczona), przychodowa 1200 PLN/MD, marża 0 (przychód = koszt po przeliczeniu — zamierzone dane testowe; jeśli chcesz marżę > 0, użyj 1400 w PDF); kafel „Aktywne MRR” = Σ marż | — |
| 15 | Insights → Rada → Klienci (MRR) | D1 na liście z MRR = kafel z kroku 14 (karta B para 7) | — |
| 16 | `/contractors` | P1 na liście, bez „Brak aktywnego zamówienia” (zamówienie od 01.10 — jeśli dziś < 01.10, dopisek „zaczyna się później”/brak dopisku — zapisz, co pokazuje) | — |
| 17 | `/contracts` domyślny filtr | kontrakt P1 obecny (active) | — |
| 18 | generator → wiersz → „Zmień status” → „Zawieś” (umowa `active`? — status handlowy umowy B2B, niezależny od podpisu) → powód `project_completed`, data dziś | jeśli umowa jest `in_progress` → 422 (zawiesić można tylko `active`); jeśli `active` → `suspended`, w zakładce 2; historia statusów +1 | — |
| 19 | (jeśli 18 udane) → „Przywróć na aktywną” → wybierz projekt D3 | 200; `closure_*` wyczyszczone; notatka na kontrakcie „Poprzedni projekt zakończony: …”; render_payload NIEtknięty | — |
| 20 | podgląd DL (D1): `/contracts/{{contract_id}}`, profil klienta | widzi kwoty (portfel); podgląd HoR: „—” | — |

## Weryfikacja końcowa (API)

```js
const tok=localStorage.getItem('access_token'); const h={Authorization:`Bearer ${tok}`};
const k = await fetch('https://api.nexus.dynaminds.pl/api/contracts/{{contract_id}}',{headers:h}).then(r=>r.json());
console.log(k.status, k.start_date, k.end_date, k.rate_unit, k.rate_candidate, k.rate_client, k.client_order_start_date, k.client_order_end_date);
console.table(k.client_rate_schedule?.map(s=>({from:s.effective_from, rate:s.rate, src:s.source_order_id})));
// oczekiwane: active, 2026-10-01?, null, md, 1200, 1200, 2026-10-01, 2026-12-31; krok z source_order_id
```

## Sprzątanie

NIE sprzątaj — P3 i P4 używają tego kontraktu i zamówienia. Wszystko do `utworzone.json`.

## Kryteria PASS

Kroki 7–8 (409 → keep terms → aktywny) i 13 (sync zamówienie → kontrakt) są sercem przepływu.
FAIL na którymkolwiek = P1 blokujący start. Krok 18/19 = P2.
