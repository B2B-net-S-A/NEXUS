# Audyt NEXUS 25.09.2026 — runda 4

> **Baza:** `c72f411a4` · **Status:** naprawione w PR #1844 (merge 8da65ef74, 26.09.2026). Decyzje: osobę od Cpro ustawia tylko admin albo DL Nordei (wskazana osoba widzi stawki); archiwum pytań zostaje przypięte do otwartych rekrutacji, ocena prepu pomija przypięcia importu; przedłużenie i „Cofnij zakończenie” anulują zaplanowane zastępstwo.
> Oryginalny raport (prywatny artefakt): https://claude.ai/artifact/RzX9M85qz2QpzzTFRU6gDY
> Reguły wynikające z naprawy: `CLAUDE.md`, sekcja „Audyt 25.09.2026 — reguły po naprawie”.

NEXUS · main po PR #1840 (c72f411a, na produkcji) · 25.09.2026

# Audyt, runda 4: poprawki rundy 3 zostawiły 10 luk, nowe moduły mają 17 błędów

Pracowało 9 agentów. Dwóch sprawdzało poprawki rundy 3, jeden szukał luk w uprawnieniach w routerach wcześniej nieprzejrzanych, a sześciu przeglądało logikę najmłodszych modułów: przydział requestów, praktykanta i akademię, follow-upy, QC i Cpro, portale ogłoszeń, archiwum pytań, historię zamówień, przejęcie MD i powrót po przerwie. Wszystko tylko w trybie odczytu. Pozycje z oznaczeniem „potwierdzone” sprawdziłem sam w kodzie. Poprzednie rundy: [1](https://claude.ai/artifact/BtnT7zb5kwPk5gNLvg56x6), [2](https://claude.ai/artifact/Hcs6cYoiaJ187RmuFMZspY), [3](https://claude.ai/artifact/CN4ffWLKsPQYm38pgGN2Dr).

## Trend  **61 → 19 → 2 → 10** błędy w kodzie poprawionym w poprzedniej rundzie (runda 3 poprawiała więcej i w trudniejszych miejscach) **1** luka w uprawnieniach w 30 nieprzejrzanych routerach: rekruter może sam dojść do stawek do klienta **10 / 16 / 5** pozycje wysokie / średnie / niskie w tej rundzie

Poprawki rundy 3 działają w ścieżkach, dla których je pisano, ale każda wprowadziła stan albo regułę, którą czyta jeszcze inne miejsce. Przykłady: podium liczone nową regułą przy numeracji listy liczonej starą, migawka progów przy ostrzeżeniu w Ustawieniach, które mówi co innego, i klauzula SQL, która przez `NULL` wyrzuca stare odrzucone maile. Nowe moduły mają ten sam wzorzec: reguła „nieaktywne konto = brak osoby” działa w jednym miejscu, a w trzech innych nie.

## Czeka na decyzję (stan w chwili raportu)

- **Czy naprawiam?** Proponuję jeden PR ze wszystkim, jak w rundzie 3: 4 agentów i obowiązkowy przegląd kodu po scaleniu. W rundzie 3 przegląd złapał 4 luki, zanim trafiły na produkcję.
- **Osoba od Cpro a stawki do klienta.** Dziś każdy może ustawić osobę od Cpro, także samego siebie, a osoba od Cpro widzi stawki do klienta. Rekruter może więc jednym kliknięciem zobaczyć stawki, których ma nie widzieć. Rekomenduję, żeby kolejka pokazywała stawkę tylko rolom, które widzą ją wszędzie, czyli admin, DL, HoR, TCM i Finanse, a zmianę osoby zostawić wszystkim.
- **Archiwum pytań z Excela.** Import przypina pytania także do otwartych rekrutacji, więc ocena prepu zaczęłaby je liczyć. Rekomenduję przypinać tylko do zamkniętych rekrutacji. Importu jeszcze nie uruchomiono, więc da się to poprawić przed pierwszym uruchomieniem.
- **Zaplanowane „Wejdź za konsultanta” przy przedłużeniu odchodzącego.** Rekomenduję, żeby aneks przedłużenia i „Cofnij zakończenie” anulowały zaplanowane zastępstwo z wpisem w historii zamówienia.

## Wysokie

### Rekruter sam ustawia się jako osoba od Cpro i widzi stawki do klienta `[Uprawnienia]` `[nowy]` `[potwierdzone]`

`api/board_tasks.py:299-302` · `services/board_tasks.py:772-803`

`PUT /cpro/sender` wymaga tylko zalogowania i przyjmuje własne id rekrutera. `GET /cpro/queue` pokazuje `client_rate_*` osobie od Cpro. To łamie decyzję z 23.09, że rekruter nie widzi stawki do klienta. Zostaje tylko wpis w historii.

### Nieaktywna osoba od Cpro ukrywa kolejkę przed wszystkimi, bez możliwości zmiany `[Cpro]` `[nowy]` `[potwierdzone]`

`cpro_sender.py:104-114` · `board_tasks.py:578-582, 677` · `BoardTasksPanel.tsx:131`

Po końcu zastępstwa wraca poprzednia osoba bez sprawdzenia, czy jej konto jest aktywne. Wyłączenie konta też niczego nie czyści. Admin i HoR widzą kolejkę tylko wtedy, gdy nikt nie jest ustawiony, więc przy wyłączonym koncie nie widzi jej nikt. Poranny skrót milczy, a przełącznik osoby wyświetla się tylko przy niepustej sekcji. Kolejka Nordei rośnie po cichu.

### Wyłączone konto na zawsze „pracuje” przy requeście `[Przydział]` `[nowy]` `[potwierdzone]`

`request_allocation_plan.py:187-213` · `request_board.py:145`

Planer zwalnia tylko przypisania automatu bez kandydatów w toku. Przypisanie ręczne albo automat z otwartym procesem osoby, której konto wyłączono, zostaje. Request liczy się jako obsadzony, automat nikogo nie dokłada, pulpit pokazuje osobę, której już nie ma, a filtr „Nikt nie pracuje” go pomija.

### Podium Ligi Mistrzów: dwie osoby na miejscu 1, a „Mój miesiąc” mówi „jesteś #1” niezakwalifikowanemu `[Konkursy]` `[po R3]` `[potwierdzone]`

`ChampionsSection.tsx:383` · `api/competitions.py:~440`

Po rundzie 3 podium liczy `award_order` i pomija niezakwalifikowanych. Lista pod podium numeruje jednak po pełnym rankingu. Lider bez wymaganego placementu stoi pod podium jako „#1”, a na podium jest inny „#1”. `/my-position` liczy miejsce tak samo jak lista.

### Poprawka daty końca po rozwiązaniu podpisanym dokumentem cofa to rozwiązanie `[Umowy B2B]` `[po R2/R3]` `[od agenta]`

`api/contracts.py:3979-4009` · `b2b_documents/effects.py:478-521`

PATCH rozpoznaje „korektę rozwiązanej umowy” tylko po `agreement_termination_mode` na kontrakcie. Dokumenty pochodne, czyli porozumienie i wypowiedzenie Partnera, trzymają tryb wyłącznie na wierszu rejestru. Zmiana daty idzie więc jako reaktywacja: wiersz wraca na „Aktywna” bez trybu, a przy nowej dacie ląduje w „Umowach bez projektu”.

### Ponownie przysłany PDF odrzuconego wcześniej zamówienia jest czytany od nowa `[Poczta zamówień]` `[po R3]` `[potwierdzone]`

`order_mail_ingest.py:630-644` · `order_mail_recheck.py:286`

Wpisy odrzucone przed rundą 3 nie mają `dismissed_from`. Dla nich `NOT (outcome = dismissed AND (NULL OR FALSE))` daje `NULL` i WHERE wyrzuca oryginał. Ten sam PDF w nowym mailu nie jest więc duplikatem: wraca do kolejki, a przy regule automatu może zostać zapisany drugi raz.

### „Cofnij zakończenie” po „Powrocie po przerwie” daje tę samą osobę dwa razy na zamówieniu `[Kontrakty]` `[nowy]` `[potwierdzone]`

`contract_termination_reversal.py:233-256, 534-627`

Zakończony kontrakt zawsze pozwala cofnąć zakończenie. Blokady „ta osoba już wróciła jako nowy kontrakt” nie ma. Wynik: C1 aktywny i C2 w szkicu u tego samego klienta oraz dwie linie tej osoby w jednym zamówieniu MD, po uzupełnieniu z dwoma budżetami.

### Zaplanowane zastępstwo przenosi pulę MD, choć odchodzący dostał przedłużenie `[Zamówienia MD]` `[nowy]` `[od agenta]`

`dl_portal_expiry_scanner.py:256-270` · `order_line_takeover.py:753-824`

Po zakończeniu z datą 30.09 DL planuje zastępcę B od 01.10, a potem klient przedłuża A aneksem. Aneks nie wydłuża linii zamówienia i nie anuluje zastępstwa. 01.10 skaner uznaje szkic B za następcę, zamyka linię A, a automat przenosi całą pulę na B. A pracuje dalej bez puli.

### QC CV blokuje poprawne CV: pusta data końca dawnej pracy liczy się „do dziś” `[QC CV]` `[nowy]` `[potwierdzone]`

`cv_qc.py:363` · `:816-845`

Profil z dwiema rolami bez daty końca, np. od 2021 i od 2012, daje 14,6 roku zamiast 8,75. Nagłówek „8 lat doświadczenia” nie zgadza się wtedy z wyliczeniem, więc blokujące sprawdzenie zwraca 409 przy „CV wysłane”. Akademia ma już regułę „bez daty dalej niż na 1. pozycji = bez dat”, QC jej nie ma.

### Panel „Praktykanci” pokazuje osobę po awansie jako nadal w programie `[Praktykant]` `[nowy]` `[potwierdzone]`

`frontend/src/lib/trainee-panel.ts:30, 107`

Awans ustawia status programu `completed`, a front uznaje za zakończone tylko `ended` i nieistniejące `finished`. Przez 30 dni osoba po awansie ma „Poniżej normy”, liczy się do aktywnych i zaniża kafel „na ile dni starczy pula” o 70 telefonów dziennie.

## Średnie

**16 pozycji**

- **Ustawienia KPI ostrzegają, że zmiana celu „działa od razu dla bieżącego miesiąca”**, a od rundy 3 działa od następnego (`KpiTargetsSettings.tsx:320`). Potwierdzone.
- **Liga kwartalna (10 000 zł) czyta wagi i progi na żywo przy zamrożeniu** (`competitions.py:770`). Zmiana punktacji 2 października działa wstecz na Q3. To bliźniak migawki progów.
- **Wyczyszczenie daty końca (Kończący się → Aktywny) nie zdejmuje znacznika czekającego rozwiązania.** Późniejsze zwykłe zakończenie zamyka umowę jako „rozwiązaną porozumieniem” ze starym trybem (`contracts.py:4035`).
- **Prywatne spotkanie traci ochronę po zmianie typu w NEXUSIE.** Ochrona działa tylko przy typie „meeting”, a typ wydarzenia z Outlooka da się edytować (`m365/sync.py:1100`).
- **Prywatne spotkania starsze niż rok zostają z pełną treścią.** Pełny odczyt obejmuje tylko ±365 dni.
- **Tytuł dla rekrutera nie przelicza się po akceptacji szkicu AI Championa ani po imporcie dokumentu.** `refresh_working_title` jest wołane tylko w trasach `jobs.py`. Potwierdzone.
- **Ręczne zdjęcie z pulpitu zostawia prowadzącego wpisanego przez automat** (`request_allocation.py:618`). Kolejny rekruter automatu nie zostaje prowadzącym.
- **Portale: zmiana ustawień albo nowy opis w trakcie wysyłki przepada.** Migawka zmian nie obejmuje treści, a zlecenie `publish` jest zerowane (`job_portals/service.py:554, 695`). Portale są na produkcji wyłączone.
- **Portale: publikacja poddana po wcześniejszym timeoucie nie zamyka ogłoszenia, które mogło powstać** (`_give_up`, `:704`). To luka w zasadzie z rundy 2.
- **Import archiwum pytań przypina je do otwartych rekrutacji,** a ocena prepu czyta wszystkie przypięte pytania. Wynik to fałszywe oceny „słaby” i dzwonki.
- **Oddzwonienie „później” umówione po końcu programu praktykanta przepada,** a kandydat jest zablokowany na listach przez 60 dni.
- **Nowe minimum stawki z telefonu praktykanta zostawia zgodę „poniżej minimum” ze starej rozmowy** (`trainee_program.py:515-533`). Potwierdzone.
- **Akademia: Luna liczy pracę bez daty końca „do dziś”,** więc zbiorcze „Zatwierdź” wyklucza osobę na zawsze (`academy_rules.py:365`). To bliźniak poprawki z 24.09. Potwierdzone.
- **Poranny skrót nie liczy follow-upów bez dzwoniącego,** choć panel pokazuje je adminowi i HoR (`candidate_followups.py:675 vs 718`). Potwierdzone.
- **Zastępstwo za osobę, której pula wyczerpała się przed odejściem,** wisi bez sygnału. Co noc do logu trafia tylko ostrzeżenie.
- **„Zużycie MD” i „Importy MD” pokazują czerwony alert „inny numer zamówienia”** dla każdej liczby w „Uwagach”, np. „delegacja 445” (`md_consumption_view.py:106`). Potwierdzone.

## Niskie i niepotwierdzone

**5 niskich + 2 do sprawdzenia**

- „Może zacząć: później” zostawia starą datę dostępności, np. przeszłą, czyli „od zaraz”.
- `generate-upload` bez klienta najpierw płaci za podgląd Championa, a dopiero potem odpowiada 422.
- Wycofanie importu archiwum nie zdejmuje przypięć istniejących pytań klienta.
- Poczta głosowa liczy się jako kontakt w follow-upie. Dziś to nieosiągalne, bo CloudTalk jest wyłączony.
- Ustawienie osoby od Cpro z datą „do kiedy” na osobę, która już wrzuca na stałe, zostawia po tej dacie brak osoby.
- _Do sprawdzenia:_ callback M365 odrzuci konto, którego e-mail w NEXUSIE różni się od loginu Microsoft, a `microsoft_upn` jest puste (konta zakładane hasłem).
- _Do sprawdzenia:_ skrzynka z trwale psującym się wydarzeniem robi pełny odczyt kalendarza ±1 rok w każdym biegu.

## Sprawdzone i czyste

**Uprawnienia (30 routerów)**

- rate_benchmarks, rate_cards, service_accounts, oauth_clients, team_structure, competence_team
- md_consumption, client_md_imports, insights_delivery_leads, client_knowledge, client_materials
- priority_work, recruitment_allocation, request_board, request_work_states
- job_board_connection, job_portals, academy, trainee, candidate_followups, cv_qc
- dashboard_metrics, user_dashboard, jarvis, finance (order-changes, order-pdfs), event_history, client_deletion, contract_client_reassign
- Kontrakt bramek sekcji: 33 testy przeszły

**Poprawki rundy 3, które trzymają**

- Skrzynka M365 tylko właściciela, JJIT tylko admin
- Wszystkie wejścia do rekrutacji tylko na Nowych i Screening, łącznie z Jarvisem i wtyczką
- Champion: notatki bez przeliczania, deduplikacja pytań, stawka tylko z cytatu, import bez kasowania notatek
- Migawka opisu publicznego na trzech powierzchniach
- SQL migawki progów, walidacja okresu, liga DL z rolą dodatkową, okna metryk
- R3-1, R3-9, R3-10, rok numeracji, mail odrzucenia (dzierżawa), karta Jarvisa


---

## Notatki weryfikacyjne koordynatora

Surowe notatki z weryfikacji (plik:linia sprawdzone w kodzie). „POTWIERDZONE” = sprawdzone przez koordynatora, bez oznaczenia = zgłoszone przez agenta.

### Audyt runda 4 — potwierdzone (baza c72f411a4)
#### IDOR
- R4-1 POTWIERDZONE [NOWY] wysokie/decyzja: board_tasks.py:299-302 kolejka Cpro pokazuje client_rate osobie od Cpro; PUT /cpro/sender (OperationalUser, _ASSIGNEE_ROLES recruiter/sourcer/tac, także siebie) → rekruter sam się ustawia i widzi stawki do klienta (łamie #1742). Decyzja: stawka tylko CLIENT_RATE_VIEW_ROLES albo zmiana osoby tylko dla nich.
- Czyste: rate_benchmarks, rate_cards, service_accounts, oauth_clients, team_structure, competence_team, md_consumption, client_md_imports, insights_delivery_leads, client_knowledge/materials, priority_work, recruitment_allocation, request_board/work_states, job_board_connection, job_portals, academy, trainee, followups, cv_qc, dashboard_metrics, user_dashboard, jarvis, finance order-changes/pdfs, event_history, client_deletion, contract_client_reassign.
#### Logika — przydział/Champion
- R4-2 POTWIERDZONE [NOWY] wysokie: request_allocation_plan.py:187-213 zwalnia tylko source=auto bez in_process; wiersz manual albo auto z procesem nieaktywnego konta zostaje na zawsze (covered → automat nikogo nie dokłada; pulpit pokazuje nieaktywnego; „Nikt nie pracuje” pomija). _adopt_owners zwalnia tylko owner.
- R4-3 POTWIERDZONE [NOWY] średnie: working_title nie przelicza się przy apply_suggestion (champion_draft_service ~1134) ani ingest_parsed_profile (champion_profile_ingest ~464) — refresh_working_title tylko w jobs.py (POST/PATCH/PUT champion).
- R4-4 POTWIERDZONE [NOWY] średnie: manual_remove (request_allocation.py:618) nie woła _clear_auto_owner dla wiersza auto → recruiter_id zostaje przy zdjętej osobie; następny rekruter automatu nie zostaje prowadzącym.
#### Portale/archiwum (portale za flagą OFF na prodzie)
- R4-5 POTWIERDZONE [NOWY] średnie: job_portals/service.py _snapshot (554) porównuje tylko pending_action+options; update_options przy publishing i zatwierdzenie opisu przy update w toku giną — _apply (695) zeruje pending_action. Portal zostaje ze starą treścią/miastem.
- R4-6 POTWIERDZONE [POPRAWKA-R2 luka] średnie: _give_up (704) close po externalId tylko przy uncertain ostatniej próby / inherited — timeout w próbie 1, pewna odmowa w próbie 2 (opis wrócił do szkicu, flaga OFF) → failed bez close, opłacone ogłoszenie wisi. Poprawka: uncertain także przy attempts>1.
- R4-7 [NOWY] średnie (przed importem): import archiwum przypina pytania (is_pinned) także do OTWARTYCH rekrutacji; prep_review.build_items (121) czyta wszystkie przypięte → ocena prepu z archiwum („słaby”, dzwonki). Poprawka: tylko zamknięte albo pomijać legacy_import bez added_by.
- niskie: rollback importu nie zdejmuje przypięć istniejących pytań (reused).
#### Praktykant/akademia
- R4-8 POTWIERDZONE [NOWY] wysokie(pewność): frontend/src/lib/trainee-panel.ts:30,107 — status "completed" (awans) nie jest „zakończony” (front zna ended/finished) → 30 dni jako aktywny, zaniża kafel puli.
- R4-9 [NOWY] średnie: oddzwonienie `later` z datą po końcu programu przepada (lista tylko dla active; pin w Moich ludziach tylko `call`); blokuje kandydata 60 dni.
- R4-10 POTWIERDZONE [NOWY] średnie: trainee_program.py:515-533 nowe minimum stawki bez odpowiedzi o zgodzie zostawia starą zgodę accepts_below_min_rate (wyjątek trainee_call w write_profile_rate).
- R4-11 POTWIERDZONE [NOWY bliźniak r1] średnie: academy_rules.py:365 Luna: end null → „present” (bez roku w cytacie) → staż zawyżony, skip → zbiorcze wykluczenie na zawsze. Profil ma regułę „bez dat”.
- R4-12 POTWIERDZONE [NOWY] niskie/średnie: trainee_program.py:548 availability=later nie czyści starej availability_date (np. przeszłej = od zaraz).
#### Poprawki R3 — umowy/konkursy
- R4-13 [POPRAWKA-R2/R3] wysokie: contracts.py:3979 korekta daty na kontrakcie ended rozpoznaje rozwiązanie tylko po contract.agreement_termination_mode; dokumenty pochodne (effects.py:478/495 — porozumienie None, wypowiedzenie Partnera) trzymają tryb tylko na wierszu rejestru → PATCH daty = reaktywacja → wiersz wraca Aktywna bez trybu → przy nowej dacie trafia do „Bez projektu”.
- R4-14 POTWIERDZONE [POPRAWKA-R3] wysokie: ChampionsSection.tsx:383 numeruje resztę po full_ranking; podium po award_order bez niezakwalifikowanych → dwie osoby na #1. Bliźniak /my-position (competitions.py ~440) → „Mój miesiąc” mówi #1 niezakwalifikowanemu.
- R4-15 POTWIERDZONE [POPRAWKA-R3] średnie: KpiTargetsSettings.tsx:320 tekst „zmiana działa od razu … dla bieżącego miesiąca” — sprzeczne z migawką.
- R4-16 [POPRAWKA-R3 bliźniak] średnie: liga kwartalna (10 000 zł) czyta get_scoring_config na żywo przy zamrożeniu (competitions.py:770) — zmiana wag/progów po końcu kwartału działa wstecz; wykluczenie lidera kwartału w wyścigu miesięcznym też.
- R4-17 [POPRAWKA-R3] średnie: contracts.py:4035 ending→active przez wyczyszczenie daty nie czyści znacznika pending_dissolution → późniejsze zwykłe zakończenie zamyka wiersz jako „rozwiązany” starym trybem.
#### Follow-upy/QC/Cpro
- R4-18 POTWIERDZONE [NOWY] wysokie: cpro_sender.effective (104) zwraca fallback bez is_active; dezaktywacja nic nie czyści → firm_sender = martwe konto → _sees_cpro False dla wszystkich (admin/HoR widzą tylko przy None), skrót milczy, przełącznik renderuje się tylko przy niepustej sekcji → nikt nie może zmienić osoby; kolejka Cpro niewidoczna.
- R4-19 POTWIERDZONE [NOWY] średnio-wysokie: cv_qc.py:363 pusta data końca dowolnej roli = do dziś → staż zawyżony → blokujące years_header 409 CV_QC_FAILED dla poprawnego CV (akademia ma regułę „bez dat” dla dalszych pozycji).
- R4-20 POTWIERDZONE [NOWY] średnie: candidate_followups.digest_counts (718) pomija caller_id None, panel (675) pokazuje je adminowi/HoR — rozjazd luster.
- niskie: voicemail liczy się jako kontakt (_FAILED_CALLS); set_sender z until dla tej samej osoby → fallback None.
#### Zamówienia MD / przejęcie / powrót
- R4-21 POTWIERDZONE [NOWY] wysokie: reversal_available (contract_termination_reversal.py:233) True dla ended zawsze; brak blokera po „Powrocie po przerwie” (returned_from_contract_id) → Cofnij zakończenie C1 przy istniejącym C2 → ta sama osoba 2 kontrakty i 2 linie w zamówieniu.
- R4-22 [NOWY] średnio-wysokie: zaplanowane „Wejdź za konsultanta” nie jest anulowane przy przedłużeniu (aneks/bulk-extend) ani cofnięciu; skaner (dl_portal_expiry_scanner:256) traktuje szkic zastępstwa jako następcę → zamyka linię A, activate_due_takeovers przenosi pulę na B mimo że A pracuje.
- R4-23 [NOWY] średnie: zastępstwo za osobę z wyczerpaną pulą: activate rzuca TakeoverError co noc (tylko warning), szkic wisi bez sygnału; przy automatycznym zamknięciu sprawy tekst „decyzję podjęto ręcznie” fałszywy.
- R4-24 POTWIERDZONE [NOWY] średnie: md_consumption_view.is_foreign_number (106) — hint to dowolny ≥3-cyfrowy ciąg z Uwag („delegacja 445”, „08/2026”) → fałszywy czerwony alert „inny numer zamówienia” w Zużyciu MD i Importach MD. Reguła wiązania (explicit_order_hints) świadomie to ignoruje.
#### Poprawki R3 — poczta/M365/CV
- R4-25 POTWIERDZONE [POPRAWKA-R3] wysokie: order_mail_ingest.dismissed_unprocessed_clause (630) — odrzucone przed r3 z extraction mają dismissed_from NULL → NOT(TRUE AND NULL)=NULL → WHERE wyrzuca → _first_with_sha None → ponowny PDF czytany od nowa (kolejka / możliwy auto-zapis). Też order_mail_recheck.py:286.
- R4-26 [POPRAWKA-R3] średnie: m365/sync.py:1100 ochrona prywatności tylko przy event_type==meeting; typ edytowalny w NEXUSIE → po zmianie typu i nowym changeKey treść prywatna wraca.
- R4-27 [POPRAWKA-R3] średnie: pełny odczyt ±365 dni nie czyści prywatnych spotkań starszych niż rok.
- R4-28 [POPRAWKA-R3] niskie: generate-upload bez klienta płaci za podgląd Championa (2706) przed 422 (2781).
- niepotwierdzone: callback M365 może odrzucić konto z innym e-mailem niż login MS i pustym microsoft_upn; skrzynka z trwale psującym się wydarzeniem robi pełny odczyt co bieg.
