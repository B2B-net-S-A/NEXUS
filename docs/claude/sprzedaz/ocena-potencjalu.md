# Ocena potencjału firmy przed spotkaniem — decyzje Artura 23.11.2026
<!-- indeks: prompt handlowca, ocena potencjału, zakładka Potencjał na karcie firmy, skrót w Przygotowaniu do spotkania, tryb potential biegu briefing, research firmy (zdarzenia, ogłoszenia IT, stos, PKD), test KSC z PKD i wielkości, F54 sales_potential_assessment, baza wiedzy w app_settings sales_potential_knowledge, Sprzedaż → Leady → Boty → Baza wiedzy, referencje po numerze, import tabeli, ogłoszenia o pracę wyjątkowo dozwolone, pierwsze spotkanie zamiast punktów, 0761 -->

Handlowiec ze Sprzedaży przysłał rozbudowany prompt do „agenta, który weryfikuje
potencjał pod pracę z nowymi klientami” (15 sekcji, baza wiedzy o nas
i referencje). Weryfikacja 23.11.2026: próba 1:1 na firmie z kartoteki dała
1938 słów, z czego handlowiec użyje ok. 600, 20 razy „brak danych”, a kroki
1–3 i 7 dublowały kartę firmy, rejestry, „Kogo znamy” i mapę decydentów.
Raport z makietami: https://claude.ai/artifact/ASEpFNd7QqZBiMpM2KUsmq.
Artur wybrał budowę w trzech warstwach.

## Trzy warstwy

1. **Z NEXUSA, bez modelu:** karta, szanse otwarte i przegrane (24 mies.),
   test KSC (`potential.ksc_test`), a na ekranie panele „Kogo znamy” i mapa
   decydentów, które już są. Czy firma jest klientem, mówi bramka klienta,
   nie lista logotypów: klienta NEXUSA bot nie bada (409 na przycisku).
2. **Research firmy:** bieg `briefing` z firmami w trybie `potential`
   (`bot_tasks/potential.py`), jak haczyk: bez nowego rodzaju biegu i bez
   migracji tabel. Do bota tylko nazwa, domena, NIP i KRS. Raport: PKD,
   zatrudnienie, przychód, grupa (ze źródłem), do 10 zdarzeń z 18 miesięcy
   z linią oferty, do 20 ogłoszeń IT z roku, do 10 faktów o stosie. Pól osób
   raport nie ma. Punkty, haczyki i `no_signal` tych firm odpadają przy zapisie.
3. **Ocena:** model z rejestru F54 `sales_potential_assessment` (Sonnet 5.5,
   zapas Sonnet 5; migracja 0761 to tylko klucz AI) dostaje 1, 2 i bazę wiedzy.
   Powód przegranej idzie tylko ze stałej listy powodów (wolny tekst handlowca
   może mieć nazwiska); tytuł szansy idzie, bo mówi, z czym handlowiec idzie
   na spotkanie. Odsyła werdykt, punkt wejścia i dalsze kroki, mapę 7 linii 0–5, numery
   referencji, pytania w 5 grupach, rzeczy do sprawdzenia, ryzyka i wiadomość
   do 80 słów. `parse_assessment` przepuszcza tylko linie z listy i numery
   referencji z bazy; tekst referencji ekran bierze z bazy, więc model nie
   dopisze zakresu. Hipotezy promptu to sekcja „Do sprawdzenia na spotkaniu”,
   nie etykiety (decyzja „bez oznaczeń bota” z 13.11.2026 zostaje).

## Zapis i stany

- Research i ocena: jeden wiersz `sales_bot_results` (rodzaj `potential`) na
  bieg i firmę. `payload.state`: `pending` → `ready` albo `failed`
  (`no_knowledge`, `no_model`, `model` po 3 próbach). Status wiersza zostaje
  `new`: to podpowiedź, nie wynik do przyjęcia.
- Ocenę zaczyna zadanie w tle zaraz po przyjęciu raportu
  (`integrations_sales_signals.receive_report` → `potential.assess_run`).
  Wiersz `pending` starszy niż 10 minut i przejęcie starsze niż 15 minut bierze
  pętla `sales_signals` (`assess_stale`, 2 na obrót, własna sesja), bo
  wdrożenie ubija zadania w tle.
- **Jedno wywołanie modelu na research:** ocena najpierw przejmuje wiersz
  warunkowym `UPDATE` (`state` → `assessing` z `claim`), a wynik zapisuje tylko
  pod tym samym przejęciem (`payload || {...}`). Bez tego zadanie w tle i pętla
  płaciły za model dwa razy, a późne `failed` nadpisywało `ready`.
- **Raport bota jest wyrozumiały na poziomie elementu:** zdarzenie, ogłoszenie
  albo fakt o stosie, które nie przechodzą walidacji, odpadają same; zła data
  ogłoszenia to brak daty, nieznana linia oferty to brak linii. Pole spoza modelu
  na poziomie firmy dalej daje 422.
- Ocena to dodatek: bez modelu albo bazy wiedzy research zostaje na ekranie,
  a skrót w „Moim dniu” pokazuje wtedy zdarzenia ze źródłami zamiast oceny.

## Kiedy powstaje

- **Przycisk** „Oceń potencjał” / „Odśwież” na karcie firmy:
  `POST /api/sales/companies/{id}/potential` („Sprzedaż: edycja”, 10 na
  godzinę na osobę; ta sama firma nie wcześniej niż 30 minut po ostatnim
  biegu, który nie padł; pusta baza wiedzy, klient NEXUSA i „Nie
  kontaktować” = 409).
