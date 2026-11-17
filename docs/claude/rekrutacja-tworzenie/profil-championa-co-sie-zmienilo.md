# „Co się zmieniło” w Profilu Championa: karta, zakładka „Zmiany” i zdanie DL (0730, 17.11.2026)
<!-- indeks: wersje profilu po przekazaniu (champion_profile_revisions), różnica po etykietach wierszy, „Przeczytane” per osoba, zakładka „Zmiany”, okno „Na co klient kładzie nacisk?” po zapisie -->

Pomysł rekruterki 17.11.2026, decyzja Artura tego dnia po dwóch rundach makiet
(https://claude.ai/artifact/An7dHv22qkmMoX95DfNqx1, wariant „A + B” i okno DL).
Do tej daty zapis profilu zostawiał w `activities` tylko wiersz
`champion_profile_updated` bez treści, a dzwonek mówił „zmienił stack
technologiczny”. Rekruter nie wiedział, co wypadło ani na co klient teraz
kładzie nacisk. W kopii stagingu z 16.11 118 z 264 rekrutacji z 60 dni miało
profil zapisany co najmniej dwa razy.

- **Wersja powstaje tylko dla rekrutacji w pracy** (`status = published`, ten sam
  warunek co ochrona przed nowym brakiem w `save_champion_core`) i tylko gdy
  różnica ma coś do pokazania. Szkic, import dokumentu i zapis samych wymagań
  do wyszukiwania w bazie wersji nie robią. Historia zaczyna się od wdrożenia
  0730; starsze zapisy nie mają treści, więc nie da się ich pokazać.
- **Różnicę liczy serwer przy zapisie** (`services/champion_profile_changes.py`,
  `describe_changes`) i zapisuje ją w wierszu razem z `before`/`after`
  (znormalizowane profile, do ponownego policzenia). Wiersze wymagań porównujemy
  po pierwszym słowie, nie po indeksach: usunięcie jednego wiersza przesuwa
  wszystkie następne, a surowa różnica JSON-a dla jednej zmiany miała 70 linii.
  Kolejność wierszy i wielkość liter to nie zmiana. Profil sprzed wierszy
  (same `must`/`nice`/`critical`) czytamy w tym samym kształcie, żeby nie było
  fałszywego „wszystko usunięte, wszystko dodane”. Krytyczność bierzemy też
  z `stack.critical`, bo zapis trzyma tam wybór, a wiersz zostaje na „musi mieć”.
- **„Do dopytania u klienta”**: zamknięcie albo usunięcie otwartego pytania
  (`topic = ask_client`) to jedna pozycja z liczbą i treścią pytań. Inne notatki
  sekcji 8 nie trafiają do zmian, bo to nie zmiana roli.
- **Karta nad Briefem** (`ChampionChangesCard`) pokazuje najnowszą zmianę, której
  dana osoba nie oznaczyła jako przeczytaną, i nie jest autorem. „Przeczytane”
  zapisuje się per osoba (`champion_profile_change_reads`, tylko do przodu)
  i zwija kartę do jednej linii na 14 dni od zmiany. W „Podglądzie jako” stan nie
  zmienia się, jak przy powiadomieniach. Awaria zapytania chowa kartę; błąd
  pokazuje zakładka.
- **Zakładka „Zmiany”** (`?ptab=changes`) pojawia się, gdy profil ma choć jedną
  wersję; licznik = nowe dla tej osoby. Rekruterka chciała móc wrócić do zmian
  po kliknięciu „Przeczytane”, stąd zakładka obok karty, a nie zamiast niej.
- **Zdanie DL po zapisie, nie przed nim.** Odpowiedź `PUT …/champion-profile`
  niesie `change_revision`; edytor wysyła zdarzenie, a `ChampionChangeNoteHost`
  na stronie rekrutacji otwiera okno „Na co klient teraz kładzie nacisk?”
  (szuflada bloku jest już wtedy zamknięta). Okno pokazuje to, co zobaczą
  rekruterzy, i można je pominąć. W makiecie okno było przed zapisem; po zapisie
  różnicę liczy ten sam kod co zapis, bez drugiej ścieżki „na próbę”. Zdanie
  zapisuje `PATCH …/champion-profile/changes/{id}`: tylko autor zmiany albo
  admin, najwyżej 600 znaków. Pole w stopce szuflady z rundy 1 rekruterka
  oceniła jako nieczytelne.
- Trasy: `GET …/champion-profile/changes` i `POST …/changes/seen` mają bramkę
  odczytu Profilu (`OperationalUser` + widoczność DL), `PATCH` — tę samą co
  zapis profilu (`JobEditUser`).
