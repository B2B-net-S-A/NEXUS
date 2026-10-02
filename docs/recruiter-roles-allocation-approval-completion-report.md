# Role przy rekrutacji, akceptacja propozycji automatu, priorytet — raport (02.10.2026)

Źródło: feedback Olafa (Head of Recruitment) do modułu „Rekrutacje” i decyzje
Artura z 02.10.2026. Makiety: https://claude.ai/artifact/Kt5dniKtgBLdryqMfzc122.
Reguły dla kolejnych zmian: CLAUDE.md, sekcja „Role przy rekrutacji: Delivery
Lead · Rekruter · Kategoria; propozycje automatu akceptuje Head of Recruitment”.

## Decyzje Artura

| Temat | Decyzja |
|---|---|
| Role przy rekrutacji | Delivery Lead (otwiera request), Rekruter (jedna albo kilka osób, które pracują), Kategoria (informacyjnie) |
| Automat przydziału | Tylko proponuje osobę według kategorii i obłożenia |
| Kto zatwierdza propozycje | Head of Recruitment (i admin) na swoim pulpicie: akceptuje, zmienia osobę albo odrzuca |
| Przekazanie do searchu | Delivery Lead wybiera „Zaproponuje automat” albo „Wybieram sam”; bez wyboru działa automat |
| Head of Recruitment | Zmienia rekrutera i priorytet rekrutacji |
| Priorytet | Trzy poziomy: P1 Pilne, P2 Standard, Przyjmujemy kandydatów |
| Podkategorie | Nie teraz |
| Urlopy | Start bez danych o urlopach z Compassa; panel mówi to wprost |

## Co zmieniono

1. **Jedna reguła „kto jest Rekruterem”** (`backend/app/services/job_team.py`,
   lustro `frontend/src/lib/job-team.ts`): prowadzący rekrutacji, aktywne
   przypisanie do requestu albo współpracownik dopisany ręcznie. Propozycja
   automatu nie jest pracą. Tę samą regułę czyta lista rekrutacji, pulpit
   „Requesty i obłożenie”, panel „Zespół”, filtr „Rekruter”, „Bez rekrutera”
   i zakres „Moje”.
2. **Panel „Zespół” rekrutacji** — pięć wierszy: Delivery Lead, Rekruter,
   Kategoria, Termin, Priorytet. Zniknęły nazwy „Właściciel projektu”
   i „Współpracownicy”. Kategoria pokazuje zwiniętą listę osób z kategorii
   z dopiskiem, że nad rekrutacją nie pracują, dopóki ktoś ich nie przydzieli.
3. **Propozycje automatu do akceptacji** — pierwsza sekcja panelu „Czeka na
   Ciebie” na pulpicie Head of Recruitment i admina: request, proponowana
   osoba, powód wyboru (priorytet w kategorii, obłożenie, urlop), przyciski
   „Akceptuj”, „Zmień”, „Odrzuć” i „Akceptuj wszystkie”. Do akceptacji nikt
   nie jest przypisany i nikt nie dostaje powiadomienia. Zaakceptowana albo
   wskazana osoba dostaje dzwonek. Head of Recruitment dostaje jeden dzwonek
   dziennie o czekających propozycjach.
4. **Lista rekrutacji** — kolumna „Rekruter” (osoby, propozycja w przerywanej
   ramce, „Bez rekrutera”, pod spodem Delivery Lead), plakietka priorytetu
   przy tytule, zakres „Moja kategoria”, filtry w kolejności Delivery Lead ·
   Klient · Rekruter · Kategoria · Priorytet · Termin · Data otwarcia.
5. **Pulpit „Requesty i obłożenie”** — te same kolumny i filtry co lista,
   obłożenie liczy osoby w roli „Rekruter” (propozycje osobno: „2 + 1”),
   „Akceptuj” przy propozycji dla Head of Recruitment i admina.
6. **Priorytet** — trzy poziomy w panelu „Zespół” i na `/jobs/new`, filtr na
   liście i pulpicie, sortowanie „Wymaga uwagi” stawia P1 na górze, automat
   proponuje najpierw do P1 i nie proponuje do „Przyjmujemy kandydatów”.
7. **Szyna „Otwarte karty”** — także na liście rekrutacji i u kandydatów.
   Na laptopie (poniżej 1536 px) to wąska zakładka w marginesie strony, żeby
   nie zabierać tabeli szerokości.
8. **Zabezpieczenie flagi automatu** — włączenie `RECRUITMENT_ALLOCATION_ENABLED`
   nie dokłada już bramki przy dodawaniu osób ani ciężkiego zapytania co 30 s
   (szczegóły w CLAUDE.md).
