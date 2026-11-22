# Porcja dnia: 12 kart z pilnych i 8 z pozostałych rekrutacji, karty bez decyzji od 2 dni roboczych schodzą na koniec
<!-- indeks: `review_batch_plan.URGENT_TIERS`, `REST_SHARE` = 0,4, `rest_seats`, `plan_portions` (pilne bez miejsc na niepilne → niepilne → reszta do pilnych), `review_batch.STALE_BUSINESS_DAYS` = 2, `is_stale`, `batch_cards(fresh_only=True)`, `settle_owners`, `load_plan`, `_room`, `review_queue` (odłożone na końcu), `sources.urgent` / `other` / `other_seats` / `stale`, pozycja kolejki `stale` i `opened_on`, „z pilnych” / „z pozostałych”, „Na końcu porcji: N kart z …” -->

Decyzje Artura z 22.11.2026 (R2 i R5 z raportu
https://claude.ai/artifact/Ec7UJD6UbQqwe4HgSiebZW).

## Dlaczego

- Od 20.11 porcja ma sufit 20, a kolejność od 10.11 to „najpierw P0, potem P1
  Pilne, potem reszta”. Przy 50 kartach kolejka sięgała po pilnych do reszty,
  przy 20 już nie: 20.11 rekrutacje „Bez priorytetu” dostały 0 kart, średnie 12,
  pilne 289 z 301. A w 16–19.11 rekrutacje niepilne dały 105 ze 168 CV (62%).
- W 789224 (pilna) 29 kart z 18–19.11 czekało bez decyzji. Porcja liczy karty
  do 7 dni, więc w piątek nie dodała tam nikogo nowego, a sześć osób wysłano
  tam ręcznie albo przepięciem.

## Jak działa

- **Podział (R2):** pilne = P0 i P1 Pilne (`URGENT_TIERS`). Osoba, która ma też
  rekrutacje niepilne, dostaje z pilnych najwyżej porcję minus `rest_seats`
  (40%: 20 → 12 + 8, 10 → 6 + 4). Niepilne biorą resztę po kolei jak dotąd
  („Bez priorytetu”, potem „Przyjmujemy”). Czego niepilne nie wezmą (pusta pula),
  wraca do pilnych. Bez rekrutacji niepilnych cała porcja jest z pilnych.
  P0 dalej idzie przed P1 wewnątrz pilnych.
- **Nagłówek porcji:** „Twoja porcja dziś: 20 · 12 z pilnych · 8 z pozostałych
  · …, ale 8 miejsc czeka na rekrutacje bez pilnego priorytetu”
  (`sources.urgent`, `other`, `other_seats`; stare `p0` i `rest` zostają).
- **Odłożone karty (R5):** karta od systemu bez decyzji od `STALE_BUSINESS_DAYS`
  dni roboczych (`is_stale`, święta z `is_business_day`) zostaje w „Nowych”
  i w porcji osoby, ale:
  - nie liczy się w planie, przy właścicielach ani w dopełnianiu
    (`batch_cards(fresh_only=True)` w `load_plan`, `settle_owners`, `_room`),
    więc system dokłada świeże osoby;
  - stoi na końcu kolejki porcji (`review_queue`);
  - ekran pokazuje nad kartą „Na końcu porcji: N kart z DD.MM–DD.MM bez decyzji
    od 2 dni roboczych”.
- Decyzje o odłożonej karcie liczą się do minimum jak dotąd (`in_batch` bez
  zmian), skrypt wycofania przed porcją (`plan_batch_reset`) też bez zmian.

## Czego nie robić

- Nie wracaj do „pilne biorą całą porcję” bez pomiaru, skąd idą wysyłki.
- Nie zdejmuj odłożonym kartom właściciela: wróciłyby do rozdania innym.
