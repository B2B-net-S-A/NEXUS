# Jeden formularz screeningu (0424, 07.10.2026)

Decyzje Artura D1–D10 z 07.10.2026 (makieta https://claude.ai/artifact/TNGomEmwM6ehsbdPDSaaBi). Rekruter rozmawia
na podstawie Profilu Championa i zapisuje wynik **dla Delivery Leada** — z NEXUSA nic nie idzie do klienta.
Kontrakt: `docs/screening-form-contract.md`, raport: `docs/screening-form-completion-report.md`.

- **Arkusz screeningu, ręczne pola karty rekomendacji i stawka kandydata to JEDEN formularz**
  (`api/screening_form.py`, `services/screening_form.py`, front `components/v2/screening-form/`). Zapis jest jedną
  transakcją: arkusz na NAJNOWSZY wiersz etapu pary, pola karty (`save_manual`, tylko różne od wartości efektywnej),
  stawka przez `candidate_rate_change.change_rate(source="screening")`, tekst z „Uzupełnij z notatki” jako notatka
  HUMAN. Stare trasy (`POST /pipeline/stages/{id}/screening`, `PUT /recommendation-cards`) zostają dla starych kart
  przeglądarki; ich zmiany łapie wersja `external`. Nowy ekran zapisujący arkusz albo kartę = ta trasa.
  Zapis i przywrócenie odsyłają `state_token` (odcisk stanu pary z `GET`): zmiana zrobiona obok formularza zmienia
  odcisk → 409, przeglądarka wczytuje nowy stan i zostawia niezapisane zmiany (odświeżenie w tle robi to samo,
  `keepDirtyValues`). Front wysyła tylko zmienione pola karty i `null` dla nieruszonego arkusza i stawki.
  „Cofnij” = tylko własny ostatni zapis; od „CV wysłane” podwyżka z „Cofnij” idzie do DL jak każda inna. `note_import` przy
  wyłączonym `RECOMMENDATION_CARD_ASSIST_ENABLED` = 422. `note_import.note_id` (D3, 14.10.2026) wiąże zapis
  z notatką zapisaną już w doku zamiast zakładać drugą — reguły w `karta-rekomendacji-z-notatki-i-uloz-w-zdanie.md`.
- **Historia wersji** `screening_form_versions`: każda realna zmiana = wersja z migawką i zmianami przed/po;
  „Przywróć” i „Cofnij” zapisują NOWĄ wersję. Tabela trzyma wartości (także narodowość) — czytają ją wyłącznie ludzie
  (strażnik w `test_recommendation_card_ai_privacy.py`). Przywrócenie stawki tylko przed „Zweryfikowany” — później
  zmianę stawki prowadzi Delivery Lead (0418).
- **Edycja na każdym etapie, dopóki proces trwa** (`assert_pair_editable`): tylko do odczytu przy zamkniętej
  rekrutacji albo zamkniętym/unieważnionym procesie pary. Blokada 12 h bez zmian (Nowi/Screening).
- **Panel osoby ma szerokość `split`** (`PersonPanelShell size`): kliknięcie osoby w Nowi/Screening otwiera od razu
  panel na całą szerokość okna — podgląd po LEWEJ na całą wysokość (CV oryginalne / CV firmowe / inne pliki,
  Wymagania, Po ludzku), formularz w stałej prawej kolumnie (460 px, od 1536 px okna 520 px), a nad nim blok
  „Co już wiemy”. „Zwiń” wraca do doku 380 px. Układ od 09.10.2026 — sekcja „Duży podgląd po lewej stronie
  panelu osoby”.
- **Formularz od razu, także w „Nowych” (P2, 14.10.2026, `droga-rekrutera-do-dl.md`).** Bez kroku „Zacznij
  screening” i bez „Biorę — 12 h” przed formularzem: zapis, który dodał wersję, w kolumnie „Nowi”/„Screening”
  i otwartym procesie bierze wolną osobę na 12 h jak „Biorę” (`screening_form._claim_on_save`: blokada
  i `Activity("candidate_claimed")` z tymi samymi szczegółami co trasa `claim_candidate`, potem odświeżenie
  Tablic zespołu). Cudzej aktywnej blokady nie przejmuje (rekruter dostaje 423 jak dotąd, DL/admin/HoR
  zapisują bez przejęcia), własnej nie przedłuża, przywrócenie wersji nikogo nie bierze.
- **Stawka na start (D2, 14.10.2026).** Etap bez stawki: pole stawki dostaje — jako zmianę formularza, więc
  zapisuje się z „Zapisz” — najpierw najnowszą stawkę z notatek z dosłownym cytatem (`suggestions_from_notes.
  rate`, tylko PLN i znana jednostka), potem stawkę z karty (`rate_hints.card` + `card_raw`), na końcu „Stawkę
  od” (`lib/screening-form.ts` `ratePrefill`). Pod polem jedna linia „z notatki 2.04.2025: „…” · zmień” /
  „z karty rekomendacji: „…” · zmień” / „Stawka od · najniższa z 18 mies. · zmień”; podpowiedź „Użyj” z tą
  samą wartością co w polu znika. Bez prawa do stawek (`can_edit_rate`) nic się nie wpisuje; ręcznie
  ruszona stawka nie wraca po odświeżeniu; stawka z notatki z rozmowy zastępuje wpis na start. Do tej daty
  zapis porównywał pole ze stawką z karty i gubił ją — etap zostawał bez stawki (`buildSavePayload`
  porównuje teraz tylko ze stawką etapu, jak serwer).
  Od 18.10.2026 sama stawka na start nie zapala w stopce „Niezapisane zmiany” (`model.unsaved`): formularz
  otwarty bez żadnej edycji wyglądał na zmieniony. Zapis nadal ją niesie; „Niezapisane zmiany” wraca, gdy
  rekruter ruszy cokolwiek, także stawkę na inną kwotę.
- **Stawka na start = najniższa znana (R1–R3, 17.10.2026, zgłoszenie Artura: formularz wpisał 140 przy
  zadeklarowanych 90 i budżecie 135).** Kolejność z D2 zmieniona: najpierw stawka z karty TEJ rekrutacji (kandydat
  powiedział ją o tę rolę — notatka już jej nie zastępuje), przy żywej umowie (`rate_hints.rate_from_source =
  "contract"`) „Stawka u nas” z podpisem „Stawka u nas · z umowy”, a w pozostałych przypadkach NIŻSZA z dwóch:
  stawka z notatek z cytatem albo „Stawka od” (porównanie po godzinie, remis — notatka). Do 17.10 wygrywała
  najnowsza notatka, także wyższa.
  - **R2:** stawka w polu ponad budżetem, a znana jest niższa, która się w nim mieści („Stawka od”, przy umowie
    `rate_hints.declared_from`, stawka z notatek) — ramka „ponad budżet” dopisuje „Znana też niższa stawka: 90 zł/h
    (Stawka od, 8.10.2026) — mieści się w budżecie.” z przyciskiem „Użyj 90 zł/h” (`lowerKnownRate`,
    `VerifiedRateFields.overBudgetNote`). To samo w oknie „Przesuń na „Zweryfikowany”” (z „Stawką od” karty
    Tablicy). Dopisek nie blokuje ruchu.
  - **R3:** ekstrakcja notatek zostawia „Stawka: 90” bez jednostki; `screening_suggestions` czyta wtedy `raw`
    regułą karty (`recommendation_card_parser.parse_rate`) i oznacza PLN/h tylko, gdy kwota zgadza się
    z ekstrakcją (pomiar prod 17.10: 1 748 osób). Podpowiedź bez „Użyj” mówi powód: „bez jednostki” albo „inna
    waluta” (`rateSuggestionBlocker`), a data samego miesiąca („2026-10”) pokazuje się jako „10.2026”.
  - **R4 w formularzu:** przy umowie podpowiedź „Stawka u nas” zamiast „Stawka od” i „Zadeklarowana od: 120 zł/h ·
    1.09.2026” z „Użyj”. Reguła i profil: `stawka-od-i-historia-stawek-kandydata.md`, sekcja „Żywa umowa”.
- **Pola „Warunków” i „Oceny” czyta się w widoku „Screening”** (dok, przegląd DL, profil) — od 09.10.2026 bez
  osobnej sekcji i nazwy „Karta rekomendacji” (sekcja „Jeden widok „Screening”…” niżej). Pole „Notatki
  rekrutera” (`screening_answers.notes`) zniknęło z formularza — stare wartości pokazujemy jako „Notatka z arkusza”
  z „Przenieś do Dlaczego ten kandydat”.
- **Nic do klienta (D2):** udostępnianie karty Championa usunięte — `POST …/share-token` i publiczny GET = 410,
  tokeny odwołane w 0424; `notes` zdjęte z `client_safe_screening`. Odpowiedzi nadal są źródłem treści CV firmowego.
- **Pominięcie pytań sprawdza zapis (14.10.2026).** `PUT /screening-form` (i stara trasa arkusza)
  odrzuca `answers[*].skipped` bez powodu „Pomiń brakujące” (`screening_reassign.skip_missing_reason`)
  kodem 422 `SCREENING_FORM_INVALID`. Pominięcie zapisane wcześniej w arkuszu pary przechodzi przy
  ponownym zapisie. Powód: audyt 13.10 pokazał zapis samych `skipped` z pominięciem ekranu, który
  spełniał bramkę „Zweryfikowany”. Bramka liczy teraz tylko odpowiedzi
  (`move_requirements.sheet_answered`), szczegóły w „Rekrutacja bez pytań…”.
- Wzmianki w sekcjach 0413 i 0421 o edycji karty w jej oknie, kafelkach importu notatki i `/note/apply` opisują
  stan sprzed 0424.

## Screening pod kilka rekrutacji w jednej rozmowie — „Screening dla” (14.10.2026)

Decyzje Artura D3–D4 z 14.10.2026 (makiety https://claude.ai/artifact/RTUD8nEm1dRXrarnwHrE7f, B1–B3). Raport:
`docs/joint-screening-completion-report.md`, kontrakt: `docs/screening-form-contract.md`, sekcja „Screening dla”.

- **Gdzie:** nad formularzem w panelu osoby, gdy karta jest w „Nowych”/„Screeningu”, patrzący ma prawo zapisu, a para
  nie ma prośby DL o poprawki (`ScreeningWorkbench`, `JointScreeningPicker`). Lista z `GET …/joint-context`: inne
  rekrutacje osoby (do wyboru tylko Nowi/Screening bez cudzej blokady; dalsze etapy i cudza rezerwacja wyszarzone
  z powodem) i podpowiedzi „Pasuje też do” z „+ Dodaj i dołącz” (`proposals/bulk`, źródło `also_fits`). „Screening
  razem” z okienka „+N rekrutacja” na karcie Tablicy otwiera panel z zaznaczonymi rekrutacjami (`store/joint-screening`).
  Zaznaczenie choć jednej innej rekrutacji zamienia formularz pary na formularz wspólny (`JointScreeningForm`).
  Najwyżej 4 rekrutacje w jednej rozmowie (kotwica + 3, `JOINT_MAX_OTHERS`) — trasa grup pytań przyjmuje 2–4;
  „Screening razem” bierze pierwsze 3 i działa też dla osoby, której panel jest już otwarty.
- **Jeden stan, zapis per para** (`lib/joint-screening.ts`): `projectPair` rzutuje stan wspólny na wartości
  pojedynczego formularza pary, a `buildSavePayload` z JEJ stanu buduje zwykły `PUT /api/screening-form` — wersje,
  `state_token`, blokada 12 h i 409/423 działają jak dotąd, osobno dla każdej pary. Kotwica zapisuje się pierwsza.
  Rzut liczy się od NAJŚWIEŻSZEGO stanu pary (tego, którego odcisk idzie w zapisie): pole nieruszone w tej rozmowie
  bierze wartość serwera, ruszone — wartość z rozmowy, a odświeżenie w tle przerysowuje pola nieruszone
  (`keepDirtyValues`). Do 14.10.2026 (przegląd przed PR-em) zapis po odświeżeniu w tle odsyłał wartości sprzed
  otwarcia formularza ze świeżym odciskiem i po cichu cofał cudzą zmianę.
- **Pola wspólne** (dostępność, lokalizacja, narodowość, angielski, red flags; „Czy pracował u Klienta”
  per klient) i odpowiedź na wspólne pytanie: ruszone w tej rozmowie → do każdej pary; nieruszone → tylko tam,
  gdzie puste; inna zapisana wartość w parze → pod polem „W <rekrutacja>: …”. Stawka: „Ta sama stawka we
  wszystkich” zaznaczone, gdy stawki par na start są równe albo puste; przy zaznaczonym — kwota z pola wspólnego
  (ta, którą widać) idzie do każdej pary, gdy rekruter ruszył stawkę albo przełącznik, i do pary bez własnej
  stawki, a nieruszona zostawia parze jej stawkę startową (`ratePrefill` jak pojedynczy formularz); osobne
  stawki — ruszona albo startowa. Porównanie z budżetem każdej rekrutacji pod polem. „Dlaczego ten kandydat”, motywacja, ogólna ocena i pozostałe
  pola karty — osobno, w zakładkach per rekrutacja.
- **Tryb pracy osobno dla każdej rekrutacji (zgłoszenie rekrutera 29.10.2026):** w jednym projekcie bywa 1 dzień
  z biura, w drugim 2. Pole stoi w „Warunkach” jako „Tryb pracy · <rekrutacja>” (`PER_JOB_TERMS_KEYS`), pod nim
  „W rekrutacji: …”, gdy rekrutacja ma tryb podany; zapis idzie tylko do swojej pary. Do tej daty był wspólny.
- **Zakładki oceny montują panel od nowa per rekrutacja** (`key` = rekrutacja). Do 29.10.2026 przełączenie
  zakładki zostawiało to samo pole tekstowe pod nową nazwą — RHF nie przepisywał wartości, więc „Dlaczego ten
  kandydat” i motywacja jednej rekrutacji stały w drugiej, a w formularzu miała je tylko jedna i „Zapisz
  i przekaż dalej” wołało o brak mimo widocznego tekstu (zgłoszenie rekrutera).
- **Pytania:** grupy z `GET …/question-groups` (reguła `screening_question_groups.py`) — wspólne zadajesz raz,
  pozostałe w sekcjach „Tylko <rekrutacja>”; deal-breaker zaznaczasz per rekrutacja.
- **„Zapisz i przekaż dalej w N”:** najpierw braki wszystkich par (pytania bez odpowiedzi, „Dlaczego ten kandydat”
  bez pytań) — nic się nie zapisuje, dopóki ich nie ma; potem per para zapis i ruch na „Zweryfikowany” (`stage_def_id`
  z `joint-context`, `expected_state_version` z wyniku zapisu tej pary, `silent` w `usePipelineMoveCore`, odświeżenie
  Tablic innych rekrutacji). **Para z trafionym deal-breakerem nie przechodzi sama** — karta wyniku daje „Przekaż mimo
  to” (pojedynczy formularz deal-breakera nie blokuje) i „Otwórz jej kartę”; odmowa kwalifikowalności też ma „Przekaż
  mimo to” (z `acknowledge_eligibility`). Karta wyniku mówi per rekrutacja: przekazano / nie zapisano (komunikat
  serwera, np. cudza rezerwacja) / zapisano bez przekazania i dlaczego. Od startu zapisu do zamknięcia karty wyniku
  panel trzyma formularz z tym samym wyborem (`onSessionChange`), choć kotwica jest już w „Zweryfikowanym”, a lista
  rekrutacji się odświeżyła. `onForwarded` (panel przechodzi na CV) dopiero po zamknięciu karty wyniku, gdy kotwica
  przeszła.
- **Notatka z rozmowy:** pasek „Uzupełnij z notatki” odczytuje notatkę dla kotwicy, a ten sam tekst dla pozostałych
  rekrutacji (`recommendationCardsApi.readNote` per rekrutacja); wyniki trafiają tylko w puste miejsca
  (`noteFillPatches`); „Cofnij wypełnienie” zdejmuje tylko to, co wpisała notatka (pole poprawione po wypełnieniu
  zostaje). Notatkę zakłada zapis pierwszej pary, kolejne wskazują ją `note_id` — serwer przyjmuje notatkę
  z innej rekrutacji tej osoby z tej samej rozmowy (`_joint_note_from_other_pair`, ≤ 60 min).
- **Pochodzenie wartości (15.10.2026):** pole albo odpowiedź wpisana z notatki, zdaniem z haseł albo z podpowiedzi
  Luny niesie pochodzenie (`JointOrigin`, klucz = ścieżka pola wspólnego) do zapisu KAŻDEJ pary (`card.origins`,
  `origin`/`keywords` odpowiedzi) — jak w pojedynczym formularzu. Pochodzenie trzyma się wartości: poprawka ręczna
  je zdejmuje (zdanie z haseł — dopiero wyczyszczenie). Pod polem „z notatki (AI) — zapisz formularz”, przy pytaniu
  plakietka („z notatki”, „zdanie z haseł”, „z podpowiedzi Luny”).
- **Narzędzia pojedynczego formularza w trybie wspólnym (15.10.2026, `joint-screening-tools.tsx`):**
  - wcześniejsze odpowiedzi: `reassign-context` i Luna (`reassign-suggestions`) osobno dla każdej pary (płatne
    wywołanie tylko przy wcześniejszych rozmowach i pytaniu bez zapisanej odpowiedzi); pod wspólnym pytaniem
    podpowiedź z pierwszej rekrutacji, która ją ma; „Użyj tej odpowiedzi” / „Użyj wszystkich odpowiedzi (N)” /
    „Pomiń”;
  - „Pomiń brakujące” osobno w każdej rekrutacji, której serwer na to pozwala (`skip_reason`), z notatką
    wewnętrzną TEJ rekrutacji — pomija tylko jej pytania bez odpowiedzi;
  - „Ułóż w zdanie” przy odpowiedziach (kontekst pierwszej rekrutacji pytania) i polach opisowych oceny
    (`CARD_PHRASABLE_FIELDS`, kontekst ich rekrutacji); język zdań: przełącznik albo język CV klienta rekrutacji;
    błąd Luny stoi w formularzu (bez dymka), formularz działa ręcznie.
- **Liczenie (D4):** każda para to osobny screening i osobna weryfikacja w KPI i lidze — bez zmian.
- **Pamięć rozmowy (16.10.2026, decyzje Artura D1 A, D2 A, D3 B; makiety
  https://claude.ai/artifact/8n9ReijRxXmYDHJqzPW1gW).** Do tej daty formularz wspólny był kluczowany zestawem
  zaznaczonych rekrutacji, więc odznaczenie, dołożenie, „+ Dodaj i dołącz”, przejście pojedynczy ↔ wspólny
  i odświeżenie listy w tle kasowały wszystkie niezapisane wpisy — także w rekrutacjach, które zostały
  (zgłoszenie rekrutera). Teraz:
  - wpisy rekrutera żyją w pamięci osoby (`lib/screening-memory.ts`, `store/screening-memory.ts`) pod adresem
    niezależnym od zaznaczenia: odpowiedź = rekrutacja + pytanie, pola o osobie raz, „Czy pracował u Klienta”
    per klient, ocena/stawka/„Pomiń brakujące” per rekrutacja, pochodzenia pod stałymi kluczami, notatka
    z rozmowy. Formularz (pojedynczy i wspólny, dowolny zestaw) przy starcie bierze z niej wpisy swoich
    rekrutacji jako zmiany rekrutera; nowy zestaw może więc dalej montować nowy formularz;
  - w pamięci jest tylko to, co rekruter ruszył i co różni się od stanu serwera pary (porównanie bez skrajnych
    odstępów) — stawka na start i odpowiedź innej rekrutacji na wspólne pytanie się nie liczą. Wpis
    przywrócony z pamięci, który jest równy wartości startowej formularza (np. „Tak” w kotwicy, gdy inna
    rekrutacja ma zapisane „Tak”), nie jest dla RHF „ruszony” — zostaje, bo był w pamięci wcześniej;
  - stawka z formularza pojedynczego jest stawką tej rekrutacji; w formularzu wspólnym wraca do pola
    wspólnego tylko w trybie „Ta sama stawka we wszystkich”, inaczej do pola tej rekrutacji. Zapamiętana
    stawka niesie tryb, w którym ją wpisano (`shared.same_rate`) — tryb na start zależy od stawek par.
    „Czy pracował u Klienta” z formularza wspólnego ma kopię przy kotwicy (formularz pojedynczy nie zna
    klienta przed wczytaniem listy „Screening dla”);
  - zapis do pamięci czyta ruszone pola z `control._formState`, nie z `formState` (w RHF 7.88 to migawka
    z ostatniego renderu — zapis zaraz po przywróceniu gubił przywrócone wpisy);
  - wspólne pytanie po ponownym zaznaczeniu bierze odpowiedź z rekrutacji, która była w rozmowie najpóźniej
    (`touchedAt`, remis — kotwica);
  - odznaczona rekrutacja z wpisami ma „N odpowiedzi w pamięci · zaznacz, żeby wróciły”, pod listą
    „Odznaczono … · Cofnij”, ponowne zaznaczenie mówi „Wróciły N odpowiedzi z pamięci”;
  - **zapis czyści pamięć całej rozmowy (D2 A)**, także wpisy odznaczonych rekrutacji — nad przyciskami stoi
    wcześniej „Zapis obejmie … Wpisy odznaczonych rekrutacji są w pamięci — po zapisie znikną” z „zaznacz”;
    para z nieudanym zapisem (cudza rezerwacja, 409) zachowuje swoje wpisy. Zapis odznaczonych z rozmową
    odrzucony (D2 C) — rezerwacja 12 h i screening w KPI tam, gdzie kandydat odpadł;
  - **pamięć w `sessionStorage` per osoba pisząca i kandydat, najdłużej 12 h bez zmian (D3 B)** — przeżywa
    zamknięcie panelu, kliknięcie innej osoby i odświeżenie; po powrocie „Przywrócono niezapisany screening
    z HH:MM” i zaznaczenie z tej samej Tablicy, „Odrzuć szkic” (z potwierdzeniem) kasuje. Wylogowanie czyści
    (`clearSessionArtifacts`). Wpis z karty to dane z zewnątrz — zepsuty kształt = brak pamięci;
  - tylko w panelu osoby w Nowych/Screeningu z prawem zapisu (tam, gdzie „Screening dla”); poza nim
    formularz pojedynczy działa jak dotąd. Sekcja 4 Championa (`experience_checks`) i „Cofnij wypełnienie”
    po zmianie zestawu nie są pamiętane (cofnięcie zdejmuje wtedy tylko powiązanie z notatką).
- **„W innych rekrutacjach”** w „Co już wiemy” pyta quick-view z `exclude_job_id` i pokazuje sumę
  (`current_recruitments_total`) — do 14.10.2026 bieżąca rekrutacja zajmowała jedno z 3 miejsc i „…i N więcej” nigdy
  się nie pokazywało.

