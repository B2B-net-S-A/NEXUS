# Back office jako kolejka spraw — karty, zespoły, kroki, eskalacja, poczta, start
<!-- indeks: moduł `back_office`, `bo_cards`, adaptery źródeł, Biorę/Zastępuję, limit 5, eskalacja po dniu roboczym, kroki wejścia i wyjścia, Ławka 60/14, reguły + AI + Do rozdzielenia, odpowiedź ze sprawy, przegląd przed startem, runbook włączenia -->

Decyzje Artura z 02.11.2026 (makiety: https://claude.ai/artifact/5ZaNZYJvVHJz1cKqAH1E2W,
plan: https://claude.ai/artifact/HUabikQpDcGioAiPpiEEAy). Cały back office pracuje na
jednej kolejce. Ta reguła ma pierwszeństwo przed opisem „Do zrobienia” w
`opieka-mapa-technologii-i-sprawy.md`, gdy moduł `back_office` jest włączony.

## Zasady, których nie cofamy przy okazji

- **Rekord źródłowy zostaje prawdą.** Karta (`bo_cards`) nigdy nie zmienia premii,
  raportu ani zamówienia sama. Akcept na karcie woła istniejącą trasę z jej
  uprawnieniami, a potem `POST /api/back-office/cards/{id}/refresh`. Bo premia czy mail
  z zamówieniem nie mają gdzie trzymać osoby i terminu, a dwie prawdy się rozjeżdżają.
- **Karta nie liczy swoich reguł.** Przerwy i zmiany w zamówieniach biorą się z
  `build_order_changes`, bo liczby z surowej tabeli różnią się od ekranu Finansów
  (02.11: 14 w tabeli, 6 na ekranie).
- **Tytuł i `meta` bez kwot.** Kwotę dostaje przy odczycie tylko osoba z Płacami,
  także przy „Zastępuję”. Tytuł negocjacji i cudzej sprawy to „Sprawa: <obszar>”, bez osoby
  i klienta.
- **„Zastępuję” nie otwiera sprawy.** Osoba prowadząca przechodzi `may_read`, więc kartę sprawy
  bierze jej zespół albo osoba ze „Sprawami”; negocjacje zespół Umów (`service.reads_case`).
  Notatkę dodaje osoba prowadząca albo zespół, bo przy sprawie to komentarz w sprawie.
- **„Biorę” sprawdza sprawę, nie lustro.** Karta bywa starsza o przebieg pętli, a zmiana z karty
  nie ożywia zamkniętej sprawy (409).
- **Sprawa wyjścia z bezpiecznika znika przy przedłużeniu** (`close_extended_exit_cases`), o ile nie
  ma `terminated_at` ani decyzji „nie przepinamy”. Kroki zamknięte razem ze sprawą wracają, gdy
  ta się otworzy; sprawa otwarta po komplecie kroków czeka na człowieka.
- **Przy sprawie osoba i stan są w `admin_cases`.** Karta je lustruje, przejęcie idzie
  przez `update_case` w tej samej transakcji.
- **Kanban zostaje 1:1 pod „Po statusie”** (warunek z 22.10). Pilnuje
  `frontend/src/lib/work-board-feature-inventory.json`. Stare linki `?card=` i
  `?filter=` dalej otwierają kanban, a `/care` działa obok `/back-office`.
- **„Zrobione” przy rozmowie daje wyłącznie jej zapis, a zamkniętą decyzję da się
  cofnąć.** Oba warunki z 22.10 żyją w kanbanie i ich nie ruszamy.

## Moduł i dostęp

- Wyłącznik: `back_office` w `app_settings['hr_modules']`, także bez podglądu admina
  (`NO_ADMIN_PREVIEW`), bo wszyscy mają zobaczyć kolejkę jednego dnia. Wyłączony moduł
  to dzisiejsza Opieka bez zmian: pętla nic nie robi, plan kontaktów liczy stary rytm.
- Kierownik: head back office (`hr_divisions`), zastępca
  (`app_settings['back_office'].deputy_user_id`), admin.
- Zespół: `bo_team_members`. Dopóki tabela jest pusta, zespół wynika z uprawnień
  (`access.default_teams`), żeby włączenie przed spisaniem składu nikogo nie odcięło.
  Pierwszy wpisany wiersz wyłącza to dla wszystkich.
- Członek zespołu Opieka bez uprawnienia „Sprawy” nie otworzy pełnego ekranu sprawy, więc
  przed startem trzeba je nadać. Nadaje admin w „Osoby i role”.

## Kolumny i źródła (`services/back_office/sources.py`)

Opieka: Pomoc (sprawy administracyjne, kontakt 7. dnia, kontakt po ocenie 1–2), Wejścia,
Ławka, Wyjścia. Finanse: Raporty, Premie (jedna karta na okres), Faktury konsultantów,
Zmiany w zamówieniach (audyt poprzedniego miesiąca). Umowy: Do umowy, Podpis, Aneksy i
stawki, Zakończenia. Zamówienia: Poczta zamówień, Przerwy, Przedłużenia (45 dni), Zużycie MD.

- Adapter zwraca karty, które powinny stać; synchronizacja domyka resztę. Awaria adaptera
  nie domyka jego kart ani nie wstrzymuje reszty (punkt zapisu na rodzaj).
- „Nie dotyczy” (`meta.dismissed`) nie wraca, choć źródło dalej ją liczy; inna zamknięta
  karta wraca, gdy źródło wraca. Przeniesiona ręcznie (`lane_locked`) zostaje w kolumnie.
- Pętla `back_office_sync` co 5 minut, na stagingu zablokowana (dzwonki): tam „Odśwież”
  kierownika albo `POST /api/back-office/sync`.

## Reguły pracy

- **„Biorę”**: blokada wiersza i `expected_updated_at`, kolizja = 409 z `detail.code`
  (`taken`, `stale`, `limit`, `priority`, `closed`). **Limit 5 w toku** blokuje tylko nowe
  „Biorę”; przydział kierownika go nie sprawdza.
- **„Zastępuję”**: karta innego zespołu, bez kwot i bez akceptów (`substituting`).
- **Pierwszeństwo**: osoba, która rozmawiała z konsultantem w 90 dniach, ma 3 dni na
  kartę Opieki. Inni biorą przez „Biorę mimo to”. Eskalacji to nie przesuwa.
- **Eskalacja**: bez osoby o tej samej godzinie następnego dnia roboczego (kalendarz firmy),
  karty z akceptem się nie eskalują. Jeden dzwonek zbiorczy `back_office_escalated`.
- **Kroki** (`steps.py`) stoją na sprawach `contract:<id>:end|start`, więc moduł `lifecycle`
  zostaje wyłączony. Krok zalicza się sam ze źródła albo ręcznie i odhacza checklistę;
  wszystkie zrobione = sprawa `done`. Krok własnego zespołu widać w panelu sprawy,
  cudzego także w kolumnie zespołu.
- **Ławka**: karta 60 dni przed końcem. **Bezpiecznik 14 dni**: sprawa wyjścia powstaje też
  bez decyzji, bo dostępy nie mogą czekać na rozmowę. „Nie przepinamy” zakłada ją od razu.
- **Rytm** przy włączonym module: tylko 7. dzień i 60 dni przed końcem (`important_only`),
  plus karta po rozmowie z oceną 1–2.

## Poczta

- Zgłoszenia z maila i portalu rozdziela `triage.py`: jedna reguła wygrywa, bez reguły pyta
  model (`case_triage`, F42), a niepewność, awaria albo sprzeczność idą do „Do rozdzielenia”
  u kierownika. Rozstrzyga się raz na kartę. Wynik modelu nigdy nie blokuje ścieżki.
- Odpowiedź ze sprawy (`admin_cases/reply.py`, `POST /api/cases/{id}/reply`) wychodzi w wątku
  Graph tylko z kliknięcia obsługi. Własny mail wraca przez czytnik jako `direction = out`
  i nie zakłada sprawy ani nie otwiera zamkniętej.

## Start (runbook)

Poza kodem, przed włączeniem: head back office w „Struktura”, zastępca, skład zespołów,
uprawnienie „Sprawy” dla zespołu Opieka, `wsparcie@` w M365 (`ADMIN_CASES_MAILBOX` przez
workflow „Coolify set env”), czytnik (`ADMIN_CASES_MAIL_INGEST_ENABLED`), potwierdzenie, że
Compass nie prowadzi już spraw, FAQ, IOD.

1. Wdrożenie kodu w oknie (moduł wyłączony: nic się nie zmienia). `/api/health` = SHA z maina.
2. Włączyć `back_office` w Ustawienia → Kadry → Moduły, w oknie wdrożeń.
3. `POST /api/back-office/sync` albo „Odśwież”: karty powstają, stare sprawy mają `needs_review`.
4. Kierownik robi „Przegląd przed startem” i klika „Zakończ przegląd”.
5. `python -m scripts.close_overdue_contact_plan` (na sucho), a po zgodzie Artura `--apply`.
6. Wpis w `novelties.json` (`tier: process`, `path_prefix: /back-office`) małym PR-em tego
   dnia: wcześniej ludzie dostaliby nowość do ekranu, którego nie mają.

Wycofanie: wyłączyć moduł. Menu wraca do „Opieki”, `/care` działa jak wcześniej, karty zostają
w bazie, plan kontaktów wraca do starego rytmu przy nocnym przebiegu. Portal konsultanta zamyka się
razem z modułem (`portal_settings.load`), także dla ludzi z zewnątrz.
