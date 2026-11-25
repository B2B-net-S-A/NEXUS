# NIP kontraktora z faktur KSeF zapisuje się sam (25.11.2026)

<!-- indeks: NIP kontraktora, podpowiedź NIP-u, E4.0, nip_state confirmed bez decided_by, contractor_nip, faktury Benefit, inkubator, imiennicy, partner_nip, candidates.nip, contractor_nip_backfill_2026_11 -->

Decyzja Artura z 25.11.2026: brakujące dane, których NEXUS może dowieść, NEXUS
uzupełnia sam i utrzymuje regułą. Na kopii produkcji z 25.11 żaden kontraktor
z kontraktem (ok. 575 osób) nie miał `candidates.nip`, więc prawie każda faktura
kontraktora czekała w Rozliczeniach na zatwierdzenie NIP-u przez Finanse.

Zawęża regułę E4.0 „Finanse zatwierdzają NIP” (`docs/rozliczenia-klientow-roadmapa.md`):
zatwierdzenie zostaje dla wszystkiego, czego reguła niżej nie udowadnia.
Kod: `client_settlements/contractor_nip.py`, wołany z `contractor_invoices.consider`.

## Reguła

Faktura z KSeF, która byłaby podpowiedzią (nieznany NIP, w nazwie sprzedawcy imię
i nazwisko osoby z kontraktem bez NIP-u), zapisuje NIP osobie sama, gdy:

- każdy dokument z tym NIP-em nazywa tę jedną osobę i nikogo innego: faktury
  zakupowe z KSeF (`approval_documents` i `client_contractor_invoices`, nazwa
  sprzedawcy) i nasze faktury „Benefit” (`client_sales_invoices`, numer
  `…/Benefit`, nazwa nabywcy). Porównanie jak w podpowiedzi (`name_tokens`):
  imię i nazwisko osoby zawierają się w słowach nazwy;
- jest faktura zakupowa i drugi dokument z innego miesiąca wystawienia albo
  faktura „Benefit” na ten NIP (wtedy wystarcza jedna faktura zakupowa);
- NIP nie jest NIP-em innego kandydata (`candidates.nip`), osoby z Płac ani
  `partner_nip` umowy z generatora B2B innej osoby;
- Finanse nie odrzuciły tego NIP-u tej osobie;
- osoba nie ma NIP-u, także `partner_nip` innego niż ten.

Zapis jak przy zatwierdzeniu przez Finanse (`approve_nip`): `candidates.nip`,
faktura `confirmed`, pozostałe podpowiedzi tego NIP-u dla tej osoby też
`confirmed`. `decided_by` NULL znaczy „zapisał NEXUS”, `decided_at` to chwila
zapisu, w logu jedna linia z samymi ID. Kolejne faktury tego NIP-u wiążą się
jako `known`. Wszystko inne zostaje podpowiedzią dla Finansów jak dotąd, także
przy awarii reguły (faktura zapisuje się wtedy jako `suggested`).

## Progi i dlaczego

- **Dwa miesiące, nie dwie faktury.** Dwie faktury z jednego miesiąca (dwóch
  klientów, faktura i korekta) to jedno zdarzenie. Dostawca o tym samym imieniu
  i nazwisku co kontraktor zwykle nie wystawia co miesiąc. Korekty się nie liczą,
  bo powtarzają nazwę i miesiąc faktury korygowanej.
- **„Benefit” zamiast drugiego miesiąca.** Fakturę „Benefit” wystawiamy sami,
  na firmę kontraktora z jej NIP-em i nazwą. Gdy zgadza się z fakturą zakupową
  co do NIP-u i osoby, nowa osoba dostaje NIP przy pierwszej fakturze. Same
  faktury „Benefit” bez zakupu nie wystarczą, bo NIP nabywcy pakietu nie musi
  być NIP-em, z którego osoba fakturuje.
- **Wszystkie dokumenty NIP-u, nie jeden pasujący.** Jeden dokument bez osoby
  w nazwie albo z inną osobą wyklucza NIP (pułapka 1).
