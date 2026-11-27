# Maile CPro od Nordei zmieniają statusy w NEXUSIE (02.11.2026)
<!-- indeks: `noreply@onevms.se`, `services/cpro_mail.py`, pętla `cpro_mail`, dziennik `/settings/cpro`, zamknięcie i odrzucenie z maila, Authentication-Results -->

CPro (`nordea.onevms.se`) to system Nordei do zamawiania konsultantów. Wysyła
Delivery Leadom maile z `noreply@onevms.se`, a numer w tytule to
`jobs.client_reference`. Pomiar 12.10–02.11.2026 w skrzynkach obu DL-i: 334
maile, 24 rekrutacje zamknięte ręcznie po mailu (16 w ciągu 15 minut), 2 otwarte
dalej mimo zamknięcia w CPro, 40 ze 115 odrzuconych przez klienta nadal „w toku”.
Makiety: https://claude.ai/artifact/NDLBxLTB1GZZpWMQst5Hnk.

## Decyzje Artura (02.11.2026)

- **Zamknięty request:** NEXUS zamyka wszystkie otwarte rekrutacje z tym numerem.
  „consultant contracted” → `competitor`, „demand change” → `budget`, reszta →
  `other` (wtedy trafia do przeglądu zamknięć). Autor pusty, notatka z powodem.
- **Odrzucenie:** karta do „Zamknięci”, `ended_by="client"`, „Candidate withdrew”
  jako rezygnacja. **Kandydat nie dostaje nic**, prowadzący dostaje dzwonek
  i „Napisz do kandydata”. Karta przesunięta po mailu zostaje na miejscu.
- **Wiadomość przy zamknięciu:** dzwonek i mail do każdego rekrutera z kartą
  w toku, także w „Nowych” (`notify_closed_from_cpro`). To wyjątek od reguły
  „automaty nie piszą do rekruterów” z `rekrutacja-tablica/zamkniecie-rekrutacji-osoby-w-toku.md`.
- **Start od razu, bez okresu próbnego;** zaległości od `CPRO_MAIL_SINCE` (12.10)
  automat nadrabia w pierwszym przebiegu, także 42280 i 42693.

## Reguły, które łatwo cofnąć

- **Osoba w „Akceptacji i umowie” albo zatrudniona zatrzymuje zamknięcie.**
  Automat pyta DL-a dzwonkiem `cpro_close_needs_decision`. Cztery rekrutacje
  wygrane przez nas nie miały maila o zamknięciu, więc „consultant contracted”
  to zwykle cudza osoba, ale automat nie wpisze przegranej przy naszej umowie.
- **Prośba o rozmowę, wycofanie, zmiana terminów = tylko dzwonek.** Mail nie
  podaje terminów, są wyłącznie w CPro. Mail starszy niż 2 dni nie dzwoni.
- **Nadawca jest sprawdzany przy każdym mailu** (`verify_with_graph`): adres,
  `Authentication-Results` (`sender_authenticated`) i link do `nordea.onevms.se`.
  Domena ma DMARC `p=none`, więc nikt inny nie odrzuci podszytego maila; samo pole
  „Od” nie wystarcza. Brak potwierdzenia = wiersz „Do ręcznego”, zero zmian.
  Treść bierzemy z Grapha, bo `emails` bywa puste.
  Wiersz odmowy jest ostateczny: gdyby kontrola okazała się za ostra, po poprawce
  usuń z `cpro_mail_events` wiersze „Nie potwierdzono nadawcy…” i kolejny przebieg
  przeczyta te maile jeszcze raz.
- **Numeru nie zgadujemy.** Brak numeru w NEXUSIE albo osoby w rekrutacji =
  „Do ręcznego”. 42845 i 42846 to dwa requesty, a w NEXUSIE jest tylko 42846:
  mail o 42845 nie może zamknąć 42846.
- **Stary mail nie zamyka rekrutacji otwartej ponownie** po jego dacie.
- **Jeden mail = jeden wiersz** `cpro_mail_events` (klucz `internetMessageId`),
  więc kopia w drugiej skrzynce i restart niczego nie powtarzają.
- Automat nie obsługuje: `Offer:`, `Re:`, nowych zapytań `Request:`. Temat spoza
  `SUBJECT_FILTER` nic nie zmienia.

## Robot widzi zamknięty request: NEXUS zamyka rekrutację (27.11.2026)

CPro **nie wysyła maila o zamknięciu requestu, który wygrała nasza osoba**
(oferta CONTRACTED). 27.11 rekrutacja z dwiema osobami w „Zatrudnionych”
została przez to „published”. Ludzie dalej trafiali z niej do „Do Cpro”,
a robot osiem razy skończył ich karty wynikiem `failed/request_closed`.
W CPro request miał status CLOSED i baner „The Requisition is not Active”.

Decyzja Artura z 27.11.2026: gdy robot zobaczy zamknięty request, NEXUS sam
zamyka rekrutację (`cpro_mail.close_from_robot`, wołane z
`cpro_bot/ingest.apply_report`).

- Zamyka wszystkie otwarte rekrutacje z tym numerem requestu, tą samą ścieżką
  co mail: `close_job_core` i dzwonek do rekruterów (`notify_closed_from_cpro`).
