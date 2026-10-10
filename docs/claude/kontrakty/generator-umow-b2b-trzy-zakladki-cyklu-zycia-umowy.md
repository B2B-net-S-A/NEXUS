# Generator Umów B2B — trzy zakładki cyklu życia umowy

Rejestr rozbity na trzy zakładki odpowiadające fazom życia umowy (migracje
`0226_b2b_generated_contract_suspended` i `0328_b2b_generated_contract_cancelled`,
na bazie 0203/0224):
**„Umowy bieżące"** (`active` + `in_progress` + `cancelled`) ·
**„Umowy bez projektu"** (`suspended`) · **„Zakończone umowy"** (`closed`).
Wszystko w `components/v2/pages/B2BContractGeneratorV2.tsx`.

- **„Anulowana" (`cancelled`, 0328) = umowa, która NIE DOSZŁA DO SKUTKU** —
  Partner wycofał się przed podpisem. To NIE `closed`: tam skończył się projekt,
  tu umowa nigdy nie zaczęła obowiązywać. Powstał, bo jedynym wyjściem była
  „Zakończona", a numer jest już zużyty i nie wraca do puli (UNIQUE(year, seq)),
  więc wpis musi zostać w rejestrze.
  - **Wiersz ZOSTAJE w pierwszej zakładce** (stąd jej nazwa „Umowy bieżące",
    nie „Umowy aktywne i w trakcie podpisu" — nagłówek wyliczający statusy
    przestałby być prawdziwy). Ma być pod ręką, żeby dało się go cofnąć tam,
    gdzie użytkownik patrzy. Filtr zakładki pyta o TRZY statusy.
  - **BEZ powodu i daty**: `cancelled` jest w gałęzi „pola zamknięcia puste"
    CHECK-a spójności, a NIE w `B2B_CLOSING_STATUSES`. Umowa, która nie doszła
    do skutku, nie ma czego ani kiedy kończyć, a powrót na „W trakcie" ma być
    jednym kliknięciem. Dialog nie pokazuje wtedy pól powodu i daty.
  - **Umowy podpisanej obustronnie nie da się anulować** (409) — ta doszła do
    skutku i kończy się przez „Zakończona". Opcja nie renderuje się w dialogu
    (`canCancel = signature_status !== "signed_both"`).
  - **Z „Anulowanej" nie ma skrótu na „Aktywną"** (422): `active` ustawia
    WYŁĄCZNIE potwierdzenie podpisu obustronnego. Droga wiedzie przez „W trakcie".
  - **Ręczny wybór „W trakcie" zszedł z walidatora DTO do handlera PATCH-a.**
    `B2BGeneratedContractUpdate` odrzucało ten status bezwarunkowo; od 0328 ma
    dwa legalne wybory ręczne — powrót z „Anulowanej" i (od 23.09.2026)
    cofnięcie pomyłkowego zamknięcia NIEPODPISANEJ umowy — a ten warunek
    zależy od BIEŻĄCEGO statusu wiersza, którego DTO nie widzi. Komunikat dla
    przypadku niedozwolonego (`_IN_PROGRESS_IS_AUTOMATIC`) jest ten sam co był.
  - **Status podpisu zostaje „Niepodpisana"**, zmienia się tylko kolor wskaźnika
    na czerwony (`Badge variant="danger"` — badge nie ma osobnego elementu
    kropki, ikona dziedziczy jego wariant). Etykiety nie ruszamy: podpisu
    naprawdę nie ma.
  - **Przycisk „Oznacz jako podpisaną" chowa `can_confirm_signed` z backendu**
    (+ `blocked_reason` `_CANCELLED_BLOCKS_SIGNATURE`), a `confirm-fully-signed`
    odmawia 409. Jedno i drugie, bo ukryty przycisk nie jest kontrolą — ten
    endpoint do 0328 NIE patrzył na `contract_status` w ogóle.
  - Drugi, łatwy do przeoczenia mirror etykiet:
    `components/v2/jobs/JobContractTab.tsx` (`Record<string, string>`, więc
    TypeScript NIE zgłosi brakującego statusu — wyjdzie surowe `cancelled`).

