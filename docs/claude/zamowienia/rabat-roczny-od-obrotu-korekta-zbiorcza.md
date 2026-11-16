# Rabat od obrotu rocznego klienta: pozycja na każdej fakturze, wyższa stawka od nadwyżki (16.11.2026)

Zgłoszenie Artura 16.11.2026: faktury Nordei nie uwzględniają rabatu 2,5%, a po przekroczeniu progu
obrotu stawka rośnie do 3%. Umowa ramowa (Appendix 6, aneks od 01.03.2026) liczy rabat od rocznego
obrotu za usługi (1.01–31.12) z progiem w EUR. Kwot, progów i stawek nie ma w repo, bo repo jest
publiczne. Wpisują je Finanse w ustawieniach.

## Decyzje Artura (16.11.2026)

Umowa przewiduje roczną notę do 31.01. Artur ustalił inną praktykę i ona obowiązuje. Pierwsza odpowiedź
z tego dnia („korekta roczna”, „3% od całego obrotu”) została zastąpiona drugą, opisaną niżej.

- **Rabat to pozycja na każdej fakturze miesięcznej.** Ujemna pozycja „Rabat od obrotu rocznego X%”,
  osobna dla każdej stawki VAT na fakturze.
- **Stawka pochodzi z obrotu sprzed miesiąca faktury.** Faktury za miesiąc M mają stawkę progu, w którym
  jest narastający obrót roku do końca miesiąca M−1. Faktury za miesiąc, w którym obrót przekroczył
  próg, idą jeszcze po niższej stawce. Wyższa stawka obowiązuje od następnego miesiąca.
- **Wyższa stawka dotyczy tylko nadwyżki ponad próg**, nie całego obrotu.
- **Za miesiąc przekroczenia trzeba wystawić korektę.** Wynosi ona różnicę stawek (np. 0,5%) od części
  obrotu tego miesiąca ponad próg. NEXUS pokazuje jej kwotę na karcie faktury. Do KSeF wysyłamy ją
  tylko po „tak” Artura.
- **Próg w EUR liczymy po kursie NBP z każdej faktury.** Bierzemy średni kurs z ostatniej tabeli przed
  datą sprzedaży. Gdy kursu brak, faktura wypada z obrotu progu i karta ostrzega. Kursu 1:1 nie
  stosujemy nigdy.
- **Podróże i faktury nieusługowe nie wchodzą ani do obrotu, ani do bazy rabatu.**

## Jak to działa w kodzie

- Warunki zapisane są w `app_settings['client_invoice_issue'].clients[<id>].rebate`. Finanse wpisują je
  w Ustawieniach wystawiania, w sekcji „Rabat roczny od obrotu” przy kliencie:
  - waluta progu;
  - okresy „od roku” z progami (górna granica włącznie, ostatni próg bez granicy, stawka w %);
  - słowa wyłączające: pozycja z takim słowem w nazwie wypada z obrotu i z bazy rabatu.

  Zapis ze złymi warunkami kończy się odmową z komunikatem. Złe dane w bazie odpadają przy odczycie
  z wpisem w logu.
- Obrót to faktury sprzedaży z KSeF (`client_sales_invoices`) za miesiące roku. Miesiąc wyznacza okres
  usługi, a gdy go brak, data wystawienia. Korekty wchodzą jako różnica stanów. Pozycje rabatu
  (`REBATE_PREFIX`) i pozycje wyłączone nie są liczone.
- `issue.apply_rebate` dokłada pozycję rabatu do szkiców z „Wystaw za miesiąc”. Po edycji pozycji
  przelicza jej kwotę. Pozycji usuniętej ręcznie nie dokłada z powrotem. Rozpoznaje ją po nazwie
  (`rebate.is_rebate_line`), więc nie zmieniaj początku nazwy „Rabat od obrotu”.
- Karta faktury (`rebate` w `GET /api/finance/issued-invoices/{id}`, ramka „Rabat od obrotu”) pokazuje:
  - stawkę;
  - obrót do końca poprzedniego miesiąca;
  - obrót z tą fakturą;
  - licznik do progu;
  - kwotę pozycji;
  - korekty za miesiące przekroczenia.

  Brak pozycji u klienta z rabatem to ostrzeżenie.
- Porównanie faktury z zamówieniem („Do faktury”, `ledger.check`, dopasowanie po kwocie) idzie po
  `Chain.order_net`, czyli netto bez pozycji rabatu. Rabat obniża fakturę, a nie zamówienie, więc bez tego
  każdy wiersz klienta z rabatem pokazywałby różnicę. Do zapłaty i sumy liczą się z rabatem.
- Kod: `services/client_invoicing/rebate.py`, `issue.apply_rebate`, `issue_settings.client_rebate`.

## Czego jeszcze nie ma

- Szkicu faktury korygującej za miesiąc przekroczenia. Korekta obejmuje wiele faktur z tego miesiąca,
  a NEXUS koryguje dziś pojedynczą fakturę wystawioną w NEXUSIE. Kwotę bierze się z karty.
- Obrotu sprzed 4.08.2026: NEXUS czyta KSeF od tego dnia. Faktury ze stycznia–lipca 2026 trzeba
  dograć z archiwum eBI24, inaczej licznik do progu jest zaniżony.