- **Powód:** jeśli ktoś jest w „Zatrudnionych”, to `filled_by_us`; w każdym innym
  przypadku `other`, bo robot nie zna powodu z CPro i rekrutacja trafia do przeglądu
  zamknięć. Osoba w „Umowie” tu nie zatrzymuje zamknięcia (inaczej niż przy mailu),
  bo strona CPro pokazuje stan bieżący, a nie stary mail.
- **Rekrutacji, którą ktoś już kiedyś zamknął i otworzył ponownie ręcznie, robot
  nie zamyka.** Robot zagląda do CPro co kilka minut, więc nie może walczyć
  z decyzją człowieka.
- Obowiązuje ten sam wyłącznik reguły „closed” w `/settings/cpro`. Wpisu w
  dzienniku maili nie ma; ślad zostaje w `activities` (notatka „robot zobaczył…”)
  i w logu `cpro_bot … closed_request`.

## Zmiany w kontrakcie: nowy adres faktury (24.11.2026)

„Important changes made to contract N — Please update your invoice reference details”
CPro wysyła DL-owi przypisanemu do kontraktu. **N to numer Call-Off, czyli tytuł zamówienia
Nordei** (`client_orders.title`; na kopii produkcji 12 z 12 numerów), a nie numer requestu.
Treść to linie `<Pole> was updated from: X, to: Y` (w `emails.body_text` sklejone bez `<br>`),
daty zmiany w mailu nie ma — liczy się data maila w kalendarzu firmy.

Decyzje Artura z 24.11.2026 (przegląd skrzynek DL-ów: zmiana z 15.09 F218 Abp S.A. → F206
Abp Finland przyszła tylko do PM-a i nie dotarła do rozliczeń):

- **„Invoice address was updated … to: F206 …” → nabywca kontraktu od miesiąca maila**
  (`services/cpro_invoice_buyer.py`, reguła `invoice_address` w `/settings/cpro`). NEXUS
  szuka nabywcy klienta z tym „Kodem w CPro” (ustawienia wystawiania → Nabywcy per kontrakt),
  dopisuje go w `contract_buyers` od `RRRR-MM` maila i dzwoni do Finansów
  (`cpro_invoice_buyer`, migracja 0766) z listą faktur od tego miesiąca na innego nabywcę
  i liczbą szkiców do poprawy. Dzwonek idzie też **mailem od razu** (rodzaj
  `cpro_invoice_buyer`, obowiązkowy): typ nie ma ikony na pasku, więc bez maila osoba
  offline zobaczyłaby tylko chwilowy dymek.
- **Faktur NEXUS nie zmienia.** Korekta albo refaktura to decyzja Finansów.
- **Kodu nie zgadujemy po nazwie** („Abp S.A.” i „Abp Finland” mają wspólny początek).
  Kod spoza listy, adres faktury bez czytelnego kodu (kod bywa na początku wartości albo w nawiasie,
  przecinek przed nową linią), brak zamówienia z tym numerem albo kilka kontraktów pod jednym numerem =
  „Do ręcznego” i dzwonek Finansów. Zmiana adresu faktury nigdy nie ląduje w „Bez zmian”.
- **Line manager, cost center, NIIDS** (wszystkie 12 maili z kopii 08–11.2026) idą tylko do
  dziennika jako „Zmiana w kontrakcie” / „Bez zmian”, bez wartości (nazwiska zostają w CPro).
- Automat widzi tylko skrzynki zsynchronizowane z NEXUSEM: mail z 15.09 (283051) nie trafił do
  `emails`, więc ten kontrakt Finanse przypisują ręcznie w szkicu.
- Ekran ustawień wystawiania nie nadpisuje przypisań kontraktów (`keep_stored_mapping`):
  karta otwarta przed mailem CPro odesłałaby stare `contract_buyers`. Każdy zapis po odczycie
  (automat CPro, wybór nabywcy w szkicu, ekran ustawień) czyta ustawienia z blokadą wiersza
  (`issue_settings.load(db, lock=True)`), bo zapis podmienia cały JSON.

## Gdzie to siedzi

- Odczyt bez bazy: `services/cpro_mail_parse.py`. Przebieg: `services/cpro_mail.py`,
  nabywca z adresu faktury: `services/cpro_invoice_buyer.py`.
- Pętla `cpro_mail` co 3 minuty (`tasks/cpro_mail.py`), na stagingu zablokowana.
  Kill-switch `CPRO_MAIL_ENABLED`, wyłączniki reguł w `app_settings['cpro_mail:rules']`.
- Trasy `api/cpro_mail.py`: `GET /api/cpro/log`, `PUT /api/cpro/rules` (HoR, admin),
  `GET /api/jobs/{id}/cpro-events`. Front: `JobCproBanner`, `CproSettings`,
  `/settings/cpro`. Dziennik ostrzega, gdy skrzynka nie synchronizuje się od godziny:
  24 z 34 maili o zamknięciu przyszły tylko do jednej osoby.
- Migracja 0635, DDL w `services/cpro_mail_schema.py` (czyta go też `entrypoint.sh`).
