# Rozliczenia: fałszywe blokady przy MD zgodnych z fakturą (mail w mailu, nazwa pliku w NFD, nagłówek PKO, daty z innego miesiąca, nadgodziny BNP, zrzut ekranu OCR)

<!-- indeks: fałszywa blokada, blok_zgodne, mail w mailu, załączony mail, msg w eml, message/rfc822, Załącz element, mail_text.thread, attached, acceptance_mail, from_client, NFD, Unicode, nazwa pliku z Maca, period_for, find_period, okres z tematu, TimeSheet RRMM, nagłówek PKO, sheet_month, month_from_dates, Godziny nadliczbowe, nadgodziny BNP, zaokrąglenie MD, rounded_in_file, fields.md_hours, Sumy MD nie zgadzają się z godzinami, proof.accept_has_hours, proof.month, template_month_fixed, Daty wierszy z innego miesiąca, Wpisy spoza rozliczanego miesiąca, Date from, cytat z „>”, zlecenie nadgodzin, extra.mail_accept, FIN-MD-01, podział na zamówienia, OCR, zrzut ekranu, screenshot_ocr, judge_screenshot, acceptance_image, tesseract, koordynator z Time Sheet, Senders.people -->

Od 24.11.2026, po powtórce 6 próby rozliczeń IX–X 2026 (kopia produkcji z nocy 23/24.11).
Kilka przypadków stało na blokadzie albo uwadze, choć MD z dokumentu zgadzały się
z fakturą Finansów. Przyczyny były w odczycie, nie w regułach klienta.

## Mail załączony do maila to wiadomość wątku

Konsultant PKO wysyła Time Sheet z prywatnej skrzynki i dołącza akceptację banku
jako plik `.msg` albo jako element („Załącz element”, część `message/rfc822`).
Kontrola `proof.accept_has_hours` czytała tylko sam mail konsultanta, bez liczby
i bez słowa akceptacji, więc dawała „Akceptacja bez liczby godzin lub MD”.

Teraz `mail_text.read` czyta też maile załączone (do dwóch poziomów), a
`service._read_mails` bierze cały wątek (`mail_text.thread`). Każdy załączony mail
to osobna wiadomość: słowo akceptacji liczy się tylko od klienta, jak dotąd
(`rozliczenia-akceptacja-od-klienta-orlen-cez.md`). Nadawców ze środka widzi też
`acceptance_mail.read` (`from_client` w kontrolach pliku), a `mail_file` oddaje
część `message/rfc822` jako załącznik `.eml`.

## Akceptacja ze zrzutu ekranu (OCR)

Decyzja Artura z 24.11.2026. Konsultant wkleja do maila zrzut odpowiedzi klienta
z Outlooka zamiast maila (PKO: „potwierdzam odbiór usług za październik 2026 (176h)”).
Gdy żaden mail miesiąca nie przechodzi `proof.accept_has_hours`, NEXUS czyta OCR-em
(tesseract, pol+eng) do trzech najnowszych obrazów miesiąca osoby
(`client_settlements/screenshot_ocr.py`; logo ze stopki pomija, ciemny motyw odwraca,
mały zrzut powiększa, wynik trzyma w pamięci po skrócie pliku).
Zrzut jest akceptacją (`mail_text.judge_screenshot`), gdy ma jednocześnie:

- słowo akceptacji („potwierdzam”, „akceptuję”);
- rozliczany miesiąc;
- liczbę godzin albo MD równą dowodowi (samo „Akceptuję” ze zrzutu nie wystarcza);
- nadawcę, który jest osobą klienta: koordynatorem albo akceptującym z nagłówka Time
  Sheet PKO (`ParsedPko.acceptors`) albo kontaktem klienta w NEXUS-ie
  (`Senders.people`). Na zrzucie nie ma adresu, więc liczy się imię i nazwisko
  w linii nagłówka albo w podpisie. Linie adresatów („Do”, „DW”) się nie liczą,
  jednowyrazowa nazwa nie wystarcza.

Kontrola pokazuje wtedy „Akceptacja ze zrzutu ekranu: … za …”, a id obrazu trafia do
danych przy kontrolach (`acceptance_image`). Paczka dla klienta (`package_zip`)
bierze wtedy obraz zamiast HTML maila. Mail, który przechodzi kontrolę, ma
pierwszeństwo przed zrzutem.

Ryzyko przyjęte przez Artura: zrzut łatwo podrobić, a nazwisko koordynatora zna
konsultant.

## Okres z nazwy pliku w NFD

Nazwy plików z Maca przychodzą rozłożone (NFD): „październik” to „paz” + akcent +
„dziernik”. Wzorzec miesiąca w `mailbox.find_period` go nie łapał, więc okres brał
się z tematu wątku. ERSTE: „Time Sheet - październik 2026 ….pdf” w wątku
„Re: Timesheet wrzesień 2026” poszedł na wrzesień. `find_period` normalizuje tekst
do NFC. Od 01.09 w poczcie było 9 takich plików, okres zmienił się tylko temu jednemu.
Klasyfikacji raport/faktura to nie dotyczyło.

Poprawka działa dla nowej poczty, a okresu zapisanego dokumentu nikt w aplikacji nie
zmienia. Odczyt produkcji z 24.11.2026 znalazł w `cp_documents` jeden plik z akcentem
rozłożonym i był to właśnie ten Time Sheet (dokument 11, zapisany na IX). Rozliczenie IX
liczyło się z pliku za X, a rozliczenia X nie było. Jednorazowa naprawa
(`app/services/cp_document_period_repair.py`, krok startu w `entrypoint.sh`, decyzja
Artura z 24.11.2026) przestawia go na X i przelicza oba miesiące.

## PKO: nagłówek starszego szablonu z poprzedniego miesiąca

