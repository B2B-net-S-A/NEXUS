# Rozliczenia: czyj jest plik z poczty — nazwisko po zmianie, literówka, skrzynka u klienta, numer umowy

<!-- indeks: przypisanie pliku, plik innej osoby, names_someone_else, zmiana nazwiska, Nowe (Stare), nazwisko w nawiasie, _surnames, literówka w imieniu, resolve_named_in_scope, portfel DL, delivery_lead_client_assignments, staff_client_ids, external., poddomena klienta, de.bosch.com, bosch.com, _clients_of_domain, numer umowy wykonawczej, CeZ/177/2026, resolve_by_agreement, agreement_numbers, treść maila z Time Sheet, _store_mail_body, proof.excel_with_mail, cytat Gmaila, napisał(a), пише, quoted_messages, akcept rozliczenia, _store_client_acceptance, dni wolnych od pracy, wrzeniu -->

Od 24.11.2026. Szósta próba rozliczeń IX–X 2026 (kopia produkcji z nocy 23/24.11)
miała 13 przypadków bez rozliczenia albo z uwagą, bo czytnik poczty rozliczeń nie łączył
dokumentu z kontraktem właściwej osoby. Do tego jeden plik trafił do innej osoby.

## Reguły

- **Plik innej osoby nie dziedziczy osoby z maila.** Koordynator wysłał jednym mailem
  protokoły dwóch osób. Jedną kartoteka znała, drugą nie (stare nazwisko). Osoba
  rozpoznana z tematu albo z nazwy jednego pliku przechodziła dotąd na wszystkie pliki
  maila, więc protokół drugiej osoby trafił do cudzego kontraktu. Teraz plik dziedziczy
  osobę z maila tylko wtedy, gdy sam ją nazywa albo nie nazywa nikogo innego
  (`identity.names_someone_else`). „Ktoś inny” to imię albo nazwisko innej osoby
  z działającym kontraktem. Taki plik czeka na człowieka, jak każdy plik bez osoby.
- **Nazwisko po zmianie: „Nowe (Stare)”.** Finanse wpisują zmianę nazwiska w kartotece
  jako nowe nazwisko z poprzednim w nawiasie (Orlen, 23.11.2026). Nawias nie jest częścią
  słowa, a każde z nazwisk wskazuje osobę samo (`identity._surnames`). Plik może więc mieć
  stare nazwisko, nowe albo oba. Tak samo działają: adres `imie.nazwisko@` w skrzynce
  firmowej i u klienta, nazwa pliku od klienta, temat KEŚU, kontrola
  „Imię i nazwisko jak w kontrakcie” (`rcp_checks.name_tokens`). Osobnego pola na
  poprzednie nazwisko nie ma. Nawias wystarcza i nie wymaga migracji. Pole będzie
  potrzebne dopiero wtedy, gdy Finanse zechcą trzymać nazwisko poza kartoteką.
- **Literówka w imieniu, tylko w portfelu DL-a z wątku.** Plik „PROTOKÓŁ_ Tomsz
  Nazwisko_…” od koordynatora po naszej stronie nie wskazywał osoby, bo pełne imię nie
  pasowało. Teraz wskazuje, gdy spełnia wszystkie warunki
  (`identity.resolve_named_in_scope`):
  - każdy człon nazwiska stoi w nazwie pliku;
  - imię stoi całe albo różni się jedną literą (brak, nadmiar, zamiana, przestawienie)
    przy tej samej pierwszej literze i imieniu od 4 liter;
  - nazwisko nosi jedna osoba wśród klientów z portfela DL-a, który mail wysłał albo
    jest jego adresatem (`delivery_lead_client_assignments`);
  - w nazwie nie stoi imię innej osoby z działającym kontraktem.

  Bez DL-a w wątku nie ma klienta, wśród którego szukać, więc plik czeka na człowieka.
