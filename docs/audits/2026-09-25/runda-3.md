# Audyt NEXUS 25.09.2026 — runda 3

> **Baza:** `9d85252d8` · **Status:** naprawione w PR #1840 (merge c72f411a4, na produkcji 25.09.2026). Decyzje: przeskok „Zweryfikowany → Rozmowa u klienta” bez QC zostaje; progi wyścigu = migawka na okres; prywatne spotkania Outlook bez treści.
> Oryginalny raport (prywatny artefakt): https://claude.ai/artifact/CN4ffWLKsPQYm38pgGN2Dr
> Reguły wynikające z naprawy: `CLAUDE.md`, sekcja „Audyt 25.09.2026 — reguły po naprawie”.

NEXUS · main + PR #1836 (9d85252d) · 25.09.2026

# Audyt, runda 3: poprawki trzymają, nowe obszary mają swoje błędy

Pracowało 7 agentów. Dwóch sprawdzało poprawki z rundy 2, pięciu przeglądało obszary, których rundy 1–2 nie audytowały głęboko: generator CV i Championa, generator B2B, Insights i konkursy, uprawnienia trasa po trasie, powiadomienia, M365 i Jarvisa. Wszystko tylko w trybie odczytu. Pozycje oznaczone jako „potwierdzone” sprawdziłem sam w kodzie. Poprzednie rundy: [1](https://claude.ai/artifact/BtnT7zb5kwPk5gNLvg56x6), [2](https://claude.ai/artifact/Hcs6cYoiaJ187RmuFMZspY).

## Trend  **61 → 19 → 2** błędy w poprawionym kodzie: runda 1, runda 2 (głównie niekompletne poprawki), runda 3 (1 regresja + 1 bliźniak) **0** luk typu IDOR przy przeglądzie trasa po trasie (~40 plików API) **21** nowych pozycji z obszarów dotąd nieaudytowanych (10 wysokich)

Poprawki z rund 1–2 są stabilne. Z rundy 2 wypadła jedna regresja: warunek „data końca = dzień zakończenia” jest zawsze prawdziwy dla umów, które zakończył nocny cron. Został też jeden bliźniak: `/from-linkedin` obok naprawionego wcześniej bulk-add. Pozostałe znaleziska są w obszarach, do których audyt dopiero teraz zajrzał. Najpoważniejsze to podpięcie cudzej skrzynki Outlook i trzy błędy wokół nagród w konkursach oraz rozwiązań umów B2B.

## Czeka na decyzję (stan w chwili raportu)

- **Czy naprawiam?** Proponuję jeden PR z 10 wysokimi i 13 średnimi pozycjami. Każda dostanie test, który najpierw pada, i przegląd bliźniaczych ścieżek.
- **Skok przez „CV wysłane”.** Czy przesunięcie z „Zweryfikowany” wprost na „Rozmowę u klienta” lub „Umowę” ma przechodzić QC i stawkę DL tak jak „CV wysłane”? Okno w UI już to blokuje, serwer nie. Rekomenduję tak.
- **Progi wyścigu 1 500 zł.** Czy zamrażać próg na koniec miesiąca (migawka), a edycję celów, od których zależy nagroda, zostawić tylko adminowi? Dziś zmienia je Head of Recruitment i zmiana działa wstecz.
- **Prywatne spotkania z Outlooka.** Pomijać przy synchronizacji, czy importować bez treści (sam „zajęty”)?

## Wysokie

### Link logowania M365 podpina cudzą skrzynkę do konta rekrutera `[Bezpieczeństwo]` `[nowy]` `[potwierdzone]`

`api/microsoft365.py:191-251` · `services/m365/oauth.py:223`

Callback bez logowania ustala właściciela tylko z podpisanego `state` i nie porównuje `mailbox_upn` ani `oid` z kontem NEXUS. Rekruter A wysyła koledze B adres logowania, B loguje się swoim kontem, a skrzynka i kalendarz B trafiają do konta A. A może wtedy czytać pocztę B i wysyłać z niej maile.

### `/from-linkedin` wstawia kandydata na dowolny etap, z pominięciem QC CV, stawki DL i Cpro `[Rekrutacja]` `[bliźniak R2]` `[potwierdzone ×2]`

`schemas/candidate.py:922` · `api/candidates.py:3364`

`stage` przyjmuje każdy `PipelineStage`. `"cv_sent"` stawia kartę od razu w „CV wysłane”, `"hired"` zatrudnia bez kontraktu, a `"rejected"` kończy się 500 na CHECK-u. Rozszerzenie Chrome używa tylko czterech etapów wejściowych, więc zawężenie niczego nie psuje.

### „Cofnij zakończenie” robi z umowy zlecenia zakończonej przez cron umowę bezterminową `[Kontrakty]` `[regresja R2]` `[potwierdzone]`

`contract_termination_reversal.py:499-503`

Bez migawki `terminated_on` pochodzi z `end_date`, więc warunek `end_date == terminated_on` jest zawsze prawdziwy. Umowa zlecenie z datą końca w treści wraca jako bezterminowa, a blokada `end_date_passed` się nie uruchamia. Warunek ma wymagać `terminated_at`.

### Podpisane rozwiązanie lub wypowiedzenie zamyka umowę w Generatorze natychmiast i z pominięciem 0367 `[Generator B2B]` `[nowy]` `[potwierdzone]`

`b2b_documents/effects.py:283, 500, 515, 600`

Umowa trafia do „Zakończonych” już przy podpisie, także gdy wypowiedzenie kończy się w przyszłym miesiącu. Nie powstają przy tym `termination_restore`, `termination_mode` ani dane rozwiązania na kontrakcie. Przy powrocie po przerwie brakuje nowej umowy, a rozwiązana umowa wraca do „Aktywnych”.

### Wiersz z Excela utyka w „Umowach bez projektu” bez drogi powrotu `[Generator B2B]` `[nowy]` `[od agenta]`

`contract_termination_sync.py:185-197` · `b2b_contract_generator.py:3462`

Synchronizacja zakończenia bierze wiersz z Excela po kandydacie i przestawia go na `suspended`. „Przywróć” wymaga `contract_id`, którego wiersz z Excela nigdy nie dostanie, więc kończy się 409. Jedynym wyjściem zostaje nieprawdziwe „Zakończona”.

### Podium lig na ekranie pokazuje innych zwycięzców i inne kwoty niż wypłata `[Konkursy]` `[nowy]` `[potwierdzone]`

`api/competitions.py:119-133`

Ligi biorą `ranked[:3]` bez `award_order`: pomijają kwalifikację i remisy, które rozstrzyga admin. Lider bez wymaganego placementu stoi na ekranie przy kwocie 5 000 zł, a wypłata trafiłaby do kogoś innego. Wyścigi miesięczne mają już tę poprawkę, ligi nie.

### Mail o zmianie etapu omija wyciszenia i uprawnienia do sekcji `[Powiadomienia]` `[nowy]` `[potwierdzone]`

`stage_notification_emitter.py:204-227`

Dzwonek idzie przez `emit` i respektuje wyciszenia oraz sekcje. Mail sprawdza tylko politykę dostarczania, bez `user_can_receive_notification`. Wyciszona kategoria dalej przysyła maile, a osoba bez sekcji Pipeline dostaje nazwisko kandydata, klienta i notatkę.

### Karta akcji Jarvisa pokazuje kandydata od modelu, a zapis trafia gdzie indziej `[Jarvis]` `[nowy]` `[od agenta]`

`jarvis/tools.py:2014, 2060, 1908, 1947`

W `save_interview_debrief` `candidate_id` służy tylko do opisu karty, a zapis celuje w `event_id`. Nikt nie sprawdza, czy to rozmowa tego kandydata. Debrief i pytania klienta mogą trafić do cudzej rozmowy, a wiązanie RODO powstaje z kandydatem z karty.

### Akceptacja pytań screeningowych ze szkicu AI po cichu gubi pytania `[Champion]` `[nowy]` `[od agenta]`

`champion_draft_service.py:867`

Deduplikacja po `id` (`q1…`) i przy konflikcie wygrywa istniejące pytanie. Profil ma q1–q3, DL przyjmuje 8 pytań z „Generuj z opisu”. Zapisuje się 5, 3 znikają, a propozycja dostaje status `accepted`.

### Zapis samych notatek Championa unieważnia dopasowania i budzi automaty `[Champion]` `[nowy]` `[potwierdzone]`

`api/jobs.py:3011-3022, 3093, 3099`

Zwolnienie z przeliczenia obejmuje tylko `["search"]`. Samo „odhacz do dopytania” w notatkach oznacza wszystkie wyniki jako nieaktualne i wrzuca rekrutację do auto-matchu. To łamie regułę „Notatki nie zmieniają wymagań”.

## Średnie

**13 pozycji**

- **Kafle pulpitu i Jarvis porównują niepełny miesiąc z pełnym, przesuniętym oknem.** Na początku miesiąca pokazują fałszywe spadki. `custom_metrics/windows.py:66` nie używa `previous_matching_window`. Potwierdzone.
- **Metryka finansów w kreatorze ignoruje wybrany okres.** Liczy „na dziś”, a podpisuje wynik okresem z formularza. „Marża w sierpniu” to w rzeczywistości dzisiejsze MRR (`engine.py:587`). Potwierdzone.
- **Liga DL uwzględnia tylko główną rolę** (`competitions.py:509`). Cele DL liczą się też przy roli dodatkowej. Potwierdzone.
- **`POST /competitions/freeze` nie sprawdza okresu.** Przyjmuje dowolny format i okres, który się jeszcze nie skończył. Zamrożenie jest nieodwracalne.
- **Progi wyścigu 1 500 zł** są czytane przy zamrażaniu, a zmienia je HoR. Zmiana działa wstecz. Precyzja w % nie ma górnego limitu.
- **Skok przez „CV wysłane” omija QC i stawkę DL po stronie serwera.** Dotyczy też Jarvisa (`pipeline.py:558`). Potwierdzone.
- **Mail odrzucenia bez trwałej rezerwacji.** Deploy w trakcie wysyłki może spowodować drugi mail do kandydata (`rejection_email_scheduler.py:392`). Potwierdzone.
- **Strona kariery:** wymagania, miasto, start i długość są czytane na żywo. Nie obejmuje ich zatwierdzenie ani kontrola nazwy klienta.
- **Prywatne spotkania z Outlooka** (`sensitivity`) są importowane z treścią i widoczne dla admina, HoR i Finansów.
- **Ręczna zmiana statusu w Generatorze B2B nie kasuje `termination_restore`.** Cofnięcie zakończenia albo powrót po przerwie przywraca wtedy „Aktywną”.
- **Import Championa z generatora CV kasuje notatki zespołu** i nadpisuje zapisane pola pustymi wartościami (`CvGenerator.tsx:108`, brak `current`).
- **Stawka ze szkicu AI Championa trafia do budżetu bez reguły „z tekstu”.** Zakres albo MD przeliczone przez model staje się dealbreakerem.
- **Wpis główny poczty zamówień łapie każdy `IntegrityError`,** nie tylko konflikt unikalności, więc inny błąd więzu po cichu gubi załącznik.

## Niskie

**9 pozycji**

- `/generate-upload` nie wymaga klienta. JSON `/generate` w tej sytuacji odpowiada 422.
- Płatny podgląd AI Championa w uploadzie rusza przed walidacją pliku CV.
- `PUT champion-profile` i `/champion/validate` ze złym typem dają 500 zamiast 422.
- Przywrócenie opublikowanej centralnie reguły CV daje 422.
- Numeracja B2B bierze rok z UTC, więc 1 stycznia przed 01:00 podpowiada poprzedni rok. Zbieżność numerów w obrębie roku jest sprawdzana tylko dla wierszy z Excela.
- Odrzucony wpis „Nieudane” staje się „oryginałem”. Ponownie przysłany ten sam PDF zostanie duplikatem (zgodne z instrukcją, do potwierdzenia).
- Finanse widzą zdanie „odrzuć wpis”, choć przycisku nie mają.
- Zapisane wyszukiwanie z odwróconym zakresem przy każdym przebiegu skanera loguje ostrzeżenie, a właściciel nie dostaje sygnału.
- CLAUDE.md jest nieaktualny: pisze, że „edycja obowiązującej reguły CV zdejmuje zatwierdzenie”, a od #1437 działa szkic.

## Sprawdzone i czyste

- **Uprawnienia trasa po trasie:** ~40 plików API bez nowej luki IDOR. Każdy zasób ładuje jedna funkcja ze sprawdzeniem zakresu, używana przez wszystkie jego trasy. Impersonacja odcina zapis centralnie, a rola `user` dostaje redakcję pól. Poza zakresem z braku czasu zostały `rate_cards`, `md_consumption` (fragmenty), `job_portals`, `service_accounts` i kilka innych.
- **Poprawki z rundy 2:** poczta (`_add_journal_row`, pojedynczy wpis bez sha, `_first_with_sha`), `update_contract`, skaner MD, `gate_stage_row`, `/bulk-move`, `_is_entry_column`, `_recover_session` (20/20 savepointów), pickery, 422 dla zakresów i krótkiego tekstu. PR #1834 (lista wymagań) jest zgodny z regułami obu silników i zapisów v3.

- **Generator CV:** bramka zgody RODO obejmuje każdą trasę, która oddaje plik. AI nie blokuje generacji. Kwota jest naliczana po walidacjach. Wersja blind jest lustrem renderera.
- **Konkursy:** `award_order` i remisy w wypłacie, wykluczone placementy we wszystkich licznikach, kwoty ukryte przed HoR, 3. dzień roboczy i import Traffita przed zamrożeniem.
- **Jarvis:** idempotentne potwierdzenie, wykonanie z zapisanymi argumentami, tryb internetu bez danych. **Strona kariery:** zgoda, pułapka na boty, biała lista pól.

**Niepotwierdzone:** nie uruchamiałem testów z bazą, bo lokalnie nie ma Postgresa. Pozycje „od agenta” mają plik:linia i scenariusz z raportu, ale ich nie czytałem. Wdrożenie #1836 w chwili pisania raportu jeszcze czekało na produkcję (`/api/health` pokazywał `ab1a9301a`).


---

## Notatki weryfikacyjne koordynatora

Surowe notatki z weryfikacji (plik:linia sprawdzone w kodzie). „POTWIERDZONE” = sprawdzone przez koordynatora, bez oznaczenia = zgłoszone przez agenta.

### Audyt runda 3 — potwierdzone
#### Poprawki r2 poczta+pieniądze
- R3-1 POTWIERDZONE [POPRAWKA-R2]: contract_termination_reversal.py:499-503 warunek end_date == terminated_on; bez migawki terminated_on = terminated_at or pending.effective_date or end_date → dla umowy zakończonej przez cron (bez terminated_at) tautologia → UZ/UoP z datą w treści wraca bezterminowa (regres R1), end_date_passed nie odpala. Poprawka: wymagać contract.terminated_at is not None.
- niskie: order_mail_ingest 1826 łapie każdy IntegrityError (zawęzić do uq_*); odrzucony failed staje się oryginałem sha (świadomie?); Finanse widzą "odrzuć wpis" bez przycisku.
#### Powiadomienia/M365/Jarvis
- R3-2 POTWIERDZONE [NOWY] wysokie: microsoft365.py callback — state podpisany z user_id, brak porównania bundle.mailbox_upn/oid z user.email → link logowania A kliknięty przez B podpina skrzynkę B do A (czyta pocztę, wysyła jako B).
- R3-3 POTWIERDZONE [NOWY]: stage_notification_emitter.py:204-227 mail bez user_can_receive_notification (wyciszenia, sekcje) — tylko load_policy.
- R3-4 [NOWY] (agent, wysoka): Jarvis save_interview_debrief karta z candidate_id modelu, zapis po event_id bez sprawdzenia; pool_name/title od modelu.
- R3-5 [NOWY] (agent): strona kariery — must/nice, miasto, start, długość czytane na żywo, poza hashem zatwierdzenia i lintem.
- R3-6 POTWIERDZONE [NOWY] średnie: rejection_email_scheduler.py:392 send_new bez commit_reservation → po CancelledError/commit fail drugi mail do kandydata.
- R3-7 [NOWY] średnie: kalendarz M365 bez sensitivity → prywatne spotkania rekruterów widoczne adminowi/HoR/Finansom.
#### B2B
- R3-8 POTWIERDZONE [NOWY]: b2b_documents/effects.py _set_register_status zamyka umowę natychmiast (także przyszła data), bez migawki termination_restore / termination_mode → powrót po przerwie przywraca rozwiązaną umowę, cron pomija.
- R3-9 [NOWY] średnia: ręczna zmiana statusu nie kasuje termination_restore → cofnięcie/powrót przywraca „Aktywna”.
- R3-10 [NOWY] wysoka: wiersz z Excela → suspended przez sync, bez drogi powrotu (409 contract_id NULL).
- niskie: rok numeracji z UTC 1.01; zbieżność seq między latami dla wierszy NEXUSA.
#### Insights/konkursy
- R3-11 POTWIERDZONE [NOWY]: custom_metrics/windows.py:66 Window.previous = okno tej samej długości wstecz (dla this_month 1–3.10 → 31.08–30.09) zamiast previous_matching_window → fałszywe spadki na kaflach i w Jarvisie.
- R3-12 POTWIERDZONE [NOWY]: custom_metrics/engine.py:587 finance group_by none/client liczy na dziś, etykieta okresu z wyboru → „marża w sierpniu” = dzisiejsze MRR.
- R3-13 POTWIERDZONE [NOWY]: api/competitions.py:119 ligi (poza monthly_recommendations) top3 bez award_order (kwalifikacja, remisy) → ekran pokazuje inne podium/kwoty niż wypłata.
- R3-14 [NOWY] średnia: POST /competitions/freeze bez walidacji okresu (format, zakończony) — nieodwracalne.
- R3-15 [NOWY] średnia: progi wyścigu 1500 zł czytane przy zamrażaniu z celów KPI edytowalnych przez HoR, działają wstecz, brak limitu dla precyzji w %.
- R3-16 POTWIERDZONE [NOWY] średnia: competitions.py:509 liga DL tylko User.role==delivery_lead (bez roles), a cele DL liczone dla roli dodatkowej.
#### CV/Champion
- R3-17 POTWIERDZONE [NOWY bliźniak R2]: candidates.py:3364 from-linkedin target_stage = data.stage (dowolny PipelineStage) → open_process na cv_sent/hired bez QC/DL/Cpro.
- R3-18 POTWIERDZONE [NOWY] średnia: pipeline.py:558 bramka QC/DL tylko dla celu cv_sent/Cpro — skok Zweryfikowany→Rozmowa u klienta/Umowa omija QC i stawkę DL (front blokuje, serwer/Jarvis nie).
- R3-19 POTWIERDZONE [NOWY]: jobs.py:3011 search_rows_only tylko dla fields_changed==["search"]; zapis samych insights unieważnia dopasowania i budzi automaty (łamie „notatki nie zmieniają wymagań”).
- R3-20 [NOWY] średnia: import Championa z generatora CV (bez current) kasuje notatki i nadpisuje pola pustymi.
- R3-21 [NOWY] wysoka: szkic AI Championa — dedup pytań screeningowych po id q1.. gubi pytania.
- R3-22 [NOWY] średnia: stawka ze szkicu AI do budżetu bez reguły z tekstu.
- drobne: generate-upload bez client_id; podgląd Championa płatny przed walidacją; 500 na złym typie champion; 422 przy przywróceniu publikacji centralnej; CLAUDE.md nieaktualny opis „edycja zdejmuje zatwierdzenie”.
- R2 fixes (rekrutacja/front/#1834): czyste; LinkedIn potwierdzony niezależnie (+ stage=rejected → 500 CHECK)
