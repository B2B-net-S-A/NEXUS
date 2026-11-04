# Zgody na wydatki i premie poza umową (0483, 20.10.2026)

Artur zatwierdzał mailem („approved”) premie poza umową, subskrypcje,
delegacje, prezenty i szkolenia. Decyzja 20.10.2026: robimy to w NEXUSIE.
Kafelek ma zakładkę „Zgody” w „Ludzie → Akceptacje”, obok urlopów
i timesheetów. Pasek dostaje ikonę „Zgody” tylko u osób, które zatwierdzają.
Do decydującego idzie mail z kwotą i przyciskami. Etap 2 (też 20.10.2026):
odpowiedź „approved” na ten mail zatwierdza zgodę — niżej „Odpowiedź mailem”.
Makiety: https://claude.ai/artifact/BMmUXqykCRrfcocgPfHChj.

- **Premie z umowy nie przechodzą przez zgody.** Placementy, ligi i reguły
  Płac liczą się same (automat premii). Zgoda to tylko to, czego nie ma
  w umowie ani w regułach: premia uznaniowa, nagroda, wyjątek, wydatek.
- **Tabela `approval_requests`** (`services/hr_approvals_schema.py`, model
  `models/hr_approval.py`). Rodzaje: `bonus`, `subscription`, `trip`,
  `gift`, `training`, `other`. Stany: `pending_supervisor`,
  `pending_final`, `approved`, `rejected`, `returned` (pytanie do autora —
  poprawia i wysyła znowu, `PUT`), `withdrawn`. Premia ma osobę i miesiąc
  wypłaty, jest raz i brutto (CHECK `bonus_shape`). Nikt nie decyduje we
  własnej sprawie ani o premii dla siebie — CHECK w bazie i 403 w serwisie.
- **Premia dla B2B ma podstawę w umowie** (0491, decyzja Artura 21.10.2026).
  Uznaniowa nagroda od koordynatora to dla PIP cecha wynagrodzenia ze stosunku
  pracy (od 08.07.2026 PIP może sam stwierdzić stosunek pracy). Dlatego:
  - wniosek o premię dla osoby z formą B2B albo z formą „do uzupełnienia”
    (`employment_type_pending`, kartoteka z konta) wymaga pola „Podstawa
    w umowie” (`approval_requests.contract_basis`, do 200 znaków): punkt umowy
    albo numer aneksu, np. „§ 6 ust. 2 umowy z 01.03.2025”. Bez niej albo bez
    żadnej cyfry w tekście — 422 przy wysłaniu i przy poprawce
    (`service.needs_contract_basis`, `_assert_bonus_allowed`);
  - umowa o pracę i zlecenie bez zmian — pole jest, ale nieobowiązkowe;
  - podstawa jest tylko przy premii (CHECK `ck_approval_requests_contract_basis`,
    422 przy wydatku). Formy nie zapisujemy w zgodzie — liczy się kartoteka
    w chwili wysłania;
  - `GET /beneficiaries` niesie `needs_contract_basis`, więc formularz oznacza
    pole jako wymagane; podstawa jest w szczególe zgody, w „Moich zgodach”,
    w mailu do zatwierdzającego i w Płacach: opis premii „Premia poza umową ·
    podstawa: …” (widzi go też osoba w „Moim czasie” — to punkt jej umowy)
    i `rule_snapshot.contract_basis`;
  - podstawa to tekst, nie wybór z rejestru: umowy zespołu (`hr_agreements`)
    są w większości poza NEXUSEM, a `b2b_contract_documents` to umowy
    konsultantów z klientami. Słowa formy („wynagrodzenie dodatkowe”,
    „koordynator”) zmienia osobna praca.
- **Droga** (`services/hr/approvals/service.py`, `route`):
  - Premia: prosi Płace albo przełożony osoby
    (`PayrollViewer.manages_bonuses_of`). Wniosek przełożonego to jego
    poparcie, więc idzie prosto do zatwierdzającego.
  - Wydatek: najpierw przełożony autora (`recipients.supervisor_of`,
    przełożony z kartoteki albo head pionu). Kadry jako zapas się nie liczą,
    bo Kadry nie decydują o wydatkach. Do progu przełożony zatwierdza sam,
    ponad próg jego „Zatwierdź” to poparcie i sprawa idzie do
    zatwierdzającego. Inną kwotę ustala tylko decyzja zamykająca sprawę.
    Autor bez przełożonego (zarząd) trafia od razu do zatwierdzającego.
  - Zatwierdzający decyduje na każdym etapie.