- **Dostęp: KAŻDA rola (decyzja produktowa, 20.08 — mirror Talent Radar 19.08).**
  Sidebar nigdy nie miał tu `roles` ("Generator Umów B2B — dostępny dla
  wszystkich ról (sourcing tooling)"), ale backendowa `B2BGeneratorAccess`
  (`require_b2b_generator_access` w `contract_access.py`) do 20.08 wpuszczała
  tylko admin/HoR/TAC (+ DL ze scope'em) — dokładnie ten sam gap co przy
  Talent Radar: link widoczny, klik = 403. Otwarte na finance/recruiter/sourcer/
  legacy `user`. **Delivery Lead zostaje WYJĄTKIEM**, nietknięty: nadal wymaga
  jawnego przypisania klienta (operuje na swoim portfelu, nie całej bazie).
  Samo przepuszczenie roli przez bramkę NIE wystarczało — role bez żadnego
  wiersza w `ClientTacAssignment`/`DeliveryLeadClientAssignment`
  (`resolve_client_team_client_ids` zna tylko DL/TAC) dostawałyby trwale pustą
  listę, więc `_generator_unscoped` w `b2b_contract_generator.py` (pełny,
  nieoskopowany dostęp — pierwotnie tylko admin/HoR/TAC, „full-access TAC
  tool") poszerzony w lockstep o te same role. `contract_templates.py` (render
  dla DOWOLNEGO typu kontraktu, nie tylko B2B) stoi za osobną, węższą
  `ContractLegalAccess` i tej decyzji NIE dotyczy — pozostaje admin/HoR/DL/TAC.
  Węższe bramki wewnątrz generatora zostają nietknięte: edycja `client_name`
  (autor albo admin), DELETE (autor albo admin), katalog 29 ról (`AdminUser`),
  `confirm-fully-signed` (akcja RBAC `b2b_signature_confirmation` na
  poziomie `manage` + ścisły client-scope — audytowana, jednokierunkowa
  automatyzacja zatrudnienia; stan po audycie 23.09.2026, wcześniej ten opis
  mówił „`TacPlus`”). Test kontraktowy: `test_contract_legal_access.py`.
- **TCM działa w całej organizacji (decyzja Artura, 10.09.2026).** #1430 dał
  roli TCM `confirm-fully-signed`, a #1421 zmianę statusu kontraktu
  (`PATCH /contracts/{id}/status`) — obie akcje bez zakresu klienta, bo nie ma
  modelu przypisania TCM do klienta. To jest stan docelowy, nie przeoczenie:
  ścisły client-scope z punktu wyżej dotyczy DL/TAC — ale nie konta, które
  ma też rolę TCM (29.09.2026: TCM + TAC bez przypisań nie mógł oznaczyć
  podpisu). Jedyna granica TCM to
  sekcja Delivery: wyjątek TCM w `section_access.py` wymaga co najmniej
  odczytu Delivery, więc odebranie sekcji w panelu naprawdę odbiera akcję
  (do 10.09 wyjątek wracał, zanim porównał `granted`).
- **Do kontraktu prowadzi JEDNA droga: „Oznacz jako podpisaną"** (zgłoszenie
  09.2026, umowa 1506/2026). `POST /render` (generowanie DOCX) pisze wyłącznie
  wiersz rejestru (`signature_status="unsigned"`, `contract_status="in_progress"`,
  `contract_id` NULL) i **nie zakłada ani kontraktu, ani zamówienia** — kontakt
  dopisuje fill-only do JUŻ istniejącego kontraktu. Kontrakt (od razu `active`)
  i szkic zamówienia powstają dopiero w `confirm-fully-signed`. Z paska akcji
  generatora zdjęte są trzy przyciski, które wołały `POST /generate` i zakładały
  szkic kontraktu PRZED podpisem: „Wyślij do podpisu (QES)", „Oznacz: wysłana
  mailem", „Wgraj podpisaną (z maila)" — umowy podpisujemy offline (17.09.2026),
  a na produkcji ta ścieżka użyta była 4 razy, wyłącznie 2026-06-05. Endpoint
  `POST /generate`, `signingApi` i `app/services/signing/` **zostają** (nietknięte,
  bez konsumenta w generatorze); `reuseOrGenerateContractId` też — razem z testami.
  Nie dokładaj do generatora akcji, która zakłada kontrakt przed podpisem.
- **Potwierdzenie podpisu mimo różnic = „zachowaj warunki kontraktu", nigdy
  „nadpisz z dokumentu".** Gdy para (kandydat, rekrutacja) ma już żywy
  kontrakt o innych wypełnionych warunkach niż dokument, automatyzacja odmawia
  409 z listą różnic (`conflicts`) i podpowiedzią `can_keep_existing_terms`.
  Drugi, jawny krok — checkbox w dialogu →
  `keep_existing_contract_terms: true` — WIĄŻE podpisaną umowę z kontraktem,
  zapewnia zamówienie i przesuwa kandydata na „Zatrudniony" (od 23.09.2026,
  Pipeline v4; 17–22.09 etap ustawiał człowiek), ale nie zmienia niczego, co na
  kontrakcie już jest (stawka, jednostka, harmonogram, daty, szczegóły B2B).
  Puste pola nadal uzupełnia z dokumentu (`_complete_absent_terms`), z jednym
  wyjątkiem: stawki GODZINOWEJ z dokumentu nie wpisuje obok jednostki dziennej
  ani obok harmonogramu. Numer umowy w `b2b_contract_details` jest stemplowany
  zawsze — identyfikuje, KTÓRY dokument podpisano, nie jest warunkiem i nigdy
  nie trafia na listę różnic; data podpisania (warunek) zostaje. Zgoda jest
  przypięta do pary (kandydat, rekrutacja): w wierszu historycznym zmiana
  rekrutacji w dialogu kasuje listę różnic i checkbox. Przypadek z 09.2026: Delivery
  założyło kontrakty ręcznie PO wygenerowaniu dokumentu, w jednostce dziennej
  (68 zł/h w dokumencie = 544 zł/dzień w kontrakcie) — to ta sama kwota,
  nie konflikt handlowy. Nadpisywanie z dokumentu jest wykluczone, bo
  `rate_unit` rządzi TAKŻE stawką klienta: dzienna stawka klienta przeczytana
  jako godzinowa rozsadza marżę. Flaga nie obchodzi żadnej innej odmowy
  (duplikaty kontraktorów, inny klient, kontrakt nie-B2B, zdublowane
  zamówienia, umowa już podpisana) i bez różnic nic nie zmienia. Ślad:
  `acknowledged_conflicts` w Activity `fully_signed_confirmed` i
  `existing_terms_kept` w `linked_to_generated_contract`. Kolumna akcji
  rejestru jest ikonowa (`aria-label` + `title`), a autor siedzi pod datą
  w „Wygenerowano": kontener `max-w-7xl` przycinał tabelę na KAŻDYM
  monitorze, a przyklejona kolumna akcji (283 px) zasłaniała to, co pod nią —
  pół „Status podpisu". Testy: `test_b2b_signature_automation.py`
  (`keep_existing_terms*`), `B2BContractGeneratorSignature.test.tsx`.