9. **Poprawki po przeglądzie kodu** — ponowne „Przekaż do searchu” innej
   osobie zastępuje rekrutera (wcześniej poprzednia osoba z aktywnym
   przypisaniem zostawała obok nowej); zmiana roli na Finanse zwalnia
   przypisania do requestów i propozycje tej osoby.

Migracja: `0409_request_allocation_proposals` (nowy typ powiadomienia), lustro
w `backend/entrypoint.sh`.

## Odchylenia od planu

- Lista rekrutacji: bez nowych progów szerokości i bez osobnych kolumn
  „Delivery Lead” i „Priorytet”. Tego samego dnia weszły #1967 i #1970 (listy na
  cały ekran, dodatkowe kolumny od 1700 px tabeli), więc priorytet jest
  plakietką przy tytule, a Delivery Lead drugą linią komórki „Rekruter”.
- Szyna na laptopie: plan mówił o pasku 40 px. Pomiar przy 1280 px pokazał, że
  pasek z odstępem zabiera listom 56 px, a lista kandydatów i tak przewija się
  tam w poziomie — stąd zakładka w marginesie.
- Podpis przy osobie po akceptacji to „przydzielił(a) X”, nie „automat,
  zaakceptował X” (akceptacja jest decyzją człowieka i tak jest zapisywana).

## Jak sprawdzono

Wyniki komend i zrzuty: patrz opis PR-a. Testy backendu z bazą biegną w CI
(sito na PR-ze i pełny bieg w kolejce); lokalnie puszczone dodatkowo na
tymczasowym Postgresie bez kontenerów, razem z migracją 0409 w górę i w dół.
Przegląd kodu: bezpieczeństwo, TypeScript i Python — bez blokerów.

## Włączenie automatu (po wdrożeniu)

1. `/api/health` zwraca SHA z maina zawierający tę zmianę.
2. Workflow „Coolify set env”: `RECRUITMENT_ALLOCATION_ENABLED=true`.
   Tryb w bazie to `shadow` (same propozycje).
3. Na starcie panel propozycji jest pusty: wszystkie 20 requestów „Szukamy”
   ma dziś rekrutera. Propozycje pojawią się, gdy Delivery Lead przekaże nowy
   request z „Zaproponuje automat” albo gdy request zostanie bez rekrutera.
4. Wycofanie: ta sama zmienna na `false`.

## Poza zakresem i znane ograniczenia

- Urlopy z Compassa dla automatu: osobny krok, wymaga wspólnego sekretu
  ustawionego w obu aplikacjach.
- Tryb `auto` (automat przydziela sam): decyzja po zmierzeniu, jak często
  Head of Recruitment akceptuje propozycje (`Activity allocation_proposal_decided`).
- Zakres powiadomień rekrutacji nadal obejmuje osoby „z kategorii”
  (`auto_cc`) — świadomie: wiersze `auto_cc` zostają odbiorcami powiadomień.

## Poprawki po wdrożeniu (03.10.2026)

Sześć pozycji z pierwszej wersji tej listy poprawiono osobnym PR-em:

- **Wieczorny „poranny” skrót.** Pierwszy przebieg automatu po deployu
  (20:54) wysłał Delivery Leadom „Requesty do decyzji”. Przegląd wychodzi
  teraz tylko między ustawioną godziną a 17:00 czasu firmy; godzina ustawiona
  przez admina na 17:00 albo później działa bez okna.
- **Zdjęcie rekrutera bez wiersza przypisania** zostawia ślad „zdjęty
  ręcznie” (wiersz `source='owner'`, `released`, `manual`) — automat nie
  proponuje tej osoby ponownie w tym stanie requestu. Tylko request w puli
  i osoba z rolą roboczą.
- **`POST /api/jobs/{id}/owner` na zamkniętej rekrutacji** = 409; zdjęcie
  osoby zostaje dozwolone. Panel „Zespół” chowa „Przypisz…” i „Zmień”.
- **„Moje przypisane” w operacjach rekrutacji** liczy tylko ręcznych
  współpracowników, bez osób „z kategorii”.
- **Tryb `auto`:** poranny skrót pomija request, o którym osoba dostała już
  dzwonek przy akceptacji.
- **Pulpit, „Czeka na Twój przegląd (DL)”:** przy wąskiej kolumnie plakietka
  QC, czas i „Przejrzyj” schodzą pod nazwisko. Pomiar w harnessie przy
  1280×720: nazwiska miały 90 z 147 px i 61 z 133 px, teraz mieszczą się
  w całości (147/147, 133/133); przy 1920 px wiersz zostaje jednoliniowy.

Sprawdzono: 16 plików testów backendu z bazą (325 zaliczonych), testy frontu
pulpitu i panelu „Zespół” (153), `tsc`, `ruff`, stemple przewodników.
