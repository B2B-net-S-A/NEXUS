# „Zweryfikowany” w rekrutacji bez pytań i „Pomiń brakujące” poza przepięciem — raport z wdrożenia

12.10.2026. Reguła: `docs/claude/screening-notatki/rekrutacja-bez-pytan-i-pomin-brakujace.md`.

## Po co

Kilka osób z zespołu zgłosiło, że po przepięciu kandydata do innej rekrutacji nie da się
przesunąć go na „Zweryfikowany”: serwer odpowiadał „Przed „Zweryfikowany” uzupełnij: arkusz
screeningu”, a w formularzu nie było czego uzupełnić.

## Co pokazał pomiar na produkcji (tylko odczyt, przed zmianą)

- Oba zgłoszone przypadki miały tę samą przyczynę: rekrutacja docelowa pochodziła z Traffita
  i nie miała Profilu Championa, czyli miała 0 pytań screeningowych. Bramka wymagała arkusza,
  a arkusz to odpowiedzi na pytania — pola oceny się do niego nie liczyły.
- 33 z 206 otwartych rekrutacji nie miały ani jednego pytania; wszystkie z Traffita, żadna
  z 50 założonych w NEXUSIE (przekazanie do searchu wymaga dwóch pytań).
- W tych 33 rekrutacjach przed „Zweryfikowany” stało 311 osób, 134 ruszane w ostatnich
  14 dniach (22 rekrutacje, 13 osób z zespołu).
- Od rana 12.10: 30 przejść na „Zweryfikowany” w rekrutacjach z pytaniami, 0 w rekrutacjach
  bez pytań.
- „Pomiń brakujące” było dostępne tylko po przepięciu z panelu „Podobne rekrutacje”. Od 05.10
  osoby dodano ręcznie 152 razy: 56 miało już arkusz w innej rekrutacji, 9 było zatrudnionych
  gdzie indziej (panel nie pozwala wybrać zatrudnionych w rekrutacji źródłowej).

## Co weszło

- **Bramka i okno „Przesuń dalej”** — jedna reguła `move_requirements.screening_requirement`:
  rekrutacja z pytaniami wymaga arkusza (albo odpowiedzi w notatce) jak dotąd; rekrutacja bez
  pytań wymaga „Dlaczego ten kandydat”. Fakty pary dostały `has_screening_questions`
  i `card_recommendation`. Stawka kandydata jest wymagana w obu przypadkach. Ocena podlega
  temu samemu oknu próby co arkusz: wpis z próby zamkniętej ponad 30 dni temu nie otwiera
  bramki osobie wracającej z „Zamkniętych” (znalezione w przeglądzie kodu).
- **Komunikaty** — odmowa 409 w rekrutacji bez pytań nazywa pole i powód (klucz braku
  `why_candidate`); okno „Przesuń dalej” pokazuje „Dlaczego ten kandydat” z przyciskiem
  „Uzupełnij w screeningu”; pusty stan sekcji pytań w formularzu mówi, co wystarcza do ruchu
  dalej (wcześniej odsyłał do roli, której już nie ma).
- **Formularz** — „Zapisz i przekaż dalej” w rekrutacji bez pytań zatrzymuje się na pustym
  „Dlaczego ten kandydat”: błąd pod polem, kursor w polu, komunikat. Błąd znika po wpisaniu
  treści.
- **„Pomiń brakujące”** — trasa kontekstu oddaje `skip_reason`: przepięcie, wcześniejsza
  rozmowa screeningowa w innej rekrutacji albo osoba zatrudniona przez nas (etap „Zatrudniony”
  w innej rekrutacji albo trwający kontrakt). Pole wyboru ma napis zależny od powodu. Osoba
  zatrudniona bez wcześniejszych rozmów dostaje samo pole wyboru — Luna nie jest wtedy wołana.
  Domyślna notatka wewnętrzna i znacznik przy pominiętym pytaniu mówią prawdziwy powód
  (znalezione w przeglądzie kodu: zapisywałaby się „Pominięte — przepięcie” także przy osobie
  zatrudnionej); etykieta w historii zmian to „Notatka wewnętrzna (pominięte pytania)”.
- **Przewodniki Jarvisa** — „Tablica” i „Karta kandydata” opisują nową regułę; stemple
  odświeżone.
- **Podgląd** — `/preview/screening-form` ma stany `noquestions` i `employed`.

## Weryfikacja

