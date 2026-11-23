# Aplikacje z Pracuj.pl trafiają do rekrutacji ogłoszenia (23.11.2026)

<!-- indeks: pracuj_ads, pracuj_ad_applications, numer ogłoszenia ze strefy, „Wskaż ogłoszenie na Pracuj.pl”, „Na Pracuj.pl bez rekrutacji w NEXUSIE”, PUT /api/portal-ads/pracuj, portal „pracuj” w portal-application -->

Zgłoszenie Delivery Leada z 20.11.2026: „nie dodają się ogłoszenia wstawione
na pracuj do rekrutacji w Nexus”. Kopia produkcji z 22.11: 8 292 zdarzeń
źródła „Pracuj.pl” z 30 dni, żadne z rekrutacją; na rekrutacjach zgłaszającego
140 aplikacji i 10 kart. JustJoin.IT i RocketJobs robią to od 06.11
(`aplikacja-z-formularza-justjoin-do-rekrutacji-ogloszenia.md`), Pracuj.pl
nie miał jak, bo strefa pracodawcy zna tylko swój numer ogłoszenia (np.
8819139), a link wklejany przy „Oznacz jako opublikowane” ma inny numer albo
GUID (trzy formaty: `,oferta,1005…`, `showjoboffer/<guid>`, `groupId=<guid>`).
Decyzja Artura z 23.11.2026, wariant A z makiet
https://claude.ai/artifact/Y3LES7QkZNB58thpDKHFZ8.

Kod: `services/pracuj_ads.py`, tabele w `services/pracuj_ad_schema.py`
(migracja 0754), trasy w `api/job_ads.py` i `api/candidate_sources.py`; front
`components/v2/job-ad/PracujAdPairing.tsx` (karta Pracuj.pl okna „Ogłoszenie”)
i `PracujUnpairedAds.tsx` (kolejka „Ogłoszenia do nadrobienia”). Scraper:
`~/pracuj scrapper/pracuj-traffit-scraper/scraper.py` na Macu.

- **Ogłoszenie z rekrutacją łączy człowiek, nigdy tytuł.** 22.11 trzy aktywne
  ogłoszenia miały tytuł „Tester Manualny (k/m/x)” i pasowały do dwóch
  rekrutacji dwóch DL-i. `suggests` tylko podpowiada (bez „(k/m/x)”, numeru
  zlecenia i prefiksu klienta; dłuższy tytuł pasuje tylko z dopiskiem typu
  „x4”). Łączy DL rekrutacji, Head of Recruitment albo admin
  (`publications.can_mark`); rekruter widzi tylko, z którego ogłoszenia
  aplikacje trafiają do „Nowi”.
- **Scraper oddaje listę i każdą aplikację z numerem ogłoszenia.** Na początku
  biegu `PUT /api/portal-ads/pracuj` (opublikowane ogłoszenia: numer, tytuł,
  liczba aplikacji ze strefy), po każdym udanym `from-cv`
  `POST /api/candidates/{id}/portal-application` z `portal: "pracuj"`
  i `ad_id` = numer ze strefy. Obie trasy przyjmują tylko token integracji.
- **Dziennik aplikacji zapisuje się zawsze** (`pracuj_ad_applications`), także
  gdy ogłoszenie nie ma rekrutacji (`no_job`). Z niego połączenie dociąga
  zaległe aplikacje do „Nowi” — tą samą drogą co nowe
  (`portal_application.place_application`: bramki rekrutera, źródło
  z rekrutacją, jeden dzwonek zbiorczy do prowadzącego). Dociąganie nie
  dopisuje do kolejki „Dziękujemy za zgłoszenie” (`enqueue_terms=False`):
  aplikacja jest tam od importu, a wpis starszy niż doba nie łączy się z nowym
  (staging 23.11: 17 z 22 osób dostałoby drugi mail).
- **Ogłoszenie należy do jednej rekrutacji; rekrutacja może mieć kilka
  ogłoszeń** (to samo stanowisko w kilku miastach). Ogłoszenie połączone
  gdzie indziej = 409 `pracuj_ad_taken` z nazwą tamtej rekrutacji.
  „Odłącz” zatrzymuje nowe aplikacje, karty zostają.
- **„Na portalu” = widziane przez ostatni bieg importu z zapasem 3 dni**
  (`LIVE_SLACK`): bieg idzie raz dziennie i stoi, gdy Mac jest wyłączony.
- **„Rekrutacja wewnętrzna”** (np. „IT Rekruter / IT Rekruterka”) zdejmuje
  ogłoszenie z kolejki braków, z potwierdzeniem. Połączonego ogłoszenia nie
  oznaczy (409 `pracuj_ad_taken`) — odłącza tylko DL tej rekrutacji. Ogłoszenie
  wewnętrzne zostaje do wyboru w karcie Pracuj.pl, a połączenie cofa oznaczenie.
- **Dociąganie bierze blokady kandydatów rosnąco przed pętlą**
  (`lock_candidates_stmt`, globalna kolejność z `recruitment_process_commands`),
  a `job_for_ad` czyta z FOR SHARE, więc aplikacja z chwili łączenia czeka na
  jego koniec zamiast dostać `no_job`. Brak daty w TXT = data wpisu w dzienniku.
- **Historia sprzed wdrożenia:** dziennik zaczyna się od pierwszego biegu
  scrapera po wdrożeniu. Starsze aplikacje dociąga jednorazowy bieg
  `nexus_replay` scrapera (od daty z argumentu).