- **Brak zamówienia po podpisie jest legalny WYŁĄCZNIE z powodem.**
  `_ensure_open_order` zwraca `(order, created, skipped_reason)`; dwa powody:
  `cost_client` (typ zamówienia wybiera Delivery Lead) i `open_group_line`
  (osoba jest już na żywej linii zamówienia MD/kosztowego — auto-szkic
  okresowy dublowałby współpracę na tym samym kontrakcie, #1321). Endpoint
  `confirm-fully-signed` rzuca `RuntimeError` (→ 500, pełny rollback) tylko
  wtedy, gdy zamówienia nie ma i NIE MA powodu. Do 09.2026 bramka pytała
  wyłącznie o klienta kosztowego, więc drugi powód kończył się 500 („Network
  Error") i wycofaniem całego podpisu u BIK/BNP — konsultant, którego Delivery
  obsadziło na linii MD przed potwierdzeniem dokumentu, zostawał niepodpisany
  i niezatrudniony. Linia grupy jest sprawdzana PRZED dźwignią klienta
  kosztowego (Polkomtel jest jednym i drugim — powód „linia grupy" niesie
  właściwy następny krok). Replay (`already_processed`) zwraca w `order_id`
  wyłącznie zamówienie okresowe (nigdy id linii grupy) i liczy powód tak samo.
  Powód idzie w odpowiedzi (`order_skipped_reason`) i w audycie obu Activity
  (`fully_signed_confirmed`, `linked_to_generated_contract`); komunikat po
  polsku nazywa go i wskazuje inny następny krok niż u klienta kosztowego.
  Nie zdejmuj
  `RuntimeError` dla braku bez powodu: cichy „brak zamówienia" zostawiłby
  zatrudnienie bez rekordu, który czytają skaner wygasania, MRR i sync
  terminacji. Testy: `test_confirm_links_a_consultant_already_on_a_group_line_without_500`,
  `test_confirm_still_fails_loudly_when_no_order_and_no_reason`.
- **`suspended` powstał, bo bez niego rejestr kłamał.** Kontraktor kończy projekt
  u klienta, ale umowa B2B dalej obowiązuje — czeka na kolejne zlecenie. `active`
  twierdziłby, że ktoś pracuje; `closed`, że umowy nie ma. Ten status odpowiada na
  pytanie „ilu mamy dziś kontraktorów bez projektu", a to pytanie o pieniądze.
- **Zawiesić można WYŁĄCZNIE umowę `active`** (422 dla reszty). Bez tej reguły
  `in_progress → suspended` byłby ślepym zaułkiem: powrót na `active` wymaga
  powiązanego kontraktu, a ten powstaje dopiero przy potwierdzeniu podpisu.
- **Powrót z zawieszenia wymaga projektu i powiązanego kontraktu.** `job_id`
  obowiązkowy; `contract_id IS NULL` → **409**, nie 422 (to nie błąd w danych,
  tylko stan świata do zmiany gdzie indziej). Klienta wyprowadza SERWER z projektu —
  front go nie przesyła, żeby nie dało się zapisać pary projekt/klient, która
  w bazie do siebie nie należy. Do powiązanego kontraktu leci notatka
  „Poprzedni projekt zakończony: [data], powód: [powód]" (konstrukcja `Note(...)`
  wprost w handlerze — `NoteCreate` nie ma `contract_id`, a `POST /api/notes` stoi
  za bramką `CandidateWriteAccess`, czyli w złej domenie autoryzacji).
- **Przypisanie projektu NIE dotyka `render_payload`** — w odróżnieniu od korekty
  literówki w nazwie Klienta ([[b2b-generated-contract-clientname-dual-write]]).
  Tam poprawiamy to, co MIAŁO być w dokumencie; tu zmienia się fakt handlowy,
  a podpisany DOCX jest zapisem tego, co strony podpisały.
- **Historia żyje w `b2b_generated_contract_status_events`.** Powrót na `active`
  MUSI wyczyścić `closure_*` (wymusza to CHECK), więc bez dziennika data i powód
  zakończenia poprzedniego projektu przepadałyby. `GET /generated/{id}/status-history`
  + dialog „Historia statusów". FK z **ON DELETE CASCADE** — `DELETE /generated/{id}`
  usuwa wpis (numer i tak nie wraca do puli — patrz niżej), RESTRICT
  zamieniłby dziennik w blokadę tej operacji.
- **Status handlowy ≠ status podpisu.** `contract_status` jest **niezależny** od
  `signature_status`. Podpisaną umowę też się wypowiada, więc PATCH statusu **nie
  jest** blokowany po podpisaniu — blokada 409 obejmuje wyłącznie treść dokumentu
  (`client_name`).
- **Dwie różne bramki w tym samym PATCH-u.** `contract_status` — każdy, kto widzi
  wiersz I ma akcję generatora na poziomie `manage`
  (`_require_generated_contract_management`; + client-scope). Delivery Lead
  czyta rejestr wszystkich klientów, a zapisuje wyłącznie u przypisanych
  (`_assert_generator_client_access(..., write=True)`).
  `client_name` — nadal autor albo admin. Reguła „autor albo admin" dla statusu
  była za wąska: kontraktora na nowy projekt kieruje delivery, nie osoba, która
  kiedyś kliknęła „generuj" — przycisk byłby niewidoczny dla większości zespołu.
- **Zamknięcie NIE usuwa wiersza** — dopisuje `closure_reason`, opcjonalny
  `closure_reason_other` i obowiązkowy `closure_date`. Powrót na `active` czyści komplet.
- **Powody opisują KONIEC PROJEKTU, nie rozstanie z Partnerem** (jeden katalog dla
  `closed` i `suspended`): `no_client_budget` | `contractor_found_other_project` |
  `contractor_health_reasons` | `contractor_underperformance` | `project_completed` |
  `internalization` | `other`. Trzy wartości sprzed 0226
  (`resignation_before_signing` | `termination` | `mutual_agreement`) **zniknęły
  z pickera, ale ZOSTAJĄ** w Literalu, w CHECK-u i w etykietach: produkcja ma
  wiersze `closed`, które je niosą. Zawężenie domeny wywaliłoby `ADD CONSTRAINT`,
  a usunięcie etykiet zamieniłoby historyczny powód w puste miejsce.
  Etykiety PL żyją w warstwie prezentacji (`B2B_CLOSURE_REASON_LABEL` w komponencie,
  **nie** w `lib/api.ts`) — testy mockują `@/lib/api` w całości, więc stałe trzymane tam
  wychodziłyby w testach jako `undefined`. Wyjątek: `_CLOSURE_REASON_LABEL_PL`
  w API — buduje TREŚĆ NOTATKI zapisywanej do bazy, czyli artefakt, nie widok.
- **Etykieta `closed` to „Zakończona"** (dawniej „Zamknięta"); wartość w bazie bez zmian.
- **Spójność wymuszona w bazie**, nie tylko w API: `ck_b2b_generated_contracts_closure_coherence`
  odrzuca `closed` bez powodu/daty oraz `active` z wypełnionym powodem. `closure_reason_other`
  jest wymagany dokładnie dla `other`. DTO `B2BGeneratedContractUpdate` to lustro tego CHECK-a
  (czytelne 422 po polsku zamiast surowego IntegrityError).