- **Skrzynka u klienta w poddomenie, z przedrostkiem `external.`.** Konsultant Boscha pisze
  z `external.imie.nazwisko@de.bosch.com`, a kontrakt nie ma adresu. Rejestr domen
  (`order_policies/known_clients`) ma teraz `bosch.com` i NIP Boscha.
  `identity._clients_of_domain` schodzi z poddomeny do domeny z rejestru tylko przy
  domenach z `SUBDOMAIN_SENDER_DOMAINS` (dziś `bosch.com`). `_by_company_address` zdejmuje
  przedrostek `external.`/`ext.` przed imieniem. W akceptacji klienta domeny dalej
  porównujemy dokładnie, więc skrzynka konsultanta w `de.bosch.com` nie jest klientem.

  Poddomena innej domeny z rejestru zostaje obca. `consult.nordea.com` to skrzynki
  naszych konsultantów, którzy w wątku występują jako strona klienta. Przy schodzeniu
  bez listy raport z testu bezpieczeństwa wykonanego przez inną osobę trafił w pomiarze,
  przez łańcuch przekazania, do kontraktu takiego konsultanta.
- **Numer umowy wykonawczej.** CeZ zawiera umowę wykonawczą na osobę, a protokół ma jej
  numer w temacie („do umowy CeZ/177/2026”) albo w nazwie pliku („do CeZ_177_2026-sig.pdf”).
  Imię w temacie bywa inne niż w kartotece. Numer wskazuje kontrakt, gdy spełnia
  wszystkie warunki (`identity.resolve_by_agreement`):
  - jest numerem zamówienia w NEXUS-ie;
  - zamówienie ma jedną osobę z działającym kontraktem;
  - w tekście nie ma drugiego numeru;
  - temat ani nazwa pliku nie nazywa pełnym imieniem i nazwiskiem innej osoby.

  Numer z nazwy pliku wygrywa z tematem. Okres „za 10/2026” ze spacją nie jest numerem.
  Działa dla nadawcy z adresu firmy, a dla nadawcy z domeny klienta tylko wśród jego
  zamówień.
- **Treść maila z Time Sheet, gdy w wątku pisze klient.** Konsultant ERSTE i Polkomtelu
  przekazuje Time Sheet razem z odpowiedzią kierownika („Potwierdzam”, „akceptuję”).
  Konsultant ERSTE nie może wysłać maila poza bank, więc pisze z prywatnej skrzynki.
  Treść maila zapisywaliśmy tylko przy `proof.accept_has_hours`, więc
  `proof.excel_with_mail` pisała „Brak maila z akceptacją godzin”. Teraz `.eml` powstaje
  też przy `proof.excel_with_mail` albo `extra.mail_accept`. Warunek
  (`mailbox._client_wrote`): w wątku jest wiadomość z domeny klienta (domeny jak w
  `service.acceptance_senders`) od kogoś innego niż sam konsultant.
  - Skrzynka konsultanta u klienta (`…@kir.pl`, ERSTE, PKO) jest w domenie klienta, ale
    jego własny mail z fakturą to nie akceptacja.
  - Mail bez wiadomości klienta nie zostawia `.eml`.
  - Temat KEŚU (Alior) też nie. Tam akceptacją jest mail automatu Jiry, a dodatkowy mail
    miesiąca zmieniał źródło KEŚU i dawał „Brak maila z Jiry z akceptacją opiekuna”.
- **Cytat z Gmaila.** Odpowiedź z Gmaila cytuje wątek liniami z „>” po linii
  „… <adres> napisał(a):” (także po angielsku i ukraińsku, czasownik bywa w następnej
  linii). `acceptance_mail.quoted_messages` czyta teraz oba wzory.
- **Akceptacja ze skrzynki samego konsultanta.** Konsultant przekazuje akceptację
  kierownika ze swojej skrzynki u klienta bez nazwiska w temacie („PD: akcept
  rozliczenia”). `_store_client_acceptance` przypisuje wtedy `.eml` do kontraktu nadawcy,
  gdy spełnia wszystkie warunki:
  - nadawca to jego adres z kontraktu, a jego klient ma regułę akceptacji mailowej;
  - w wątku pisze ktoś z klienta inny niż on (`_client_wrote`);
  - temat nie nazywa innej osoby, także niejednoznacznej.

  Dotąd mail czekał bez osoby i tak zostaje, gdy pisze sam konsultant („Kiedy przelew?”).