Nagłówek „Liczba godzin realizacji usług <miesiąc> <rok>” w starszym szablonie to
tekst wpisany ręcznie. Konsultant kopiuje plik z poprzedniego miesiąca i zmienia
nazwę na „TimeSheet 2610 - …”, a nagłówek zostaje „wrzesień 2026”. Bank akceptuje
godziny za październik. Kontrola dawała „Time Sheet za inny miesiąc”.

Teraz, gdy nagłówek nie pasuje, a nazwa „TimeSheet RRMM” wskazuje rozliczany miesiąc,
Time Sheet liczy się za ten miesiąc (`timesheet_pko.sheet_month`, „Miesiąc z nazwy
pliku”). Ten sam miesiąc dostaje akceptacja „Akceptuję” bez liczby. Nowszy szablon
ma miesiąc z dat dni (`month_from_dates`) i nazwa pliku go nie zmienia.

## BNP: „Godziny nadliczbowe” i MD zaokrąglone do 0,1

- Wiersz podsumowania „Godziny nadliczbowe w sobotę” (i „Nadgodziny …”) to praca
  dodatkowa, jak „Godziny dodatkowe …” z szablonu. Wcześniej szedł do dni zwykłych,
  bez mnożnika `extra.multiplier`, a Finanse fakturowały go jako nadgodziny.
- Podsumowanie pokazuje MD z jednym miejscem po przecinku: 9 h to 1,125 MD, w pliku
  stoi 1,1. Gdy suma różni się od godzin tylko zaokrągleniem (mniej niż 0,05 MD na
  zaokrąglony wiersz, „Total MD's” zgodne z godzinami), MD liczymy z godzin
  (`rcp_checks.rounded_in_file`). Różnicę dostaje część, której wiersze nie są pełnymi
  godzinami. Gdy takie wiersze są i w dniach zwykłych, i w pracy dodatkowej, zostaje
  kontrola `fields.md_hours` dla człowieka.
- Zlecenie nadgodzin od klienta bywa w przekazanym mailu, w którym każda linia cytatu
  zaczyna się od „> ” (Gmail, Thunderbird). `acceptance_mail` czyta teraz takie linie
  „> From:” i „> Sent:”, więc `extra.mail_accept` widzi wiadomość klienta i jej datę.

## Time Sheet: daty wierszy z innego miesiąca

Decyzja Artura z 24.11.2026. Konsultant kopiuje Time Sheet z innego miesiąca, zmienia
nagłówek „Date from/Date to”, a daty wierszy zostają (Bosch: nagłówek wrzesień,
wszystkie wiersze z czerwca, godziny równe fakturze). Gdy nagłówek obejmuje dokładnie
cały rozliczany miesiąc, a wszystkie wiersze mają daty z jednego innego miesiąca
mieszczące się w rozliczanym, liczymy je za rozliczany miesiąc z informacją „Daty
wierszy z innego miesiąca” (`timesheet.template_month_fixed`), bez blokady.
Wiersze z dwóch miesięcy, wiersz bez daty, nagłówek na część miesiąca albo dzień 31
przy miesiącu 30-dniowym zostają kontrolą „Wpisy spoza rozliczanego miesiąca”.
To ten sam wzór co rok z zeszłorocznego szablonu (`template_year_fixed`), ale bez
kontroli kalendarza: wystarcza nagłówek na cały miesiąc.

## Bez zmiany kodu (ustalenia z tej samej powtórki)

- **Limit MD w miesiącu u Banku Pocztowego** („34 MD przy 22 dniach” przy 17 MD z KCP):
  to suma z drugim aktywnym kontraktem tej samej osoby u innego klienta, z tymi samymi
  dniami po 8 h. `fields.md_month_limit` liczy innych klientów celowo (Velo, 12.11).
  Decyzja Artura z 24.11.2026: kontrola zostaje, sprawę wyjaśniają Finanse.
- **BIK, godziny na dwa zamówienia w treści maila:** NEXUS kieruje do faktury tyle,
  ile zostało na zamówieniu (`md_charged`), tak jak Finanse. Nadwyżka czeka na nowe
  zamówienie z uwagą „Ponad zamówienie”. Podziału rozliczenia na kilka zamówień
  z treści maila klienta (BIK „4500…: 40 h”, tabela osoba × numer SAP Polkomtelu)
  jeszcze nie ma: przyjęcie odmawia miesiąca na dwóch zamówieniach (FIN-MD-01).

## Pomiar

Kopia produkcji `nexus_staging_klodko_v6`, IX–X 2026, 353 rozliczenia przeliczone
w transakcji z rollbackiem, kod `main` i kod tej zmiany na tych samych danych. Pliki
z nazwą w NFD dostały okres z nowego `period_for` (jak przy ponownym wczytaniu poczty).
7 rozliczeń przechodzi z blokady albo „Sprawdzania” do „ok”: PKO 4, ERSTE 1, BNP 1,
Bosch 1. MD we wszystkich siedmiu są równe fakturom Finansów; przy BNP i ERSTE także
kwota co do grosza. Pozostałe 346 rozliczeń bez zmiany statusu, MD, kwot i kontroli.
OCR zrzutu (ta sama kopia, prawdziwy tesseract z obrazu backendu): PKO IX i X jednej
osoby przechodzą do „ok” (X z fakturą Finansów, MD równe), pozostałe 351 rozliczeń bez
zmian. Ze dwóch zrzutów za X przeszedł poprawiony; pierwszy bank wysłał z pomylonym
miesiącem.

Powiązane: `finanse-insights/rozliczenia-akceptacja-od-klienta-orlen-cez.md`,
`finanse-insights/rozliczenia-nadawca-i-okres-z-poczty.md`,
`finanse-insights/rozliczenia-czytniki-plikow-klientow.md`.
