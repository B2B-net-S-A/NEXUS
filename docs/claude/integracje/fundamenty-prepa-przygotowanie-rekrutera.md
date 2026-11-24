# Fundamenty prepa — przygotowanie kandydata przez rekrutera (Ocena prepów → „Przygotowanie”)
<!-- indeks: 18 punktów w 5 grupach, warunki stop (A), „kandydat po przygotowaniu umie”, klucz `preparation` w ustawieniach oceny, startowe w `services/prep_fundamentals.py`, wyjątki klienta w karcie, bez imion DL-i w repo, plan F1–F5 -->

Decyzje Artura z 24.11.2026, na podstawie odpowiedzi sześciu Delivery Leadów
i KAM-ów z 10–17.11.2026. Przed rozmową u klienta rekruter
przechodzi z kandydatem tę samą listę u każdego klienta, a Delivery Lead
na swoim prepie zajmuje się już wymaganiami rekrutacji i brakami.

- **Gdzie:** Ustawienia → Ocena prepów, zakładka „Przygotowanie · rekruter”,
  klucz `preparation` w JSON-ie `prep_review_configs` (bez migracji). Wartość
  startowa to `DEFAULT_PREPARATION` w `backend/app/services/prep_fundamentals.py`:
  obowiązuje, dopóki żadna opublikowana wersja nie ma klucza `preparation`
  (wersja z bazy czyta się na tle startowej). Zmienia Head of Recruitment albo
  admin jak resztę ustawień: nowa wersja z powodem i wpisem w historii
  („Przygotowanie · fundamenty zmienione (N punktów)”). Rekruter i DL czytają.
- **Lista:** 18 punktów w pięciu grupach (A warunki, B klient i rozmowa, C CV
  i przykłady, D sposób rozmowy, E organizacja i po rozmowie), numeracja ciągła.
  Każdy punkt ma „co mówisz albo o co pytasz” i „zaliczone, gdy”. **Warunek
  stop** mają tylko punkty grupy A (forma współpracy, stawka, dostępność
  i stabilność, tryb pracy): nie zgadza się = rekruter kończy rozmowę i od razu
  daje znać DL-owi. Osobno pięć punktów „kandydat po przygotowaniu umie”
  (sprawdzian kandydata, nie tematy rekrutera).
- **Wszystkie 18 punktów są obowiązkowe**, także sześć zgłoszonych przez jedną
  albo dwie osoby (tryb pracy, B2Bnetwork i nasza rola, autoprezentacja, luki
  i motywacja, bez ChatGPT i nagrywania, feedback po rozmowie).
- **Tło w Teams:** „tło B2Bnetwork, a gdy kandydat nie może go ustawić —
  neutralne”. Nikt nie odpada przez tło.
- **Wyjątki od warunków stop stoją w karcie klienta, nie na liście.** Lista
  mówi przy punktach 1 i 3 „wyjątki: karta klienta”. Repo jest publiczne:
  nie wpisuj tu ani w kodzie, u którego klienta i jaki wyjątek obowiązuje,
  zwłaszcza gdy uwaga jest tylko dla zespołu (klient mógłby ją przeczytać).
- **Uwagi DL-i do 30.11.2026** zbiera Artur; poprawki wchodzą jedną nową
  wersją ustawień. Nie zmieniaj listy w kodzie po wdrożeniu: startowa zmiana
  w `prep_fundamentals.py` nie dotknie wersji opublikowanej w bazie.
- **Repo jest publiczne:** przy punktach nie ma imion osób, które je zgłosiły
  (makieta z 17.11 je miała), ani stawek.
- **Ekran przy 1280 × 720:** pasek zakładek stoi nad siatką na pełnej
  szerokości, a zakładka „Przygotowanie” ma jedną kolumnę poniżej `2xl`
  (obok kolumny 320 px zostawało ok. 380 px i pola edycji miały po ok. 150 px).
- **Plan dalej:** F2 „Specyfika na prep” w karcie klienta (osobny PR,
  migracja), F3 przygotowanie jako trzeci prep (`prep_no` 0, opcjonalne na
  start — `przygotowanie-trzeci-prep-rekrutera.md`), F4 ocena
  przygotowania (fundamenty, specyfika klienta, „kandydat umie”; warunek stop →
  dzwonek do DL-a), F5 raport „Jakość prepów”, przewodniki i stemple.