- **PATCH jest częściowy** — pola rozróżniane po `model_fields_set`, więc pominięcie pola
  zostawia je bez zmian. Bez tego zmiana statusu kasowałaby `client_name` (wszystkie pola
  są `Optional[...] = None`).
- **Wyszukiwarka:** `GET /generated?q=` filtruje **po stronie serwera** (nie po pobranych
  `limit` wierszach) po numerze umowy, `partner_name`, `client_name` oraz — przez OUTER JOIN
  na `candidates` — po imieniu/nazwisku powiązanego kandydata (także pełne „Imię Nazwisko"
  jednym ciągiem). Wildcardy `%`/`_` są escapowane, więc `%` szuka znaku, nie zwraca całej
  listy. Dodatkowo `?closure_reason=` jako filtr w zakładkach cyklu życia.
  FE debounce 300 ms.
- **`?contract_status=` jest POWTARZALNY** (`list[str]`), bo zakładka pierwsza pyta
  o dwa statusy naraz. Walidacja w ciele handlera, nie `Query(pattern=…)`: regex na
  `list[str]` FastAPI stosuje do CAŁEJ listy. Nieznana wartość → 422 z nazwą pomyłki;
  ciche zignorowanie filtra zwróciłoby PEŁNĄ listę pod nagłówkiem zakładki, która
  obiecuje wąski podzbiór. Axios musi serializować `indexes: null` — domyślne
  `contract_status[]=` to po stronie FastAPI INNA nazwa pola i filtr milcząco pada.