- **Zasady** `app_settings['hr_approval_rules']`
  (`services/hr/approvals/rules.py`, `GET/PUT /rules`, tylko admin):
  - `final_approver_user_id` — puste albo nieaktywne konto = aktywni admini;
  - `supervisor_limits[rodzaj]` — brutto w PLN, `null` = nigdy. Domyślne
    progi z makiety: premia i subskrypcja `null`, delegacja 1500, prezent
    200, szkolenie 1000, inny 500.
  - Do progu liczy się: netto ×1,23, co miesiąc ×12, inna waluta = zawsze
    zatwierdzający (w NEXUSIE nie ma kursów).
- **Po zatwierdzeniu premii** powstaje przyznana premia w Płacach:
  `hr_bonuses`, `source='manual'`, kategoria „Inna”, `proposed_by` = autor,
  `assigned_by` = zatwierdzający, `rule_snapshot.approval_request_id`.
  Płace jej drugi raz nie zatwierdzają. Zamknięty miesiąc wypłaty = 409
  i zgoda zostaje do decyzji. Miesiąc wypłaty mieści się w oknie od
  poprzedniego do dwóch kolejnych. Kontekst decyzji („NEXUS sprawdził”,
  `context_for`) rozdziela premie osoby w roku na automatyczne, poza umową
  (z `approval_request_id`) i inne ręczne.
- **Dzwonki i mail.** `hr_approval_requested` idzie do decydującego na
  danym etapie: przełożony albo zatwierdzający, nigdy oba naraz.
  `hr_approval_decided` idzie do autora. Oba mają temat `other` (dymek)
  i mail „Czas i ludzie”.
  - Mail do decydującego składa `services/hr/approvals/mail.py`, z kwotą,
    „po co” i przyciskami. To świadomy wyjątek od `hr_mail.py`, który kwoty
    wycina.
  - Przyciski otwierają NEXUS na zgodzie z `&decide=approve|reject`.
    Decyzję potwierdza się tam. Bez przycisku zatwierdza tylko odpowiedź
    mailem (etap 2, niżej).
  - Zgoda już rozpatrzona albo u kogoś innego nie daje maila.
  - Mail do autora nie niesie uwagi decydującego (wolny tekst).
- **Moduł `approvals`** w `hr_modules` jest domyślnie wyłączony (admin widzi
  ekrany zawsze). Bramka `require_hr_approvals`, trasy
  `/api/hr/approval-requests` za wyłącznikiem programu. Licznik zakładki to
  `consents` w `GET /api/hr/counts`, osobno od `approvals` (urlopy
  i timesheety).
- **Poza etapami 1–3** (nie dopisuj „przy okazji”):
  - zastępca zatwierdzającego w czasie urlopu.

## Odpowiedź mailem (etap 2, 20.10.2026)

Decyzja Artura: odpowiedź „approved” z jego adresu zatwierdza zgodę. Kod:
`services/hr/approvals/mail_reply.py` (znacznik, rozpoznanie słowa),
`mail_reader.py` (czytnik skrzynki), pętla `hr_approval_mail_replies`
w `tasks/hr_loops.py` co 2 minuty.

- **Włączenie**: `HR_APPROVALS_MAIL_REPLY_ENABLED=true`
  i `HR_APPROVALS_REPLY_MAILBOX` (skrzynka M365, `zgody@b2bnetwork.pl`),
  plus moduł `approvals`, `HR_PROGRAM_ENABLED` i `HR_LOOPS_ENABLED`. Bez
  którejkolwiek mail jest jak w etapie 1 (bez Reply-To i znacznika), a czytnik
  niczego nie czyta.
- **Mail do decydującego** ma wtedy Reply-To na skrzynkę zgód
  (`send_email(reply_to=…)`, tylko dla `hr_approval_requested`), znacznik
  `[Zgoda <id>/<kod>]` na końcu tematu i zdanie „Możesz też odpowiedzieć…
  „approved”…”. Kod to HMAC z `SECRET_KEY` po numerze zgody i
  `submitted_at`: sam numer nic nie zatwierdzi, a odpowiedź na wersję sprzed
  poprawki autora („stale”) nic nie robi. Zmiana `SECRET_KEY` unieważnia
  odpowiedzi na maile wysłane wcześniej — to w porządku, przyciski działają.
- **Kto**: nadawca `from` = e-mail aktywnego konta, które według `can_decide`
  może TERAZ zdecydować; `sender` ≠ `from` (w czyimś imieniu) = nic.
  Exchange musi potwierdzić nadawcę (`authenticated`, fail-closed):
  `X-MS-Exchange-Organization-AuthAs: Internal` albo `dmarc=pass`, bez
  `fail`/`softfail` w `Authentication-Results`. Na MX (home.pl) nie polegamy —
  na adres domeny w M365 da się wysłać wprost przez
  `*.mail.protection.outlook.com`.
