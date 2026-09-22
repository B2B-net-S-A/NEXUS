# Audyt NEXUS — 22 września 2026

Stan raportu: zakończony audyt przekrojowy wskazanego snapshotu; nie jest pełną certyfikacją wszystkich procesów ani ról.

## Wynik

Zidentyfikowano **48 ustaleń: 10 P1, 37 P2, 1 P3; brak ustalonego P0**. Osobno: **1 niezgodność kontraktu Fireflies do potwierdzenia na rzeczywistym API**, poza licznikiem 48. Kilka ekranów z tą samą przyczyną zgrupowano w jedno ustalenie, np. cztery pozorne puste stany w FE-03.

To nie znaczy „48 awarii zaobserwowanych na produkcji”. Podstawa ustaleń: **27 z reprodukcją syntetyczną, 17 potwierdzonych przepływem kodu/kontraktem, 3 operacyjne potwierdzone w GitHub oraz 1 bezpośrednio w HTTP produkcji**. Incydentów biznesowych, liczby dotkniętych osób i strat nie mierzono.

Najważniejsze problemy:

1. **Uprawnienia integracji:** wybrane scopes OAuth nie ograniczają rodzaju zasobu (AUTH-01), a ich cofnięcie nie ogranicza już wydanego tokena (AUTH-02). RBAC acting usera nadal działa.
2. **Poprawność podpisów:** negatywny wynik może zamknąć sprawę, nie jest sprawdzane powiązanie PDF z umową/osobą, a liczba podpisów zastępuje kontrolę stron (SIG-01–03). Błędy warunkowe na użyciu modułu; jego aktywacja produkcyjna nie została ustalona.
3. **Matching i CV:** C/C++/C# zlewają się w jeden skill (SCV-01); mapa CV może pokazywać stare wymagania (SCV-03); wspólny kraj zawyża dopasowanie miasta (SCV-02).
4. **Finanse:** harmonogram kosztu/prognozy jest pomijany, przyszłe aktywne kontrakty zasilają bieżące kwoty, a API przyszłego aneksu zmienia godziny już dziś (AN-01–03).
5. **Niezawodność:** wysyłka systemowa ma `degraded` (OPS-04); brak udanego restore drill (OPS-03); E2E nie jest wymaganą bramką merge queue (OPS-01).
6. **Codzienna praca:** duplikaty checklisty, ukryte błędy, stare dane po aneksie, ucięte listy i błędne daty (FE-01–13).

### Priorytety

- **P1:** istotna luka granicy dostępu, błędna kwalifikacja dokumentu/kandydata/kwoty, ryzyko błędnego przypisania prywatnych danych albo brak krytycznego zabezpieczenia operacyjnego.
- **P2:** funkcja daje zły wynik lub nie wykonuje operacji w opisanym warunku, istnieje obejście albo wpływ jest ograniczony.
- **P3:** mniejszy wpływ lub rzadki/przyszły próg skali; nadal konkretny defekt.

Priorytet oznacza wagę w chwili spełnienia warunku, a nie dowód częstotliwości. Autenti w publicznym health jest `unconfigured`; CloudTalk/Fireflies i signing nie mają w tym audycie potwierdzonej aktywacji. Nie są opisane jako bieżące incydenty tych usług.

## Wersje i stan produkcji

| Element | Ustalenie |
|---|---|
| Audytowany kod i reprodukcje | `e4eb0d7beb91d3dfcb74ca2824022e5966107d8a` |
| Początkowy odczyt produkcji, 10:19 CEST | ten sam `e4eb0d7beb91d3dfcb74ca2824022e5966107d8a` |
| Końcowy origin/main i backend, 10:35 CEST | `2a983aa61bdfe747c4a88c5677bff35aeb1d18d6` |
| Zmiana w trakcie audytu | dwa commity; przejrzano różnicę 14 plików, +103/−21 |
| Wpływ nowych commitów na findingi | jedyny wspólny plik to JobShareTab; zmiana stopki poza logiką FE-13. Pozostałe cytowane pliki niezmienione |
| Backend health | HTTP 200, healthy; **m365_mail=degraded** w obu odczytach |
| Deep health | początkowo HTTP 200, healthy; nie jest to test poprawności danych biznesowych |
| Alembic | DB i kod: `0340_career_public_title`, brak orphaned — w obu odczytach |
| Auth methods | password=false, microsoft=true, self_registration=false |
| Odczyty anonimowe | candidates/jobs/clients/margin-totals: 401, bez ujawnienia danych |
| Frontend version.json | bez sesji HTTP403; dokładny SHA frontendu nie został niezależnie potwierdzony |

