# Wzmianki „@” w notatkach i czatach (08.10.2026)

Zgłoszenie: „NEXUS nie pozwala oznaczać innych użytkowników”. Serwer zwracał
listy poprawnie; zawodził ekran i stara reguła „tylko zespół”.

- **Oznaczyć można każdą osobę, która może przeczytać to, w czym ją oznaczono**
  — `mention_parser.mentionable_users` (aktywne konto, odczyt danych
  kandydatów, odczyt sekcji). Ta sama funkcja zasila listę
  `GET /api/users/mentionable` i zapis wzmianki (`parse_mentions*`). Do 08.10
  notatka rekrutacji i oba czaty przyjmowały wzmiankę tylko osoby z zespołu
  rekrutacji (reguła sprzed 23.09.2026), a lista ogólna pomijała Head of
  Recruitment i Finanse. `job_id` / `candidate_id` w zapytaniu o listę
  zmieniają już tylko kolejność (zespół pierwszy). Nie wracaj do filtrowania
  po członkostwie.
- **Każde pole notatki i czatu to `MentionTextarea`** (profil, dok osoby,
  notatki warsztatu, oba czaty). Zwykłe `<textarea>` przy notatce = brak
  wzmianek na tym ekranie (tak było w doku osoby na Tablicy).
- **Lista otwiera się po samym „@” i staje tam, gdzie jest miejsce**
  (`lib/mention-autocomplete.ts`: `findMentionToken`, `matchMentionUsers`,
  `choosePopupPlacement`; pomiar z przodków z `overflow`). Do 08.10 zawsze nad
  polem — w profilu pole stoi przy górnej krawędzi karty i lista była ucięta.
  „@” w środku słowa to adres e-mail, nie wzmianka; adres dopasowujemy po
  części przed „@” (domena jest wspólna dla firmy).
- **Do tekstu trafia `@adres` (format parsera), a ekran pokazuje imię
  i nazwisko** (`renderWithMentions` — notatki i wiadomości czatu).
- **Licznik „zespół: N” w czacie pokazuje się dopiero po wczytaniu** — „0
  członków” w trakcie ładowania czytało się jak czat bez nikogo. Zespół to
  osoby, które dostają powiadomienie o każdej wiadomości; pisać i być
  oznaczoną może każda rola wewnętrzna.