- **Blokada**: zgoda jest blokowana (`FOR UPDATE`) przed sprawdzeniem kodu,
  więc poprawka autora nie wejdzie między sprawdzenie a decyzję.
- **Co**: liczy się tylko nowa treść — HTML ucięty na podpisie i cytacie
  Outlooka (`Signature`, `_MailAutoSig`, `appendonsend`, `divRplyFwdMsg`,
  `<hr>`, `blockquote`), tekst na „Od:”/„From:”, „W dniu … napisał”, „>”.
  - Samo słowo w pierwszej linii (`approved`, `approve`, `ok`, `okay`, `okej`,
    `zgoda`, `tak`, `zatwierdzam`, `akceptuję`; bez znaczenia wielkość liter
    i końcowe „.”/„!”), dalej najwyżej podpis = `decide(approve)`. Podpis
    zaczyna się od „--”, imienia albo imienia i nazwiska konta, „Sent
    from…” albo zwrotu („Dzięki”, „Pozdrawiam”), po którym jest koniec albo
    imię — „tak / Dzięki / ale do 500 zł” to treść. U przełożonego
    ponad próg to poparcie, jak przycisk.
  - Każda inna niepusta treść („ok?”, „not approved”, „ok, ale do 500 zł”,
    „nie”) = `decide(return)` z treścią jako pytaniem do autora (wariant
    wybrany przez Artura 20.10.2026). Odrzuca się tylko w NEXUSIE.
  - Pusta odpowiedź, autoodpowiedź, mail bez znacznika = nic.
  - Kanał decyzji `mail_reply` (`decision_channel`, audyt).
- **Idempotentnie**: skróty przetworzonych wiadomości leżą w
  `app_settings['hr_approval_mail_reader']` razem ze znacznikiem czasu,
  zapisywane w tej samej transakcji co decyzje; wiersz jest blokadą przebiegu
  (`FOR UPDATE SKIP LOCKED`). Zgoda już rozpatrzona dostaje „already_decided”.
  Wiadomość, która 3 razy padła, jest pomijana.
- **Odpowiedź od decydującego, której nie zapisaliśmy** — nieuwierzytelniona,
  na wersję sprzed poprawki, odmowa serwisu (np. zamknięty miesiąc wypłaty
  premii), zgoda już u autora, odrzucona albo wycofana — daje mu dzwonek
  i krótki mail „Odpowiedź w sprawie zgody nie została zapisana”
  (`hr_approval_requested`, `related_entity_type='approval_mail_reply'`,
  BEZ `related_entity_id` — dzienny dedup `ix_notif_dedup_daily` liczy
  osobę, typ i id encji, bez rodzaju, więc z id zgody połknąłby go razem
  z dzwonkiem „zgoda do decyzji”). Bez kwoty i bez treści odpowiedzi, bez
  Reply-To. Obcym adresom nic nie wysyłamy.
- **Stan czytnika** bez adresów i treści: `mail_reader.read_status`
  (liczniki `approved`, `endorsed`, `returned`, `stale`, `unauthenticated`,
  `refused`, `foreign_sender`,
  `not_decider`, `already_decided`, `no_marker`, `auto_reply`, `empty`).

### Runbook włączenia (Codex / Artur)

1. Exchange Online (admin): skrzynka współdzielona bez licencji
   `New-Mailbox -Shared -Name "NEXUS Zgody" -PrimarySmtpAddress zgody@b2bnetwork.pl`.
2. Dostęp czytnika: `Add-DistributionGroupMember -Identity
   nexus-kadry-skrzynki@b2bnetwork.pl -Member zgody@b2bnetwork.pl` (zakres
   RBAC for Applications rejestracji „NEXUS Kadry”; NIE dodawać `Mail.Read`
   w Entra — działałby na całą firmę). Sprawdzenie:
   `Test-ServicePrincipalAuthorization -Identity <AppId NEXUS Kadry>
   -Resource zgody@b2bnetwork.pl` → `Mail.Read` `InScope = True`.
3. Mail testowy z Outlooka Artura na `zgody@` ląduje w Inbox tej skrzynki.
4. Zmienne przez workflow „Coolify set env” (gałąź `main`, `redeploy=false`):
   `HR_APPROVALS_REPLY_MAILBOX=zgody@b2bnetwork.pl`, potem
   `HR_APPROVALS_MAIL_REPLY_ENABLED=true`. Wchodzą przy zwykłym „Deploy”
   w oknie 19:00–07:00 (pon–pt), w weekend o każdej porze.