- **Pusty wynik wyszukiwania ma inny komunikat niż brak umów** — „Brak umów pasujących do
  wyszukiwania" vs „Brak umów bieżących." (ten sam błąd co przy 403
  renderowanym jako pustka: pustka czyta się jak utrata danych). Padnięte zapytanie ma
  WŁASNĄ gałąź `isError` z przyciskiem „Ponów" — awaria nie może udawać zera.
- **Safety-net entrypointu** zawiera lustro DDL (kolumny + CHECK-i + `CREATE TABLE`
  dziennika) — prod alembic bywa orphaned. `CREATE TABLE` idzie do listy DDL, NIE przez
  `Base.metadata.create_all`: tamten blok jest jedną transakcją i na prodzie potrafi paść
  w całości (incydent Cortex, PR #664). Uwaga: wpis `ck_..._closure_reason` do 0226 miał
  wyłącznie `EXCEPTION WHEN duplicate_object`, więc poszerzenie katalogu nigdy by na
  prodzie nie zadziałało — dołożony DROP przed ADD. Obie tabele B2B są w `core_checks`
  `/api/health/deep`.
- **`link-contract` wymaga zapisu u klienta WIERSZA**, odrzuca wiersze z Excela
  i kontrakt innej osoby (klucz `candidate_identity_key`; zdublowany rekord tej
  samej osoby przechodzi — ticket 1460) (audyt 24.09.2026).
- **Poprawki po audycie 23.09.2026** (`test_b2b_generator_audit_2026_09_23.py`):
  - **Numer nigdy nie wraca do puli.** Usunięty wpis zostawia `Activity`
    `deleted` z numerem (`_deleted_contract_numbers`): `/render` odmawia 409
    dokładnie tego numeru, a `_next_seq` go POMIJA (max żywych + 1, dalej
    przeskok usuniętych) — nie liczy z usuniętych maksimum, bo jedna usunięta
    literówka („15190/2026”) zawyżyłaby numerację na zawsze. 1518 i 1522/2026
    zostały wydane dwóm różnym Partnerom, a usunięty DOCX mógł już wyjść mailem.
    Numeracja jest **ciągła między latami** (zmienia się tylko rok), więc
    `_next_seq` liczy maksimum po wszystkich latach — z filtrem po roku
    1 stycznia sugestią byłoby „1/2027”.
  - **„Aktywna” wyłącznie po podpisie obustronnym.** PATCH odrzuca 422 każde
    przejście na `active` niepodpisanej umowy (poza powrotem z `suspended`);
    pomyłkowo zamkniętą niepodpisaną umowę cofa się na „W trakcie”.
  - **Poprawka = ten sam numer:** `POST /generated/{id}/rerender` (autor albo
    admin, tylko `in_progress` i niepodpisana, bez zmiany kandydata/rekrutacji)
    nadpisuje `render_payload` i snapshot. Do 23.09 jedyną drogą była
    „usuń i wygeneruj” (15 usunięć na ~104 generacje), a wersja EN dostawała
    drugi numer. `/render` i `/rerender` zwracają `X-Generated-Contract-Id`.
    `GET /generated/{id}/form` (ta sama bramka, `_load_row_for_correction`)
    oddaje zapisany formularz — „Popraw umowę” z wiersza rejestru działa też
    po odświeżeniu, a nie tylko w karcie, w której umowę pobrano.
  - **DOCX renderuje się PRZED zapisem wiersza** — błąd renderu nie zużywa
    numeru.
  - **Rejestr stronicuje** (`offset`, okno po `created_at DESC, id DESC`) —
    front ładował 100 wierszy bez „Pokaż więcej”. Wiersz niesie
    `linked_contract_status`/`linked_contract_end_date`: rejestr NIE zmienia
    się sam, gdy kontrakt się kończy albo znika, więc lista ostrzega.
  - **`POST /generate` nie nadpisuje stawki kontraktu, który istniał przed
    wywołaniem**, jeśli wołający jej nie widzi (`_require_generator_rate_content`).
  - **Front:** formularz po pobraniu pamięta wiersz (baner „Umowa N zapisana”,
    „Popraw i pobierz ponownie” / „Nowa umowa”), jeden przycisk DOCX w języku
    z przełącznika, ostrzeżenie o istniejącej umowie tej osoby w tej
    rekrutacji, plakietki kontraktu zakończonego/kończącego się/usuniętego,
    „Pokaż więcej”, `?tab=`/`?q=`/`?candidate=&job=` w adresie, „Zmień status”
    w „Zakończonych”. Reguły: `lib/b2b-generator-register.ts`.
  - Stawka zaokrąglana do groszy w schemacie (jedna reguła dla kwoty i kwoty
    słownie); nazwy Partnera/Klienta ≤ 255 znaków (422, nie 500).
- **Runda 8 audytu (26.09.2026):** podpis i ruch na „Zatrudniony” wiążą
  ŻYWY kontrakt tej osoby u klienta także bez rekrutacji (tożsamość jak
  `_assert_no_duplicate_contract`; ten sam e-mail na innym rekordzie = 409
  „scal duplikaty”), niepodpisana „Zakończona”/„Bez projektu” nie przyjmuje
  podpisu (409), przywrócić z zawieszenia na projekt może tylko ktoś, kto
  widzi stawki umowy, numer porządkowy jest zajęty w KAŻDYM roku (409
  z kodem `contract_number_taken` — tylko przy nim front podmienia numer),
  a umowy z podpisanym dokumentem pochodnym nie da się usunąć.
- **Dokumenty pochodne (0362, zakładka „Dokumenty”, `?tab=documents`)** —
  aneksy (stawka, data startu, dane firmy JDG/spółka, oddelegowanie, zlecenie),
  porozumienie o rozwiązaniu (B2B i zlecenie, opcja zwolnienia z zakazu
  konkurencji), wypowiedzenie przez B2B.net, cofnięcie wypowiedzenia Partnera
  i umowa przedwstępna CeZ. Osobna tabela `b2b_contract_documents`, NIE typ
  wiersza rejestru — kilkanaście miejsc zakłada „wiersz rejestru = umowa B2B”.
  Aneksy nie mają własnego numeru (decyzja Artura 23.09.2026). Typy, pola
  i języki: JEDEN rejestr `services/b2b_documents/registry.py` (front buduje
  formularz z `GET /document-types`); szablony `app/templates/documents/`
  budowane skryptem `scripts/build_b2b_document_templates.py` ze wzorów działu
  (oryginałów z przykładowymi danymi osób NIE commitujemy; zmiana wzoru =
  zmiana skryptu). Numery paragrafów cytowanych w dokumentach zależą od
  `b2b_generated_contracts.template_version` (`contract_versions.py`, dziś
  tylko „2026”); wiersz bez wersji (import z Excela) = formularz prosi o
  paragrafy. Rejestr klauzul klienta NIE dotyczy dokumentów pochodnych.
  - **Generowanie niczego nie zmienia — zmienia „Oznacz jako podpisany”**
    (`effects.apply`, idempotentnie po `effect_applied_at`, pod blokadą),
    zawsze istniejącą ścieżką domeny: aneks stawki = handler aneksu
    z `api/contracts.py`, rozwiązanie/wypowiedzenie =
    `_apply_termination_to_contract`, cofnięcie wypowiedzenia =
    `reopen_contract` (NIE `revert_contract`, który cofa do szkicu). DOCX
    ląduje w dokumentach kontraktu. Okno podpisu pokazuje skutki liczone przez
    serwer (`GET /documents/{id}/effects`), blokada wyłącza przycisk.
  - **PESEL, dowód i adres zamieszkania NIGDY nie trafiają do bazy** —
    `strip_sensitive` przed zapisem `render_payload`; ponowne pobranie takiego
    dokumentu prosi o te pola jeszcze raz (`POST /documents/{id}/docx`).
  - Wypowiedzenie złożone przez Partnera nie ma wzoru — to akcja bez
    dokumentu (`POST /documents/partner-notice`, koniec z okresu wypowiedzenia
    wersji umowy: 2026 = miesiąc na koniec miesiąca).
- **Generator aneksów (`?tab=annexes`, 0401, 29.09.2026)** — KAŻDY aneks
  powstaje w tej zakładce (Dokumenty tworzą rozwiązania i przedwstępną;
  `documentsHref` z typem `annex_*` przekierowuje tam). Trzy typy z ticketu
  (dane firmy, data startu, stawka) mają `allows_external`: umowa z „Umów
  bieżących” ALBO „Umowa spoza Nexusa” (dane wpisane ręcznie, dokument NIE jest
  zapisywany, odpowiedź bez `X-Document-Id`, `X-Document-Saved: 0`). Treść trzech
  szablonów PL buduje `scripts/build_b2b_annex_templates.py` z opisu w tickecie
  (oprawa z `annex_party_data_pl.docx`), nie builder wzorów działu — zmiana
  treści = zmiana listy bloków i ponowne uruchomienie. EN tych typów zostało
  wyłącznie do ponownego pobrania starych dokumentów (`legacy_languages`).
  - **Rejestr zmienia się PRZY WYGENEROWANIU, kontrakt po podpisie** (decyzja
    Artura 29.09.2026 — wyjątek od „generowanie niczego nie zmienia”):
    `annex_register.apply` wpisuje firmę+NIP / datę rozpoczęcia /
    `annex_rates` (stawki z aneksu, lista widoczna tylko przy widocznych
    stawkach) i zapamiętuje `register_before`; anulowanie i usunięcie
    niepodpisanego aneksu cofają TYLKO pola, które nadal mają wartość z tego
    aneksu (późniejszy aneks wygrywa). `render_payload` wiersza (podpisana
    umowa) nigdy nie jest przepisywany.
  - **Paragraf jest polem, nie `refs`** (`uses_refs=False`): podpowiedź dla
    umowy ze znaną wersją wzoru NEXUSA to § 13/§ 14 ust. 2 (data startu,
    JDG/spółka), dla Excela i umów spoza NEXUSA — § 12/§ 13 ust. 2 z ticketu;
    stawka zawsze § 6 ust. 1. Zmiana wariantu podmienia paragraf tylko, gdy
    człowiek go nie zmienił.
  - **Stawki = lista pozycji** (`rate_items`: kwota, klient z NEXUSA, od, do).
    Nazwę klienta do dokumentu serwer bierze z bazy (`_resolve_rate_clients`,
    usunięty/scalony = 422), słownie „… złotych 00/100”
    (`pln_words_with_fraction`). Kilka pozycji bez daty „od” i klienta = 422.
    Przy podpisie każda pozycja klienta TEGO kontraktu (albo bez klienta) to
    osobny krok harmonogramu; pozycja innego klienta = ostrzeżenie, kontrakt
    bez zmian.
- **Sprawdzenie firmy w CEIDG/KRS przy KAŻDYM „Pobierz DOCX” (ticket 6,
  28.09.2026)** — `GET /company-verification`
  (`services/b2b_contract_generator/registry_verification.py`), zawsze 200:
  JDG → CEIDG v3 po NIP, spółka → odpis aktualny KRS (numer z Białej Listy);
  wykreślona spółka ma odpis aktualny 204 i jest rozpoznawana po ostatnim
  wpisie odpisu PEŁNEGO (`stanPozycji` NIE mówi o wykreśleniu). Ostrzeżenia
  (zawieszona/wykreślona w CEIDG, likwidacja/upadłość/wykreślenie w KRS)
  i `unverified` są WYŁĄCZNIE informacją — okno `RegistryCheckDialog` zawsze
  pozwala „Generuj mimo to”; nie zamieniaj tego w bramkę. Różnice nazwy,
  adresu i REGON-u liczy `lib/b2b-registry-check.ts` po normalizacji („ul.”,
  wielkość liter, REGON 14-cyfrowy z zerami) i domyślnie wstawia dane
  z rejestru. Pod jednym NIP-em CEIDG ma często kilka wpisów (10 z 40
  Partnerów) — bieżący wybiera `pick_current_ceidg_firm` (status, potem
  najnowszy start); do 28.09 auto-uzupełnianie brało pierwszy, bywało
  wykreślone przedsiębiorstwo ze starym adresem.
- **Rejestr z Excela działu (0363)** — Excel „UMOWY I ZAMÓWIENIA” jest
  prowadzony RÓWNOLEGLE, więc import jest powtarzalny: Ustawienia → Umowy
  i stawki → „Rejestr umów z Excela” (admin): podgląd → zapis → cofnięcie
  ostatniego przebiegu. `source = generator | excel`; wiersza z NEXUSA import
  nigdy nie zmienia (rozbieżność pod tym samym numerem = raport), wiersz
  z Excela aktualizuje się po `source_key`, zniknięty z pliku dostaje
  `excel_missing_since` (nie jest kasowany). `year`/`seq` są NULL-owalne,
  UNIQUE(year, seq) częściowy — numer spoza formatu („264A”, „bez numeru”)
  żyje w `raw_contract_number`. Wiersze z Excela są tylko do odczytu poza
  statusem i dokumentami pochodnymi. Arkusz „Bez działalności” zasila kolejkę
  „Aneks uzupełnienia danych do zrobienia” (`needs_business_data_annex`,
  zdejmuje ją podpisany aneks „dane firmy”) — także na umowie wydanej
  w NEXUSIE, bo ta flaga to jedyne pole, które import może na niej zmienić
  (decyzja Artura 26.09.2026). `GET /generated/export.xlsx`
  oddaje rejestr w układzie kolumn Excela działu.
- **Wariant „Umowa spółka” (ticket 8, 29.09.2026)** — przełącznik „Umowa JDG /
  Umowa spółka” (`contract_variant`, domyślnie `jdg`; zapisany payload bez pola
  = JDG, dokument bez zmian). Przełączenie nie czyści pól formularza.
  - **Komparycja spółki siedzi w szablonie**: warunek
    `b2b.is_company is defined and b2b.is_company` w dwóch runach komparycji
    umowy i umowy powierzenia (`is defined`, bo ten sam HTML renderuje
    „Generuj z szablonu” na kontrakcie ze StrictUndefined). Źródeł prawnika nie
    ma w repo — szablony zmienia `python scripts/build_b2b_templates.py
    --company-variant` (idempotentnie, na zacommitowanych plikach).
  - **§ 12 „Osoby skierowane…”, przenumerowanie i wiersz „Osoba skierowana”
    w Załączniku nr 3 to przekształcenie gotowego dokumentu**
    (`services/b2b_contract_generator/company_variant.py`), PO klauzulach
    Klienta: przesuwa nagłówki ≥ 12 umowy głównej i odwołania „§ N … Umowy
    Głównej / of the Main Agreement” w załącznikach, nie rusza własnej
    numeracji załączników (DPA § 1–5, Credit Agricole § 11–15) ani przepisów
    („art. 22 § 1”). Brak kotwicy = `CompanyVariantError` (500), nigdy cicha
    umowa JDG.
  - **Osoba skierowana = kandydat z rekrutacji** (`_stamp_assigned_person` w
    `/render` i `/rerender`, zapisana w `render_payload`) — nie spółka i nie
    osoba reprezentująca. Wariant spółki stempluje `partner_entity_type =
    company` i `template_version = "2026-company"` (dokumenty pochodne cytują
    § 13 wypowiedzenie i § 14 datę startu, `contract_versions.COMPANY_VERSION`).
  - **KRS**: `lookup_krs_company_details` — siedziba i kapitał z odpisu
    aktualnego, sąd rejestrowy z OSTATNIEGO wpisu sądu (nie „SYSTEM”) w odpisie
    pełnym. Publiczne API maskuje imiona i nazwiska zarządu — osobę
    reprezentującą wpisuje człowiek (front podpowiada funkcje i biernik,
    `lib/b2b-company-variant.ts`). Harness `/preview/b2b-generator`.
- **Umowę generuje rekruter z rekrutacji (0417, 04.10.2026, decyzje Artura
  D1–D5).** Przegląd: https://claude.ai/artifact/YJwAxv4ByNdj19Z1gPmDGj —
  od 01.08 rekruterzy wygenerowali 0 z 61 umów, choć mieli poziom generowania.
  - **Poprawia pod tym samym numerem** (`_may_correct_generated`; `/form`,
    `/rerender`, `client_name` w PATCH, `can_edit` wiersza): autor, zespół
    z NADANIA (`_jobs_led_by`: prowadzący, TAC, DL, aktywne przypisanie), TCM,
    admin — zawsze przy widocznych stawkach (TCM bez wglądu w stawki cudzej
    umowy dostaje 403). Ręczny współpracownik NIE poprawia i nie prosi
    o podpis — każda rola wewnętrzna może dopisać się sama. Usuwa nadal autor
    albo admin (`can_delete`).
  - **Wgląd w stawki rejestru** (`_jobs_run_by`) liczy jak „Rekruter”
    z `job_team` (z ręcznym współpracownikiem); uczestnik z kategorii
    (`auto_cc`) nie widzi stawek.
  - **Podpis potwierdzają nadal admin, DL i TCM** („Podpis B2B”); rekruter
    prosi: `POST /generated/{id}/signature-request` (kolumny
    `signature_requested_at/by`, dzwonek `b2b_signature_requested` do DL-a
    rekrutacji → DL-i portfela → TCM, druga prośba w 24 h bez dzwonka; brak
    odbiorcy = 409 bez zapisu prośby).
  - **Podpowiedzi formularza** `GET /prefill?candidate_id&job_id`
    (`services/b2b_agreement_prefill.py`): stawka z karty rekomendacji → „W tej
    rekrutacji” → „Stawka od”, data z `availability_date`, stawka do klienta
    tylko dla `user_can_view_client_rate`, istniejąca umowa pary.
  - **Stan umowy na karcie Tablicy** (`agreement`, `services/agreement_status.py`)
    w KAŻDEJ kolumnie; rejestr niesie `created_by_role`, `pair_column`, filtry
    `candidate_id` i `author=recruiter`.
  - **Grupa „Umowy” w `GET /api/board-tasks`** (`services/agreement_tasks.py`):
    `requested`, `hired_unsigned` (karta „Zatrudniony” przy umowie „W trakcie”
    — D5: sprawa, nie automat), `closed_unsigned`, `closed_signed_active`; tylko
    dla posiadaczy „Podpis B2B” w ich zakresie; prośby autora w
    `waiting_on_others`.
  - **Ręczne „Zatrudniony” z UoP albo zleceniem zakłada kontrakt tego typu**
    (do 04.10 zawsze B2B). Stawki do klienta z etapu NIE wpisujemy do szkicu
    zamówienia z podpisu: start + stawka spełnia `complete_order_clause`, więc
    Finanse nie dostałyby dzwonka „bez zamówienia”, a kontrakt dostałby
    przychód przed zamówieniem od klienta (przegląd kodu 04.10.2026).
  - Wygenerowanie umowy NIE przesuwa karty (D4 — bramka debriefu).
- **Kontener listy:** `max-w-6xl` → `max-w-7xl` (9 kolumn + akcje).
