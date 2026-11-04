# Nazwy w „Ludziach”: Koordynacja, Do potwierdzenia, Rozliczenia, Moja współpraca
<!-- indeks: słownik nazw z 03.11.2026, tylko słowa bez zmian funkcji, wyjątki UoP, strażnik test_hr_visible_names, folder „Umowy pracowników”, aplikacja „NEXUS Kadry”, etap „Zatrudniony” -->

Decyzja Artura z 03.11.2026, po uwadze Head of Recruitment o oknie „Ustaw”.
Zmieniliśmy same słowa. Funkcje, uprawnienia, dane i API działają jak wcześniej.
Klucze techniczne zostają po angielsku (`/people/team`, `payroll`, `people_admin`,
`timesheet`, `manager_user_id`). Rozszerza regułę o słowach na ekranach wielu osób
z `ludzie/modul-ludzie-dostep-schemat-i-przelaczenie.md`.

## Słownik

| Było | Jest |
|---|---|
| Przełożony | Koordynator |
| Mój zespół (ekran) | Koordynacja |
| Mój zespół (chip i wybór) | Moje osoby |
| Akceptacje, Do Twojej decyzji, Do decyzji, Akceptuj | Do potwierdzenia, Potwierdź |
| Zdecydowane | Załatwione |
| Zgłoś kolizję | Zgłoś uwagę |
| Płace | Rozliczenia |
| Kadry | Administracja współpracy |
| Mój czas | Moja współpraca |
| Timesheet | Raport godzin |
| Brakuje 2 dni, termin minął | Bez wpisu 2 dni, do wysłania |
| Uzupełnij dzień | Dodaj godziny |
| Do końca dnia pracy, Poniżej tempa | Do końca dnia, Poniżej planu |
| Na daily | Przegląd requestów |
| P0 ultrapilne teraz | Pilne u klientów |
| Rytm dnia, Za mało pracy | Aktywność w NEXUSIE, Niska aktywność |

„Administracja współpracy” jest w liczbie pojedynczej, więc „widzi”, „ustawi”,
„poproś Administrację współpracy”. Bez tej odmiany wychodzą błędy typu
„Administracja współpracy widzą”.

## Co zostaje po staremu

- **Umowa o pracę:** słowa ze słownika form (`hr-employment-terms`,
  `services/hr/employment_terms.py`). Osoba na UoP dalej ma przełożonego, urlop,
  wniosek, ewidencję czasu pracy i listę płac.
- **Nazwy spoza NEXUSA:** aplikacja „NEXUS Kadry” w Entra ID i folder „Umowy
  pracowników” w SharePoincie. Tak nazywają się tam, zmiana wymagałaby zmian poza kodem.
- **Klienci i kandydaci:** „Akceptacje” w Insights i przy kliencie to akceptacja
  kandydata przez klienta. Etap „Zatrudniony” też dotyczy kandydata.
  „Akceptuj — do Cpro” w przeglądzie zostaje.
- **Szablony ścieżek w bazie** (`hr_lifecycle_schema.py`), bo ich zmiana wymaga
  migracji, a moduł wejścia i odejścia jest wyłączony. Przed jego włączeniem
  popraw też ich nazwy.

## Pilnowanie

`backend/tests/test_hr_visible_names.py` czyta menu, zakładki, okruszki, przewodniki
Jarvisa i ekran startowy i zgłasza stare słowa. Nowy ekran w „Ludziach” bierze słowa
z tej tabeli albo ze słownika form. Nie wpisuj starych nazw na sztywno.