5. Próba: zgoda testowa na kilka złotych do Artura → odpowiedź „approved”
   → po ok. 2 minutach status `approved`, kanał `mail_reply`. Druga próba
   „a po co?” → „Pytanie” u autora. Jeśli przyszedł mail „Odpowiedź…
   nie została zapisana” z „Nie dało się potwierdzić…” (licznik
   `unauthenticated`), Graph nie oddał `AuthAs`/`dmarc=pass` dla poczty
   wewnętrznej — sprawdzić nagłówki tej wiadomości i poprawić
   `mail_reader.authenticated`, nie wyłączać sprawdzenia. Jeśli samo „approved” wróciło jako
   pytanie z treścią podpisu — podpis Artura nie jest rozpoznany; dopisać
   jego początek do `_SIGN_OFF` w `mail_reply.py`.
6. Wyłączenie: `HR_APPROVALS_MAIL_REPLY_ENABLED=false` + Deploy — maile
   wracają do postaci z etapu 1, czytnik staje.

## Etap 3 — rozliczenie w Finansach (0486, decyzje Artura 20.10.2026)

Makiety: plansze 4 i 5 w https://claude.ai/artifact/BMmUXqykCRrfcocgPfHChj.
Schemat `services/hr_approval_settlement_schema.py`, serwis
`services/hr/approvals/settlement.py` (+ `cost_invoices.py`, `finance_views.py`,
`reader.py`, `store.py`), trasy autora w `api/hr_approvals.py`, Finanse
w `api/hr_approval_finance.py` (`/api/finance/approved-expenses`).

- **Decyzje Artura (20.10.2026):**
  - faktura z KSeF pasująca do zgody przypina się sama, ale „Rozliczone”
    klika osoba z Finansów — automat niczego nie rozlicza;
  - „Wydatki ze zgodą” widzi uprawnienie „Moduł Finanse” (`FinanceModuleUser`)
    i admin; premie poza umową są tam tylko sumą miesiąca, bez osób
    (szczegóły premii zostają w Płacach, D2); premia nie ma rozliczenia;
  - do „Faktur bez zgody” trafia każda niedopasowana faktura kosztowa;
    Finanse oznaczają sprzedawcę jako „stały koszt” (`approval_fixed_cost_sellers`)
    i jego faktury przestają wpadać do kolejki (obecne przechodzą od razu);
  - faktury kosztowe zapisujemy **z samych metadanych KSeF** (sprzedawca,
    numer, data, kwoty), bez pobierania XML-a i bez pozycji — limit pobrań
    zostaje dla faktur kontraktorów.
- **Rozliczenie zgody** (`approval_requests.settlement_status`, ustawia
  `settlement.on_approved` w `decide`): wydatek raz `open` → `documented` →
  `settled` i **bez dokumentu nie wygasa** (decyzja Artura 22.10.2026, audyt
  22.10 F21) — delegacja czy szkolenie zatwierdzone na dwa miesiące przed
  terminem rozliczają się rachunkiem po wydarzeniu, więc `expires_on` zostaje
  puste, a `expire_stale` pomija `recurrence = 'once'` (zgody „raz” sprzed
  decyzji mają jeszcze datę z backfillu 0486; payloady nie pokazują jej przez
  `settlement.expiry`, a lista „Czeka na fakturę” w Finansach nie ma „wygasa”
  i idzie od najstarszego zatwierdzenia). Zgody „raz”, które przed F21 zdążyły
  wygasnąć, wracają do `open` bez terminu dopiero po uruchomieniu narzędzia
  `python -m app.cli.hr_one_off_expiry_restore` (najpierw liczby z
  `backend/scripts/hr_one_off_expired_report.sql`) po zgodzie Artura (decyzja
  23.10.2026) — samo wdrożenie F21 ich nie przywraca. Cykliczny (subskrypcja,
  „co miesiąc / co rok”) `active` → `ended`, każda faktura rozliczana osobno; bez żadnego
  dokumentu przez 30 dni od startu (`starts_on`, gdy jest późniejszy niż
  zatwierdzenie) → `expired` (pętla `hr_lifecycle` od 8:00, dzwonek do autora,
  potem nowa zgoda) — nic nie kupiono, więc rejestr nie liczy „wiszącej”
  kwoty. Zatwierdzone przed 0486 dostają rozliczenie w migracji.
