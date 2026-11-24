# Porcja dnia: 12 kart z pilnych i 8 z pozostałych rekrutacji, karty bez decyzji od 2 dni roboczych schodzą na koniec
<!-- indeks: `review_batch_plan.URGENT_TIERS`, `REST_SHARE` = 0,4, `rest_seats`, `plan_portions` (pilne bez miejsc na niepilne → niepilne → reszta do pilnych), `review_batch.STALE_BUSINESS_DAYS` = 2, `is_stale`, `batch_cards(fresh_only=True)`, `settle_owners`, `load_plan`, `_room`, `review_queue` (odłożone na końcu), `sources.urgent` / `other` (tylko świeże) / `other_seats` / `stale`, „+N odłożonych”, `stale_summary`, `/me/queue` → `stale`, pozycja kolejki `stale` i `opened_on`, „z pilnych” / „z pozostałych”, „Na końcu porcji: N kart z …” -->

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
  · +14 odłożonych · …, ale 8 miejsc czeka na rekrutacje bez pilnego priorytetu”
  (`sources.urgent`, `other`, `stale`, `other_seats`; stare `p0` i `rest` zostają
  i dalej liczą wszystkie czekające karty). „z pilnych” i „z pozostałych” liczą
  tylko świeże karty, więc na starcie dnia sumują się do porcji; odłożone stoją
  obok w plakietce „+N odłożonych” w kolorze ostrzeżenia (szczegóły niżej).
  W ciągu dnia obie liczby maleją z decyzjami, jak dotąd.
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

## Odłożone w pasku i w linii nad kartą (decyzja Artura z 24.11.2026)

Makieta na kopii stagingu, 1280 × 720:
https://claude.ai/artifact/QVTX8mqHz2HynmrmR8RcP3.

- **Dlaczego:** pasek liczył odłożone w „z pilnych” i „z pozostałych”, a plan
  dokłada za nie świeże osoby, więc suma wychodziła ponad porcję. Na kopii
  z 24.11 po porannym przebiegu porcji 10 z 17 rekruterów miało w pasku więcej
  niż porcję; u 9 nadwyżka to były dokładnie odłożone (konto 119: porcja 20,
  w pasku 26 z pilnych + 8 z pozostałych, w tym 14 odłożonych). Wszystkie
  odłożone były z rekrutacji pilnych, więc zawyżały „z pilnych”.
- **Wybrany wariant A:** podział liczy świeże karty (`status_for`), odłożone
  idą osobno w `sources.stale` i plakietce „+N odłożonych” z podpowiedzią „Bez
  decyzji od 2 dni roboczych: stoją na końcu kolejki i nie zajmują miejsca
  w porcji.”. Odrzucony wariant B: liczby jak dawniej i dopisek „w tym N
  odłożonych” (suma dalej 34 przy porcji 20).
- **Linia „Na końcu porcji”:** liczbę i dni bierze z całej kolejki
  (`stale_summary`, pole `stale` w `/me/queue`), bo ekran pobiera tylko 20
  pierwszych kart, a odłożone stoją za świeżymi: przy pełnej porcji linii nie
  było, a konto z 22 odłożonymi po 10 decyzjach widziało „10 kart”. Kiedy linia
  się pokazuje, zostaje bez zmian: gdy odłożone wchodzą na stronę kolejki.
- **Co zostaje:** karty wzięte („Biorę”, „Dzwonię”) ponad plan nie schodzą
  w porannym przebiegu (`settle_owners(release=True)` pomija `taken`), więc
  taka osoba może mieć świeżych kart więcej niż porcja (24.11: 1 z 17 kont,
  3 karty). Zakładka „Do decyzji” liczy całą kolejkę razem z odłożonymi.

## Czego nie robić

- Nie wracaj do „pilne biorą całą porcję” bez pomiaru, skąd idą wysyłki.
- Nie zdejmuj odłożonym kartom właściciela: wróciłyby do rozdania innym.
- Nie dokładaj odłożonych z powrotem do „z pilnych” i „z pozostałych” ani nie
  licz linii „Na końcu porcji” ze strony kolejki (decyzja z 24.11.2026 wyżej).
