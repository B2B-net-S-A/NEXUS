# Kwarantanna tożsamości: co znika z profilu

Gdy plik zostaje uznany za CV innej osoby, `_clear_cv_projection` usuwa z profilu
fakty z tego pliku. Decyzje z 05.11.2026, po ręcznej naprawie dwóch profili:

- Porównujesz kolumnę z tym, co naprawdę zapisał `_apply_cv_enrichment`, nie
  z surowym odczytem. Umiejętności idą przez `normalize_llm_skills`, LinkedIn przez
  `normalize_linkedin_url`, e-mail małymi literami. Wykształcenie, lata i telefon
  zapisują się bez zmian (sama przycięta spacja), więc tam wystarcza równość.
- Umiejętności dopisane z notatek zostają. Notatki dopisują na końcu listy, więc
  zgodny początek to odczyt CV. Inna kolejność nie jest dowodem pochodzenia, bo
  `FILL_EMPTY` nie nadpisuje kolumny.
- Blokady są wiążące: `skills_manually_curated` i każda `_manual_override_<pole>`.
- Decyzja człowieka (`mark_confirmed_mismatch`) sprawdza też, czy tekst CV w profilu
  jest tekstem tego pliku, i wtedy czyści fakty, choć plik nie jest główny, a odczyt
  nie ma `source_document_id`. Automat tego nie robi, bo decyzja parsera bywa
  fałszywym alarmem.

## Wskaźnik `cv_storage_key` po kwarantannie pliku

Kwarantanna nie zdejmuje `cv_storage_key`. Pomiar 05.11.2026 na 243 aktywnych
kwarantannach plików: klucz nie jest kluczem dokumentu w żadnej, 66 wskaźników
trzyma te same bajty pod własnym kluczem, a 177 to inny plik, często własne CV
osoby. Zdjęcie wskaźnika odebrałoby tym 177 osobom plik, a zwolnienie
z kwarantanny nie miałoby czego przywrócić.

Kto czyta bajty ze wskaźnika, sprawdza je przez `cv_bytes_quarantined`, po skrócie,
nie po kluczu: `get_current_cv`, `cv_text_backfill`, `cv_backfill`. 54 z tych 66
dokumentów nie ma `content_sha256`, więc funkcja liczy go z pliku. Nieczytelny plik
liczy się jako kopia, bo cudzy tekst w profilu jest gorszy niż brak tekstu.

`cv_text_backfill` zapisuje wtedy końcowy znacznik `quarantined`, żeby nie pobierać
pliku co bieg. `override_identity_quarantine` zdejmuje ten znacznik, więc po
zwolnieniu tekst wraca przy następnym biegu, bez naprawy danych.

## Drugi dokument z bajtami pliku z kwarantanny

Decyzja dotyczy jednego wiersza, a `current_cv_filters` patrzy na id. Pomiar 05.11.2026:
17 żywych dokumentów w 16 profilach ma bajty pliku z kwarantanny. W SQL ich nie
znajdziesz, bo `ux_candidate_documents_candidate_sha` nie pozwala na dwa takie same
skróty w profilu, więc para nigdy nie ma obu.

Kto wybiera plik jednej osoby, bierze `current_cv_filters_for`, a kto oznacza pliki na
liście, `quarantined_copy_document_ids`. Tak robią `get_current_cv`, domyślny plik
generatora, QC, „Zmień plik” w CV oryginalnym i lista plików w karcie. Ponowny odczyt
głównego CV pomija taką kopię, zanim plik pójdzie do modelu. Bez tego odczyt z imieniem
`?` przeszedłby bramkę jako `inconclusive` i wpisał cudze dane do profilu.

Odpowiedź liczymy przy odczycie, nie zapisujemy jej przy kopii:

- decyzja parsera bywa fałszywym alarmem, więc kopia nie dostaje własnej decyzji. Zwolnienie
  oryginału (`override_identity_quarantine`) od razu oddaje wszystkie kopie, bez naprawy
  danych i nowego kroku. To też jedyna droga powrotu, gdy kopia była jedynym plikiem osoby;
- wiersz z własnym werdyktem (zwolniony albo `confirmed_match`) nie jest kopią, bo to dowód
  o nim samym;
- nieczytelny plik nie jest kopią. Przy wskaźniku jest odwrotnie, bo tam odpowiedź dotyczy
  jednej kopii, a tu jeden brakujący plik w magazynie ukryłby wszystkie pliki osoby.

Profil bez kwarantanny płaci jedno zapytanie i nie pobiera plików. Narzędzia naprawcze
w `app/cli` zostają przy `current_cv_filters`: nie wysyłają pliku dalej, a sam wybór
i tak przechodzi przez powyższe.
