# Rabat roczny od obrotu klienta: dane przy kliencie, rozliczenie zbiorczą korektą (16.11.2026)

Zgłoszenie Artura 16.11.2026: faktury Nordei „nie uwzględniają rabatu”. Umowa ramowa Nordei (Appendix 6,
w wersji pierwotnej i z aneksem obowiązującym od 01.03.2026) przewiduje rabat od rocznego obrotu za usługi,
rozliczany raz w roku notą kredytową do 31 stycznia następnego roku. Aneks wprowadził dwa progi w EUR
w miejsce jednej stawki. Kwoty, progi i stawki są w umowie i w ustawieniach. W repo ich nie ma,
bo repo jest publiczne.

## Decyzje Artura (16.11.2026, AskUserQuestion)

- **Forma: korekta roczna.** Faktury miesięczne zostają bez pozycji rabatu, tak jak w umowie. NEXUS liczy
  stan rabatu narastająco i pokazuje go na karcie faktury. Rabat za rok rozlicza jedna zbiorcza faktura
  korygująca (rabat posprzedażowy), wystawiona do 31.01 następnego roku. Ujemnej pozycji „Rabat”
  na fakturach nie dodawaj, bo to inne rozliczenie niż w umowie i wymagałoby zgody klienta na piśmie.
- **Stawka od całego obrotu.** Stawka progu, w który wpada obrót roku, dotyczy całego obrotu, a nie tylko
  nadwyżki ponad próg. Obrót równy granicy progu zostaje w tym progu.
- **Nowe progi obowiązują przez cały rok wejścia aneksu.** Rabat liczy się raz za rok, więc rozstrzyga
  reguła obowiązująca na koniec roku. Dla 2026 progi z aneksu dotyczą obrotu od 1 stycznia, także
  stycznia i lutego.
- **Kurs NBP z każdej faktury.** Gdy próg jest w innej walucie niż faktura, każdą fakturę przelicza się
  po średnim kursie NBP z ostatniej tabeli przed datą sprzedaży. Rabat liczy się w walucie faktur.
  Brak kursu oznacza fakturę poza obrotem progu i ostrzeżenie na karcie. Nigdy nie licz kursu 1:1.
- **Wystawione faktury bez rabatu zostają.** Nie koryguj każdej faktury osobno. Rozliczenie idzie jedną
  zbiorczą korektą za rok. Wysyłka korekty do KSeF na produkcji wymaga osobnego „tak” Artura.

## Jak to działa w kodzie

- Warunki to dane w `app_settings['client_invoice_issue'].clients[<id>].rebate`. Wpisują je Finanse
  w Ustawieniach wystawiania („Rabat roczny od obrotu” przy kliencie):
  - waluta progu;
  - okresy „od roku” z progami: górna granica włącznie, ostatni próg bez granicy, stawka w %;
  - słowa wyłączające: faktura, której każda pozycja zawiera takie słowo (podróże, refaktury), jest poza
    obrotem, bo umowa wyłącza koszty podróży i faktury nieusługowe.

  Zapis sprawdza warunki i odmawia z komunikatem. Złe dane w bazie przy odczycie odpadają z logiem, żeby
  nie zatrzymać wystawiania. Kod: `services/client_invoicing/rebate.py`, `issue_settings.client_rebate`.
- Obrót to faktury sprzedaży z KSeF (`client_sales_invoices`) klienta wystawione w roku kalendarzowym,
  razem z korektami, czyli tak samo jak w raporcie „Rabat od obrotu rocznego” z katalogu raportów.
  Szkic z NEXUSA (jeszcze nie w KSeF) dolicza się do stanu na swojej karcie.
- Karta faktury (`GET /api/finance/issued-invoices/{id}` → `rebate`, ramka „Rabat roczny” na
  `/finance/faktury/{id}`) pokazuje:
  - obrót od 1 stycznia w walucie progu;
  - bieżącą stawkę i brakującą kwotę do następnego progu;
  - rabat narastająco w walucie faktur;
  - udział tej faktury;
  - termin korekty.

  Ramka nie zmienia pozycji, sum ani XML-a faktury.
- Nowe progi od roku dodaje się przyciskiem „Nowe progi od roku (aneks)”. Starszy okres zostaje dla lat
  wcześniejszych.

## Czego jeszcze nie ma

- Szkicu zbiorczej faktury korygującej za rok z listą faktur korygowanych w FA(3) (do 31.01.2027 za 2026).
  To osobne zadanie. Do tego czasu kwotę bierze się z ramki na karcie albo z raportu w katalogu.
- Obrotu sprzed 4.08.2026: NEXUS czyta KSeF od tego dnia. Faktury ze stycznia–lipca 2026 trzeba
  dograć z archiwum eBI24, zanim policzy się rabat za 2026.