| Część | Stan | Dowód |
|---|---|---|
| Reguła bramki (bez bazy) | zielone | `tests/test_move_requirements.py` + `test_move_requirements_deal_breaker.py`: 40 testów; 6 nowych pada na regule sprzed zmiany (sprawdzone podmianą reguły) |
| Stemple, indeks reguł, reguły formularza | zielone | `test_screen_guides_freshness.py`, `test_claude_md_index.py`, `test_screening_form_rules.py`: razem z poprzednim wierszem 141 testów; `check_stamps.py` i `build_claude_index.py --check` kod 0 |
| Backend: lint | zielone | `ruff check` i `ruff format --check` na 10 zmienionych plikach |
| Backend: testy z bazą | w CI | `tests/test_verified_gate.py` (rekrutacja bez pytań), `test_screening_reassign.py` (cztery przypadki `skip_reason`), `test_process_entry_and_screening_attempt.py` (ocena sprzed roku nie przepuszcza) — lokalnie nie ma Postgresa |
| Front | zielone | `npx vitest run` na 7 plikach, 170 testów (formularz, reguły formularza, wcześniejsze odpowiedzi, hooki ruchu karty, zasiew podglądów); `npm run type-check` kod 0; `eslint` na zmienionych plikach kod 0 |
| Podgląd przy 1280 × 720 | przeklikane | `?state=noquestions`: pusty stan, odmowa z kursorem w polu, błąd znika po wpisaniu; `?state=employed`: blok „zatrudniona przez nas”, pole wyboru, licznik pominiętych pytań, notatka wewnętrzna; konsola bez błędów |
| Przegląd kodu (tylko blokery) | dwa blokery, oba poprawione | niezależny przegląd diffu: okno próby dla oceny i fałszywy powód w domyślnej notatce pominięcia — poprawki i testy w tym PR-ze |
| Produkcja po wdrożeniu | potwierdzone 13.10.2026 | `/api/health` zgłasza SHA scalenia; odczyt bazy: obie zgłoszone pary mają 0 pytań, otwarty proces, wpisane „Dlaczego ten kandydat” i stawkę — spełniają nową regułę. Samego ruchu na produkcji nie wykonywano |

## Skutki uboczne, zamierzone

- W rekrutacjach bez pytań da się przejść na „Zweryfikowany” z samą oceną i stawką — Delivery
  Lead dostaje wtedy osobę bez odpowiedzi na pytania, bo pytań nie zadał.
- Rekruter może pominąć pytania przy osobie po wcześniejszym screeningu albo zatrudnionej przez
  nas; pominięte odpowiedzi i notatka wewnętrzna są widoczne dla zespołu i nie idą do klienta.

## Dopisek 13.10.2026 — napis na karcie Tablicy i w „Czeka na Ciebie”

Po wdrożeniu bramki karta w „Screeningu” i kolejka dalej pisały o arkuszu, którego w rekrutacji
bez pytań nie ma. Osobny PR:

- **Karta Tablicy** — w rekrutacji bez pytań niesie `screening_requirement: "why_candidate"`,
  a `screening_done` znaczy „ocena wpisana” (ta sama reguła co bramka, liczona z podsumowań kart,
  które Tablica już wczytuje). Krok: „Wpisz „Dlaczego ten kandydat”” (skrót na karcie „Wpisz
  ocenę”), po wpisaniu „Zweryfikuj i przenieś dalej”; podpowiedź strzałki „Brak „Dlaczego ten
  kandydat””. Ten sam krok widzi „Twoje najbliższe kroki” na pulpicie.
- **„Czeka na Ciebie”** — sekcja „Screening — brakuje danych” pokazuje plakietkę „Dlaczego ten
  kandydat” zamiast „arkusz”; osoba z wpisaną oceną ma już tylko brak stawki. Poranny skrót
  mailem czyta te same wiersze i pisze „brak „Dlaczego ten kandydat”” (znalezione w przeglądzie
  kodu: bez wpisu w jego mapie etykiet mail wypisałby surowy klucz).
- **Rekrutacje z pytaniami** — bez zmian w obu miejscach.

| Część | Stan | Dowód |
|---|---|---|
| Reguła karty, zgodność front ↔ serwer i poranny skrót (bez bazy) | zielone | `tests/test_move_requirements.py`, `tests/test_next_action_parity.py`, `tests/test_team_email_notifications.py`: 162 testy; nowe przypadki padały przed zmianą kodu |
| Front | zielone | `npx vitest run` na 38 plikach dotykających zmienionych modułów: 1022 testy; `npm run type-check` i `eslint` kod 0 |
| Przegląd kodu (tylko blokery) | jeden bloker, poprawiony | poranny skrót mailem nie znał nowego klucza braku — etykieta i test w tym PR-ze |
| Podgląd przy 1280 × 720 | przeklikane | `/preview/pipeline-v4?questions=none`: karta bez oceny „Wpisz ocenę”, z oceną „Zweryfikuj”; `/preview/custom-dashboard?as=recruiter`: plakietka w kolejce, bez poziomego przewijania także przy 390 px |
| Testy z bazą | w CI | `tests/test_board_flow.py` (kolejka w rekrutacji bez pytań), `tests/test_pipeline_integrity.py` (karta Tablicy) |

## Poza zakresem

- Opis kolumny „Screening” na Tablicy („Arkusz pytań z…”) jest stały dla każdej rekrutacji.
- Arkusz z samymi sprawdzeniami doświadczenia zapisuje się, ale bramki nie spełnia.
- „Zapisz i przekaż dalej” wymaga odpowiedzi na wszystkie pytania, serwerowi wystarcza jedna.
- Odpowiedzi z notatki (`card_answers`) nie mają okna próby zamkniętej dawno temu — stan sprzed
  zmiany, ta sama luka co naprawiona tu dla oceny.
- Uzupełnienie Profilu Championa w 33 rekrutacjach z Traffita — praca Delivery Leadów, nie kod.
