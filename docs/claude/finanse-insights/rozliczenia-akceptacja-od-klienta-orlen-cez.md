# Rozliczenia: akceptacja tylko od klienta, Orlen (pgnig.pl, kwota z protokołu), oświadczenie CeZ

<!-- indeks: akceptacja klienta, Brak akceptacji klienta, mail_text.judge, Senders, acceptance_senders, proof.accept_has_hours, proof.excel_with_mail, extra.mail_accept, acceptance_mail.from_client, client_mail, akceptacja PM-a, zestawienie godzin koordynatora, forward bez cytatu, pgnig.pl, Orlen Upstream, KNOWN_SENDER_DOMAINS, client_ids_for_sender, zmiana nazwiska, dwa nazwiska w pliku, cl.protocol_amount, kwota z protokołu, faktura sprzedaży, korekta, PO, cl.copyright_statement, oświadczenie o prawach autorskich, autorskie prawa majątkowe, umowa wykonawcza, Centrum e-Zdrowia, CeZ, Senders.consultant, _without_consultant, skrzynka konsultanta u klienta, sender_contract_ids, konsultant nie akceptuje sam -->

Od 23.11.2026, po przeglądzie skrzynek Finansów (skrzynka koordynatorki rozliczeń,
wzorce: wewnętrzne zestawienie godzin, Orlen, oświadczenia CeZ).

## Akceptacja godzin liczy się tylko od klienta

Kontrola `proof.accept_has_hours` (`client_settlements/mail_text.judge`) brała dotąd
każde słowo akceptacji z wątku. Koordynatorka pisze na rozliczenia@ z adresu firmy
zestawienie „Zaakceptowane godziny … 160 h październik”. Taki mail ma liczbę godzin,
miesiąc i „zaakceptowane”, więc przechodził jako akceptacja klienta.

Teraz:

- Liczba godzin albo MD i miesiąc mogą stać w dowolnej wiadomości wątku. Zwykle stoją
  w naszej prośbie, na którą klient odpowiada „Potwierdzam”.
- Słowo akceptacji liczy się tylko w wiadomości od klienta: w samym mailu albo
  w wiadomości zacytowanej w wątku. Zacytowana wiadomość zaczyna się od linii
  „From:”/„Od:” z adresem.
- Domeny klienta (`service.acceptance_senders`) to:
  - domena z `proof.excel_with_mail`;
  - domena adresu z `cl.client_acceptance`;
  - domeny kontaktów klienta;
  - domeny z rejestru `order_policies/known_clients`, dopasowane po NIP-ie klienta.

  Porównujemy dokładnie, bez poddomen. Konsultant BNP z `external.` nie jest klientem.
- Domeny firmy (adresy rozliczeń, SSO), domeny skrzynek konsultantów u klienta
  i poczta publiczna nigdy nie są domeną klienta.
- Klient bez żadnej znanej domeny: akceptuje każdy adres spoza tych domen.
  Nadawca bez adresu, na przykład „Od: Nowak Anna” w cytacie, nie akceptuje.
- Nasz mail albo przekazanie bez cytatu odpowiedzi klienta dostaje „Brak akceptacji
  klienta” z poziomem reguły.

**„Akceptuję” bez liczby (decyzja Artura z 23.11.2026).** PKO i BIK często
odpowiadają samym „Akceptuję”. Taki mail wystarcza, gdy spełnia wszystkie warunki:

- przyszedł od klienta, według zasad wyżej;
- nie podaje innego miesiąca;
- czytnik odczytał godziny albo MD z pliku (Time Sheet, raport BIK, protokół)
  za rozliczany miesiąc.

Kontrola pokazuje wtedy „Akceptacja bez liczby, godziny z TS” z liczbą z pliku.
Gdy w miesiącu jest też mail z liczbą, wygrywa ten z liczbą. Bez pliku albo z plikiem
za inny miesiąc zostaje uwaga „Akceptacja bez liczby godzin lub MD”. Miesiąc pliku
podaje czytnik (`service._read_file` → `accepted(…, sheet_month)`).

Pomiar na kopii produkcji (`nexus_staging_klodko_v5`, IX–X 2026, przeliczenie
w transakcji z rollbackiem):

