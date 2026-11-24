# Rozliczenia: Time Sheet z pustym polem osoby — imię i nazwisko z nazwy pliku

<!-- indeks: proof.name_match, Time Sheet bez pola Consultant(s), puste Consultant(s), Print Name, osoba z nazwy pliku, Imię i nazwisko z nazwy pliku jak w kontrakcie, timesheet.evaluate file_name, _file_words, CpDocument.file_name, metadane Excela, lastModifiedBy, VeloBank szablon Time Sheet -->

Od 24.11.2026 (decyzja Artura). Jedna osoba z VeloBanku wysyła nasz szablon „Time Sheet”
z pustymi polami „Consultant(s)” i „Print Name”. Imię i nazwisko stoi tylko w nazwie pliku
(„<Imię Nazwisko> - Time Sheet - wrzesień 2026.xlsx”) i w metadanych Excela. Kontrola
`proof.name_match` („Nazwisko na RCP i fakturze takie jak w kontrakcie”) dawała wtedy uwagę
„Time Sheet bez pola Consultant(s)”. W próbie IX–X 2026 była to jedyna uwaga tej osoby za
oba miesiące, choć MD zgadzały się z arkuszem zbiorczym podpisanym przez klienta. Przez nią
rozliczenie nie przechodziło samo.

## Reguła (`timesheet.evaluate`, parametr `file_name`)

- Wypełnione pole osoby wygrywa z nazwą pliku. Inna osoba w polu daje „Inne imię lub nazwisko
  niż w kontrakcie”, nawet gdy nazwa pliku wskazuje osobę z kontraktu.
- Przy pustym polu kontrola patrzy na nazwę pliku (`CpDocument.file_name`: nazwa załącznika
  maila albo pliku z panelu konsultanta). Gdy stoją w niej wszystkie słowa imienia i nazwiska
  z kontraktu, a jest ich co najmniej dwa, kontrola jest zielona: „Imię i nazwisko z nazwy
  pliku jak w kontrakcie”. Wielkość liter i polskie znaki nie mają znaczenia, a „_”, „-”
  i kropki rozdzielają słowa (`_file_words`, `rcp_checks.name_tokens`).
- W pozostałych przypadkach uwaga „Time Sheet bez pola Consultant(s)” zostaje: gdy w nazwie
  pliku jest samo nazwisko, inna osoba albo nikt. Dopisek mówi wtedy, że nazwa pliku też nie
  ma imienia i nazwiska z kontraktu. Nazwisko po zmianie („Nowe (Stare)”) musi stać w nazwie
  pliku w obu wersjach, inaczej uwaga też zostaje.
- Metadanych Excela (autor, „ostatnio zmodyfikowany przez”) nie czytamy. Szablon niesie
  autora wzoru, a plik zapisuje też ktoś inny niż konsultant.
- Odrzucony wariant: osoba z arkusza zbiorczego podpisanego przez klienta. Arkusz potwierdza
  MD osoby, a nie to, że plik Time Sheet jest jej. Działałby też tylko u klientów z arkuszem.

## Pomiar (kopia produkcji z nocy 23/24.11 po przebiegu poczty rozliczeń 01.09–20.11)

Wszystkie 368 rozliczeń IX–X przeliczone kodem przed zmianą i po niej, za każdym razem
w transakcji wycofanej na końcu:

- Zmieniły się dwa: ta osoba za IX i za X. Oba przeszły z „uwagi” na „ok” przy niezmienionych
  MD (20 i 21, tyle co w arkuszu podpisanym przez klienta). Pozostałe 366 bez zmian.
- 102 rozliczenia IX–X z Time Sheet mają osobę w polu, więc nazwa pliku ich nie dotyczy.
- Na całej kopii (VIII–XI) uwagę „bez pola Consultant(s)” miały tylko te dwa rozliczenia na
  143 z Time Sheet. Żadna z 143 nazw plików nie wskazuje innej osoby z kontraktem.
