# Rozliczenia: MD z prośby o akceptację, którą klient zaakceptował w wątku

<!-- indeks: prośba o akceptację, prośba o akcept, akceptuję, suma godzin, bez Time Sheet, bez pliku godzin, accepted_request, _request_proof, _mails_only, Prośba o akceptację godzin zaakceptowana przez klienta, Klient zaakceptował prośbę, ERSTE, BIK, skrzynka konsultanta u klienta, jedna suma, dwie sumy, korekta po akceptacji, stopka RODO -->

Od 24.11.2026, po powtórce 7 próby rozliczeń IX–X 2026. Część osób nie ma pliku
godzin za miesiąc. Jedynym dowodem jest wątek z prośbą o akceptację z jedną sumą
i odpowiedzią klienta „akceptuję”. Rozliczenie stało w „Sprawdzaniu” bez MD, choć
Finanse fakturowały tę sumę.

Przykład z próby (ERSTE, X): konsultant ma skrzynkę w domenie klienta. Prosi
kierownika: „prośba o akcept TS za 10-2026 176h”. Kierownik odpisuje „akceptuję”,
a konsultant przekazuje wątek na rozliczenia@. Faktura Finansów: 22 MD.

## Reguła

`service._recompute` bierze MD z takiej prośby (`client_settlements/accepted_request.py`),
gdy spełnione są cztery warunki:

- żaden plik miesiąca ani podział na zamówienia z maila nie dał MD;
- w miesiącu osoby są same maile, bez pliku, z którego czytnik bierze godziny
  (PDF, XLSX, DOCX, „.xls”; `_mails_only`; obrazy się nie liczą);
- kontrakt nie jest projektem FIX;
- klient ma znane domeny (`acceptance_senders`, jak przy podziale na zamówienia).

MD = godziny / `fields.md_hours`. Gdy prośba podaje MD, bierzemy je wprost.
Kontrole są jak przy dokumencie z deklarowaną sumą (`declared.evaluate`): miesiąc
z prośby, limit MD w miesiącu, do tego `proof.accept_has_hours` na mailach miesiąca.
Na karcie źródło widać jako grupę „Prośba o akceptację godzin zaakceptowana przez
klienta” i kontrolę „Klient zaakceptował prośbę: 176 h” z adresem akceptującego,
cytatem odpowiedzi i nadawcą prośby.

## Co czytamy z wątku

- **Akceptacja**: najnowsza wiadomość z domeny klienta ze słowem akceptacji
  (`mail_text._APPROVED`: „akceptuję”, „potwierdzam”, „zatwierdzam”…) albo odmowy
  (`client_acceptance._REJECT`: „nie akceptuję”, „odrzucam”…). Odmowa = brak MD.
  Wiadomości klienta bez żadnego z tych słów („Prosimy o fakturę w PDF”) pomijamy.
  Sam konsultant ze skrzynki u klienta nie akceptuje (`_without_consultant`, #3884).
  Nie akceptuje też nikt z domen firmy.
- **Liczba**: z wiadomości akceptacji, a bez niej z wiadomości, na którą klient
  odpisał (następna w wątku). Starszych wiadomości nie bierzemy, bo mają nieaktualne
  liczby. Musi to być jedna suma: jedna liczba godzin albo jedna liczba MD.
- **Osoba**: prośbę napisał sam konsultant kontraktu albo imię i nazwisko osoby stoi
  w prośbie lub w temacie wątku.
- **Miesiąc**: jeden miesiąc z prośby, a bez niego z tematu wątku. Daty dalej niż
  o 12 miesięcy pomijamy, bo nasza stopka cytuje RODO „z dnia 27 kwietnia 2016”.

## Kiedy MD nie ma (ścieżki odmowy, testy w `test_client_settlements_accepted_request.py`)

- brak akceptacji klienta albo akceptacja z naszego adresu;
- odmowa klienta;
- akceptuje sam konsultant ze swojej skrzynki;
- dwie różne liczby albo godziny i MD naraz w prośbie;
- prośba dla innej osoby (inne imię i nazwisko w prośbie i temacie);
- prośba za inny miesiąc: kontrola `proof.month`, MD nie wpisujemy;
- nowsza wiadomość w wątku z inną liczbą (korekta po akceptacji);
- dwa maile miesiąca z różnymi sumami.

## Odpowiedź klienta bez akceptacji (decyzja Artura z 25.11.2026)

Odpowiedź klienta bez sprzeciwu **nie jest** akceptacją (BIK, IX 2026: na prośbę „- 176h”
klient odpisał tylko „Prosimy o przesyłanie również faktury w formie PDF do nas.”).
MD dalej nie ma, ale rozliczenie nie stoi już bez drogi: gdy najnowsza wiadomość klienta
w wątku nie jest ani akceptacją, ani odmową, a wiadomość, na którą odpisał, to prośba
z jedną sumą dla tej osoby za rozliczany miesiąc (`accepted_request.find_unaccepted`),
rozliczenie dostaje uwagę `proof.request_reply` „Odpowiedź klienta bez akceptacji godzin”
z adresem odpowiadającego w `acceptors`. Informacja zwrotna o wadach (`client_settlements/feedback`,
wada `accept.reply_without_ok`) prosi go o wyraźne „Akceptuję”.

## Czego to nie zmienia

- Gdy w miesiącu jest Time Sheet, RCP albo inny plik godzin, MD idą z pliku jak dotąd.
  Dotyczy to też pliku, którego nikt nie czyta: wtedy zostaje uwaga dla Finansów.
- BIK IX z próby zostaje bez MD. Klient odpisał na przypomnienie samą prośbą o fakturę
  w PDF, bez słowa akceptacji, więc NEXUS tego nie liczy.

## Pomiar (klon `nexus_staging_klodko_v7`, transakcja z ROLLBACK, 24.11.2026)

Porównaliśmy `service.recompute_and_store` 369 rozliczeń IX–X na kodzie z `main`
i z gałęzi. Zmieniło się jedno: ERSTE X przeszło z „Sprawdzania” bez MD na „ok”
z 22 MD, równo z fakturą. Pozostałe 368 rozliczeń jest bez zmian (status, MD,
kontrole).

Pliki pokrewne: `rozliczenia-akceptacja-w-tresci-maila.md`,
`rozliczenia-podzial-na-zamowienia-z-maila.md`, `rozliczenia-odpowiedz-klienta-na-nasz-wyslany-mail.md`.