- **Przed pierwszym spotkaniem:** w kroku teczek (dzień roboczy od 16:00,
  `tasks/sales_signals.py`, `_first_meetings_to_potential`) firma, z którą to
  pierwsze spotkanie (`modes_for` = `first_call`), idzie do oceny zamiast
  punktów `meeting_prep`, po 5 na bieg. Firma z researchem z 30 dni (także
  z nieudaną oceną) albo z biegiem `potential` z ostatniej doby nie dostaje ani
  nowego biegu, ani punktów. Model bez klucza, pusta baza wiedzy albo bot, który
  nie przyjął zlecenia: punkty jak dotąd. Wymaga obu flag
  (`SALES_SIGNALS_ENABLED` i `SALES_BOT_TASKS_ENABLED`), jak teczka.
- Nowy lead (teczka leada) oceny nie zamawia: osobna decyzja, gdy pierwsze
  oceny się sprawdzą.

## Ogłoszenia o pracę (decyzja Artura 23.11.2026)

Artur na pytanie o ogłoszenia: „wszystko co się da”. W trybie `potential` bot
czyta portale z ogłoszeniami (pracuj.pl, justjoin.it, theprotocol.it,
nofluffjobs) i publiczne oferty pracy na LinkedInie, bez logowania. Profili
i list osób dalej nie zbiera. Reszta botów zostaje przy zakazie portali
i LinkedIna. Polecenie rutyny ma wyjątek w zasadach ogólnych
(`docs/sales-grok-bot-setup.md`); bez wklejenia go do rutyny Grok Bota bot
pomija ogłoszenia.

## Baza wiedzy (decyzja Artura 23.11.2026)

- `app_settings` pod kluczem `sales_potential_knowledge`
  (`services/sales/potential_knowledge.py`), bez migracji: opis oferty
  (do 30 tys. znaków) i do 150 referencji (klient, typ list/realizacja/logo,
  branże, usługi, zakres, od kiedy, data listu, ważny do, podpis, cytat,
  „do przetargów”, notatka) oraz 30 ostatnich zmian (kto, kiedy, co —
  same liczby).
- Edytuje każdy z „Sprzedaż: edycja”, czyta „Sprzedaż: podgląd”
  (`GET/PUT /api/sales/potential-knowledge`). Ekran: Sprzedaż → Leady →
  Boty → Baza wiedzy (`/sales/bots/wiedza`).
- **Treść bazy nie trafia do repo** (repo publiczne): kod nie ma nazw
  klientów, podpisów ani opisu oferty. Wkleja je człowiek; import tabeli
  z dokumentu (`POST …/parse-table`, nagłówki „Klient”, „Sektor/Branża”,
  „Zakres”, „Współpraca od”, „Podpisał”, „Data listu”, „(ważny 12 mies.)”)
  pokazuje podgląd, zapis idzie zwykłym `PUT`.
- Do modelu nie idą podpis listu ani notatka. List bez daty ważności jest
  aktualny przez rok od daty listu; ekran pokazuje nieaktualne listy
  i liczbę aktywnych kontraktów klienta w NEXUSIE (dopasowanie po nazwie jak
  bramka klienta), żeby było widać rozjazd bazy z NEXUSEM.

## Test KSC (NIS2)

`ksc_test(pkd, wielkość…)`: prefiks PKD → załącznik I albo II (najdłuższy
pasujący), dolna granica zatrudnienia z karty albo z researchu. Zał. I od 250
osób = „kluczowy”, od 50 = „ważny”; zał. II od 50 = „ważny”; nieznana wielkość
= „MOŻLIWE”; PKD poza załącznikami = „PRAWDOPODOBNIE NIE” z uwagą o łańcuchu
dostaw. Obrotu i grupy kapitałowej nie liczy, dlatego zawsze „prawdopodobnie”.
Stan prawa (w życiu 03.04.2026, wykaz do 03.10.2026, dostosowanie
do 03.04.2027) jest stałą w kodzie, bot go nie szuka.

## Ekrany

- Karta firmy → zakładka „Potencjał”: werdykt, streszczenie, punkt wejścia
  i dalej, „Z NEXUSA” (szanse, test KSC, „Kogo znamy”), „Co się dzieje
  w firmie” (zdarzenia ze źródłem), ogłoszenia IT i stos, dopasowanie 0–5,
  referencje z bazy, pytania, do sprawdzenia, ryzyka, wiadomość z „Kopiuj”.
  Brak oceny: przycisk; bieg w toku: „Bot zbiera dane, zwykle kilka minut”;
  błąd zapytania to komunikat z ponowieniem, nie pusta zakładka.
- „Mój dzień” → „Przygotowanie do spotkania”: przy gotowej ocenie blok
  „Potencjał” (werdykt, 2 zdania, wejście, 3 pytania, link) zamiast punktów;
  bez oceny 3 zdarzenia z researchu ze źródłami; bez researchu punkty jak dotąd.
- Wyłączona flaga `SALES_BOT_TASKS_ENABLED`: zakładka i blok znikają, baza
  wiedzy działa.

Testy: `backend/tests/test_sales_potential_unit.py`,
`backend/tests/test_sales_potential_api.py`,
`frontend/src/components/sales/__tests__/sales-potential.test.tsx`.
