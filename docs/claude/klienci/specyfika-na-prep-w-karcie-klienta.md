# „Specyfika na prep” w karcie klienta — osiem pól, które rekruter omawia z kandydatem po fundamentach
<!-- indeks: `client_playbooks.prep_spec` (0768), `services/client_prep_spec.py`, osiem pól jako listy punktów, PUT bez klucza nie czyści, zasiew 12 kart krokiem jednorazowym, Tauron 165 h → zlecenie, uwagi tylko dla zespołu poza repo, odczyt w sekcji 6 Championa i w Pomocy -->

Decyzje Artura z 24.11.2026 (F2 planu „Fundamenty prepa i specyfika klientów”,
fundamenty: `integracje/fundamenty-prepa-przygotowanie-rekrutera.md`).

- **Pole karty, nie osobna tabela:** `client_playbooks.prep_spec` (JSONB, 0768,
  lustro w `entrypoint.sh`). Osiem stałych pól (`PREP_SPEC_FIELDS`): tryb pracy
  i biuro, język rozmowy, przebieg rozmowy, na co zwracają uwagę, typ pytań,
  za co klient odrzuca, co wyróżnia klienta, forma współpracy. Każde to lista
  punktów (najwyżej 12, punkt do 300 znaków). `NULL` = nikt nie wpisał.
- **Pytań klienta tu nie ma** — są w banku pytań z rozmów (od kilku do ponad
  tysiąca na klienta). DL-e ich nie przepisują.
- **Wyjątki od fundamentów** (inna forma współpracy, równoległy projekt) idą
  do „Forma współpracy” albo, gdy kandydat ma ich nie usłyszeć, do zasad
  procesu w karcie. Uwagi tylko dla zespołu wpisuje DL w karcie, nigdy w kodzie
  ani w zasiewie: repo jest publiczne, a klient mógłby je przeczytać.
- **Zapis jak reszta karty** (DL i admin, „Klienci: dodawanie i edycja”,
  wersja i historia z diffem), z jednym wyjątkiem od pełnej podmiany: **PUT bez
  klucza `prep_spec` zostawia zapisaną specyfikę**, jawne `null` ją usuwa.
  Front sprzed 0768 (otwarta karta przeglądarki) wysłałby kartę bez pola
  i wyczyściłby zasiew. Historia w formularzu pokazuje nazwy zmienionych pól,
  nie JSON.
- **Odczyt:** pełna karta (profil klienta, Pomoc → Klienci) ma blok z ośmioma
  polami, a puste mówią „Brak — zapytaj DL-a przed prepem”. Sekcja 6 Championa
  na rekrutacji (wariant compact) ma pole w linii i jedno zdanie z brakami.
  Karta bez specyfiki nie pokazuje bloku.
- **Zasiew 12 kart** (klienci z prepami w 60 dniach do 24.11.2026) to krok
  jednorazowy `client_prep_spec_seed_2026_11_24` w `entrypoint.sh`
  (`services/client_prep_spec_seed.py`, treść w `client_prep_spec_data.py`, id
  klientów z produkcji). Wpisuje specyfikę tylko tam, gdzie jej nie ma, i zostawia
  wpis w historii karty („NEXUS (specyfika na prep z odpowiedzi DL-i)”).
- **Tauron (decyzja 24.11):** godziny według zlecenia rekrutacyjnego. Umowa
  ramowa z 16.06.2026 nie ma limitu 165 h, a „przewidywaną ilość godzin” podaje
  każde zlecenie. Biura: Warszawa, Katowice, Wrocław. Zasiew poprawia też
  „Co powiedzieć kandydatowi” w karcie, ale tylko gdy zdania stoją jak w kopii
  z 24.11. Karta zmieniona wcześniej przez człowieka zostaje.
- **Nordea (decyzja 24.11):** wartości z karty (Collaboration, Ownership,
  Passion, Courage) w „Co wyróżnia klienta”, a to, co DL widzi na rozmowach
  („dobrze wypada: proaktywność…”), osobno w „Na co zwracają uwagę”.
- **Dalej:** F3 (przygotowanie jako trzeci prep) i F4 (ocena przygotowania
  sprawdza też specyfikę klienta). Uwagi DL-i do specyfiki do 30.11.2026 — DL
  poprawia je sam w karcie.
