# Zgody na wydatki i premie poza umową (0483, 20.10.2026)

Artur zatwierdzał mailem („approved”) premie poza umową, subskrypcje,
delegacje, prezenty i szkolenia. Decyzja 20.10.2026: robimy to w NEXUSIE.
Kafelek ma zakładkę „Zgody” w „Ludzie → Akceptacje”, obok urlopów
i timesheetów. Pasek dostaje ikonę „Zgody” tylko u osób, które zatwierdzają.
Do decydującego idzie mail z kwotą i przyciskami. Odpowiedź „approved” na
maila to kolejny etap. Makiety: https://claude.ai/artifact/BMmUXqykCRrfcocgPfHChj.

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
    Decyzję potwierdza się tam, z samego maila nic się nie zatwierdza.
  - Zgoda już rozpatrzona albo u kogoś innego nie daje maila.
  - Mail do autora nie niesie uwagi decydującego (wolny tekst).
- **Moduł `approvals`** w `hr_modules` jest domyślnie wyłączony (admin widzi
  ekrany zawsze). Bramka `require_hr_approvals`, trasy
  `/api/hr/approval-requests` za wyłącznikiem programu. Licznik zakładki to
  `consents` w `GET /api/hr/counts`, osobno od `approvals` (urlopy
  i timesheety).
- **Poza etapem 1** (nie dopisuj „przy okazji”):
  - zatwierdzenie odpowiedzią „approved” (czytnik skrzynki),
  - zastępca zatwierdzającego w czasie urlopu,
  - faktura albo paragon do zgody i dopasowanie faktur kosztowych z KSeF
    (dziś `hr/ksef` zapisuje tylko NIP-y kontraktorów),
  - rejestr subskrypcji z odnowieniami,
  - wygasanie zgody bez zakupu po 30 dniach,
  - dopłata przy fakturze wyższej o więcej niż 10%,
  - prezent w Historii klienta.
