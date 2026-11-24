# Rozliczenia: podpisany arkusz zbiorczy klienta to akceptacja godzin osoby (E6.2)

<!-- indeks: arkusz zbiorczy, podpisany arkusz, signoffs, pay.per_person, Arkusz czeka na podpis klienta, cl.client_document, od miesiąca, from, proof.excel_with_mail, Brak maila z akceptacją godzin, gdy brak podpisu, signed_sheet, Godziny zaakceptowane podpisem klienta na arkuszu zbiorczym, kind_of_file, arkusz jako faktura, B2B_09_2026.pdf, Nazwisko Imię Okres od MD., drugi strumień klienta, duplikat Time Sheet, ten sam plik drugi raz, _store_mail_body, known, VeloBank, Velo -->

Od 24.11.2026, po próbie rozliczeń IX–X 2026 na kopii produkcji. U klienta z arkuszami
zbiorczymi (Velo) żadne rozliczenie z MD nie przeszło samo, bo każdą osobę blokowały
dwie fałszywe uwagi. Podpisane arkusze za IX i X wróciły od klienta, a NEXUS ich nie
przypisał.

## Arkusz rozpoznajemy, gdy zapłata na niego czeka

`pay.per_person` („zapłata po podpisanym arkuszu tej osoby”) czeka na arkusz od
pierwszego miesiąca reguł. Rozpoznawanie (`signoffs.apply`) szukało arkusza tylko od
miesiąca z parametru „od miesiąca” reguły `cl.client_document`. Od tego miesiąca NEXUS
sam robi arkusz do podpisu, a wcześniej robili go koordynatorzy i klient też go
podpisywał. W luce między tymi miesiącami każda osoba miała „Arkusz czeka na podpis
klienta”, choć podpisany arkusz leżał w poczcie.

Teraz `signoffs.expects` szuka arkusza też wtedy, gdy w danym miesiącu działa
`pay.per_person`. „Od miesiąca” dalej decyduje o tym, od kiedy NEXUS robi arkusz
(`client_documents`) i od kiedy faktura do klienta czeka na podpisy
(`cl.after_signed_document`, `client_invoice`). Protokołu (PKO) to nie zmienia.

## Arkusz klienta bez słowa „arkusz” w nazwie to raport

Osoba z drugiego strumienia klienta ma osobny arkusz od klienta. Ma on wzór klienta
(„Nazwisko Imię · Stanowisko · Okres od · Okres do · MD.”), plik `B2B_MM_RRRR.pdf`
i temat `[BL] Rozliczenie MM.RRRR [...]`. Przekazuje go nasz opiekun klienta.
Nazwa i temat nie mają słowa-klucza, więc plik szedł jako faktura.
`refresh_for_document` czyta tylko raporty, więc podpisu nikt nie widział.
Osoba z tego strumienia miała „Arkusz czeka na podpis klienta” na stałe. Od XI
wstrzymywałaby też fakturę do klienta (`cl.after_signed_document`), która czeka na
arkusze wszystkich osób.

Teraz `mailbox.kind_of_file` pyta też czytnik arkusza (`signoffs.parse`). PDF z
nagłówkiem arkusza i co najmniej jednym wierszem osoby z MD to raport. Sam nagłówek
bez wiersza osoby zostaje fakturą.

## Podpis na arkuszu zastępuje mail z akceptacją

`proof.excel_with_mail` to w katalogu „Excel z mailem akceptującym usługi, gdy brak
podpisu”. Gdy klient podpisał arkusz z MD osoby, podpis jest. Mail akceptacji przysyła
tylko część kierowników klienta, reszta osób miała „Brak maila z akceptacją godzin”.

Teraz `service._recompute` podaje do `timesheet.evaluate` jako `signed_sheet`
informację, czy arkusz podpisał klient (`signoffs.client_signed(..., SHEET)`). Przy
takim arkuszu kontrola pisze „Godziny zaakceptowane podpisem klienta na arkuszu
zbiorczym” i nie sprawdza maila. Liczby nie przechodzą bez sprawdzenia. Inne MD
w arkuszu niż w Time Sheet daje nadal uwagę „W arkuszu X MD, w Time Sheet Y MD”
(`_signed_checks`). Arkusz bez ważnego podpisu niczego nie zmienia.

