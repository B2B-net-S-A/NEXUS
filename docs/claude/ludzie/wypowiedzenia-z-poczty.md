# Wypowiedzenia z poczty — karta „do potwierdzenia” w back office, archiwum administracja@ przy kontrakcie
<!-- indeks: notice_mail_proposals, known_sender_emails, archived_mails, 0757, notice_rules, notice_mail, notice_view, propose_for_message, /api/back-office/notices, /api/contracts/{id}/mails, NoticeProposalPanel, ContractMailFeed, CPro „Contract terminated”, wycofanie wypowiedzenia z maila, imie.nazwisko@b2bnetwork.pl, import_admin_mail_archive, archive_eml_to_jsonl -->

Decyzje Artura z 23.11.2026 (makiety: https://claude.ai/artifact/1npkbSQfNQEkho441q8JMH).
Wypowiedzenia, skrócenia zamówień przez klienta, zmiany dat i wycofania przychodzą mailem
na administracja@ i rozliczenia@ (od 18.11 kopie w wsparcie@), a zespół przepisywał je
ręcznie albo wcale: kontrakt #29 miał wypowiedzenie z 31.10 w Dokumentach, a 23.11 dalej
stał „Aktywny” bez daty końca i z zamówieniem do 31.01.2027.

## Zasady, których nie cofamy przy okazji

- **Automat proponuje, człowiek potwierdza.** Czytnik spraw (`mail_ingest._propose_notice`)
  zapisuje propozycję (`notice_mail_proposals`), ale nie zmienia kontraktu, zamówienia ani
  `admin_cases.contract_id`. Zły kontrakt albo zła data doręczenia przesunęłyby okres
  wypowiedzenia i zakaz konkurencji niewłaściwej osobie. Decyzja Artura: „karta + jedno
  Potwierdź”, nie samodzielny zapis.
- **Karta woła istniejące trasy z ich uprawnieniami**, a potem zapisuje decyzję
  (`POST /api/back-office/notices/{id}/decision`): wypowiedzenie → `POST /api/contracts/{id}/terminate`
  z rozwiązaniem umowy (ta sama ścieżka co „Zakończ współpracę”, więc zamówienia i sprawa
  wyjścia ruszają jak zawsze), klient kończy i zmiana daty → `PATCH /api/clients/{c}/orders/{o}`,
  wycofanie → `POST /api/contracts/{id}/notice-withdrawal`. Decyzja sprawdza, że zmiana się
  stała (409 `not_terminated`, `not_withdrawn`), łączy sprawę z kontraktem, uczy adresu nadawcy
  i zamyka sprawę z maila z komentarzem.
- **Jedna sprawa = jedna karta.** Propozycja nie jest osobną kartą: sprawa z maila z czekającą
  propozycją staje pod etykietą „Zakończenie” (Umowy), a chip pokazuje rodzaj
  (`notice_rules.KIND_LABELS`). Nie dokładaj kolumny ani `source_kind` — CHECK-i `bo_cards`
  by się zmieniły, a rodzaj mieści się w `meta`.
- **Reguły czytają tylko świeżą część maila** (`notice_rules.fresh_text`). „Re: Wypowiedzenie”
  cytuje oryginał; bez tego każda odpowiedź byłaby nowym wypowiedzeniem. W wątku z rozpoznanym
  końcem szukamy tylko wycofania i zmiany daty — „Re: Contract terminated” od PM-a to zmiana
  daty, nie drugi koniec.
- **Data z wzoru umowy, nie zgadywana.** Ostatni dzień liczy `notice_end_date` z wersji wzoru
  kontraktu (`b2b_generated_contracts.template_version`); bez wersji — wzór 2026 i karta mówi
  „sprawdź w umowie”. Mail po godzinach albo w weekend dostaje drugą datę (doręczenie od
  następnego dnia roboczego) do wyboru przez człowieka.
- **Treść maili przy kontrakcie tylko dla osób, które widzą kwoty klienta** (`GET /api/contracts/{id}/mails`,
  `can_read_client_finance`). Konsultanci piszą w mailach stawki; reszta widzi nadawcę, temat i datę.

## Dopasowanie kontraktu (`notice_mail.match_contract`)

1. kontrakt przypięty do sprawy (uwierzytelniony nadawca — `contract_links`),
2. numer umowy z tematu albo treści („1234/2026”) → umowa z Generatora,
3. numer CPro → linia zamówienia o tym tytule (zamówienia Nordei mają numer CPro w tytule),
4. adres nadawcy z kontraktu, profilu albo `known_sender_emails`,
5. imię i nazwisko z adresu `imie.nazwisko@…`, z nazwy nadawcy albo z tabeli CPro — tylko
   jeden żywy kontrakt o tym kluczu osoby. Kilka = karta pyta „Kogo dotyczy?”.

**Adresy @b2bnetwork.pl.** Konsultanci piszą z adresów firmowych z home.pl, których żaden
z 510 żywych kontraktów nie miał (23.11.2026). Po potwierdzeniu karta zapisuje adres w
`known_sender_emails` (pole „Zapamiętaj … przy tym konsultancie”, domyślnie włączone, gdy
adres jest nowy). Adresu przypisanego innej osobie nie nadpisujemy.

## Archiwum administracja@

- Lokalnie: `~/NEXUS-dane/archiwum-home-pl-pelne/administracja` (5 875 .eml + manifest
  z SHA-256, zweryfikowane 20.11.2026), kopia na SharePoincie (witryna „ArchiwumHomePl”)
  i w PST. Archiwum zostaje źródłem; NEXUS trzyma kopię treści bez załączników.
- Import (decyzja Artura: do historii kontraktów, bez zakładania spraw):
  `python3 -I backend/scripts/archive_eml_to_jsonl.py --root … --mailbox administracja --out x.jsonl`
  na laptopie, potem w kontenerze backendu `python -m scripts.import_admin_mail_archive`
  (na sucho), `--apply` (zapis, klucz SHA-256, ponowny bieg nic nie dubluje) i
  `--report-2026` (CSV wątków wypowiedzeń 2026 wobec kontraktów, tylko id — wynik idzie
  do Artura, nie do repo). Zapis na produkcji tylko po zgodzie Artura w czacie.

## Start

Karty pojawią się dopiero, gdy czytnik spraw czyta wsparcie@ (`ADMIN_CASES_MAIL_INGEST_ENABLED=true`,
`jedna-skrzynka-wsparcie.md`). Do tego czasu kod nic nie robi. Pierwszy bieg czyta 3 dni wstecz,
więc maile, które nie mają być sprawami, trzeba wcześniej przenieść z Inbox.
