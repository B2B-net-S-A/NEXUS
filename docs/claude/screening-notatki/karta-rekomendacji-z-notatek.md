# Karta rekomendacji z notatek (0413, 03.10.2026)

Rekruterzy piszą „kartę rekomendacji” jako wolny tekst w notatce (pomiar
03.10.2026: 10 115 notatek rodzaju `card`, ok. 640 miesięcznie, głównie
w Traffit). Od 0413 karta jest danymi: jedna na parę (kandydat, rekrutacja).
Plan całości (kierunek B, makiety https://claude.ai/artifact/HTWhqfgGh4dr6C7u8Gmwyv):
decyzje Artura 03.10.2026 — nic nie znika, porządki w tle, wymagania tylko
miękkie. Ekrany dochodzą w kolejnych etapach.

- **Karta = projekcja notatek + pola wpisane ręcznie** (`recommendation_cards`,
  reguły bez bazy w `services/recommendation_card_rules.py`, zapis w
  `recommendation_cards.py`). `fields_notes` przelicza się OD ZERA z notatek
  pary rodzaju `card` i `screening_facts` (nowsza notatka wygrywa pole po
  polu, każde pole pamięta notatkę i datę); `fields_manual` zawsze wygrywa
  i import go nie dotyka; `note_answers` to pytania i odpowiedzi z notatki.
- **Parser jest czystą regułą, bez AI** (`recommendation_card_parser.py`):
  wartość surowa zostaje zawsze, znormalizowana tylko, gdy da się ją odczytać
  bez zgadywania (kwota miesięczna, dzienna i w innej walucie zostają
  tekstem). E-mail, telefon i LinkedIn są wycinane z każdej wartości.
  Zmieniasz regułę — porównaj starą i nową wersję na produkcji (tylko
  odczyt): dwie poprawki z przeglądu kodu pogorszyły odczyt prawdziwych kart,
  zanim zostały zawężone. Zmiana znaczenia = podbij `PARSER_VERSION`
  (wchodzi do odcisku, więc karty przeliczą się same). v2 (07.10.2026):
  krótka odpowiedź po „? ” w wierszu pytania („tak/nie…”, liczba, mała
  litera; tylko bez wiersza odpowiedzi pod spodem), pytania zawinięte na 2–3
  wiersze (dalszy ciąg małą literą, początek wygląda na pytanie), „Stawka:
  160/115” (pierwsza wyższa, ukośnik) = kandydat 115. Lista numerowana staje
  się pytaniami jak w v1 — tylko z odpowiedzią w osobnym wierszu.
- **Odpowiedzi z notatek trafiają do arkusza screeningu (decyzje Artura
  07.10.2026 — do tej daty reguła brzmiała „nie trafiają”).** Jedyne miejsce
  zapisu: `services/screening_note_sync.py` (strażnik
  `test_screening_note_sync_guard.py`), wyłącznik `SCREENING_NOTE_SYNC_ENABLED`
  (domyślnie OFF). Odpowiedź z notatki ma pochodzenie `note_sync`; taki arkusz
  **od razu widzi klient** (`client_safe_screening` go nie odfiltrowuje)
  i **liczy się w ocenie pary** jak arkusz człowieka — zapis oznacza wyniki
  kandydata jako stare. Arkusz „należy do automatu” wyłącznie, gdy wszystkie
  odpowiedzi to `note_sync` bez trafienia „Odpada, gdy…”, a
  `experience_checks`/`notes`/`internal_note` są puste i `overall_fit ==
  "uncertain"`; każdy inny niepusty arkusz jest ludzki i automat go nie
  dotyka (także kopii na innych wierszach pary). Zapis człowieka (arkusz,
  okno karty, trafienie „Odpada, gdy…”) zamienia `note_sync` na
  `note_import`. Przypięcie do pytań (`map_note_answers`, rapidfuzz): po
  treści ≥ 0,5 z przewagą ≥ 0,1, jeden do jednego, a słowa jednego pytania
  mieszczą się w drugim („AWS” ≠ „Azure”, choć podobieństwo 0,90); po numerze
  tylko odpowiedź bez treści pytania, przy komplecie odpowiedzi i numeracji
  zgodnej z dopasowaniami po treści; szara strefa 0,3–0,5, treść niepasująca
  do żadnego pytania i konflikty pomijane. Odpowiedź idzie przez
  `client_safe_response`: ucięta na pierwszej linii sekcji wewnętrznej karty
  (notatka, red flags, stawka, kosztorys, motywacja, @wzmianka, „czekam na”)
  albo kolejnego pytania, odrzucona przy kwocie/parze stawek i przy „[PL] …”
  (próba na produkcji 07.10: ostatnia odpowiedź karty połykała notatkę
  wewnętrzną i kosztorys w ok. 60 z 8 245 odpowiedzi). Do arkusza trafiają
  WYŁĄCZNIE przypięcia po treści pytania (`WRITE_BY_NUMBER = False`, pomiar
  07.10: przypięcia po numerze — 215 z 8 100 — myliły pytania). Przypięcie po numerze
  odrzuca „odpowiedź”, która zaczyna się od INNEGO pytania (parser nie
  oddzielił pytania od odpowiedzi), a to samo pytanie na początku ucina
  (`_answer_by_number`, powód `question_as_answer`). Rozpoznanie pytań
  (`match_score`): to samo słowo = ten sam rdzeń z polską końcówką, a słowo
  tylko z dłuższego pytania blokuje, gdy nazywa technologię, skrót albo język.
  Arkusz idzie na najnowszy wiersz pary
  (blokada wierszy pary), kopie automatu na starszych wierszach bieżącej próby
  dostają tę samą treść albo `NULL`; notatka sprzed bieżącej próby nie zasila
  arkusza. `answered_at`/`answered_by` = data i autor notatki; zamiast
  `Activity screening_answered` (liczą ją statystyki zespołu) zapis zostawia
  `screening_synced_from_note`. **Etap 1b — notatki innych rodzajów
  (wyłącznik `SCREENING_NOTE_SYNC_OTHER_NOTES_ENABLED`, domyślnie OFF):**
  gdy karta pary NIE ma odpowiedzi z bieżącej próby, źródłem bywa notatka
  czytelna dla AI (`note_kinds.ai_readable_*`, poza `card`/`screening_facts`)
  przypięta do pary — ten sam parser pytań, najnowsza notatka z co najmniej
  jednym przypięciem, wyłącznie po treści z progiem 0,6 (`OTHER_CONTENT_MIN`),
  bez numeru; odpowiedź z pytajnikiem w pierwszym wierszu odpada, kolejny
  wiersz z pytajnikiem ją ucina (`other_note_answer` — wolny tekst nie
  oddziela pytań). Karta ma pierwszeństwo w całości: gdy ma odpowiedzi,
  notatki innych rodzajów nie zmieniają arkusza (bez mieszania dwóch notatek
  w jednym arkuszu — data i autor odpowiedzi są jedne). Wyłączenie zdejmuje
  źródło: arkusz z takiej notatki znika przy najbliższym przeliczeniu pary.
  Zapis notatki w NEXUSIE przelicza arkusz jej pary; notatki z importu
  Traffita dochodzą ponownym uzupełnieniem historii z
  `include_other_notes=true` (raport: `sources` osobno dla kart i notatek;
  zapis wymaga próby w tym samym trybie i włączonego wyłącznika — 409).
  Pomiar 07.10.2026: 16 036 takich notatek, 290 par z pytaniami, do zapisu
  115 par / 354 odpowiedzi (69 par ma odpowiedzi na karcie; próba kodem tej
  gałęzi, 9 odpowiedzi odpadło za pytanie w treści). Przelicza się przy zmianie karty
  (`recommendation_card_import.refresh_candidate`, `repair_orphans`); historię
  uzupełnia admin: `POST /api/admin/screening-note-backfill?dry_run=true` →
  raport → `dry_run=false&expected=<to_change>` (próba z 7 dni; paragon
  `screening_note_backfill_2026_10`, dane do odwrócenia
  `repair_details_screening_note_backfill_2026_10`).
- **Import karty nie pisze do profilu kandydata.** Fakty profilu (stawka,
  dostępność, tryb pracy) dalej wypełnia nocny odczyt notatek i „Zapisz
  w profilu”.
- **Narodowość żyje wyłącznie na karcie** (podpowiedź z poprzedniej karty
  osoby albo `traffit_nationality`). Nie jest wejściem żadnego modelu ani
  dopasowania: `test_recommendation_cards.py` trzyma listę modułów, które
  wolno importować kartę — nowy czytelnik to świadomy wpis.
- **Wybór notatek do przeliczenia jest stanem, nie hakiem:**
  `notes.card_parsed_hash` = odcisk treści, rekrutacji, nagrobka i wersji
  parsera, liczony w SQL-u. Pętla `recommendation_card_import` bierze notatki
  z innym odciskiem (`job_id` dopisany surowym SQL-em po imporcie Traffita
  łapie się sam), przy każdej przelicza WSZYSTKIE karty kandydata (notatka
  mogła zmienić rekrutację albo rodzaj), a raz na godzinę `repair_orphans`
  czyści karty po notatkach skasowanych surowym SQL-em. Stempel nie rusza
  `notes.updated_at`. Zapis, edycja i usunięcie notatki w NEXUSIE przeliczają
  kartę od razu, w savepoincie (nigdy nie cofają notatki).
- **Flaga `RECOMMENDATION_CARD_IMPORT_ENABLED` (domyślnie OFF)** wyłącza
  pętlę i przeliczanie przy zapisie notatki; API i pola ręczne działają bez
  niej. Włączenie przez „Coolify set env”, pierwsze uruchomienie przelicza
  ok. 16 tys. notatek w tle.
- **Ponowne dodanie osoby do rekrutacji:** wartości z datą sprzed początku
  bieżącej próby procesu (`attempt_no > 1`) są podpowiedzią (`previous`),
  kompletność liczy się od nowa. Rozstrzyga data pola — osobnego licznika nie ma.
- **Kompletność liczy JEDNA funkcja** (`recommendation_card_rules.completeness`,
  10 pól wzoru działu); front ma ją tylko pokazywać.
- **Ekrany rekrutacji (03.10.2026):** karta tablicy niesie `card`
  (`status`, `missing`, `answers`; `null` = pary nie ma w kartach)
  i `contact_attempts` — po jednym zapytaniu na tablicę; plakietkę liczy
  `lib/recommendation-card.ts::boardCardBadge` (tylko Screening,
  Zweryfikowany, QC CV). Dok osoby ma sekcję „Karta rekomendacji”
  (`RecommendationCardSection`: „Dopisz” w miejscu, „Otwórz całą kartę”
  z pytaniami Championa i tekstem w starym formacie do skopiowania),
  warsztat screeningu — zakładkę „Karta”. W „Przesuń dalej” na
  „Zweryfikowany” pozycja `recommendation_card` nigdy nie blokuje (akcja
  `open_card`), a odpowiedzi zapisane w notatce spełniają pozycję „Arkusz
  screeningu”. Pytania na karcie: odpowiedź z arkusza wygrywa, bez niej —
  z notatki po numerze pytania (`merge_questions`). Harness
  `/preview/recommendation-card` (`?state=complete|empty|readonly`).
  Test na produkcji 03.10.2026 dołożył trzy rzeczy: „Przesuń dalej” nie zgłasza
  jako braku tego, co stoi na karcie (dostępność = pozycja zaliczona „jest na
  karcie rekomendacji”; stawka kandydata zostaje do potwierdzenia, ale okno
  stawki podpowiada ją z karty — `card.rate_hourly` na karcie tablicy, tylko
  PLN/h odczytane bez zgadywania; od 0414 karta wygrywa, potem „Stawka od”,
  na końcu profil), a listy braków i komunikaty
  nazywają pole „Dlaczego ten kandydat” (`DISPLAY_LABELS`; `LABELS` z „Notatka”
  zostaje dla tekstu w starym formacie).
- **Przegląd Delivery Leada (03.10.2026):** `DlReviewPanel` pokazuje kartę
  z pytaniami Championa (arkusz screeningu zwinięty pod spodem) i ma trzy
  decyzje — wysyłka, „Wróć do poprawy” (z powrotem na „Zweryfikowany”,
  `return_stage_def_id` wiersza kolejki; wymaga uwagi tylko w UI) i odrzucenie.
  „Uwagi dla rekrutera” jadą z ruchem jako `StageMove.recruiter_remark`
  i zapisują się jako notatka pary o pochodzeniu `stage_remark`
  (`services/stage_remarks.py`, jedna na wiersz etapu). Rodzaj `dl_review`
  wynika z POCHODZENIA, nie z treści (`note_kinds.REMARK_SOURCE`, także po
  edycji) — uwaga z kwotą nie staje się wpisem o stawce do klienta, a modele
  jej nie czytają. Uwaga trafia do dzwonka (`_inapp_content(remark=)`) i na
  listę „Twoje CV w drodze” (`remark`); stawka do klienta ma własne pole i do
  uwagi ani dzwonka nie trafia nigdy. Kolejka przeglądu niesie stan karty
  (`card_status`, `card_missing`; `summaries_for_pairs`). Harness
  `/preview/dl-review` (`?as=recruiter`). Na Tablicy przegląd otwiera JEDNA
  funkcja (`openDlReviewIfSending` w `KanbanBoardV2`) dla doku, strzałki na
  karcie, przeciągnięcia i akcji „Wpisz stawkę do klienta” — do 03.10.2026
  strzałka otwierała samo okno stawki i omijała kartę, uwagi i „Wróć do
  poprawy”. Kafel „Dostępność” w przeglądzie bierze wartość z karty, gdy
  profil jej nie zna. Od 08.10.2026 przegląd ma trzy kolumny z wymaganiami,
  CV i marżą, a „Wróć do poprawy…” niesie listę pól do poprawy — sekcja
  „Przegląd Delivery Leada v2”.
- **Profil kandydata (03.10.2026):** Historia ma zakładkę na każdy rodzaj
  notatki — „Rozmowy · Próby kontaktu · Delivery Lead · Maile · Automat”
  (nic nie znika), dalej „Wszystko”, „Telefony” (rejestr połączeń, dawniej
  „Rozmowy”) i „Czat zespołu”. Grupę notatki i liczniki nadaje serwer
  (`note_kinds.group_of`, `NOTE_GROUPS`; `GET /api/notes` → `group` i
  `group_counts` dla całego zakresu, niezależnie od `limit`); front tylko
  mapuje grupę na widok (`lib/candidate-note-groups.ts`, klucze adresu
  `activity=notes|contact|delivery|emails|automat` — `notes` zostaje, niosą go
  powiadomienia). „Maile” = skrzynka M365 i maile zapisane w notatkach.
  Zakładki nie mają `title` (w Chrome przejmował nazwę dostępną). „Nie
  odebrał” to `POST /api/notes` z `kind: "contact_attempt"` — jedyny rodzaj,
  który przyjmuje żądanie (`NoteCreate.kind`; odpowiedź w wątku
  i integracja go nie przyjmują); typ ogólny, więc follow-up nie liczy go
  jako kontaktu. `GET /api/candidates/{id}/recommendation-cards`
  (`recommendation_cards.candidate_overview`, bramka jak
  `…/screening-answers`) daje profilowi: najświeższe ustalenie pola z kart
  (`latest_facts`: stawka, dostępność, tryb pracy, angielski, narodowość —
  z datą, źródłem i rekrutacją), odpowiedzi z notatek dla rekrutacji bez
  arkusza (sekcja „Z kart rekomendacji w notatkach” w karcie odpowiedzi)
  i to, co z której notatki trafiło do karty (link „Karta rekomendacji z tej
  rozmowy”). Pasek faktów pokazuje WARTOŚĆ Z PROFILU (po niej filtruje
  lista), a pod nią linię z rozmowy (`lib/candidate-card-facts.ts`): ta sama
  stawka = samo „rozmowa DD.MM.RRRR”, inna = data i wartość z rozmowy.
  Karta nadal nie pisze do profilu.
- **Lista kandydatów i podgląd (03.10.2026):** kolumna `last_contact` nazywa
  się „Ostatnia rozmowa” — data i autor najnowszej notatki z zakładki
  „Rozmowy” (`note_kinds.talks_clause`), a bez niej „bez rozmowy” i liczba
  prób kontaktu (`GET /api/candidates?include_last_talk=true` → `last_talk_at`,
  `last_talk_by`, `last_talk_preview`, `contact_attempts`; dwa zapytania na
  stronę, lista wysyła flagę zawsze). Domyślnie widoczna tylko od 1536 px
  szerokości okna (`wideDefault`, `CANDIDATE_WIDE_DEFAULT_QUERY`): przy
  1280 px z przypiętym menu domyślna tabela mieści się na styk, więc na
  laptopie kolumnę włącza się w „Kolumny”. Zapisany wybór kolumn nie może
  zależeć od szerokości okna, w którym go zapisano: samo id `last_contact` na
  liście ukrytych = brak decyzji (kolumna idzie za oknem), id + znacznik
  `last_contact:hidden` = wyłączona wszędzie, brak id = włączona wszędzie
  (`candidate-table-columns.ts`). Szybki podgląd pokazuje ostatnią
  ROZMOWĘ (przypięta notatka zostaje bez względu na rodzaj) i liczbę prób
  kontaktu. Filtr „Kontakt z kandydatem” w nowej semantyce liczy tylko
  prawdziwy kontakt (`real_contact_clause`: bez „nie odbiera”, automatu, uwag
  DL i samych wzmianek; mail i ustalony termin się liczą; telefon tylko
  odebrany — lista praktykanta i koordynacja kontaktu zapisują „nie odbiera”
  jako wiersz `calls`, dlatego `contact_attempts` liczy notatki-próby ORAZ
  nieodebrane telefony, `_contact_attempt_counts`) — v1 dla alertów
  zapisanych wyszukiwań bez zmian. `include_last_talk` jest parametrem
  technicznym w czterech lustrach (`saved_search_alerts.py`,
  `saved_search_payload.py`, `saved-search-unified.ts`, `url-filters.ts`).
- **Stawka do klienta z wpisów Delivery Leada (03.10.2026):**
  `services/client_rate_notes.py`, `POST /api/admin/notes-insights/client-rates`
  (admin). Przenosi do `candidate_stages.client_rate_*` wyłącznie wpis
  JEDNOZNACZNY: notatka `dl_rate` z rekrutacją, jedna kwota po czasowniku
  wysyłki („Wyślijmy za 161 zł/h”), 40–400 PLN/h. Po kwocie może stać tylko
  „zł / h / netto / + VAT” i koniec zdania (biała lista — „160 GBP”,
  „160 zł/mc”, „150%”, „161,555” nie przechodzą); przeczenie, warunek, pytanie
  i „albo” odrzucają wpis. Para z drugim wpisem o cenie, którego nie da się
  odczytać („160/130”), albo z dwiema różnymi kwotami odpada w całości. Tylko
  para bez stawki na żadnym wierszu etapu; kwota trafia na pierwszy wiersz od
  „CV wysłane”. `dry_run=true` (domyślnie) nic nie zapisuje; zapis wymaga
  `expected=` równego liczbie z próby (409 przy rozjeździe i przy pustym
  planie), idzie pod blokadą doradczą i DOPISUJE paragon
  (`client_rate_notes_backfill_2026_10`: liczby i id) oraz szczegóły
  (`repair_details_…`: wiersz, notatka, kwota — jedyna droga odwrócenia).
  Notatek nie zmienia. Sam zapis pola robi
  `recruitment_process_commands.fill_missing_client_rate` — strażnik
  `test_priority_work_writer_architecture.py` nie dopuszcza surowego
  `UPDATE` etapów poza adapterem Traffita (pierwsza wersja wypadła przez to
  z kolejki). Pomiar 03.10.2026 (tylko odczyt): 4 676 wpisów
  z rekrutacją, 1 378 par do uzupełnienia, wszystkie w zamkniętych
  rekrutacjach z archiwum; przed zapisem stawkę do klienta miało 17 wierszy.
  Zmieniasz regułę — przelicz plan na produkcji w transakcji tylko do odczytu.
  **Od 07.10.2026 także krótki wpis „X/Y”** (`parse_dl_pair`: ≤ 160 znaków
  po zdjęciu HTML i wzmianek, rodzaj `dl_rate` albo `human` — ten drugi
  TYLKO od autora z rolą Delivery Leada albo admina (`dl_pair_from_note`,
  `DL_PAIR_AUTHOR_SQL`; rekruter pisze „Codility 85/60”, „oczekiwania
  130/120”), X > Y, obie 40–400, jedyna inna liczba to „NNNN MD” = X × 8;
  procent, „score”, waluta, stawka dzienna, pytanie oraz słowa testu
  i widełek (pkt, test, wynik, zadanie, Codility, HackerRank, ocena, widełki,
  zakres, oczekiwania) odpadają): X idzie tym samym planem do stawki do
  klienta, Y — do „Stawki od” (`note:{id}`). Pomiar 06.10.2026: niższa liczba
  zgadza się ze znanym oczekiwaniem kandydata w 94% (834 z 886); „100/110”
  (pierwsza niższa) to widełki kandydata, nie para DL-a.
- **Jarvis czyta kartę narzędziem `get_recommendation_card`** — kształt
  wyniku (`_shape_recommendation_card`) nie przepuszcza narodowości,
  podpowiedzi ani `legacy_text` (pilnuje `test_recommendation_card_ai_privacy.py`).
- **API `GET/PUT /api/recommendation-cards?candidate_id&job_id`:** sekcja
  Pipeline, odczyt jak rekrutacja, zapis jak notatka kandydata + blokada 12 h.
  `PUT` przyjmuje tekst pola (`null` zdejmuje pole ręczne) i normalizuje go tą
  samą regułą co notatkę. Wpis w dzienniku niesie nazwy pól, nigdy wartości.
- **Scalanie kandydatów** ma własną regułę (`merge_manual_fields`): pola
  ręczne obu kart się łączą, zamiast „nowszy wiersz wygrywa”.
- **Modele czytają notatkę-kartę bez pól, które nie są dla nich**
  (`recommendation_card_parser.redact_card_text`): narodowości nie dostaje
  żaden model (nocny odczyt faktów, podsumowanie aktywności, podpowiedzi
  przepięcia i QC CV, wzbogacanie Championa z notatki, narzędzia Jarvisa
  `get_candidate` i `get_candidate_timeline`), a generator CV dodatkowo nie
  dostaje stawki, red flags ani motywacji — to ustalenia handlowe, nie treść
  CV. „Dlaczego ten kandydat” wpisane na karcie w NEXUSIE dochodzi jako blok
  „[Rekomendacja rekrutera]” (tylko z bieżącej próby procesu). Dwa przejścia:
  etykiety ze słownika karty, potem wiersze z polem zapisanym inaczej
  („Nationality:”, „Stawka B2B netto:”, „Red flags – …”, samo „Motywacja”
  z wartością pod spodem). Cięcie jest ostrożne: jeden wiersz wartości albo
  lista punktów pod pustą etykietą, a w akapicie prozy (wiersz > 160 znaków)
  tylko zdanie — cięcie „do następnej etykiety” i „cały akapit” zabierały na
  produkcji fakty o kandydacie. Zmieniasz regułę — sprawdź na produkcji dwie
  liczby naraz: wycieki (wiersze z ukrywanym słowem po cięciu) i notatki,
  z których zostaje mniej niż 30% tekstu. Nowy czytelnik notatek dla modelu =
  `redact_card_text` (pilnuje `test_recommendation_card_ai_privacy.py`).
- **Rodzaj notatki da się podać wprost przy TWORZENIU** (nasłuch w
  `models/note.py` klasyfikuje nową notatkę tylko, gdy `kind` jest pusty) —
  potrzebne dla „Nie odebrał” i uwag Delivery Leada. Edycja treści zawsze
  liczy rodzaj od nowa: bez osobnego znacznika nie da się odróżnić rodzaju
  jawnego od rozjechanego z regułą, a pomyłka odsłoniłaby rekruterowi notatkę
  o stawce do klienta.
