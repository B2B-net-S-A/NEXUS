# Przydziały i zastępstwa COMPASS

Nowe przekazanie może wskazywać osobę ręcznie lub wejść do kolejki automatycznej.
Automat porównuje kolejno aktywne poszukiwania, zaległe zadania, zadania na dziś,
procesy kandydatów; następnie kompetencję, ostatni przydział i ID. Przydział i
prowadzący powstają w jednej transakcji chronionej blokadą PostgreSQL. Kolejka
sortuje priorytet, termin, czas oczekiwania i ID. Dotychczasowi prowadzący zostają.

Pozycje są liczbami dodatnimi bez limitu; pierwszych pięć zachowuje aliasy A–E.
Faworyt pauzuje tylko poszukiwania, gdy pokrywa ostatnie wolne miejsce. Odrzucenie
lub wycofanie wznawia szukanie u tej samej osoby. Ręczna pauza ma osobny stan.

## Dane i wykonawca

`COMPASS_AVAILABILITY_URL=https://compass.dynaminds.pl/api/internal/availability`.
Dedykowany bearer `COMPASS_AVAILABILITY_SECRET` odpowiada
`AVAILABILITY_EXPORT_SECRET` w COMPASS. Nie wpisywać sekretu do workflow inputs,
logów ani repozytorium. Eksport nie zawiera przyczyn urlopu ani dokumentów.

Pełny odczyt następuje co 60 sekund. Po 300 sekundach bez poprawnych danych nowe
przydziały są zatrzymane. Ostatnie poprawne zastępstwo trwa do zapisanego końca.
Mapowanie używa jednoznacznego znormalizowanego emaila aktywnego konta. Konflikt,
brak konta, niewłaściwe uprawnienia albo nieobecny zastępca wymagają korekty
przez kierownika. Obsługiwane są bezpośrednie zastępstwa, pełne dni i kalendarz
pracy Warszawy; pół dnia ani logowanie do aplikacji nie zmienia dostępności.

Otwarte zadania mają właściciela i wyliczanego wykonawcę. Obejmuje to przydziały,
procesy kandydatów, wszystkie strony kolejek kontaktów, oddzwonienia, kalendarz,
przypomnienia i przypisane checklisty onboardingu. Kolejki zachowują swoje sloty;
przejęte kontakty nie są przenoszone do 20 slotów zastępcy. Nowe zadania utworzone
w kontekście zastępowanej sprawy wracają do jej właściciela. Autor działania,
organizator spotkania i kredyt wyniku pozostają zapisani niezależnie.

## Uruchomienie

1. Wdrożyć COMPASS PR373 i migrację RPC, sprawdzić wersję health i uprawnienia
   eksportu (service_role; odrzucenie anonimowego wywołania).
2. Skonfigurować sekret i URL w obu istniejących vaultach Coolify. Workflow
   `Configure COMPASS availability`, `stage=export`, zaczyna się od `dry_run=true`.
   Wymaga dostępu tokena NEXUS do obu aplikacji na main. Przy braku lub wielu
   dopasowaniach kończy się bez zapisu; wtedy użyć właściwych paneli aplikacji.
   Istniejących niezgodnych sekretów nie obraca automatycznie.
3. Wdrożyć NEXUS. Migracja i identyczny krok startowy zapewniają tabele, pozycje,
   trigger kompatybilności oraz indeksy. Sprawdzić health/deep i health/alembic.
4. Ustawić `COMPASS_AVAILABILITY_ENABLED=true` i
   `RECRUITMENT_ALLOCATION_ENABLED=true` (workflow `stage=consumer`). Początkowy
   tryb w bazie to `shadow`: kolejka pokazuje propozycje bez zmiany prowadzących.
5. Na ekranie zespołu sprawdzić świeżość, mapowanie, wyjątki i uzasadnienia.
   Po weryfikacji kierownik wybiera `Automatyczny` dla nowych przekazań.

Przełącznik `off` na ekranie zespołu zatrzymuje automatyczne przydziały bez
wyłączania ręcznej pracy, zastępstw i historii. Brak źródła nie kasuje ostatniej
poprawnej migawki. Zmiany zadań zapisują zdarzenia w tej samej transakcji;
pętla uzgadnia stan co 30 sekund, również po imporcie omijającym ORM. Obliczanie
istniejącego rankingu kandydatów po automatycznym przekazaniu ma trwałą kolejkę,
ponowienia i dziesięciominutową dzierżawę.

Rollback operacyjny: wyłączyć automat. Downgrade schematu celowo odmawia przy
pozycjach ponad pięć lub danych niezgodnych z dawnym ograniczeniem D/E. Nie
przepisywać istniejącego portfela ani nie usuwać danych do testów produkcyjnych.

## Weryfikacja

Hostowe testy jednostkowe obejmują kolejność, remisy, kompetencje, brak limitu,
faworytów, dostępność i konflikty. CI na PostgreSQL sprawdza rzeczywistą blokadę
równoczesnych przydziałów, 24 kontakty z dwóch kolejek, nowe i istniejące zadania,
powrót właściciela, zakres uprawnień oraz trwałość zdarzeń po rollbacku/błędzie.
Testy React sprawdzają nowe pola zespołu, błędy synchronizacji i wyłącznik.
Produkcję weryfikować w Chrome dla widoków kierownika i pracy własnej; formularze
można obejrzeć i zamknąć bez tworzenia fikcyjnych danych kandydatów.