- Klienci z włączoną regułą (BIK, PKO, VIP Solution, Wedel): 67 rozliczeń, 0 zmian
  statusu. Wszystkie 42 akceptacje „ok” są od klienta.
- Reguła włączona na próbę u wszystkich klientów: 310 rozliczeń, 0 zmian.
- „Akceptuję” bez liczby z godzinami z pliku: 7 akceptacji przechodzi (BIK 5, PKO 2),
  6 rozliczeń zmienia status z „uwagi” na „ok” (BIK 4, PKO 2). Zostaje 15 uwag. To maile
  bez słowa akceptacji, na przykład przekazany TS albo wiadomość konsultanta
  z prywatnej skrzynki.

Sama zasada „tylko od klienta” dziś niczego nie zmienia. Zmiana chroni przed tym, co wejdzie z mailem
koordynatorki CeZ zapisywanym jako raport każdej osoby. Ten mail jest dowodem godzin
z decyzji Artura (`rozliczenia-protokol-odbioru-zbiorczy.md`), ale nie akceptacją
klienta w `proof.accept_has_hours`.

## Mail akceptujący w kontrolach pliku też tylko od klienta (24.11.2026)

Ciąg dalszy powyższej zasady, po przeglądzie skrzynki rozliczeń z 23.11. Podwykonawca
wysłał Time Sheet na szablonie firmy, a nasz PM odpisał „Akceptuje rozliczenie.”
z adresu firmy. Klienta w wątku nie było. `proof.excel_with_mail` w Time Sheet
(`timesheet.evaluate`) brał każdy mail miesiąca za akceptację. RCP w Excelu
i `extra.mail_accept` (`rcp_checks.evaluate`) sprawdzały domenę tylko przy wpisanym
parametrze.

Teraz wszystkie trzy kontrole pytają `acceptance_mail.from_client(wiadomości, senders)`.
Wiadomości to maile miesiąca osoby: `.msg`, `.eml`, wydruk PDF i cytaty „From:”/„Od:”.
Domeny klienta wylicza `service.acceptance_senders`, jak wyżej. Dochodzi domena
z `extra.mail_accept`. Wynik ma trzy stany:

- `True`: w wątku jest wiadomość z domeny klienta, w samym mailu albo zacytowana.
  Kontrola daje „ok”. Parametr domeny reguły nadal zawęża (`_check_domain`).
- `False`: są tylko nasze adresy, konsultant albo poczta publiczna. Kontrola daje
  „Brak akceptacji klienta” (przy nadgodzinach „… pracy dodatkowej”) z poziomem reguły,
  a `extra.mail_before` nie liczy daty zgody z naszego maila.
- `None`: klienta w wątku nie widać, ale któraś wiadomość ma nadawcę bez adresu
  („From: Nowak, Anna”). Kontrola daje „sprawdza człowiek”, bez uwagi.

W tych kontrolach słowo akceptacji nie jest potrzebne, wystarczy wiadomość klienta
w wątku. Słowo i liczbę godzin sprawdza `proof.accept_has_hours`.
Domeny klienta liczymy, gdy włączona jest którakolwiek z trzech reguł
(`service.CLIENT_MAIL_RULES`).

Pomiar na `nexus_staging_klodko_v5` (IX–X, 310 rozliczeń, `_recompute` z rollbackiem):
0 zmian statusu i 0 błędów. Zmieniają się 2 kontrole, w IX i X u jednego klienta.
Jedyny mail jest tam z domeny firmy i daje teraz „Brak akceptacji klienta” zamiast „ok”.
Status był już „uwagi”.

Projekty FIX, w których godziny podwykonawcy akceptuje PM jako koszt firmy, to wyjątek
od tej zasady: `finanse-insights/rozliczenia-projekty-fix-akceptacja-pm.md`.

## Wiadomość samego konsultanta to nie akceptacja (24.11.2026)

Decyzja Artura z 24.11.2026, po pomiarze niżej: wdrożyć, także w projektach FIX.

U kilku klientów (w próbie IX–X 2026: PKO, Alior, ERSTE, VeloBank, Polkomtel, BIK, KIR)
konsultant ma skrzynkę w domenie klienta, tej samej co kierownik. Kontrole patrzyły
tylko na domenę. Dlatego jako wiadomość klienta przechodziły:

