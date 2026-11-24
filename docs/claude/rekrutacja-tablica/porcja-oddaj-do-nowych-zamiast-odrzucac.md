# Porcja dnia: „Oddaj do Nowych” zamiast odrzucania, żeby odblokować wyszukiwanie
<!-- indeks: `ReturnToNewButton` (`review-batch/ReviewBatchReturn.tsx`), grupy po rekrutacji w „Do domknięcia” (`review-batch-close-group`), `TIER_RANK`, ruch screening → `new` przez `usePipelineMoveCore`, `_decisions` (karta, która wróciła do „Nowych”, nie jest decyzją) -->

Prośba rekrutera i decyzja Artura z 24.11.2026 (wariant A z trzech). Rekruter
19.11 o 13:14 odrzucił 39 osób ze Screeningu jednej rekrutacji w 38 sekund
z notatką „Inne — odrzucam z tego screeningu aby móc wyszukiwać ręcznie na
innym priorytecie”, bo zaległe „Do screeningu” z rekrutacji, która spadła
poniżej jego P0, blokowały wyszukiwanie. Ta notatka i „Odrzucony” stały potem
w historii osób, z którymi nikt nie rozmawiał. Na kopii z 23.11: 14 rekruterów
z blokadą, 342 screeningi po terminie, 276 (81%) z rekrutacji poniżej
najwyższego priorytetu danej osoby. Makiety ze stagingu:
https://claude.ai/artifact/6wE27cggLUiE4kAgSPmu9r.

- **„Do domknięcia” grupuje po rekrutacji**, od najwyższego poziomu porcji
  (P0, P1 Pilne, Bez priorytetu, Przyjmujemy). Nagłówek grupy: poziom, nazwa,
  „N po terminie · M” (bez „0 po terminie”). Karty „Zdjęto Cię…” zostają na
  końcu jak dotąd (`porcja-dnia-minimum-przed-wyszukiwaniem.md`).
- **Grupa poniżej najwyższego poziomu osoby ma „Oddaj N do Nowych”** z oknem
  potwierdzenia (`useConfirmV2`). Przy każdej osobie, także w P0, jest
  „Oddaj do Nowych” bez okna. Najwyższy poziom liczy front z `team_jobs[].group`.
- **Oddanie = ruch karty do „Nowych”** przez `usePipelineMoveCore`, pętla
  pojedynczych ruchów (nigdy `/bulk-move`). Bez odrzucenia, bez nowego
  podejścia: proces zostaje ten sam, karta wraca do stanu „identified”.
  Backend tego nie zmienia, bo już dziś karta, która wróciła do „Nowych”, nie
  jest decyzją (`_decisions`) i nie jest zaległością.
- **Minimum się tym nie nabija:** „Pasuje”, a potem „Oddaj” cofa licznik dnia
  (kopia 24.11: 0 → 1 → 0).
- **Oddana karta zostaje kartą od systemu właściciela z porcji.** Wraca do
  „Do decyzji”, gdy porcja dojdzie do tej rekrutacji: z P0 od razu, z niższych
  dopiero po P0. To zamierzone: wtedy decyzja „Pasuje” / „Nie pasuje”.
- **Komunikaty:** pasek porcji i komunikat blokady wyszukiwania mówią, że
  rekrutację spoza priorytetu oddaje się do „Nowych”, nie odrzuca.
- **Odrzucone warianty:** B — screeningi z niższego priorytetu automatycznie
  bez terminu (karty P1 leżałyby bez końca, a „Pasuje” w P1 nabijałoby
  minimum bez terminu); C — osobny powód odrzucenia „Zmiana priorytetu, bez
  rozmowy” (osoba dalej wypada z rekrutacji). Do B wracamy tylko wtedy, gdy
  rekruterzy dalej odrzucają zamiast oddawać.

Testy: `ReviewBatchReturn.test.tsx`, `ReviewBatchScreen.test.tsx`.