- **Imiennicy z całej bazy kontraktów i zespołu.** Osoby z kontraktem w każdym
  stanie, także dawno zakończonym, i konta zespołu (`users`): faktury osób
  z zespołu na B2B też leżą w zakupach KSeF.

## Pułapki

1. **Inkubator.** Fundacja wystawia pod jednym NIP-em faktury za wielu
   konsultantów, a w nazwie sprzedawcy nie ma osoby. Taki NIP nikomu się nie
   zapisuje, także gdy któraś faktura ma w nazwie nazwisko. Na kopii z 25.11
   inkubator wypada jako `no_person`.
2. **`partner_nip` z generatora umów bywa NIP-em firmy innej osoby.** NIP z umowy
   jednej osoby nie zapisuje się drugiej (`taken`). NIP-y już przypięte przez
   `partner_nip` kontraktu z indeksu reguła pomija (`bound`).
3. **Dwie osoby o tym samym imieniu i nazwisku.** Brak zapisu, także gdy kwota
   rozstrzyga podpowiedź i gdy imiennik ma tylko konto w zespole. Na kopii z 25.11
   dwie osoby czekają na Finanse tylko z powodu konta zespołu z tym samym nazwiskiem.
4. **Osoba z dwoma NIP-ami ze swoim nazwiskiem** (zmiana działalności, nowy NIP
   z jednym miesiącem faktur): przebieg wstecz nie zapisuje żadnego
   (`several_nips`). NIP z nowej faktury zapisze reguła w `consider`, gdy spełni próg.
5. **Po zapisie osoba przestaje dostawać podpowiedzi z innych NIP-ów**, tak jak po
   zatwierdzeniu przez Finanse. Zmieniony NIP poprawia się w karcie kandydata.

## Przebieg wstecz (raz po wdrożeniu)

- `contractor_nip.backfill_once` biegnie z pętli zakupów KSeF
  (`hr_loops.ksef_fetch_job`) przed pobraniem, więc pierwszy przebieg po wdrożeniu
  od razu wiąże faktury jako `known`. Nie ma nowej pętli w lifespanie.
- Znacznik `app_settings['contractor_nip_backfill_2026_11']`: `executed_at`,
  liczniki z powodami i ID osób z zapisanym NIP-em (do cofnięcia bez szukania
  w logach). Wyłączony moduł rozliczeń = przebieg czeka. Drugi proces nie startuje
  (`pg_try_advisory_xact_lock`).
- Ta sama reguła na całej historii, pogrupowana po NIP-ie. Zapisuje tylko
  `candidates.nip` osób bez NIP-u i zatwierdza istniejące podpowiedzi tego NIP-u.
  Wierszy `client_contractor_invoices` z historii nie tworzy.
- Każda osoba we własnym SAVEPOINT. Awaria nie zatrzymuje pobierania faktur;
  przebieg ponowi następny tick pętli.
- Na sucho: `contractor_nip.backfill(db, today=…, now=…, dry_run=True)` (te same
  liczniki bez zapisu), decyzja dla każdego NIP-u: `contractor_nip.plan`.

Pomiar na sucho na kopii produkcji z 25.11.2026 (staging, transakcja tylko do
odczytu): 776 NIP-ów w dokumentach, 373 osoby dostałyby NIP (z 425 osób
z kontraktem w indeksie bez NIP-u), w tym wszystkie 6 czekających podpowiedzi.
Pominięte: 99 NIP-ów już przypiętych, 241 bez osoby w nazwie (dostawcy, inkubator),
54 osób spoza kontraktów w indeksie (37 z zespołu), 5 z imiennikami, 3 wspólne
(część dokumentów bez osoby), 1 z jednym miesiącem. Faktury „Benefit” na tej
historii nie dodały żadnego NIP-u (każdy NIP z dowodem miał już dwa miesiące
zakupów), a na 155 NIP-ach z obu źródeł wskazały tę samą osobę co zakupy.

## Testy

`tests/test_contractor_nip.py` (reguła bez bazy, awaria przebiegu wstecz w pętli),
`tests/test_contractor_nip_db.py` (`consider`, przebieg wstecz na sucho i z zapisem,
znacznik).