Dowody: [production-initial.json](../outputs/audit-2026-09-22/production-initial.json), [production-final.json](../outputs/audit-2026-09-22/production-final.json), [source-drift-review.json](../outputs/audit-2026-09-22/source-drift-review.json). Endpointy produkcyjne: [health](https://api.nexus.dynaminds.pl/api/health), [deep](https://api.nexus.dynaminds.pl/api/health/deep), [Alembic](https://api.nexus.dynaminds.pl/api/health/alembic). Są to pomiary chwilowe.

### CI, wdrożenie i monitoring

- Audytowane e4eb0d7: [CI Gate — success](https://github.com/B2B-net-S-A/NEXUS/actions/runs/35690541367), [Deploy — success](https://github.com/B2B-net-S-A/NEXUS/actions/runs/35690667784), [E2E — failure](https://github.com/B2B-net-S-A/NEXUS/actions/runs/35691288502): 4 failed / 17 passed.
- Zakończony E2E odnotował dwie kwestie dostępności candidates/jobs oraz nieudane scenariusze kliknięcia osoby i klawiaturowej zmiany etapu. To dowód nieudanego testu, a nie automatycznie cztery potwierdzone błędy produktu. Nie dodano ich jako czterech osobnych findingów bez analizy przyczyny. [Artefakt Playwright](https://github.com/B2B-net-S-A/NEXUS/actions/runs/35691288502/artifacts/10678499746).
- Końcowe 2a983aa: [CI — success](https://github.com/B2B-net-S-A/NEXUS/actions/runs/35702337477), [CI Gate — success](https://github.com/B2B-net-S-A/NEXUS/actions/runs/35704291299), [Deploy — success](https://github.com/B2B-net-S-A/NEXUS/actions/runs/35704454801); [E2E — failure](https://github.com/B2B-net-S-A/NEXUS/actions/runs/35702337492). Dwa kolejne E2E były w toku przy końcowym odczycie; nie przyjęto dla nich sukcesu. [current-sha-ci.json](../outputs/audit-2026-09-22/current-sha-ci.json).
- [Backup drill 21.09 — failure](https://github.com/B2B-net-S-A/NEXUS/actions/runs/35585386489), przed pobraniem/dekryptacją kopii. Nie oznacza to, że kopie nie istnieją. [backup-drill.json](../outputs/audit-2026-09-22/backup-drill.json).
- [Sentry digest 21.09 — success](https://github.com/B2B-net-S-A/NEXUS/actions/runs/35605253349): log potwierdza przyjęcie przez Teams dla dwóch projektów; odbioru w kanale Teams nie kontrolowano. Historycznego błędu braku tokena Sentry nie przeniesiono do tego raportu. [sentry-monitor.json](../outputs/audit-2026-09-22/sentry-monitor.json).

## Metoda i zakres

Audyt read-only: świeży origin/main w izolowanym worktree `/private/tmp/nexus-audit-20260922`, przegląd źródeł i caller/callee, porównania frontend/API, szybkie testy istniejące, syntetyczne wejścia do rzeczywistych funkcji oraz kontrola HTTP/CI/UI. Nie zmieniano kodu aplikacji, danych biznesowych ani konfiguracji; nie użyto lokalnego Dockera ani testów obciążeniowych produkcji. Pliki raportu i dowodów są lokalnymi artefaktami audytu; nie tworzono PR ani wdrożenia.

**59 istniejących testów przeszło w 1,11 s:** okresy analityki, polityka candidate/job i semantyka read-only. [focused-tests.txt](../outputs/audit-2026-09-22/focused-tests.txt). Nie jest to wynik całego suite.

Reprodukcje są wykonywane na wyodrębnionych oryginalnych funkcjach AST, komponentach TSX w pamięci i fixture SQL/HTTP/React Query. To mocniejsze potwierdzenie niż sam grep, lecz nie pełne uruchomienie aplikacji z Postgres, Graph/DSS i wszystkimi middleware. Konkretne pominięte zależności opisano przy wynikach.

| Obszar | Pokrycie | Granica dowodu |
|---|---|---|
| OAuth/auth/RBAC | przepływ tokena, scope, onboarding, SSO password, odczyt CV | bez prób wykorzystania produkcyjnych uprawnień; brak pełnej macierzy ról |
| Podpisy i kalendarz | statusy, walidacja dokumentu, upload offline, kolejność skutków | walidator/Outlook syntetyczne; aktywacja signing nieustalona |
| Kontrakty i finanse | daty, harmonogramy, aneksy, cache, MD import | brak produkcyjnego uzgodnienia wszystkich kwot/faktur |
| Matching i CV | kanonizacja skilli, miasto, wymagania mapy CV | bez pełnej oceny jakości modeli na goldens |
| M365/CloudTalk/Fireflies/Autenti | retry, idempotencja, identyfikatory, paginacja, kursory | bez realnych wysyłek, importów i synchronizacji |
| Frontend | kontrakty, wyposażenie, onboarding, maile, spotkania, career-share | reprodukcje częściowe; większość findings nieodtwarzana na prod |
| Produkcyjny UI | zalogowane Dashboard i Insights, nawigacja Kontrakty/Analityka | końcowy render Analityki niepotwierdzony; dalszy CDP timeout, natywny fokus zmieniał się równolegle |
| CI/deploy/restore/monitoring | rzeczywiste metadane i wybrane logi GitHub, SHA/health/schema | brak uruchamiania nowych workflow i pełnego restore/load testu |

Dziennik UI: [ui-observations.md](../outputs/audit-2026-09-22/ui-observations.md). Nie ma screenshotów stanowiących dowód znalezionego błędu UI. Timeout narzędzia nie został uznany za usterkę NEXUS.

## Kolejność napraw

1. **Pilnie ograniczyć błędne decyzje i przywrócić widoczność operacyjną:** AUTH-01, SIG-01/02, SCV-01/03, AN-01, OPS-04. Najpierw ustalić aktywację i ekspozycję signing/CloudTalk; nie rozszerzać ich użycia przed testami.
2. **Usunąć ryzyko niespójnych skutków zewnętrznych:** INT-04–08/14, CAL-01 oraz AUTH-02. Wspólna trwała intencja operacji, walidacja przed wywołaniem, jednoznaczne ponowienia.
3. **Domknąć bramki operacyjne:** naprawić E2E, następnie uzgodnić wymaganą bramkę (OPS-01), uruchomienie smoke (OPS-02) i pełny restore drill (OPS-03). Zmiany polityki dostępu, rulesetu i sekretów pozostają decyzją właściciela.
4. **Dane i algorytmy:** AN-02/03, SCV-02/04, INT-01–03/11/12; po naprawie ocenić potrzebę przeliczenia wyników/backfillu na zidentyfikowanym zbiorze. Ten audyt nie ustalił jego wielkości.
5. **Codzienny interfejs:** FE-02–12, CV-01, AUTH-04, SIG-04/05; na końcu większe progi paginacji/eksportu FE-01/13 i wyłączone ścieżki legacy Autenti INT-09/10.

Każda naprawa powinna spełnić kryterium przy konkretnym ID, przejść odpowiedni test regresji i hosted CI oraz dostać dowód po wdrożeniu. Sam zielony health nie zamyka findingu. Naprawa algorytmu wymaga decyzji o wersji cache i ewentualnym przeliczeniu wyników.

## Rejestr ustaleń

| ID | Priorytet | Dowód | Problem |
|---|---|---|---|
| [AN-01](#an-01) | P1 | syntetyka | Analityka marży i prognoza pomijają harmonogramy stawek |
| [AUTH-01](#auth-01) | P1 | syntetyka | Zakres OAuth ogranicza tylko odczyt/zapis, a nie wybrany rodzaj zasobu |
| [INT-01](#int-01) | P1 | kod | CloudTalk sync przypisuje nagranie do arbitralnego kandydata przy wspólnym telefonie |
| [OPS-01](#ops-01) | P1 | GitHub | E2E nie jest wymaganą bramką kolejki merge, mimo deklaracji workflow |
| [OPS-03](#ops-03) | P1 | GitHub | Najnowszy restore drill nadal nie dociera do kopii off-site |
| [OPS-04](#ops-04) | P1 | HTTP prod | Produkcyjny kanał poczty systemowej zgłasza degraded |
| [SCV-01](#scv-01) | P1 | syntetyka | Matching uznaje C++, C# i C za tę samą umiejętność |
| [SCV-03](#scv-03) | P1 | syntetyka | Mapa wymagań CV pomija aktualny kontrakt rekrutacji i używa starych kolumn |
| [SIG-01](#sig-01) | P1 | syntetyka | Negatywny lub nierozstrzygnięty wynik walidacji podpisu może zakończyć podpis jako completed |
| [SIG-02](#sig-02) | P1 | syntetyka | Wgrany podpisany PDF nie jest wiązany z treścią umowy i oczekiwanym podpisującym |
| [AN-02](#an-02) | P2 | syntetyka | Bieżący przychód i rankingi liczą aktywne kontrakty, które jeszcze się nie rozpoczęły |
| [AN-03](#an-03) | P2 | syntetyka | API aneksu z datą przyszłą natychmiast zmienia godziny i jednostkę rozliczenia |
| [AUTH-02](#auth-02) | P2 | syntetyka | Odebranie zakresu klientowi OAuth nie ogranicza już wydanego tokena |
| [AUTH-03](#auth-03) | P2 | kod | Wymuszenie zmiany hasła jest egzekwowane w nawigacji frontendowej, ale nie w dostępie do API |
| [AUTH-04](#auth-04) | P2 | syntetyka | Formularz zmiany hasła konta SSO kończy się nieobsłużonym wyjątkiem |
| [CAL-01](#cal-01) | P2 | syntetyka | Zmiana spotkania w Outlooku następuje przed końcową walidacją i odmową w NEXUS |
| [CV-01](#cv-01) | P2 | syntetyka | Odczyt brandowanego CV zapisuje trwały draft także przy sekcji tylko do odczytu |
| [FE-02](#fe-02) | P2 | syntetyka | Zapis aneksu nie odświeża aktywnego rejestru kontraktów ani historii stawek |
| [FE-03](#fe-03) | P2 | syntetyka | Błąd odczytu aneksów, onboardingu, sprzętu i notatek wygląda jak brak danych |
| [FE-04](#fe-04) | P2 | syntetyka | Generator checklisty tworzy duplikaty po ponownym kliknięciu i niepełny zestaw po częściowej awarii |
| [FE-05](#fe-05) | P2 | kod | Operacje zapisu onboardingu i sprzętu kończą się błędem bez komunikatu dla użytkownika |
| [FE-06](#fe-06) | P2 | syntetyka | Zwrot sprzętu zapisuje poprzedni dzień przez użycie daty UTC |
| [FE-07](#fe-07) | P2 | kod | Domyślna data aneksu zamraża się na dzień załadowania modułu |
| [FE-08](#fe-08) | P2 | syntetyka | Wynik wyszukania maila innego kandydata otwiera pusty wątek |
| [FE-09](#fe-09) | P2 | kod | Czytnik maili urywa historię na 50 wątkach i wyniki szukania na 50 trafieniach |
| [FE-10](#fe-10) | P2 | kod | Historia stawek oferuje niedozwolone zapisy wszystkim rolom |
| [FE-11](#fe-11) | P2 | kod | Szybkie planowanie spotkania pozwala wybrać tylko pierwszych 100 kandydatów |
| [FE-12](#fe-12) | P2 | syntetyka | Planowanie spotkania późnym wieczorem generuje nieprawidłowe godziny 24 i 25 |
| [FE-13](#fe-13) | P2 | kod | Generator linków kariery gubi rekrutacje za pierwszą setką i nazywa je nieopublikowanymi |
| [INT-02](#int-02) | P2 | syntetyka | CloudTalk catch-up nie kończy rozmów pozostających w initiated |
| [INT-03](#int-03) | P2 | kod | CloudTalk wyznacza okno naprawcze z ostatniej rozmowy zamiast trwałego kursora importu |
| [INT-04](#int-04) | P2 | syntetyka | Równoległe wysyłki M365 wysyłają dwa maile mimo jednego klucza idempotencji |
| [INT-05](#int-05) | P2 | syntetyka | M365 po cichu pomija drugi mail z inną treścią, jeżeli temat i minuta są takie same |
| [INT-06](#int-06) | P2 | syntetyka | GraphClient automatycznie powtarza POST po niepewnym wyniku i może dublować zaproszenia |
| [INT-07](#int-07) | P2 | kod | Compose wysyła e-mail przed sprawdzeniem istnienia kandydata |
| [INT-08](#int-08) | P2 | kod | Jednorazowa awaria pobrania załącznika M365 nie trafia do kolejki ponowień |
| [INT-09](#int-09) | P2 | syntetyka | Autenti zapisuje ten sam unikalny klucz aktywności dla wysłania i każdego dalszego zdarzenia |
| [INT-10](#int-10) | P2 | kod | Autenti sweeper nie obsługuje umów ramowych i aneksów bez contract_id |
| [INT-11](#int-11) | P2 | syntetyka | Fireflies przesuwa watermark i czyści stan błędu mimo niezaimportowanych transkryptów |
| [INT-12](#int-12) | P2 | kod | Fireflies pobiera tylko pierwszą stronę transkryptów |
| [INT-14](#int-14) | P2 | kod | M365 zapisuje zmienne identyfikatory szkiców jako trwałe ID wysłanych wiadomości |
| [OPS-02](#ops-02) | P2 | GitHub | Automatyczny test produkcyjny po aktualnym wdrożeniu jest pominięty |
| [SCV-02](#scv-02) | P2 | syntetyka | Wspólny kraj wystarcza do pełnego dopasowania różnych miast |
| [SCV-04](#scv-04) | P2 | kod | Importer MD przyjmuje NaN i Infinity jako poprawne kwoty oraz osobodni |
| [SIG-03](#sig-03) | P2 | syntetyka | Dwa podpisy tej samej osoby są uznawane za podpis obu stron |
| [SIG-04](#sig-04) | P2 | syntetyka | Wgranie podpisanej umowy offline zawsze trafia w niedozwolony status draft |
| [SIG-05](#sig-05) | P2 | kod | Powiadomienie twierdzi, że kandydat przeszedł na Zatrudniony, choć kod nie zmienia pipeline |
| [FE-01](#fe-01) | P3 | kod | Eksport klientów ukrywa informację o obcięciu pliku przez CORS |

## Szczegóły i kryteria odbioru

<a id="an-01"></a>

### AN-01 · P1 — Analityka marży i prognoza pomijają harmonogramy stawek

**Dowód:** REPRO_SYNTETYCZNE_SQLITE.

**Warunek:** Wchodzi przyszła zmiana stawki kosztowej albo prognoza obejmuje przyszłą zmianę przychodu/kosztu.

**Skutek:** Ranking, sumy marż i prognoza pokazują kwoty odmienne od obowiązujących harmonogramów kontraktu.

**Uzasadnienie i granice:** Oryginalne funkcje z syntetycznym SQLite: po zmianie kosztu 50→75/h przy przychodzie100/h i160h marża=8000 zamiast4000. W prognozie nowy przychód200/h od października nadal daje16000 zamiast32000. Istnieje dobowy refresh rate_client, więc obecny przychód może zostać skorygowany przez cron; nie rozwiązuje przyszłej prognozy ani cache kosztowego. Niezależny przegląd wykluczył tę pozorną kontrę.

**Źródło:** [backend/app/api/contract_analytics.py:184–203](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/api/contract_analytics.py#L184-L203); [backend/app/api/contract_analytics.py:273–292](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/api/contract_analytics.py#L273-L292); [backend/app/api/contract_analytics.py:506–530](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/api/contract_analytics.py#L506-L530); [backend/app/api/reports.py:74–79](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/api/reports.py#L74-L79); [backend/app/services/contract_order_sync.py:1166–1209](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/contract_order_sync.py#L1166-L1209).

**Naprawa:** Współdzielić effective_rate_fields i date-effective odczyty, dla prognozy rozstrzygać stawki dla każdego miesiąca.

**Kryterium odbioru:** Aneksy kosztowe/przychodowe przed i po dacie wejścia dają zgodne kwoty w kontrakcie, analityce i prognozie; cron nie jest wymagany do poprawnego odczytu.

<a id="auth-01"></a>

### AUTH-01 · P1 — Zakres OAuth ogranicza tylko odczyt/zapis, a nie wybrany rodzaj zasobu

**Dowód:** REPRO_SYNTETYCZNE.

**Warunek:** Aktywny klient OAuth z acting_user_id i wąskim zakresem; rola konta technicznego ma szerszy dostęp.

**Skutek:** Wybór zakresów w Ustawieniach nie ogranicza integracji do wskazanego modułu. Nadal obowiązuje RBAC acting usera, ale granica candidate/job/dictionary nie jest egzekwowana.

**Uzasadnienie i granice:** Oryginalny resolver akceptuje dictionary:read dla odczytu kandydata i candidate:write dla zmiany rekrutacji. Kontrola read-only→write prawidłowo zwraca 403. Kod wprost nazywa brak mapowania świadomie odłożonym kompromisem; jest to luka kontraktu zakresów, nie brak całego uwierzytelniania. Nie testowano na produkcji.

**Źródło:** [backend/app/api/deps.py:140–189](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/api/deps.py#L140-L189); [backend/app/models/oauth_client.py:44–74](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/models/oauth_client.py#L44-L74); [backend/app/api/oauth_clients.py:59–65](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/api/oauth_clients.py#L59-L65).

**Naprawa:** Powiązać operację i zasób z wymaganym scope; wymagać także dotychczasowej roli i zakresu rekordu.

**Kryterium odbioru:** Macierz tokenów candidate/job/dictionary odrzuca operacje poza zakresem; uprawnienia samego acting usera nie omijają scope.

<a id="int-01"></a>

### INT-01 · P1 — CloudTalk sync przypisuje nagranie do arbitralnego kandydata przy wspólnym telefonie

**Dowód:** KOD.

**Warunek:** CLOUDTALK_ENABLED=true; zdarzenie pominięte przez webhook trafia do importu cyklicznego; co najmniej 2 kandydatów ma te same ostatnie 9 cyfr telefonu.

**Skutek:** Nagranie, transkrypcja i podsumowanie rozmowy trafiają na profil jednej przypadkowej osoby. Jest to ryzyko ujawnienia i błędnej atrybucji danych.

**Uzasadnienie i granice:** Resolver używa scalar(SELECT Candidate.id ... LIMIT 1), bez sprawdzenia liczby dopasowań. Upsert tworzy Call(candidate_id=wybrany_id). Webhook ma już ochronę ambiguous_match i zapis bez osoby, ale sync jej nie używa. Nie ustalano liczby takich danych produkcyjnych.

**Źródło:** [backend/app/tasks/cloudtalk_sync.py:85–97](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/tasks/cloudtalk_sync.py#L85-L97); [backend/app/tasks/cloudtalk_sync.py:113–117](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/tasks/cloudtalk_sync.py#L113-L117); [backend/app/tasks/cloudtalk_sync.py:152–165](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/tasks/cloudtalk_sync.py#L152-L165); [backend/app/api/calls.py:411–425](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/api/calls.py#L411-L425).

**Naprawa:** Wspólny resolver dla webhooka i syncu; 0/2+ dopasowania pozostawiają nieprzypisany Call do ręcznego rozstrzygnięcia.

**Kryterium odbioru:** Dwa rekordy z tym samym telefonem + call z zapisem nagrania: candidate_id pozostaje NULL, rozmowa pozostaje dostępna do ręcznego przypisania.

<a id="ops-01"></a>

### OPS-01 · P1 — E2E nie jest wymaganą bramką kolejki merge, mimo deklaracji workflow

**Dowód:** GITHUB_LIVE_I_KOD.

**Warunek:** Zmiana przechodzi pięć wymaganych checków, ale E2E stack jest czerwony.

**Skutek:** Kolejka może zmergować regresję zachowania UI i wdrożyć ją przed skutecznym E2E. Obecne SHA ma już rzeczywisty czerwony E2E.

**Uzasadnienie i granice:** Live ruleset main-baseline 22799346: required_status_checks zawiera Gitleaks secret scan, Backend (lint + migrations), Frontend (typecheck), Backend (pytest), Frontend (typecheck + build); nie zawiera E2E stack (ci-chromium). ALLGREEN nie czyni wszystkich niewymaganych workflow obowiązkowymi. Artefakt github-ruleset.json. Run 35691288502 dla e4eb0d7: 4 failed / 17 passed. Dokumentacja GitHub: [dokumentacja GitHub](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue) .

**Źródło:** [.github/workflows/e2e.yml:4–14](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/.github/workflows/e2e.yml#L4-L14).

**Naprawa:** Po naprawie rzeczywistych czerwonych scenariuszy dodać E2E jako wymagany kontekst i przywrócić właściwy trigger pull_request zgodnie z kontraktem GitHub; zmiana rulesetu wymaga osobnej zgody właściciela.

**Kryterium odbioru:** Kontrolowany czerwony E2E blokuje merge grupy, zielony kontekst raportuje się na PR i merge_group; nie stosować skipów ani słabszych asercji.

<a id="ops-03"></a>

### OPS-03 · P1 — Najnowszy restore drill nadal nie dociera do kopii off-site

**Dowód:** GITHUB_LIVE.

**Warunek:** Planowy backup-drill uruchomiony 21.09.2026.

**Skutek:** Brak bieżącego dowodu możliwości odtworzenia NEXUS z kopii poza serwerem; ścieżka odzyskania zatrzymuje się przed pobraniem/deszyfracją.

**Uzasadnienie i granice:** Run 35585386489 (2026-09-21T09:49:11Z) failure, krok Not configured — drill cannot run: The drill has no way to reach or decrypt the off-site backup. Poprzednie 34805878641 i 34082879244 także failure. Log wymienia wymagane BACKUP_AGE_PRIVATE_KEY/BACKUP_S3_ACCESS_KEY/BACKUP_S3_SECRET_KEY; nie odczytywano wartości sekretów. Dowód nie oznacza, że same kopie nie istnieją.

**Źródło:** [.github/workflows/backup-drill.yml:73–90](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/.github/workflows/backup-drill.yml#L73-L90).

**Naprawa:** Właściciel powinien uzupełnić dostęp read-only do off-site i pasujący klucz age, następnie wykonać pełny restore drill w CI.

**Kryterium odbioru:** Zielony drill z dowodem pobrania/dekryptacji, pg_restore, walidacji Alembic oraz wszystkich wymaganych artefaktów i liczników.

<a id="ops-04"></a>

### OPS-04 · P1 — Produkcyjny kanał poczty systemowej zgłasza degraded

**Dowód:** PRODUKCJA_HTTP.

**Warunek:** Odczyt produkcyjnego health22.09.2026 na audytowanym SHA.

**Skutek:** Bieżąca gotowość kanału wysyłki powiadomień systemowych nie jest potwierdzona; stan prób wskazuje problem lub niepewność doręczenia.

**Uzasadnienie i granice:** GET /api/health HTTP200 i status healthy przy checks.m365_mail=degraded. Według implementacji degraded wynika z nieudanych/niepewnych prób lub błędu odczytu stanu. Nie odczytywano sekretów ani nie wysyłano maila; nie ustalono bieżącej przyczyny, nadawcy ani liczby dotkniętych wiadomości. Główne healthy świadomie dotyczy dostępności, więc nie liczę tego jako osobny błąd health.

**Źródło:** [backend/app/main.py:1930–1942](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/main.py#L1930-L1942); [backend/app/services/m365/app_mail.py:96–124](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/m365/app_mail.py#L96-L124).

**Naprawa:** Sprawdzić trwały stan prób i konkretne kody błędów, skorygować przyczynę, następnie potwierdzić kontrolowane doręczenie i odczyt zdrowia kanału.

**Kryterium odbioru:** Kontrolowana wysyłka dochodzi do odbiorcy, zostaje trwale odnotowana, a health kanału jest healthy; ewentualne nadanie dostępu wymaga osobnej decyzji właściciela.

<a id="scv-01"></a>

### SCV-01 · P1 — Matching uznaje C++, C# i C za tę samą umiejętność

**Dowód:** potwierdzone syntetycznie w funkcjach z audytowanego SHA; bez produkcji.

**Warunek:** Oferta wymaga C++, a kandydat ma wyłącznie C# albo C (również aliasy cpp / csharp).

**Skutek:** Fałszywe zaliczenie must-have i przyznanie punktów za inną technologię. Kandydat może przejść bramkę brakujących must-have mimo znanego braku wymaganej umiejętności.

**Uzasadnienie i granice:** _canon_skill zachowuje wyłącznie znaki alfanumeryczne. skill_present("c++", {"c#"}) oraz przypadki odwrotne zwracają True. Reprodukcja najpierw używa rzeczywistej canonical_skill_names z mapą aliasów zgodną z seedem: cpp→c++, csharp→c#. Mapa aliasów nie usuwa błędu: dopiero późniejszy fallback sprowadza obie nazwy do c. Wywołania tej funkcji znajdują się w _score_skills i missing_must_skills.

**Źródło:** [backend/app/services/scoring_service.py:1022–1043](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/scoring_service.py#L1022-L1043); [backend/app/services/dealbreaker_filters.py:169–193](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/dealbreaker_filters.py#L169-L193); [backend/alembic/versions/0012_skill_taxonomy.py:50–51](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/alembic/versions/0012_skill_taxonomy.py#L50-L51).

**Naprawa:** Zachować znaczące +/# w kanonizacji; łączyć warianty przez jawny słownik aliasów. Po naprawie zmienić wersję scoringu/cache.

**Kryterium odbioru:** C, C++ i C# nie pasują do siebie; cpp↔C++ i csharp↔C# nadal pasują. Sprawdzić punkty, listę gap_must oraz bramkę must-have na tych samych przypadkach.

<a id="scv-03"></a>

### SCV-03 · P1 — Mapa wymagań CV pomija aktualny kontrakt rekrutacji i używa starych kolumn

**Dowód:** potwierdzone syntetycznie; droga zapisu i odczytu potwierdzona w kodzie, bez generowania CV w produkcji.

**Warunek:** Oferta ma legacy must_skills=[Java], nice_skills=[AWS]. Rekruter zapisuje matching_requirements z must Python i nice PostgreSQL. Aktualizacja tego kontraktu nie nadpisuje starych kolumn.

**Skutek:** Wyszukiwarka ocenia nowe kryteria, a klient otrzymuje interaktywną mapę CV dla Java/AWS. Może brakować wszystkich aktualnych wymagań; wynik porównania CV z ofertą jest merytorycznie błędny.

**Uzasadnienie i granice:** build_requirements czyta must/nice z Job bez sprawdzenia matching_requirements; fallback canonical działa tylko przy pustym legacy must i wyłącznie dla must. Syntetyczny zapis kryteriów Python/PostgreSQL daje job_skill_requirements={must:[python],nice:[postgresql]}, lecz build_requirements daje Java/AWS. Droga update_job: invalidate_changed_requirements zmienia tylko requirements_reviewed dla nowego kontraktu, następnie setattr zapisuje przesłane pola. load_candidate_generation_source rzeczywiście zapisuje wynik build_requirements do wejść generacji. Wariant tego samego błędu: stack Championa Python must + AWS nice przy pustych kolumnach daje w CV wyłącznie Python.

**Źródło:** [backend/app/services/cv_generator_b2b/requirement_map.py:78–90](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/cv_generator_b2b/requirement_map.py#L78-L90); [backend/app/services/requirement_contract.py:124–129](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/requirement_contract.py#L124-L129); [backend/app/services/scoring_service.py:777–786](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/scoring_service.py#L777-L786); [backend/app/services/cv_generator_b2b/standalone_service.py:2515–2517](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/cv_generator_b2b/standalone_service.py#L2515-L2517).

**Naprawa:** Budować obie listy z tego samego job_skill_requirements/requirements_for_job, którego używają wyszukiwanie i scoring; zachować alternatywy oraz poziom must/nice. Odświeżyć zależne mapy po zmianie kryteriów.

**Kryterium odbioru:** Po edycji matching_requirements mapa nowego CV zawiera wyłącznie aktualne Python/PostgreSQL; pusty aktualny kontrakt nie przywraca starych kryteriów. Fallback Championa zachowuje zarówno must, jak i nice.

<a id="sig-01"></a>

### SIG-01 · P1 — Negatywny lub nierozstrzygnięty wynik walidacji podpisu może zakończyć podpis jako completed

**Dowód:** REPRO_SYNTETYCZNE.

**Warunek:** SIGNING_ENABLED=true; QES raportowany z is_qes=true i TOTAL_FAILED, albo ścieżka AdES z INDETERMINATE. Nie ustalono bieżącej aktywacji modułu.

**Skutek:** System zapisuje dokument jako zakończony mimo braku pozytywnego wyniku walidacji.

**Uzasadnienie i granice:** Mapper wyznacza is_qes z nazwy poziomu; guard wyklucza tylko INDETERMINATE dla QES. Repro oryginalnych funkcji zapisuje completed dla QES/TOTAL_FAILED i AdES/INDETERMINATE. Kontrola QES/INDETERMINATE poprawnie zwraca 422. Jest to błąd stanu aplikacji, nie ocena skuteczności prawnej dokumentu.

**Źródło:** [backend/app/services/signing/sender.py:323–360](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/signing/sender.py#L323-L360); [backend/app/services/signing/validation.py:127–153](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/signing/validation.py#L127-L153); [backend/app/services/signing/sender.py:384–389](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/signing/sender.py#L384-L389).

**Naprawa:** Finalizować wyłącznie na jawnym pozytywnym werdykcie właściwym dla danej ścieżki; błąd walidatora pozostawia sprawę do ponowienia.

**Kryterium odbioru:** TOTAL_FAILED, INDETERMINATE i niedostępny walidator nigdy nie dają completed; poprawny podpis nadal przechodzi.

<a id="sig-02"></a>

### SIG-02 · P1 — Wgrany podpisany PDF nie jest wiązany z treścią umowy i oczekiwanym podpisującym

**Dowód:** REPRO_SYNTETYCZNE.

**Warunek:** Włączona ścieżka podpisu; do aktywnej sprawy trafia poprawnie podpisany plik innej sprawy lub osoby.

**Skutek:** Obcy dokument zostaje dołączony jako podpisana umowa tego kontraktu i zamyka jego sprawę podpisu.

**Uzasadnienie i granice:** finalize otrzymuje sig i pdf_bytes, ale do walidatora przekazuje tylko PDF; nie odczytuje źródłowej treści/oczekiwanych stron w celu porównania. Test z odmiennym syntetycznym plikiem i Different Signer zapisuje completed. Warstwy zewnętrzne chronią dostęp do sprawy, nie zgodność dokumentu.

**Źródło:** [backend/app/services/signing/sender.py:294–324](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/signing/sender.py#L294-L324); [backend/app/services/signing/sender.py:370–388](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/signing/sender.py#L370-L388); [backend/app/services/signing/validation.py:80–100](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/signing/validation.py#L80-L100).

**Naprawa:** Wiązać podpis z niezmiennym dokumentem źródłowym oraz sprawdzać tożsamość i rolę podpisujących; rozbieżności kierować do wyraźnej ręcznej weryfikacji.

**Kryterium odbioru:** Dokument B przesłany do sprawy A nie zamyka A; inna osoba nie jest automatycznie uznana za oczekiwaną stronę.

<a id="an-02"></a>

### AN-02 · P2 — Bieżący przychód i rankingi liczą aktywne kontrakty, które jeszcze się nie rozpoczęły

**Dowód:** REPRO_SYNTETYCZNE_SQLITE.

**Warunek:** Legalna aktywacja kontraktu z przyszłą start_date; dodatkowo okres między końcem kontraktu a dobową promocją statusu.

**Skutek:** Miesięczny przychód/marża i część liczników zawierają przyszłą współpracę; są niespójne z date-effective Insights i wykorzystaniem konsultantów.

**Uzasadnienie i granice:** WHERE ogranicza status active/ending bez start_date/end_date. Lifecycle jawnie dopuszcza przyszłą aktywację i wymaga oddzielnego okna dat dla raportów finansowych. SQLite: bieżący+przyszły+wczoraj zakończony active daje3 zamiast1. Stary status może być naprawiany cronem; przyszły kontrakt jest trwałym poprawnym warunkiem reprodukcji.

**Źródło:** [backend/app/api/contract_analytics.py:273–292](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/api/contract_analytics.py#L273-L292); [backend/app/api/contract_analytics.py:609–651](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/api/contract_analytics.py#L609-L651); [backend/app/services/contract_lifecycle.py:393–396](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/contract_lifecycle.py#L393-L396).

**Naprawa:** Rozdzielić operacyjny status kontraktu od aktywności finansowej na dzień; używać wspólnego predykatu dat.

**Kryterium odbioru:** Przyszły aktywny kontrakt trafia do odpowiednich miesięcy prognozy, lecz nie do dzisiejszego przychodu ani aktywnych osób.

<a id="an-03"></a>

### AN-03 · P2 — API aneksu z datą przyszłą natychmiast zmienia godziny i jednostkę rozliczenia

**Dowód:** KOD_I_REPRO_SYNTETYCZNE.

**Warunek:** Bezpośredni klient API tworzy rate_change dla kontraktu bez zamówień, effective_date w przyszłości, podając new_billing_hours_per_month lub new_rate_unit. Obecny formularz UI nie wysyła tych dwóch pól.

**Skutek:** Przyszły aneks zmienia bieżącą i historyczną wycenę już w chwili utworzenia.

**Uzasadnienie i granice:** Stawki mają harmonogram, lecz jednostka/godziny są przypisywane bez warunku daty. Repro gałęzi: effective_date2027-01-01, dziś2026-09-22,160h→80h od razu. Dalszy resync dla kontraktu bez zamówień tego nie odwraca (zweryfikowano niezależnie).

**Źródło:** [backend/app/api/contracts.py:4799–4817](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/api/contracts.py#L4799-L4817); [backend/app/schemas/contract_amendment.py:10–24](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/schemas/contract_amendment.py#L10-L24); [backend/app/services/contract_order_sync.py:481–501](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/contract_order_sync.py#L481-L501).

**Naprawa:** Datować wszystkie składowe stawki albo odrzucać przyszłe zmiany pól, których model nie potrafi odroczyć.

**Kryterium odbioru:** Do dnia aneksu pozostaje160h/stara jednostka; od effective_date obowiązuje80h/nowa jednostka; historia zachowana.

<a id="auth-02"></a>

### AUTH-02 · P2 — Odebranie zakresu klientowi OAuth nie ogranicza już wydanego tokena

**Dowód:** REPRO_SYNTETYCZNE.

**Warunek:** Administrator zawęża lub usuwa scopes aktywnego klienta po wydaniu tokena.

**Skutek:** Stary token zachowuje poprzedni zakres do wygaśnięcia. Wyłączenie całego klienta jest sprawdzane, samo odebranie uprawnienia nie.

**Uzasadnienie i granice:** Resolver bierze scopes wyłącznie z JWT. Syntetycznie client.scopes=[] + stary scope zapisu nadal rozwiązuje działającego usera. Wydawanie tokena sprawdza scopes, późniejsze requesty nie.

**Źródło:** [backend/app/api/deps.py:161–176](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/api/deps.py#L161-L176); [backend/app/api/oauth_clients.py:126–137](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/api/oauth_clients.py#L126-L137); [backend/app/api/oauth_token.py:94–107](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/api/oauth_token.py#L94-L107).

**Naprawa:** Przecinać scopes tokena z aktualnymi scopes klienta lub stosować wersję uprawnień/inwalidację tokenów.

**Kryterium odbioru:** Po usunięciu zakresu następne żądanie ze starym tokenem dostaje odmowę, bez oczekiwania na TTL.

<a id="auth-03"></a>

### AUTH-03 · P2 — Wymuszenie zmiany hasła jest egzekwowane w nawigacji frontendowej, ale nie w dostępie do API

**Dowód:** KOD.

**Warunek:** Hasłowe konto po admin-reset ma force_password_change=true, następnie loguje się hasłem tymczasowym i wywołuje API.

**Skutek:** Tymczasowe hasło nadal daje dostęp do danych i operacji bez spełnienia obowiązku jego zmiany. SSO celowo czyści tę flagę i nie jest objęte tym ustaleniem.

**Uzasadnienie i granice:** Przeszukanie backendu: flaga jest wydawana/zerowana, ale nie sprawdzana w domenowej ścieżce get_current_user. Middleware FE kieruje na profil. Stare tokeny przed resetem są prawidłowo unieważniane; problem dotyczy nowej sesji hasła tymczasowego.

**Źródło:** [backend/app/api/admin.py:545–570](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/api/admin.py#L545-L570); [backend/app/api/deps.py:290–321](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/api/deps.py#L290-L321); [frontend/src/middleware.ts:539–549](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/frontend/src/middleware.ts#L539-L549).

**Naprawa:** Wspólna zależność API powinna wymagać zmiany hasła i pozostawić dostęp jedynie do niezbędnych operacji odzyskania/profilu.

**Kryterium odbioru:** Nowy token z fpc nie wykonuje operacji biznesowych przed zmianą; change-password i bezpieczne odzyskanie są osiągalne.

<a id="auth-04"></a>

### AUTH-04 · P2 — Formularz zmiany hasła konta SSO kończy się nieobsłużonym wyjątkiem

**Dowód:** KOD_I_REPRO_SYNTETYCZNE.

**Warunek:** Konto SSO-only z password_hash=NULL używa widocznego formularza zmiany hasła.

**Skutek:** API zwraca 500/AttributeError zamiast jasnego komunikatu o sposobie zarządzania hasłem konta SSO.

**Uzasadnienie i granice:** Formularz jest montowany bez sprawdzenia dostawcy. verify_password wywołuje hashed_password.encode i łapie wyłącznie ValueError. Repro z None daje AttributeError. Dotyczy SSO-only, nie wszystkich kont Microsoft.

**Źródło:** [backend/app/models/user.py:83–84](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/models/user.py#L83-L84); [backend/app/api/auth.py:558–579](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/api/auth.py#L558-L579); [backend/app/core/security.py:41–55](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/core/security.py#L41-L55); [frontend/src/app/profile/page.tsx:387–394](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/frontend/src/app/profile/page.tsx#L387-L394).

**Naprawa:** Rozróżnić konto z hasłem i SSO-only w API oraz UI; null-hash obsłużyć kontrolowaną odmową.

**Kryterium odbioru:** SSO-only nie dostaje błędu 500, UI objaśnia właściwą ścieżkę; konto hasłowe nadal zmienia hasło.

<a id="cal-01"></a>

### CAL-01 · P2 — Zmiana spotkania w Outlooku następuje przed końcową walidacją i odmową w NEXUS

**Dowód:** REPRO_SYNTETYCZNE.

**Warunek:** Uprawniony właściciel modyfikuje synchronizowane spotkanie i w tej samej operacji podaje niedozwolone powiązanie rekrutacji lub lokalnie niepoprawny przedział.

**Skutek:** Outlook może już przyjąć zmianę, a API NEXUS kończy 403/422 i wycofuje lokalną transakcję. Systemy rozchodzą się; powiadomienia zewnętrzne mogły już zostać wysłane.

**Uzasadnienie i granice:** push Outlook znajduje się przed kontrolą wynikowych dat i zakresu job_id. Repro: push wywołany, potem _ensure_calendar_job_scope rzuca 403. Początkowa kontrola właściciela działa; błąd dotyczy kolejności kolejnych walidacji.

**Źródło:** [backend/app/api/calendar.py:661–701](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/api/calendar.py#L661-L701).

**Naprawa:** Wyliczyć i zwalidować pełny stan docelowy przed zewnętrznym wywołaniem; dla awarii po push stosować trwałe reconciliation.

**Kryterium odbioru:** Żądanie odrzucone lokalnie nie wywołuje Graph; udane żądanie daje spójny odczyt obu systemów.

<a id="cv-01"></a>

### CV-01 · P2 — Odczyt brandowanego CV zapisuje trwały draft także przy sekcji tylko do odczytu

**Dowód:** KOD_I_REPRO_SYNTETYCZNE.

**Warunek:** Członek zespołu rekrutacji z prawem odczytu CV i bez zapisu w sekcji otwiera CV w stanie none; również podgląd administratora jako taki użytkownik.

**Skutek:** GET zmienia stan dokumentu, rewizję i audyt autora mimo kontraktu odczytu. Finance ma osobny poprawny wyjątek transient; pozostałe role nie.

**Uzasadnienie i granice:** GET stosuje read dependency. Po renderze dla non-Finance ustawia draft i commit; drugi loader sprawdza membership, nie prawo zapisu sekcji. Syntetycznie none→draft, commits=1, activity branded_cv_initialized. Nie wykonywano takiego GET na produkcji.

**Źródło:** [backend/app/api/candidate_stage_cv.py:398–441](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/api/candidate_stage_cv.py#L398-L441); [backend/app/api/candidate_stage_cv.py:183–187](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/api/candidate_stage_cv.py#L183-L187).

**Naprawa:** Zwracać render transient dla odczytu; inicjalizację draftu przenieść pod jawny write dependency/POST.

**Kryterium odbioru:** GET z read-only i impersonacją nie zmienia żadnej tabeli; jawna inicjalizacja z write działa i jest audytowana.

<a id="fe-02"></a>

### FE-02 · P2 — Zapis aneksu nie odświeża aktywnego rejestru kontraktów ani historii stawek

**Dowód:** synthetic.

**Warunek:** Wczytać rejestr i panel wygasających kontraktów; w szczegółach przedłużyć/zakończyć kontrakt aneksem albo zmienić stawkę; wrócić przed upływem staleTime.

**Skutek:** Rejestr nadal pokazuje stary stan; panel kończących się kontraktów przechowuje stare dane nawet 5 minut. Otwarta wcześniej historia stawek także pozostaje stara.

**Uzasadnienie i granice:** onSuccess invaliduje [contracts], lecz aktualny rejestr używa [contracts-v2], a panel [contracts-expiring-v2]. Brak invalidacji [contract-rate-history,id]. Harness na rzeczywistym QueryClient: [contract,7].isInvalidated=true; trzy pozostałe klucze=false.

**Źródło:** [frontend/src/components/ContractAmendmentsTab.tsx:105–115](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/frontend/src/components/ContractAmendmentsTab.tsx#L105-L115); [frontend/src/components/v2/pages/ContractsListV2.tsx:660–703](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/frontend/src/components/v2/pages/ContractsListV2.tsx#L660-L703); [frontend/src/app/contracts/[id]/page.tsx:515–522](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/frontend/src/app/contracts/[id]/page.tsx#L515-L522).

**Naprawa:** Po aneksie unieważniać kanoniczne klucze rejestru, wygasających i historii stawek oraz zależne projekcje klienta.

**Kryterium odbioru:** Po sukcesie aneksu powrót do listy/panelu/historii od razu pokazuje nowe wartości, bez F5 i czekania na staleTime.

<a id="fe-03"></a>

### FE-03 · P2 — Błąd odczytu aneksów, onboardingu, sprzętu i notatek wygląda jak brak danych

**Dowód:** synthetic.

**Warunek:** GET odpowiedniej zakładki kontraktu zwraca 403/500 lub kończy się błędem sieci przed pierwszym poprawnym pobraniem.

**Skutek:** Użytkownik otrzymuje fałszywe zapewnienie, że nie ma aneksów, sprzętu, onboardingu lub notatek. Na onboardingu dodatkowo może uruchomić stworzenie drugiej checklisty.

**Uzasadnienie i granice:** Komponenty odczytują tylko data/isLoading, mapują data??[] i renderują empty state bez isError. Syntetyczne wykonanie aktualnych komponentów przy isError=true i data=undefined wygenerowało odpowiednio: Brak aneksów; Brak listy onboardingowej; Brak pozycji; Brak notatek ani rozmów.

**Źródło:** [frontend/src/components/ContractAmendmentsTab.tsx:99–103](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/frontend/src/components/ContractAmendmentsTab.tsx#L99-L103); [frontend/src/components/ContractAmendmentsTab.tsx:359–374](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/frontend/src/components/ContractAmendmentsTab.tsx#L359-L374); [frontend/src/components/ContractOnboardingTab.tsx:63–67](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/frontend/src/components/ContractOnboardingTab.tsx#L63-L67); [frontend/src/components/ContractOnboardingTab.tsx:110–129](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/frontend/src/components/ContractOnboardingTab.tsx#L110-L129); [frontend/src/components/contracts/ContractEquipmentTab.tsx:78–84](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/frontend/src/components/contracts/ContractEquipmentTab.tsx#L78-L84); [frontend/src/components/contracts/ContractEquipmentTab.tsx:140–147](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/frontend/src/components/contracts/ContractEquipmentTab.tsx#L140-L147); [frontend/src/components/contracts/ContractNotesTab.tsx:33–55](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/frontend/src/components/contracts/ContractNotesTab.tsx#L33-L55).

**Naprawa:** Rozdzielić loading/error/empty/success; użyć istniejącego QueryStateNotice z retry i ukryć akcje zależne od stwierdzenia pustego zbioru podczas błędu.

**Kryterium odbioru:** Mock 403/500 nigdy nie pokazuje twierdzenia Brak danych; widoczny jest błąd i ponowienie. Prawdziwe 200 [] nadal pokazuje pusty stan.

<a id="fe-04"></a>

### FE-04 · P2 — Generator checklisty tworzy duplikaty po ponownym kliknięciu i niepełny zestaw po częściowej awarii

**Dowód:** synthetic.

**Warunek:** Dwa szybkie kliknięcia Wygeneruj domyślny checklist przed odpowiedzią API albo awaria części z ośmiu osobnych POST.

**Skutek:** Powstaje do 16 pozycji dla ośmiu etykiet. Przy częściowej awarii zostaje niepełna lista; po pierwszym sukcesie znika przycisk generowania, bez informacji o brakujących pozycjach.

**Uzasadnienie i granice:** handleSeed uruchamia DEFAULT_ITEMS.forEach(createMutation.mutate), a przycisk nie ma disabled/isPending. Każdy POST osobno tworzy rekord, brak atomowego seedu/idempotencji. Harness z isPending=true potwierdził aktywny przycisk i 16 wywołań dla 8 unikalnych etykiet po dwóch kliknięciach. Scenariusz częściowej awarii potwierdzony statycznie, bez zapisów do DB.

**Źródło:** [frontend/src/components/ContractOnboardingTab.tsx:97–122](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/frontend/src/components/ContractOnboardingTab.tsx#L97-L122); [backend/app/api/contracts.py:4921–4936](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/api/contracts.py#L4921-L4936); [backend/app/models/contract_onboarding.py:21–39](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/models/contract_onboarding.py#L21-L39).

**Naprawa:** Wprowadzić atomowy/idempotentny seed po stronie API; blokować przycisk na cały batch i jasno raportować niepowodzenie.

**Kryterium odbioru:** Dwa kliknięcia tworzą dokładnie osiem pozycji. Awaria żadnej składowej nie pozostawia cichej częściowej checklisty, a retry nie duplikuje istniejących wpisów.

<a id="fe-05"></a>

### FE-05 · P2 — Operacje zapisu onboardingu i sprzętu kończą się błędem bez komunikatu dla użytkownika

**Dowód:** code.

**Warunek:** Zapis/dodanie/usunięcie pozycji onboardingu lub sprzętu odrzucone przez API, np. 403, walidacja lub 500.

**Skutek:** Kliknięcie pozornie nic nie robi. Użytkownik nie wie, czy operacja się zapisała, i może ją ponawiać; formularz nie pokazuje przyczyny walidacji.

**Uzasadnienie i granice:** Te mutacje mają wyłącznie mutationFn/onSuccess; komponenty nie renderują mutation.error/isError i nie mają onError. Globalny MutationCache przekazuje błąd do Sentry, nie do UI. Odróżnione od FE-03: tu błąd dotyczy zapisu, nie odczytu.

**Źródło:** [frontend/src/components/ContractOnboardingTab.tsx:69–95](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/frontend/src/components/ContractOnboardingTab.tsx#L69-L95); [frontend/src/components/contracts/ContractEquipmentTab.tsx:87–110](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/frontend/src/components/contracts/ContractEquipmentTab.tsx#L87-L110); [frontend/src/components/QueryProvider.tsx:24–29](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/frontend/src/components/QueryProvider.tsx#L24-L29).

**Naprawa:** Obsłużyć błędy każdej mutacji widocznym komunikatem z apiErrorMessage; zachować wprowadzone dane i umożliwić bezpieczne ponowienie.

**Kryterium odbioru:** Dla 403/422/500 użytkownik widzi komunikat odmowy/przyczynę błędu; brak toasta sukcesu i brak utraty formularza.

<a id="fe-06"></a>

### FE-06 · P2 — Zwrot sprzętu zapisuje poprzedni dzień przez użycie daty UTC

**Dowód:** synthetic.

**Warunek:** Operator w Polsce oznacza Zwrócono między 00:00 a 01:00 zimą lub 02:00 latem; analogicznie otwiera formularz przekazania sprzętu.

**Skutek:** Bez możliwości wyboru daty zwrotu przy szybkim oznaczeniu zapisuje się dzień wcześniejszy niż faktyczny dzień firmowy. Historia zwrotu staje się nieprawdziwa.

**Uzasadnienie i granice:** Komponent do opóźnień świadomie używa warsawToday(), ale returned_date i domyślne handed_over_date bierze z toISOString().slice(0,10). Reprodukcja dla 2026-09-22 00:30 Europe/Warsaw daje 2026-09-21.

**Źródło:** [frontend/src/components/contracts/ContractEquipmentTab.tsx:51–73](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/frontend/src/components/contracts/ContractEquipmentTab.tsx#L51-L73); [frontend/src/components/contracts/ContractEquipmentTab.tsx:205–216](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/frontend/src/components/contracts/ContractEquipmentTab.tsx#L205-L216); [frontend/src/components/contracts/ContractEquipmentTab.tsx:252–262](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/frontend/src/components/contracts/ContractEquipmentTab.tsx#L252-L262).

**Naprawa:** Stosować ten sam helper daty Europe/Warsaw do wszystkich dat kalendarzowych sprzętu.

**Kryterium odbioru:** Dla 00:30 22.09.2026 w Warszawie oba pola mają 2026-09-22; próby zimowa/letnia i przy zmianie DST przechodzą.

<a id="fe-07"></a>

### FE-07 · P2 — Domyślna data aneksu zamraża się na dzień załadowania modułu

**Dowód:** code.

**Warunek:** Otworzyć kontrakt, pozostawić aplikację/kartę przez noc, następnego dnia otworzyć formularz nowego aneksu.

**Skutek:** Nowy aneks otrzymuje wczorajszą datę wejścia w życie. Ten sam problem powtarza się przy kolejnych kontraktach w tej sesji SPA, bo moduł nie jest ponownie wykonywany.

**Uzasadnienie i granice:** TODAY i EMPTY są stałymi na poziomie modułu. Każde otwarcie formularza kopiuje {...EMPTY}, bez wyliczenia bieżącej daty. Dodatkowo TODAY jest datą UTC, więc o północy w Polsce może być nieaktualny już przy pierwszym załadowaniu.

**Źródło:** [frontend/src/components/ContractAmendmentsTab.tsx:65–76](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/frontend/src/components/ContractAmendmentsTab.tsx#L65-L76); [frontend/src/components/ContractAmendmentsTab.tsx:163–177](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/frontend/src/components/ContractAmendmentsTab.tsx#L163-L177).

**Naprawa:** Zastąpić stałą EMPTY fabryką formularza wywoływaną przy otwarciu, korzystającą z bieżącej daty firmowej.

**Kryterium odbioru:** Załadować moduł w dniu A, przestawić zegar na dzień B bez reloadu, otworzyć aneks: effective_date=B.

<a id="fe-08"></a>

### FE-08 · P2 — Wynik wyszukania maila innego kandydata otwiera pusty wątek

**Dowód:** synthetic.

**Warunek:** W profilu kandydata A wyszukać frazę występującą w mailach kandydata B w tej samej skrzynce i kliknąć wynik.

**Skutek:** Wynik jest widoczny, ale szczegóły pokazują zero wiadomości/(bez tematu), ponieważ zapytanie dotyczy niepasującej pary kandydat A + conversation B.

**Uzasadnienie i granice:** Wyszukiwanie backendu filtruje tylko user_id, nie candidate_id. SearchResults przekazuje tylko m365_conversation_id, gubiąc hit.candidate_id. EmailThreadView zawsze otrzymuje candidateId bieżącego profilu; backend wymaga równocześnie candidate_id i conversation_id. Harness rzeczywistego SearchResults potwierdził zgubienie candidate_id=22 w callbacku.

**Źródło:** [frontend/src/components/emails/EmailThreadList.tsx:90–103](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/frontend/src/components/emails/EmailThreadList.tsx#L90-L103); [frontend/src/components/emails/EmailThreadList.tsx:196–200](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/frontend/src/components/emails/EmailThreadList.tsx#L196-L200); [frontend/src/components/emails/EmailThreadList.tsx:413–418](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/frontend/src/components/emails/EmailThreadList.tsx#L413-L418); [frontend/src/components/emails/EmailThreadView.tsx:278–284](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/frontend/src/components/emails/EmailThreadView.tsx#L278-L284); [backend/app/api/email_threads.py:261–271](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/api/email_threads.py#L261-L271); [backend/app/api/email_threads.py:392–402](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/api/email_threads.py#L392-L402).

**Naprawa:** Zdecydować o zakresie wyszukiwarki: ograniczyć endpoint do kandydata albo przekazywać rzeczywisty kontekst trafienia i obsłużyć wiadomości nieprzypisane.

**Kryterium odbioru:** Wynik maila B otwiera właściwą korespondencję B lub nie jest zwracany w wyszukiwarce A; żadnego pustego wątku z poprawnego trafienia.

<a id="fe-09"></a>

### FE-09 · P2 — Czytnik maili urywa historię na 50 wątkach i wyniki szukania na 50 trafieniach

**Dowód:** code.

**Warunek:** Kandydat ma co najmniej 51 wątków lub zapytanie wyszukiwarki pasuje do ponad 50 wiadomości.

**Skutek:** Starsze wątki i dalsze wyniki są niedostępne z listy. UI nie informuje, że dane są obcięte i nie daje przycisku następnej strony.

**Uzasadnienie i granice:** listCandidateThreads nie podaje limitu/strony; backend domyślnie przycina do50. searchEmails ma offset, ale EmailThreadList zawsze wywołuje tylko z q, używając limit50 offset0 i ignorując total. Cały komponent nie posiada kontroli paginacji. Lista backendu dodatkowo ogranicza materiał wejściowy do1000 maili.

**Źródło:** [frontend/src/lib/api.ts:4944–4953](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/frontend/src/lib/api.ts#L4944-L4953); [frontend/src/components/emails/EmailThreadList.tsx:78–103](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/frontend/src/components/emails/EmailThreadList.tsx#L78-L103); [backend/app/api/email_threads.py:185–205](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/api/email_threads.py#L185-L205); [backend/app/api/email_threads.py:227–229](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/api/email_threads.py#L227-L229); [backend/app/api/email_threads.py:359–361](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/api/email_threads.py#L359-L361).

**Naprawa:** Dodać paginację/kursor listy wątków oraz paginację wyników wyszukiwania z rzeczywistym total i wskaźnikiem zakresu.

**Kryterium odbioru:** Przy 51+ wątkach i 51+ wynikach każdy rekord można osiągnąć z UI; licznik i komunikat zakresu odpowiadają API.

<a id="fe-10"></a>

### FE-10 · P2 — Historia stawek oferuje niedozwolone zapisy wszystkim rolom

**Dowód:** code.

**Warunek:** Delivery Lead/Finance/rekruter otwiera profil kandydata i klika Dodaj stawkę lub Usuń w Historii stawek.

**Skutek:** Użytkownik może wypełnić formularz, którego zapis zawsze dostanie403; usuwanie ma wyłącznie console.error, więc pozornie nic się nie dzieje. To rozjazd UI z API, nie obejście uprawnień.

**Uzasadnienie i granice:** RateHistoryWidget nie przyjmuje readOnly, nie sprawdza roli/capability i jest bezwarunkowo montowany w Dane handlowe. Oba backendowe endpointy zapisu wymagają AdminUser.

**Źródło:** [frontend/src/components/v2/pages/CandidateDetailV2.tsx:1450–1460](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/frontend/src/components/v2/pages/CandidateDetailV2.tsx#L1450-L1460); [frontend/src/components/RateHistoryWidget.tsx:97–123](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/frontend/src/components/RateHistoryWidget.tsx#L97-L123); [frontend/src/components/RateHistoryWidget.tsx:80–89](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/frontend/src/components/RateHistoryWidget.tsx#L80-L89); [frontend/src/components/RateHistoryWidget.tsx:208–214](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/frontend/src/components/RateHistoryWidget.tsx#L208-L214); [backend/app/api/phase5.py:196–200](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/api/phase5.py#L196-L200); [backend/app/api/phase5.py:233–237](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/api/phase5.py#L233-L237).

**Naprawa:** Uzależnić widoczność akcji od właściwej capability/admina; odczyt udostępniać zgodnie z CandidateFinanceReadAccess; jawnie pokazać błędy usunięcia.

**Kryterium odbioru:** Dla DL/Finance/rekrutera brak niedozwolonych przycisków; admin może zapisać/usunąć; odmowa serwera jest widoczna.

<a id="fe-11"></a>

### FE-11 · P2 — Szybkie planowanie spotkania pozwala wybrać tylko pierwszych 100 kandydatów

**Dowód:** code.

**Warunek:** Globalne + Dodaj → Zaplanuj spotkanie; próba przypisania kandydata spoza pierwszej strony listy.

**Skutek:** Nie da się powiązać spotkania z większością starszych kandydatów; dropdown nie oferuje wyszukiwania ani doładowania kolejnej strony.

**Uzasadnienie i granice:** Modal pobiera GET /api/candidates z page_size100 bez page/q, następnie renderuje wyłącznie items jako option. Brak odczytu total i dalszych zapytań. Ścieżka jest aktywna przez QuickActionsV2.

**Źródło:** [frontend/src/components/AppShell.tsx:1910–1914](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/frontend/src/components/AppShell.tsx#L1910-L1914); [frontend/src/components/AppShell.tsx:1960–1966](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/frontend/src/components/AppShell.tsx#L1960-L1966); [frontend/src/components/v2/shell/QuickActionsV2.tsx:165–167](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/frontend/src/components/v2/shell/QuickActionsV2.tsx#L165-L167); [backend/app/api/candidates.py:1270–1271](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/api/candidates.py#L1270-L1271).

**Naprawa:** Użyć istniejącego CandidateCombobox z wyszukiwaniem serwerowym zamiast statycznego selecta pierwszej strony.

**Kryterium odbioru:** Kandydata o pozycji >100 można wyszukać i wskazać, a zapis niesie jego właściwe candidate_id.

<a id="fe-12"></a>

### FE-12 · P2 — Planowanie spotkania późnym wieczorem generuje nieprawidłowe godziny 24 i 25

**Dowód:** synthetic.

**Warunek:** Otworzyć + Dodaj → Zaplanuj spotkanie po23:00 lokalnego czasu; po22:00 nieprawidłowy jest już domyślny koniec dla datetime-local.

**Skutek:** Formularz zawiera nieprawidłową datę/czas; po23:00 new Date(end_time).toISOString() rzuca Invalid time value przed wywołaniem API. Trzeba ręcznie poprawić wartości.

**Uzasadnienie i granice:** Godziny są składane tekstowo z getHours()+1/+2, bez rolloveru dnia. Reprodukcja dla23:15: start2026-09-22T24:00, koniec2026-09-22T25:00; koniec jest Invalid Date.

**Źródło:** [frontend/src/components/AppShell.tsx:1900–1906](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/frontend/src/components/AppShell.tsx#L1900-L1906); [frontend/src/components/AppShell.tsx:1922–1927](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/frontend/src/components/AppShell.tsx#L1922-L1927); [frontend/src/components/AppShell.tsx:1952–1957](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/frontend/src/components/AppShell.tsx#L1952-L1957).

**Naprawa:** Wyliczać przyszłe daty przez arytmetykę Date/setHours i formatować wynik jako prawidłowe lokalne YYYY-MM-DDTHH:mm.

**Kryterium odbioru:** Dla23:15 22.09 formularz proponuje00:00–01:00 23.09; wartości są akceptowane przez datetime-local i serializację ISO.

<a id="fe-13"></a>

### FE-13 · P2 — Generator linków kariery gubi rekrutacje za pierwszą setką i nazywa je nieopublikowanymi

**Dowód:** code.

**Warunek:** Użytkownik widzi ponad100 opublikowanych rekrutacji; chce utworzyć link dla pozycji z kolejnej strony lub otwiera dialog z defaultJobId takiej pozycji.

**Skutek:** Nie można wybrać tej rekrutacji z dropdowna; wejście z kontekstu wyświetla fałszywy komunikat Ta rekrutacja nie jest opublikowana, choć API statusu nie sprawdzono.

**Uzasadnienie i granice:** listPublishedJobs pobiera jedną stronę page_size100 i wyrzuca metadane paginacji. JobShareTab wnioskuje o nieopublikowaniu z !jobs.find(id), a nie ze statusu rekordu. Produkcyjnej liczby dostępnych published jobs nie sprawdzano.

**Źródło:** [frontend/src/lib/api/careerLinks.ts:208–215](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/frontend/src/lib/api/careerLinks.ts#L208-L215); [frontend/src/components/v2/career-share/JobShareTab.tsx:134–144](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/frontend/src/components/v2/career-share/JobShareTab.tsx#L134-L144); [frontend/src/components/v2/career-share/JobShareTab.tsx:349–362](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/frontend/src/components/v2/career-share/JobShareTab.tsx#L349-L362); [backend/app/api/jobs.py:610–614](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/api/jobs.py#L610-L614); [backend/app/api/jobs.py:868–868](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/api/jobs.py#L868-L868).

**Naprawa:** Pobierać wszystkie strony lub serwerowo wyszukiwać rekrutacje; dla defaultJobId odczytać wskazany rekord i rozstrzygać status na jego podstawie.

**Kryterium odbioru:** Rekrutacja published o pozycji101+ jest wybieralna i nie pokazuje fałszywego ostrzeżenia. Faktycznie zamknięta nadal dostaje właściwy komunikat.

<a id="int-02"></a>

### INT-02 · P2 — CloudTalk catch-up nie kończy rozmów pozostających w initiated

**Dowód:** REPRO_SYNTETYCZNE.

**Warunek:** CLOUDTALK_ENABLED=true; initiate-call utworzy stub z ID CloudTalk; końcowy webhook nie dotrze; okresowy import pobierze finalny status.

**Skutek:** Rozmowa pozostaje rozpoczęta mimo potwierdzonego zakończenia; wyniki i statystyki oparte na statusie są nieprawidłowe.

**Uzasadnienie i granice:** status jest obliczany, ale używany tylko przy INSERT. UPDATE dopisuje transkrypcję/czas, nigdy status. Uruchomienie oryginalnej funkcji AST na stubie: remote completed, duration=42 -> local initiated, duration=42, changed=1. Dowód repro_integrations.json: cloudtalk_status_recovery.

**Źródło:** [backend/app/tasks/cloudtalk_sync.py:145–193](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/tasks/cloudtalk_sync.py#L145-L193).

**Naprawa:** Stosować tę samą monotoniczną zmianę initiated -> status końcowy co w webhooku.

**Kryterium odbioru:** Brak webhooka + finalny rekord API kończy lokalny stub; replay nie cofa statusu końcowego.

<a id="int-03"></a>

### INT-03 · P2 — CloudTalk wyznacza okno naprawcze z ostatniej rozmowy zamiast trwałego kursora importu

**Dowód:** KOD.

**Warunek:** Webhook rozmowy z 10:00 zadziała, wcześniejszy z 09:30 zginie; importer uruchomi się po 10:00. Także błąd drugiej strony po zapisaniu nowszej pierwszej.

**Skutek:** Starsze brakujące rozmowy oraz późno dostępne nagrania/transkrypcje nie są już pobierane; deklarowany catch-up nie domyka luk.

**Uzasadnienie i granice:** date_from=max(MAX(Call.started_at), 30-dniowa podłoga). MAX pochodzi z wszystkich zapisanych rozmów, nie z potwierdzonego kompletnego przebiegu synchronizacji. Brak overlapu oraz trwałego punktu ostatniego pełnego sukcesu.

**Źródło:** [backend/app/tasks/cloudtalk_sync.py:196–207](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/tasks/cloudtalk_sync.py#L196-L207); [backend/app/tasks/cloudtalk_sync.py:219–255](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/tasks/cloudtalk_sync.py#L219-L255).

**Naprawa:** Trwały kursor potwierdzonego pełnego okna plus overlap na późno aktualizowane rozmowy; watermark przesuwać dopiero po wszystkich stronach.

**Kryterium odbioru:** Webhook nowszej rozmowy nie usuwa starszej luki z okna; awaria strony i ponowienie odtwarzają wszystkie rekordy bez duplikacji.

<a id="int-04"></a>

### INT-04 · P2 — Równoległe wysyłki M365 wysyłają dwa maile mimo jednego klucza idempotencji

**Dowód:** REPRO_SYNTETYCZNE.

**Warunek:** Dwa równoległe żądania compose tego samego użytkownika/odbiorcy/tematu w tej samej minucie; oba odczyty poprzedzają zapis.

**Skutek:** Adresat otrzymuje 2 wiadomości, a druga odpowiedź API może być 500; UNIQUE chroni tylko lokalny zapis po wysyłce.

**Uzasadnienie i granice:** SELECT istniejącego klucza -> Graph draft -> Graph send -> db.flush. Repro oryginalnego send_new z barierą w asynchronicznym Graph: external_send_calls=2, persisted_rows=1, drugi wynik IntegrityError.

**Źródło:** [backend/app/services/m365/sender.py:124–166](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/m365/sender.py#L124-L166); [backend/app/services/m365/sender.py:194–197](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/m365/sender.py#L194-L197).

**Naprawa:** Rezerwować trwały intent/outbox z unikalnym kluczem przed skutkiem zewnętrznym; obsługiwać wynik niepewny oraz współbieżne oczekiwanie.

**Kryterium odbioru:** Dwa równoległe żądania oraz retry po utracie odpowiedzi powodują jedną wysyłkę i spójne odpowiedzi bez 500.

<a id="int-05"></a>

### INT-05 · P2 — M365 po cichu pomija drugi mail z inną treścią, jeżeli temat i minuta są takie same

**Dowód:** REPRO_SYNTETYCZNE.

**Warunek:** Rekruter wysyła wiadomość i w tej samej minucie osobny nowy mail/korektę do tych samych odbiorców z tym samym tematem.

**Skutek:** Druga treść nie opuszcza NEXUS; API oddaje poprzedni mail jako udany wynik. Klucz nie rozróżnia też candidate_id i rodzaju wiadomości.

**Uzasadnienie i granice:** Fingerprint nie zawiera treści ani stabilnego ID intencji. Repro dwóch send_new z body Pierwsza tresc i Wazna korekta tresci: external_send_calls=1, second is first, zwrócona stara treść.

**Źródło:** [backend/app/services/m365/sender.py:66–92](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/m365/sender.py#L66-L92); [backend/app/services/m365/sender.py:117–137](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/m365/sender.py#L117-L137).

**Naprawa:** Klucz intencji generowany w UI i utrzymywany tylko dla ponowień tej operacji; weryfikować zgodność całego payloadu.

**Kryterium odbioru:** Dwie świadomie odrębne wiadomości są wysłane, ponowienie tej samej intencji nie wysyła drugi raz.

<a id="int-06"></a>

### INT-06 · P2 — GraphClient automatycznie powtarza POST po niepewnym wyniku i może dublować zaproszenia

**Dowód:** REPRO_SYNTETYCZNE_I_DOKUMENTACJA.

**Warunek:** Graph przyjmie POST /me/events i wyśle zaproszenie, lecz odpowiedź zginie (ReadTimeout/ReadError).

**Skutek:** Klient powtarza POST i tworzy drugie spotkanie oraz drugą wysyłkę do uczestników.

**Uzasadnienie i granice:** Retry nie zależy od metody HTTP, a payload wydarzenia nie zawiera transactionId. Repro oryginalnej pętli: POST wywołany 2 razy po utracie pierwszej odpowiedzi. Microsoft opisuje transactionId właśnie jako ochronę powtórzenia create-event: [dokumentacja Microsoft](https://learn.microsoft.com/en-us/graph/api/user-post-events?view=graph-rest-1.0) .

**Źródło:** [backend/app/services/m365/graph_client.py:140–150](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/m365/graph_client.py#L140-L150); [backend/app/services/m365/calendar.py:108–124](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/m365/calendar.py#L108-L124); [backend/app/services/m365/calendar.py:153–164](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/m365/calendar.py#L153-L164).

**Naprawa:** Dla create-event utrwalać transactionId intencji; retry operacji zapisu wymaga ochrony idempotencji albo statusu wyniku niepewnego.

**Kryterium odbioru:** Symulacja utraty odpowiedzi po przyjętym żądaniu pozostawia jedno wydarzenie i jedno zaproszenie.

<a id="int-07"></a>

### INT-07 · P2 — Compose wysyła e-mail przed sprawdzeniem istnienia kandydata

**Dowód:** KOD.

**Warunek:** POST /candidates/{nieistniejące_id}/emails/compose przez uprawnionego użytkownika z aktywną skrzynką; również usunięcie kandydata pomiędzy otwarciem formularza i wysłaniem.

**Skutek:** Rzeczywisty mail zostaje wysłany, potem flush z błędnym FK zwraca 500 i lokalny ślad wysyłki nie powstaje. Retry może ponowić mail.

**Uzasadnienie i granice:** Endpoint sprawdza połączenie M365, nie pobiera Candidate. Send_new robi Graph send przed Email(candidate_id=...) i flush; FK emails.candidate_id wymaga istniejącego rekordu.

**Źródło:** [backend/app/api/email_threads.py:328–347](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/api/email_threads.py#L328-L347); [backend/app/services/m365/sender.py:160–170](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/m365/sender.py#L160-L170); [backend/app/services/m365/sender.py:196–197](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/m365/sender.py#L196-L197); [backend/app/models/m365.py:175–178](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/models/m365.py#L175-L178).

**Naprawa:** Przed utworzeniem intencji wysyłki pobrać i zweryfikować kandydata; utrwalać zewnętrzną wysyłkę niezależnie od późniejszych zmian rekordu.

**Kryterium odbioru:** Nieistniejący kandydat daje 404/410 bez żadnego wywołania Graph; usunięcie po rozpoczęciu nie powoduje zgubienia historii ani duplikatu.

<a id="int-08"></a>

### INT-08 · P2 — Jednorazowa awaria pobrania załącznika M365 nie trafia do kolejki ponowień

**Dowód:** KOD.

**Warunek:** Wiadomość z CV została pobrana, lecz listowanie załączników, download lub zapis pliku chwilowo zawiedzie.

**Skutek:** Mail zostaje zaimportowany i delta potwierdzona, lecz CV nie ma pliku i nie trafia do parsera; bez kolejnej zmiany maila lub ręcznego backfillu luka może trwać bez końca.

**Uzasadnienie i granice:** Błąd listowania zwraca pustą listę, błąd pobrania ustawia parse_error; _upsert_message nie zwiększa result.errors. Worker wymaga storage_path IS NOT NULL i nie jest workerem downloadu. Przesunięcie kursora zależy tylko od result.errors.

**Źródło:** [backend/app/services/m365/attachment_handler.py:89–95](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/m365/attachment_handler.py#L89-L95); [backend/app/services/m365/attachment_handler.py:149–174](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/m365/attachment_handler.py#L149-L174); [backend/app/services/m365/sync.py:730–739](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/m365/sync.py#L730-L739); [backend/app/tasks/m365_cv_parse.py:124–135](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/tasks/m365_cv_parse.py#L124-L135); [backend/app/services/m365/sync.py:540–553](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/m365/sync.py#L540-L553).

**Naprawa:** Utrwalać zadania pobrania załączników przed potwierdzeniem delty albo traktować nieutrwalone pobranie jako błąd strony.

**Kryterium odbioru:** Pierwsze list/download 503, druga próba sukces: po ponowieniu plik i CV istnieją bez ponownej zmiany maila w Outlooku.

<a id="int-09"></a>

### INT-09 · P2 — Autenti zapisuje ten sam unikalny klucz aktywności dla wysłania i każdego dalszego zdarzenia

**Dowód:** REPRO_INWARIANTU_SQL_I_KOD.

**Warunek:** AUTENTI_ENABLED=true / istniejący proces legacy; po zapisanym signature_sent przychodzi completed/rejected/withdrawn albo użytkownik wysyła remind.

**Skutek:** INSERT drugiej Activity narusza UNIQUE(external_source,external_id), więc webhook/transakcja stanu podpisu nie przechodzi; remind/withdraw wykonuje skutek zewnętrzny przed lokalnym błędem.

**Uzasadnienie i granice:** Wszystkie akcje używają external_source=autenti, external_id=process_id. Indeks z 0075 nie zawiera action i nie znaleziono późniejszej migracji go wyłączającej. Repro SQLite dokładnego indeksu odrzuca wszystkie cztery dalsze akcje po signature_sent. To dowód inwariantu schematu, nie uruchomienie produkcyjnej bazy. Autenti jest opisane jako legacy i domyślnie wyłączone.

**Źródło:** [backend/alembic/versions/0075_traffit_phase5b_external_ids.py:29–45](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/alembic/versions/0075_traffit_phase5b_external_ids.py#L29-L45); [backend/app/services/autenti/sender.py:408–434](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/autenti/sender.py#L408-L434); [backend/app/services/autenti/webhook_handler.py:265–274](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/autenti/webhook_handler.py#L265-L274); [backend/app/api/autenti.py:294–305](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/api/autenti.py#L294-L305).

**Naprawa:** Oddzielić ID procesu od unikalnego ID zdarzenia; używać event_id / unikalnego klucza per akcja-intencja z właściwą deduplikacją.

**Kryterium odbioru:** Sekwencja sent -> remind -> completed przechodzi transakcyjnie; replay tego samego zdarzenia jest idempotentny.

<a id="int-10"></a>

### INT-10 · P2 — Autenti sweeper nie obsługuje umów ramowych i aneksów bez contract_id

**Dowód:** KOD.

**Warunek:** AUTENTI_ENABLED=true; klientowa umowa ramowa/aneks (contract_id=NULL) wymaga wykrycia wygaśnięcia albo pobrania podpisanego pliku.

**Skutek:** Expiry tworzy Activity(entity_id=NULL) i blokuje commit całej partii; retry pobrania tworzy ContractDocument(contract_id=NULL), którego baza nie przyjmie. Przy błędzie zapisu retry_count nie rośnie, więc job może pobierać bez końca.

**Uzasadnienie i granice:** Selektory obejmują wszystkie DocumentSignature. Sender klientowy celowo tworzy contract_id=None. Activity.entity_id oraz ContractDocument.contract_id są NOT NULL. Webhook świadomie pomija pobranie dokumentów klientowych, lecz retry sweeper nie ma tego filtra ani osobnej ścieżki zapisu.

**Źródło:** [backend/app/services/autenti/client_contracts_sender.py:114–126](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/autenti/client_contracts_sender.py#L114-L126); [backend/app/tasks/autenti_expiry_sweeper.py:68–75](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/tasks/autenti_expiry_sweeper.py#L68-L75); [backend/app/tasks/autenti_expiry_sweeper.py:99–109](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/tasks/autenti_expiry_sweeper.py#L99-L109); [backend/app/tasks/autenti_expiry_sweeper.py:153–158](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/tasks/autenti_expiry_sweeper.py#L153-L158); [backend/app/tasks/autenti_expiry_sweeper.py:210–239](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/tasks/autenti_expiry_sweeper.py#L210-L239); [backend/app/models/activity.py:30–32](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/models/activity.py#L30-L32); [backend/app/models/contract_document.py:30–33](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/models/contract_document.py#L30-L33).

**Naprawa:** Rozdzielić obsługę per target_kind; dla klientowych dokumentów zapisywać właściwy typ encji/pliku, a transakcję ograniczyć do jednego podpisu.

**Kryterium odbioru:** Partia kontrakt + umowa ramowa + aneks wygasa/pobiera się bez NULL constraint i bez blokowania pozostałych rekordów.

<a id="int-11"></a>

### INT-11 · P2 — Fireflies przesuwa watermark i czyści stan błędu mimo niezaimportowanych transkryptów

**Dowód:** REPRO_SYNTETYCZNE.

**Warunek:** Przynajmniej jeden stary transkrypt rzuci błąd przetwarzania niezatrzymujący transakcji, np. speaker_name=null albo niejednoznaczny email kandydata.

**Skutek:** Transkrypt nie trafia do notatek, następny przebieg pyta od bieżącej daty, status pokazuje error=None. Historyczny rekord pozostaje poza oknem do restartu/backfillu.

**Uzasadnienie i granice:** Oryginalna funkcja AST z transkryptem 2026-09-01 i speaker_name=null: errors=1, synced=0, last_synced_at przesunięte na 2026-09-22, state.error=null. Ścieżka nie uzależnia watermarku od errors.

**Źródło:** [backend/app/services/fireflies_sync.py:209–211](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/fireflies_sync.py#L209-L211); [backend/app/services/fireflies_sync.py:323–329](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/fireflies_sync.py#L323-L329); [backend/app/services/fireflies_sync.py:356–368](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/fireflies_sync.py#L356-L368).

**Naprawa:** Kursor aktualizować tylko po kompletnym imporcie albo trwałej kwarantannie/ponowieniach; last_success odróżnić od last_attempt.

**Kryterium odbioru:** Błąd jednego starszego transkryptu nie gubi go z następnego okna; status pozostaje partial/error do skutecznego ponowienia.

<a id="int-12"></a>

### INT-12 · P2 — Fireflies pobiera tylko pierwszą stronę transkryptów

**Dowód:** KOD_I_DOKUMENTACJA.

**Warunek:** Pierwszy import / dłuższa przerwa, w oknie znajduje się ponad 50 transkryptów; po zapewnieniu zgodności typu fromDate (INT-13).

**Skutek:** Część historii nigdy nie zostaje pobrana, mimo przesunięcia watermarku na teraz.

**Uzasadnienie i granice:** Jedno zapytanie transcripts(fromDate:...) bez limit/skip oraz bez pętli. Oficjalne API ogranicza pojedynczą odpowiedź do 50 i udostępnia skip: [dokumentacja Fireflies](https://docs.fireflies.ai/graphql-api/query/transcripts) . Nie odczytywano rzeczywistych transkryptów ani liczby konta.

**Źródło:** [backend/app/services/fireflies_sync.py:31–50](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/fireflies_sync.py#L31-L50); [backend/app/services/fireflies_sync.py:73–98](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/fireflies_sync.py#L73-L98); [backend/app/services/fireflies_sync.py:356–361](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/fireflies_sync.py#L356-L361).

**Naprawa:** Paginować limit/skip do końca stabilnego okna; dopiero wtedy potwierdzić jego watermark.

**Kryterium odbioru:** Fixture 125 transkryptów daje 125 notatek; awaria strony 2 jest ponawiana bez luki i bez duplikacji.

<a id="int-14"></a>

### INT-14 · P2 — M365 zapisuje zmienne identyfikatory szkiców jako trwałe ID wysłanych wiadomości

**Dowód:** KOD_I_DOKUMENTACJA.

**Warunek:** Mail wysłany z NEXUS przechodzi z Drafts do Sent Items albo użytkownik przenosi wiadomość między folderami.

**Skutek:** Lokalny wiersz zostaje z nieaktualnym ID szkicu; delta Sent Items może utworzyć drugi wiersz tego samego maila, a operacja po starym ID może dostać 404.

**Uzasadnienie i granice:** GraphClient nie ustawia Prefer: IdType="ImmutableId"; repo nie ustawia tego nagłówka w żadnym module M365. Sender zapisuje draft.id po send, a sync upsertuje wyłącznie po ID Graph. Microsoft dokumentuje zmianę domyślnych IDs po move i wymaga ImmutableId dla odnalezienia draftu po send: [dokumentacja Microsoft](https://learn.microsoft.com/en-us/graph/outlook-immutable-id) . Dodatkowa kontrola całego _upsert_message: internetMessageId jest wyłącznie odczytywane w 602 i przekazywane do nowego wiersza w 664/777; oba SELECT existing (579,706) używają tylko m365_message_id. Nie ma fallbacku po internetMessageId ani unikalnego indeksu na tym polu.

**Źródło:** [backend/app/services/m365/graph_client.py:109–113](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/m365/graph_client.py#L109-L113); [backend/app/services/m365/sender.py:160–172](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/m365/sender.py#L160-L172); [backend/app/services/m365/sync.py:574–584](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/m365/sync.py#L574-L584); [backend/app/services/m365/sync.py:660–706](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/m365/sync.py#L660-L706).

**Naprawa:** Wdrożyć spójne ImmutableId dla odczytów, wysyłki i subskrypcji oraz migrację/reconciliation obecnych identyfikatorów; nie dodawać samego nagłówka bez obsługi danych istniejących.

**Kryterium odbioru:** Compose -> send -> sync Sent Items pozostawia jeden Email i działające ID; przeniesienie między folderami nie traci powiązań.

<a id="ops-02"></a>

### OPS-02 · P2 — Automatyczny test produkcyjny po aktualnym wdrożeniu jest pominięty

**Dowód:** GITHUB_LIVE.

**Warunek:** Zakończony Deploy aktualnego e4eb0d7 uruchamia workflow_run E2E.

**Skutek:** Udane wdrożenie nie otrzymuje automatycznego potwierdzenia realnych odczytowych przepływów po zalogowaniu.

**Uzasadnienie i granice:** Run 35690855813: event=workflow_run, headSha=e4eb0d7..., job Playwright against production=skipped. Odnotowano w e2e-post-deploy.json. Nie odczytano wartości repo variables (bot otrzymał 403), więc nie twierdzimy, który konkretnie warunek bramki spowodował skip ani czy istnieją sekrety konta.

**Źródło:** [.github/workflows/e2e.yml:214–222](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/.github/workflows/e2e.yml#L214-L222).

**Naprawa:** Zweryfikować konfigurację konta E2E i warunków po-deploy; po zielonym kontrolowanym smoke uruchamiać go automatycznie dla każdego wydania.

**Kryterium odbioru:** Kolejny udany deploy ma rzeczywiście wykonany prod-smoke z liczbą testów, SHA i wynikiem, nie skipped.

<a id="scv-02"></a>

### SCV-02 · P2 — Wspólny kraj wystarcza do pełnego dopasowania różnych miast

**Dowód:** potwierdzone syntetycznie w rzeczywistej funkcji scoringu; bez produkcji.

**Warunek:** Job location={locality: Warszawa, country: Polska}, kandydat location={locality: Kraków, country: Polska}; obie strony deklarują onsite.

**Skutek:** Scoring przyznaje pełne 5/5 za lokalizację i opis lokalizacja OK, chociaż miasto nie pasuje. Sam błędny bonus miasta to 2,5 pkt przy domyślnych wagach. Wpływa na wynik/ranking i wyjaśnienie; nie twierdzimy, że omija osobny office-city dealbreaker.

**Uzasadnienie i granice:** location_tokens łączy miasto, regiony i kraj w jeden zbiór; _score_location daje pełną połowę city za dowolny wspólny token. Reprodukcja zwraca points=5.0 i reason="remote onsite OK, lokalizacja OK" dla Warszawy oraz Krakowa. Dodatkowy false-positive check: osobny candidate_office_tokens usuwa Polska/Poland, ale scorer z niego nie korzysta.

**Źródło:** [backend/app/services/scoring_service.py:1371–1376](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/scoring_service.py#L1371-L1376); [backend/app/services/location_utils.py:27–27](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/location_utils.py#L27-L27); [backend/app/services/location_utils.py:53–56](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/location_utils.py#L53-L56).

**Naprawa:** Rozdzielić porównanie kraju/regionu od porównania miasta; wspólny kraj nie może oznaczać city match. Użyć strukturalnej lokalizacji i wspólnej semantyki z bramką biurową.

**Kryterium odbioru:** Warszawa/Polska vs Kraków/Polska otrzymuje 0 za city half przy znanych różnych miastach, Warszawa/Warszawa pełny city half, brak miasta zachowuje politykę unknown.

<a id="scv-04"></a>

### SCV-04 · P2 — Importer MD przyjmuje NaN i Infinity jako poprawne kwoty oraz osobodni

**Dowód:** potwierdzone na syntetycznym XLSX i lokalnej arytmetyce; bez zapisu w bazie.

**Warunek:** Komórka tekstowa MD zawiera NaN, a Faktura zawiera Infinity; nazwisko i nagłówki są prawidłowe. Wiersz kieruje się do zamówienia/puli MD.

**Skutek:** Nieprawidłowy wiersz nie jest oznaczany jako pominięty. Przy rozliczaniu puli porównanie NaN z zerem rzuca decimal.InvalidOperation i może przerwać całą partię zamiast zwrócić błąd danego wiersza. Pozostałe ścieżki dostają niefinitywne dane do zapisu; zachowania rzeczywistej bazy nie testowano.

**Uzasadnienie i granice:** Rzeczywisty parse_md_sheet na XLSX z nagłówkami Konsultant/MD/Faktura zwraca 1 wiersz, skipped_rows=[], md_reported=Decimal(NaN), invoice_amount=Decimal(Infinity). Rzeczywisty quantize_md(NaN) zwraca NaN; następujące w shared_md_orders value < ZERO rzuca InvalidOperation. Oba parsery sprawdzają jedynie możliwość zbudowania Decimal, bez is_finite.

**Źródło:** [backend/app/services/md_import_parser.py:191–200](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/md_import_parser.py#L191-L200); [backend/app/services/md_import_parser.py:212–224](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/md_import_parser.py#L212-L224); [backend/app/services/shared_md_orders.py:186–188](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/shared_md_orders.py#L186-L188); [backend/app/api/md_consumption.py:772–789](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/api/md_consumption.py#L772-L789).

**Naprawa:** Odrzucić wszystkie wartości, dla których Decimal.is_finite() jest False, oraz jawnie walidować zakresy przed utworzeniem rekordu importu. Zwracać czytelny błąd z numerem wiersza.

**Kryterium odbioru:** XLSX z NaN, sNaN, Infinity, -Infinity oraz przekroczeniem skali/zakresu nie doprowadza do wyjątku całej partii; nieprawidłowe wiersze są jawnie raportowane, a poprawne zachowują ustaloną politykę importu.

<a id="sig-03"></a>

### SIG-03 · P2 — Dwa podpisy tej samej osoby są uznawane za podpis obu stron

**Dowód:** REPRO_SYNTETYCZNE.

**Warunek:** PDF zawiera dwa podpisy zatwierdzające tej samej osoby albo drugi podpis ma negatywny wynik.

**Skutek:** UI/audyt/powiadomienie stwierdza podpisanie przez obie strony bez dowodu dwóch właściwych stron.

**Uzasadnienie i granice:** both_parties_signed sprawdza tylko signature_count>=2. Repro: Same Person dwukrotnie, drugi TOTAL_FAILED → both_parties_signed=true.

**Źródło:** [backend/app/services/signing/provider.py:69–85](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/signing/provider.py#L69-L85); [backend/app/services/signing/validation.py:120–136](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/signing/validation.py#L120-L136); [backend/app/services/signing/sender.py:362–368](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/signing/sender.py#L362-L368).

**Naprawa:** Oceniać wszystkie podpisy, unikalne tożsamości i ich oczekiwane role; licznik podpisów oddzielić od kompletu stron.

**Kryterium odbioru:** Dwa podpisy jednej osoby oraz jeden poprawny + jeden błędny nie dają both_parties_signed.

<a id="sig-04"></a>

### SIG-04 · P2 — Wgranie podpisanej umowy offline zawsze trafia w niedozwolony status draft

**Dowód:** KOD_I_REPRO_SYNTETYCZNE.

**Warunek:** SIGNING_ENABLED=true; uprawniony operator przesyła niepusty PDF do upload-signed, a prepare_send przechodzi walidację kontraktu.

**Skutek:** Endpoint zwraca 409 zamiast zapisać podpis; zostaje już zatwierdzony rekord draft i activity.

**Uzasadnienie i granice:** prepare_send zawsze tworzy nowy draft i commituje. Handler bez zmiany statusu wywołuje finalize, który akceptuje tylko sent/in_progress. Repro guarda dla draft daje 409; pełną sekwencję potwierdza kod caller/callee.

**Źródło:** [backend/app/api/signing.py:174–183](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/api/signing.py#L174-L183); [backend/app/services/signing/sender.py:153–183](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/signing/sender.py#L153-L183); [backend/app/services/signing/sender.py:315–321](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/signing/sender.py#L315-L321).

**Naprawa:** Zaprojektować poprawne przejście offline oraz jedną transakcję; ponowienie powinno używać tej samej intencji.

**Kryterium odbioru:** Poprawny upload offline kończy sprawę; odrzucony plik nie pozostawia zbędnych draftów.

<a id="sig-05"></a>

### SIG-05 · P2 — Powiadomienie twierdzi, że kandydat przeszedł na Zatrudniony, choć kod nie zmienia pipeline

**Dowód:** KOD.

**Warunek:** Poprawna finalizacja pliku oznaczonego both_parties_signed=true.

**Skutek:** Rekruter dostaje fałszywy komunikat o wykonanej zmianie etapu; pipeline wymaga osobnej akcji.

**Uzasadnienie i granice:** Komentarz z 17.09 i implementacja usunęły przenoszenie etapu. Tekst powiadomienia nadal mówi kandydat przeszedł na etap Zatrudniony; response i audit nadal zawierają pipeline_stage.

**Źródło:** [backend/app/services/signing/sender.py:362–368](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/signing/sender.py#L362-L368); [backend/app/services/signing/sender.py:409–432](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/signing/sender.py#L409-L432).

**Naprawa:** Dostosować powiadomienie i pola odpowiedzi do rzeczywiście wykonanej operacji; informować o potrzebie ręcznego ruchu.

**Kryterium odbioru:** Powiadomienie nie przypisuje systemowi niewykonanej zmiany; test porównuje komunikat z faktycznym stanem pipeline.

<a id="fe-01"></a>

### FE-01 · P3 — Eksport klientów ukrywa informację o obcięciu pliku przez CORS

**Dowód:** code.

**Warunek:** Eksport CSV/XLSX kategorii mającej co najmniej 10 000 zakresów, frontend i API na różnych originach.

**Skutek:** Plik zawiera tylko limit wierszy, a komunikat o częściowym eksporcie nigdy się nie wyświetla. Operator może potraktować częściowy plik jako kompletny.

**Uzasadnienie i granice:** Frontend uzależnia toast od res.headers.get("X-Export-Truncated"). API ustawia nagłówek przy len(rows)>=limit, ale expose_headers zawiera wyłącznie ETag, Content-Disposition i X-Request-Id. Skrypt przeglądarki nie może odczytać niewystawionego nagłówka CORS. Wielkości portfela na produkcji nie sprawdzano.

**Źródło:** [frontend/src/components/v2/pages/ClientsListV2.tsx:408–436](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/frontend/src/components/v2/pages/ClientsListV2.tsx#L408-L436); [backend/app/main.py:961–964](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/main.py#L961-L964); [backend/app/api/client_directory.py:444–478](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/api/client_directory.py#L444-L478).

**Naprawa:** Wystawić X-Export-Truncated przez CORS i przetestować eksport z małym limitem przy dwóch originach.

**Kryterium odbioru:** Przy limicie mniejszym niż liczba dopasowań plik i widoczny komunikat wskazują częściowy eksport; poniżej limitu brak ostrzeżenia.

## Aneks: wymaga potwierdzenia na rzeczywistym API

### INT-13 — Zapytanie Fireflies ma typ i format fromDate niezgodne z aktualnym kontraktem API

Poza licznikiem 48. **Proponowany priorytet po potwierdzeniu: P2.**

Kod deklaruje $fromDate: String i wysyła YYYY-MM-DD. Aktualna dokumentacja określa argument jako DateTime i pełny ISO 8601 z godziną. GraphQL nie akceptuje zmiennej String w miejscu odrębnego skalara DateTime. [dokumentacja Fireflies](https://docs.fireflies.ai/graphql-api/query/transcripts) . Nie wykonano introspekcji ani zapytania na koncie użytkownika: traktować jako potwierdzoną niezgodność z kontraktem, nie potwierdzoną awarię produkcyjną.

**Do wykonania:** Zapytanie przechodzi walidację schematu dla fromDate=null i daty z czasem; jeden kontrolowany read-only odczyt potwierdza realny kontrakt.

**Źródła:** [backend/app/services/fireflies_sync.py:31–33](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/fireflies_sync.py#L31-L33); [backend/app/services/fireflies_sync.py:68–71](https://github.com/B2B-net-S-A/NEXUS/blob/e4eb0d7beb91d3dfcb74ca2824022e5966107d8a/backend/app/services/fireflies_sync.py#L68-L71).

## Pakiet dowodów i powtórzenie audytu

- [Pełny rejestr maszynowy](../outputs/audit-2026-09-22/findings.json).
- [Reproduktor finansów](../outputs/audit-2026-09-22/analytics_reproduce.py) + [wyniki finansów](../outputs/audit-2026-09-22/analytics_reproduce.json).
- [Reproduktor auth/podpisów/kalendarza](../outputs/audit-2026-09-22/security_reproduce.py) + [wyniki auth/podpisów/kalendarza](../outputs/audit-2026-09-22/security-reproduction-results.json). Numery SEC w surowym wyniku są roboczymi identyfikatorami; mapowanie poniżej.
- [Reproduktor frontend](../outputs/audit-2026-09-22/frontend-repro.cjs) + [wyniki frontend](../outputs/audit-2026-09-22/frontend-repro.json).
- [Reproduktor integracji](../outputs/audit-2026-09-22/repro_integrations.py) + [wyniki integracji](../outputs/audit-2026-09-22/repro_integrations.json).
- [Reproduktor matching/CV/MD](../outputs/audit-2026-09-22/search_cv_reproduce.py) + [wyniki matching/CV/MD](../outputs/audit-2026-09-22/search_cv_reproduce.json).
- [Manifest SHA-256 artefaktów](../outputs/audit-2026-09-22/evidence-manifest.json).

Mapowanie surowych SEC: SEC-01→AUTH-01, SEC-02→AUTH-02, SEC-03→SIG-01, SEC-04→SIG-02, SEC-05→SIG-03, SEC-06→SIG-04, SEC-08→CV-01, SEC-09→AUTH-03, SEC-10→AUTH-04, SEC-11→CAL-01. SIG-05 jest osobnym dowodem kodu.

Uruchomienie wyłącznie na izolowanym checkout audytowanego SHA, bez sekretów i bez połączeń produkcyjnych:

```sh
python3 /Users/arturtwardowski/NEXUS/outputs/audit-2026-09-22/analytics_reproduce.py /private/tmp/nexus-audit-20260922
python3 /Users/arturtwardowski/NEXUS/outputs/audit-2026-09-22/security_reproduce.py /private/tmp/nexus-audit-20260922
python3 /Users/arturtwardowski/NEXUS/outputs/audit-2026-09-22/repro_integrations.py /private/tmp/nexus-audit-20260922
python3 /Users/arturtwardowski/NEXUS/outputs/audit-2026-09-22/search_cv_reproduce.py /private/tmp/nexus-audit-20260922
node /Users/arturtwardowski/NEXUS/outputs/audit-2026-09-22/frontend-repro.cjs /private/tmp/nexus-audit-20260922
```

Frontend harness korzysta z istniejących zależności `/Users/arturtwardowski/NEXUS/frontend/node_modules`; Python używa zainstalowanych bibliotek m.in. SQLAlchemy/Pydantic/FastAPI/openpyxl. Wyników nie należy utożsamiać z pełnym testem PostgreSQL ani z transakcją zewnętrznego dostawcy.

Raport wygenerowano: `2026-09-22T08:40:39.984808+00:00`. Dowody źródłowe prowadzą do niezmiennego audytowanego SHA; późniejszy stan systemu wymaga odrębnego retestu.
