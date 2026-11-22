# Porcja dnia: najpierw osoby już wysyłane do klientów, reguły ich nie wycinają, sufit porcji 20
<!-- indeks: `services/sent_before.py`, `sent_before.MIN_SCORE` = 50, `POOL_EXTRA` = 30, `DAYS` = 365, `known_queue_points.SENT_POINTS` = 8, `KnownFacts.sent_elsewhere`, `entry_meta.sent_before`, `PendingCard.sent_before`, `in_batch`, `_by_rules` (budżet i km), `auto_full_review._sent_before_extras`, `process_entry_meta.caution_views`, „Wysłany do klienta 2× · ostatnio …”, `review_batch_levels.CAP` = 20 -->

Decyzja Artura z 20.11.2026 (Z1 i Z3 z raportu
https://claude.ai/artifact/2jac9hsRwpqE4yGpERqXDx) i zmniejszenie porcji
z 50 do 20. Cel Artura: osoby, które proponuje AI, to osoby, które potem
wysyłamy. Pytanie kandydata mailem przed kartą (Z2) Artur odrzucił:
„wysłanie emaila to czekanie bez sensu, my musimy ciągle dzwonić”. Nie wracaj
do tego bez nowego faktu.

## Dlaczego

- Z 325 CV wysłanych 09–19.11 aż 204 (63%) to osoby już przez nas sprawdzone.
  Wśród kart od systemu osoba wysłana wcześniej do innego klienta trafiała do
  klienta w 12,2% (wszystkie karty 7,9%, nowa dla nas osoba 5,7%). Sam
  screening bez wysyłki nie podnosi trafności (3,0%), więc liczy się
  wyłącznie etap `cv_sent`.
- Silnik ocenia treść CV. Historia osoby dawała dotąd punkty tylko za etap
  u tego samego klienta (+6) i za notatkę, i to tylko w puli 150 najlepszych.
  Z 89 sprawdzonych osób wysłanych ręcznie 53 miało w ostatnim przeglądzie
  wynik od 50% (31 od 65%), ale były poza pulą.
- 42 wysłane osoby system sam wyciął regułami (budżet, dojazd), 20 z nich
  było już wcześniej wysyłanych.
- Karta porcji pokazywała ostrzeżenia jako pusty prostokąt: kolejka oddawała
  surową migawkę (`key`, `city`, `over_pct`), a karta czyta `label`.

## Jak działa

- **Wysłany wcześniej** = etap `cv_sent` w innej rekrutacji w ostatnich 365
  dniach (`sent_before.facts_for`, `sent_elsewhere_select`). Liczba rekrutacji
  i ostatnia wysyłka (dni, tytuł rekrutacji) idą na kartę porcji.
- **Pula przeglądu** (`refresh_autofill_pool`) po 150 najlepszych dokłada do
  30 takich osób z tego samego przeglądu od 50%, tym samym filtrem (dopuszczony,
  oceniony, zmierzony, bez innej roli, bez osób z rekrutacji), z
  `evidence.sent_before`.
- **Nowe CV nie wycina dołożonych** (22.11.2026): `auto_match_service._write_pool`
  przycina pulę do 150 tylko wśród osób bez `evidence.sent_before`, a nowy
  wynik osoby dołożonej zostawia jej flagę. Wcześniej cięcie liczyło całą pulę
  i 27 z 33 pilnych pul miało 0 dołożonych. Strażnik:
  `test_new_cv_does_not_trim_people_sent_before_from_the_pool`.
- **Próg (od 22.11.2026, R3):** w porcji osoba wysłana wcześniej liczy się od
  progu porcji jak inni (`in_batch`, `ranked_picks(min_score=…)`). Od 20.11
  liczyła się od 50%, ale porcja 20.11 pokazała: karty „wysłany wcześniej”
  60–64% zajęły 116 z 301 miejsc i dały 0 CV z 40 decyzji, od 65% 4 CV
  z 9 decyzji. W puli zostają od 50% (lista kandydatów), a w kolejce dostają
  `SENT_POINTS`. Raport: https://claude.ai/artifact/Ec7UJD6UbQqwe4HgSiebZW.
- **Kolejność:** `known_queue_points.SENT_POINTS` = 8 (stała, nie suwak panelu),
  ta sama skala co „u klienta” 6 i świeża notatka 8. Działa na Tablicy, w porcji
  i w dobieraniu (`facts_for_jobs`). Odrzucenie przez tego klienta dalej zeruje
  punkty.
- **Reguły (`_by_rules`):** u osoby wysłanej wcześniej budżet ponad 15% i miasto
  dalej niż 100 km od biura to ostrzeżenie (`budget`, `office_city` z `km`),
  nie wycięcie. Praca teraz u klienta (`client_off_limits`) dalej wycina.
- **Ostrzeżenia na karcie porcji** idą przez `process_entry_meta.caution_views`,
  tę samą funkcję co plakietki Tablicy. Strażnik:
  `tests/test_review_batch_cautions_unit.py`.
- **Sufit porcji 20** (`review_batch_levels.CAP`), wyżej zapisane poziomy czytane
  jako 20; minimum HoR dalej jest podłogą.

## Czego nie robić

- Nie dawaj punktów ani niższego progu za sam screening bez wysyłki.
- Nie przywracaj progu 50% w porcji bez nowego pomiaru (R3, 22.11.2026).
- Nie podnoś sufitu porcji bez nowego pomiaru decyzji dnia (21+ dawały 0,9%).
- Nie zastępuj telefonu mailem z pytaniem do kandydata w porcji (decyzja 20.11).
- Pomiar po wdrożeniu: tygodniowy udział wysłanych, których system pokazał
  (`entry_meta.system_view`), dziś 47–48%; cel Artura 100%.