- własny mail konsultanta z fakturą;
- cytat jego wiadomości w wątku;
- jego „potwierdzam” w odpowiedzi na pytanie naszej koordynatorki.

Teraz:

- `service._without_consultant` zbiera nadawców z maili miesiąca osoby: sam mail,
  cytaty „From:”/„Od:”, maile w mailu i wydruk PDF. Sprawdza tylko adresy, które
  i tak byłyby akceptującym.
- Adres trafia do `Senders.consultant`, gdy czytnik poczty wskazuje nim ten kontrakt
  (`identity.sender_contract_ids`). Pasuje adres z kontraktu, z kartoteki, alias
  Gmaila albo forma `imie.nazwisko@` w domenie klienta z rejestru. Ta sama zasada
  decyduje o zapisie treści maila (`mailbox._client_wrote`, PR #3876).
- `Senders.accepts_from` nie przyjmuje adresów konsultanta. Tak działają
  `proof.accept_has_hours` (`mail_text.judge`), `proof.excel_with_mail`
  i `extra.mail_accept` (`acceptance_mail.from_client`). Domenę i datę zgody na pracę
  dodatkową (`_check_domain`, `extra.mail_before`) bierzemy tylko z cudzych wiadomości.
- Projekt FIX: podwykonawca ze skrzynki firmy też nie akceptuje własnych godzin.
- Akceptacja ze zrzutu ekranu (`judge_screenshot`, PR #3875) rozpoznaje nadawcę po
  imieniu i nazwisku. Nazwisko samego konsultanta odpada z osób klienta, nawet gdy
  stoi w kontaktach klienta. Na kopii tak jest przy jednym kontrakcie, a jego klient
  nie ma reguły akceptacji.
- Samo „potwierdzam” konsultanta daje „Brak akceptacji klienta” z opisem
  „Potwierdzenie w mailu napisał sam konsultant ze swojej skrzynki”.
- Kontrakt sprawdzamy z perspektywy rozliczanego miesiąca (wcześniejsza z dat: dziś
  albo koniec miesiąca). Dzięki temu przeliczenie po 60 dniach od końca kontraktu
  nadal rozpoznaje konsultanta.

Pomiar IX–X 2026, `_recompute` w transakcji z rollbackiem:

- `nexus_staging_klodko_v6r2`, 354 rozliczenia: skrzynka konsultanta w domenie
  akceptującego w 53. Zmian statusu 0, zmian kontroli 0.
- `nexus_staging_klodko_v6r2id` (poczta odczytana kodem z #3876), 365 rozliczeń:
  skrzynka konsultanta w 70. Zmian statusu 0, zmian kontroli 0.
  - W 68 w wątku pisze też ktoś od klienta. W pozostałych 2 kontrola już pada
    z innego powodu („Akceptacja bez liczby godzin lub MD”, „Mail bez odpowiedzi
    akceptującego”).
  - „Potwierdzam” samego konsultanta bez akceptacji klienta jest raz (KIR). MD nie
    jest tam odczytane, więc dziś zmiany nie widać.
- Każdy z 70 adresów to skrzynka konsultanta: nazwisko w adresie albo adres
  z kontraktu. Żadnego kierownika nie wyłączyło.
- Koszt: przeliczenie dwóch miesięcy trwa 109 s zamiast 94 s (mediana +0,03 s na
  rozliczenie, najwięcej +0,6 s). Maile czytamy drugi raz i robimy kilka zapytań na
  każdy adres z domeny klienta.

## Orlen

- **Domena `pgnig.pl`.** Kierownik i finanse Orlen Upstream piszą z `pgnig.pl`.
  Podpisany protokół za IX przyszedł z niej 26.10. Rejestr domen
  (`known_clients.KNOWN_SENDER_DOMAINS`) ma teraz `orlen.pl` i `pgnig.pl` pod kluczem
  `orlen`, a `KNOWN_REGISTRY_IDS` ma NIP Orlenu.
- **Domeny z rejestru w czytniku poczty.** `identity.client_ids_for_sender` bierze domeny
  z kontaktów klienta i z rejestru. Orlen nie ma kontaktu w `pgnig.pl`, a plik od
  kierownika z tej domeny wskazuje osobę po nazwie, wśród kontraktów Orlenu.
- **Zmiana nazwiska.** Plik „PROTOKÓŁ_ Imię Nowe (Stare)_…” pasuje do kontraktu, bo
  `identity.resolve_named_in_text` wymaga imienia i każdego członu nazwiska
  z kontraktu, a dodatkowe nazwisko w nazwie nie przeszkadza. Na v5 taki plik był
  przypisany do właściwej osoby. Od 24.11.2026 kartoteka „Nowe (Stare)” pasuje do pliku
  z każdym z nazwisk (`finanse-insights/rozliczenia-osoba-z-pliku-skrzynki-i-umowy.md`).
  Bez nawiasu w kartotece samo nowe nazwisko nie wskazuje osoby z kontraktem na stare.
- **`cl.protocol_amount`** (sekcja „Faktura do klienta”, domyślnie wyłączona).
  `engine.compute` porównuje kwotę do faktury z kwotą netto z protokołu klienta
  (`declared.evaluate` → `meta.document_amount`). Kwota do faktury to MD × stawka
  przychodowa z zamówienia. Różnica daje uwagę „Kwota do faktury inna niż w protokole
  klienta” z obiema kwotami, zgodność daje „ok”. Uwaga nie blokuje. Finanse Orlenu
  23.11 zakwestionowały fakturę za X, która różniła się od protokołu, i zażądały
  korekty albo nowego PO.

  Kontrola nie potrzebuje modułu faktur sprzedaży, bo porównuje kwotę przed fakturą.
  Pomiar na v5 (Orlen IX–X, 12 rozliczeń z protokołem): 7 zgodnych, 5 z różnicą.
  W 2 z nich Finanse wystawiły fakturę z kwotą z protokołu, czyli stawka w zamówieniu
  NEXUSA jest inna niż w PO. W 2 faktura (KSeF) poszła z kwotą NEXUSA, czyli inną
  niż w protokole. To ten sam wzór co zakwestionowana faktura za X.

## Centrum e-Zdrowia: oświadczenie o prawach autorskich

**`cl.copyright_statement`** (sekcja „Faktura do klienta”, domyślnie wyłączona;
poziom „Ostrzega” = uwaga). CeZ przyjmuje fakturę za miesiąc z oświadczeniem każdej
osoby o przeniesieniu autorskich praw majątkowych, osobno na każdą umowę wykonawczą.
Wymagania CeZ:

- wzór CeZ;
- okres „od 01.MM do 30/31.MM”;
- podpis po końcu miesiąca.

W XI 2026 CeZ odrzuciło cztery oświadczenia: podpis 30.10, zły okres, logotypy,
nagłówek „Wzór”.

`client_settlements/copyright_statement.py` szuka oświadczenia wśród PDF-ów i DOCX-ów
miesiąca osoby. Rozpoznaje je po nazwie („oświadczenie” + prawa/autorskie/CeZ) albo po
treści („autorskich praw majątkowych”). Daje uwagę przy:

- braku oświadczenia;
- braku okresu albo okresie innym niż rozliczany miesiąc;
- podpisie przed końcem miesiąca: data z podpisu elektronicznego PDF, a bez niego
  najpóźniejsza data w treści poza okresem;
- nagłówku „Wzór”.

Logotypów nie sprawdzamy, bo tekst pliku ich nie niesie.

Na 23.11.2026 oświadczenia idą od konsultantów do koordynatorki i do CeZ, a nie na
rozliczenia@. Na v5 i w archiwum rozliczenia@ nie ma żadnego. Reguła włączona dziś
dałaby uwagę każdej osobie CeZ. Ma sens dopiero, gdy oświadczenia trafią do NEXUSA:
w DW rozliczenia@ albo przez panel konsultanta.

Powiązane: `finanse-insights/rozliczenia-akceptacja-w-tresci-maila.md`,
`finanse-insights/rozliczenia-protokol-odbioru-zbiorczy.md`,
`finanse-insights/rozliczenia-nadawca-i-okres-z-poczty.md`.