- **Dokumenty** (`approval_documents`): autor albo Finanse wgrywają PDF/JPG/PNG
  do 10 MB (`store.py`, podkatalog `approval_documents/<zgoda>/` — nie e-teczka,
  bo to papier firmy). Odczyt kwoty, waluty, NIP-u i sprzedawcy robi model
  z rejestru (`expense_document_read`, F32) — to podpowiedź, osoba poprawia
  pola (`PATCH`), awaria albo brak limitu AI zostawia dokument bez odczytu.
  Kwoty i NIP sprzedawcy faktury z KSeF są wiążące (409 przy poprawce). Ta sama faktura wgrana
  i z KSeF (NIP + numer) to jeden wiersz.
- **Dopasowanie KSeF** (`settlement.match_document`): zgoda zatwierdzona,
  otwarta, ten sam NIP sprzedawcy (z formularza, z odczytu pliku albo z
  pierwszej przypiętej faktury) i waluta, prośba nie później niż 30 dni po
  wystawieniu faktury. Kilka takich zgód — wygrywa jedyna, w której kwota się
  mieści, inaczej kolejka (`several`). Korekty idą do kolejki. Najpierw zgoda,
  potem „stały koszt”. Ręczne przypięcie zapamiętuje NIP przy zgodzie, więc
  następna faktura subskrypcji przypina się sama. Nowa zgoda z NIP-em próbuje
  przypiąć faktury z kolejki (`rematch_seller`). Pobieranie: `ksef/sync.py`
  `_store_cost`, licznik `costs` — tylko przy włączonych modułach „Rozliczenia”
  (pętla KSeF) i „Zgody” oraz tokenie KSeF.
- **Próg 10%**: wydatek raz porównuje sumę dokumentów, cykliczny — każdą
  fakturę z kwotą zgody (podstawa netto/brutto ze zgody; inna waluta albo
  brak kwoty = porównuje człowiek). Ponad zgoda + 10% + zatwierdzone dopłaty
  = „Poproś o dopłatę” (autor albo Finanse, jeden przycisk) → dzwonek
  `hr_approval_topup_requested` do zatwierdzającego, decyzja w
  „Akceptacje → Zgody” (`GET /topups`, licznik `consents`) i dzwonek do autora.
  „Rozliczone” przy fakturze ponad próg bez dopłaty = 409; po odrzuconej
  dopłacie Finanse rozliczają z obowiązkową notatką.
- **Nikt nie rozlicza własnego wydatku** (403); autor nie decyduje o swojej
  dopłacie.
- **Subskrypcje**: rejestr z zatwierdzonych zgód cyklicznych; roczna ma
  `renews_on` (rocznica startu albo zatwierdzenia). 30 dni przed odnowieniem
  opiekun (autor) dostaje raz `hr_subscription_renewal` i odpowiada
  „Dalej potrzebna” / „Wyłącz” (`POST /{id}/renewal`); minione odnowienie bez
  odpowiedzi przesuwa się o rok. Poranny skrót zatwierdzającego i Finansów
  ma linię „Odnowienia roczne subskrypcji w ciągu 30 dni” (admin bez ról
  ze skrótu go nie dostaje — `DIGEST_ROLES`).
- **Prezent dla klienta**: pole klienta tylko przy prezencie (422 przy innym
  rodzaju); po zatwierdzeniu wpis `client.gift` w Historii zdarzeń klienta
  (`critical_events`, z kwotą i numerem zgody).
- **Delegacja**: po zatwierdzeniu dni robocze `starts_on`–`ends_on` autora
  (z kartoteką) dostają obecność `business_trip`; dzień urlopu zostaje urlopem;
  delegacja dłuższa niż 62 dni nie trafia do obecności (pomyłka w datach).
- **Poza etapem 3**: „Zapytaj, kto kupił” przy fakturze bez zgody, „nieużywane
  60 dni” przy subskrypcji, sprzęt z zakupu w module Sprzęt.

## Ukryte do odwołania — także dla admina (decyzja Artura 21.10.2026)

Wydatki i premie poza umową na razie idą mailem, jak przed NEXUSEM. Moduł
`approvals` jest wyłączony, a w przeciwieństwie do innych modułów „Ludzi”
admin nie ma podglądu wyłączonych „Zgód” (`NO_ADMIN_PREVIEW` w
`services/hr/modules.py`). Znikają: Akceptacje › Zgody, „Moje zgody”, ikona
w pasku, Finanse › „Wydatki ze zgodą”, karta „Zasady zgód” w Ustawieniach,
trasy `/api/hr/approval-requests` i `/api/finance/approved-expenses` (404).
Powrót = włączenie „Zgód” w Ustawienia → Kadry → Moduły; nic nie trzeba
wdrażać. Nie przywracaj podglądu admina „przy okazji” — to on pokazywał moduł
Arturowi mimo wyłączonego przełącznika.
