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
- **Poza etapami 1 i 2** (nie dopisuj „przy okazji”):
  - zastępca zatwierdzającego w czasie urlopu,
  - faktura albo paragon do zgody i dopasowanie faktur kosztowych z KSeF
    (dziś `hr/ksef` zapisuje tylko NIP-y kontraktorów),
  - rejestr subskrypcji z odnowieniami,
  - wygasanie zgody bez zakupu po 30 dniach,
  - dopłata przy fakturze wyższej o więcej niż 10%,
  - prezent w Historii klienta.

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
  (`hr_approval_requested` z encją `approval_mail_reply`, osobno od dzwonka
  „zgoda do decyzji”, więc dzienny dedup `emit` go nie połyka). Bez kwoty
  i bez treści odpowiedzi, bez Reply-To. Obcym adresom nic nie wysyłamy.
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