- **Deklaracja „dni wolnych od pracy”.** mLeasing: „We wrzeniu nie miałam dni wolnych od
  pracy.” Nadawcę czytnik rozpoznawał (`sender_contract_ids`). MD nie wchodziły przez
  dwie rzeczy: „od pracy” spoza białej listy i nazwę miesiąca z brakującą literą.
  Szczegóły w `finanse-insights/rozliczenia-deklaracja-konsultanta-w-mailu.md`.

## Pomiar

Próba IX–X 2026: pełny przebieg poczty 01.09–20.11 na klonie kopii produkcji
(`nexus_staging_klodko_v6r2`, reguły zalecane), porównany z przebiegiem na `main`
z 24.11, plik po pliku i przypadek po przypadku.

- **Dokumenty:**
  - 4 przepięte z kontraktu innej osoby: pliki z 14.09 i 13.10 nie są już przy 428;
  - 28 nowych przypisań, każde sprawdzone ręcznie, wszystkie trafne;
  - 68 nowych `.eml` z wiadomością klienta w wątku;
  - 0 odpiętych, 0 zmian rodzaju i okresu.
- **Rozliczenia bez Nordei:** zgodne MD bez człowieka w 169 z 223 przypadków (było 158).
  - Doszły: Orlen 429 IX i 432 IX, mLeasing 438 IX, Polkomtel 474 IX i X, ERSTE 477 IX
    i X oraz 614 X. Także BNP 382 i 552 IX i X: w przekazanym wątku było „akceptuję”
    pracownika banku, a NEXUS nie zapisywał treści maila.
  - Orlen 429 X ma zgodne MD i uwagę o kwocie z protokołu (`cl.protocol_amount`).
- **Przypisane bez MD:**
  - ERSTE 479 X: w poczcie są same akceptacje, Time Sheet nie przyszedł na rozliczenia@.
  - Bosch 627 IX i X: czytnik Time Sheet nie czyta wierszy tego PDF-a.
  - CeZ 668 X: tabela przestawna w protokole.

  Czytniki to osobna praca.
- **Dwie zmiany na liście, które nie wynikają z tej zmiany:**
  - Alior 491 IX. Świeże przeliczenie tym kodem daje „ok”. Różnicę robi kolejność
    dokumentów z tym samym `created_at` w przebiegu (`_month_reports` sortuje bez
    rozstrzygnięcia remisu).
  - ERSTE 619 IX ma 6 MD przy 28 na fakturach. Do kontraktu przypięto też fakturę
    innej osoby (22 MD), więc 6 MD jest poprawne.

## Czego ta zmiana nie robi

- Nie wpuszcza maila bez pliku z prywatnej skrzynki konsultanta („Fwd:” z akceptacją,
  ERSTE). Taki mail dalej jest tylko sprawą. Akceptacja liczy się, gdy przyjdzie w mailu
  z Time Sheet albo ze skrzynki konsultanta u klienta.
- Nie łączy zestawienia godzin Finansów ze zrzutem ekranu (CeZ, „Zaakceptowane godziny …”
  z obrazkiem). Router oddaje ten mail sprawom.
- Nie przypisuje pliku, w którym inne imię stoi bez numeru umowy i bez portfela DL-a.

Powiązane: `finanse-insights/rozliczenia-nadawca-i-okres-z-poczty.md`,
`finanse-insights/rozliczenia-akceptacja-od-klienta-orlen-cez.md`,
`finanse-insights/rozliczenia-odpowiedz-klienta-na-nasz-wyslany-mail.md`,
`finanse-insights/rozliczenia-deklaracja-konsultanta-w-mailu.md`.