Podpis nie przechodzi weryfikacji łańcucha zaufania (`rcp_bnp.signatures`: CA banku
jest wewnętrzne). Każdy może więc podpisać PDF własnym certyfikatem. Dlatego
`signoffs.apply` zapisuje w znaczniku `by_client` (`_by_client`). Wartość jest fałszywa,
gdy:

- plik wgrał konsultant w panelu (kanał `portal` z jego kontraktem; Finanse wgrywają
  bez kontraktu), jak przy KEŚU (`kesu_flow._trusted`);
- mail przyszedł z adresu konsultanta tego kontraktu (`identity.sender_contract_ids`,
  jak w #3884);
- jedyny podpis ma imię i nazwisko samej osoby.

Taki arkusz nie zastępuje maila: zostaje „Brak maila z akceptacją godzin” i Finanse
sprawdzają ręcznie. Znacznik bez `by_client` (sprzed tej zmiany) też nie zastępuje
maila.

Decyzja Artura z 24.11.2026: ta sama zasada obowiązuje bramkę zapłaty. `pay.per_person`
(`_signed_checks`) otwiera zapłatę tylko po arkuszu od klienta (`client_signed`).
Arkusz od samej osoby daje „Arkusz czeka na podpis klienta” z opisem, skąd przyszedł.
Osoba bez Time Sheet dostaje MD z arkusza też tylko z arkusza od klienta. Finanse
mogą wgrać arkusz od klienta sami („Wgraj podpisany dokument”, bez kontraktu).
Na kopii produkcji z nocy 24.11 nie było ani jednego znacznika podpisu, więc zmiana
niczego już otwartego nie zamyka.

## Akceptacja z tym samym Time Sheet, który już był

Konsultant wysyła Time Sheet, a po kilku dniach przekazuje akceptację kierownika
z tym samym plikiem w załączniku. Plik był duplikatem, więc `_ingest_message` nie
liczył go jako nowego i nie wołał `_store_mail_body`. Akceptacja przepadała.

Teraz plik nadawcy, który już mamy (`known`), też prowadzi do `_store_mail_body`. Reszta
zasad bez zmian. Przy `proof.excel_with_mail` treść zapisujemy tylko wtedy, gdy
w wątku pisze klient (`_client_wrote`). Samo ponowne wysłanie pliku przez konsultanta
treści nie zapisuje.

## Pomiar (24.11.2026)

Dwa klony kopii próby `nexus_staging_klodko_v6r2`. Na każdym poczta 01.09–20.11 od zera
(harness próby, obraz stagingu). Na jednym kod `main` 58953b191, na drugim gałąź.

- Klient z arkuszami, IX–X:
  - zgodne MD bez człowieka 0 → 9 z 16;
  - „Arkusz czeka na podpis klienta” znika we wszystkich 13 rozliczeniach z MD;
  - „Brak maila z akceptacją godzin” znika w 3, czyli wszędzie, gdzie stała na `main`;
  - 2 nowe rozliczenia z samego arkusza, MD zgodne z prawdą (TS tych osób za IX czeka
    na przypisanie);
  - 2 rozliczenia dostają MD z arkusza, bo plik osoby nie ma czytnika;
  - nowa uwaga „34 MD przy 22 dniach” u jednej osoby jest prawdziwa: ta sama osoba
    pracuje w tych dniach u drugiego klienta, a przeliczenie po arkuszu widzi już jego
    kartę.
- Inni klienci: 0 zmian w rozliczeniach IX–X (statusy, MD, kwoty, uwagi). Doszły
  3 maile `.eml` przy plikach, które już były. Wyniki tych osób są takie same.
- Rodzaj pliku zmienił się tylko przy arkuszach klienta z drugiego strumienia
  (VIII–X: faktura → raport).

## Czego to nie zmienia

- Przekazanie TS ze skrzynki konsultanta w domenie klienta z „Akceptuję” kierownika
  w cytacie działa od #3876 (zapis treści) i #3884 (konsultant nie akceptuje sam).
  W próbie na kodzie sprzed #3876 ta uwaga była też przy takich mailach.
- Plik za wrzesień z firmowego adresu konsultanta, który ma jeszcze kontrakt
  zakończony 31.08 u innego klienta, zostaje bez osoby. To osobna sprawa tożsamości.
