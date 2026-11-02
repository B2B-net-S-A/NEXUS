# Licznik użycia obszarów do przeglądu dostępów (0631, 02.11.2026)
<!-- indeks: ACCESS_USAGE_COUNTER_ENABLED domyślnie wyłączony, osoba × obszar × dzień, po ekranie nie po trasie, X-Nexus-Screen, retencja 90 dni, scripts.access_usage_review -->

Program najmniejszych dostępów (Artur 02.11.2026): dużo osób ma dostępy, których
nie używa, ale `activities` zapisuje tylko zapisy i część pobrań, a odczyty ekranów
nie są nigdzie logowane. Bez pomiaru nie da się uczciwie zdecydować, komu odebrać
odczyt. Plan: cztery tygodnie licznika, potem przegląd osoba po osobie.

**Licznik jest domyślnie wyłączony.** To dane o aktywności pracowników, więc
`ACCESS_USAGE_COUNTER_ENABLED` włącza wyłącznie decyzja Artura. Dopóki jest
`false`, front nie wysyła nagłówka, a pętla nie pisze do tabeli.

## Co zbieramy

Tabela `access_usage_daily`, jeden wiersz na osobę × obszar × dzień:
`user_id`, `area`, `day`, `entries`. Bez treści, bez identyfikatorów rekordów,
bez parametrów zapytań i bez godzin. Zawężenie jest w konstrukcji: `area` pochodzi
z zamkniętej mapy, więc wartość z żądania nie ma którędy trafić do tabeli. Test
`test_table_holds_only_the_agreed_columns` zatrzymuje dopisanie kolumny.

Retencja 90 dni (`ACCESS_USAGE_RETENTION_DAYS`). Kasowanie biegnie też przy
wyłączonym liczniku, a usunięcie konta kasuje jego wiersze (`ON DELETE CASCADE`).

## Liczymy ekran, nie trasę API

Pomiar na stagingu 02.11.2026: samo wejście na pulpit odpytuje `/api/jobs`,
`/api/board-tasks`, `/api/kpis/me/today`, `/api/order-mail/queue`,
`/api/finance/order-changes/summary` i `/api/b2b-generator/esign/mine`. Licznik po
trasach zapisałby rekruterowi po zalogowaniu 6 obszarów, a listy „ma dostęp,
0 wejść” by nie było. Dlatego:

- **Front wysyła nazwę ekranu** w nagłówku `X-Nexus-Screen` (`lib/usage-screen.ts`):
  pierwsze dwa człony adresu bez identyfikatorów. Tylko gdy `/api/health` niesie
  `usageCounter: true`, bo starsza wersja API odrzuciłaby nieznany nagłówek w CORS
  i wywróciła każde żądanie (front bywa nowszy od API w trakcie deployu). Sygnał
  jest pamiętany w `localStorage`, inaczej karta otwarta z linku wysłałaby pierwszą
  partię żądań bez nagłówka i wizyta by się nie liczyła.
- **Karta w tle się nie liczy** (`visibilityState`), to odpytywanie, nie praca.
- **Obszar bierze się z ekranu** (`AREA_BY_SCREEN`). Pulpit, profil, własny czas
  pracy i strony publiczne są w `UNTRACKED_SCREENS`. Nowy ekran bez decyzji
  zatrzymuje `test_every_frontend_screen_has_a_decision`.
- **Eksporty liczą się z trasy** (człon `export` albo `export.*`), z każdego ekranu
  i co do sztuki, bo to zawsze osobne kliknięcie. Pliki własne (`/me/`) się nie liczą.
- **Wejście = najwyżej jedno na osobę i obszar na 30 minut** (`ENTRY_GAP_SECONDS`).
  Ekran robi po kilka żądań naraz, więc inaczej liczba mówiłaby o ekranie.
- **Liczą się tylko odpowiedzi 2xx/3xx**: odmowa 403 to nie użycie dostępu.
- **Nie liczymy:** admina w „Podglądzie jako” (ani jego, ani podglądanej osoby),
  tokenów integracji, kluczy API i wtyczki. Stempel osoby stawia
  `get_authenticated_user` (`request.state.access_usage_user_id`).

## Zapis poza ścieżką żądania

`AccessUsageMiddleware` po skończonej odpowiedzi dolicza jedynkę w słowniku procesu,
bez `await`. Pętla `access_usage` co minutę składa to w UPSERT. Błąd licznika
kończy się wpisem w logu, a błąd zapisu zostawia liczby w pamięci do następnej
próby. Restart gubi najwyżej ostatnią minutę. Pętla jest na liście dozwolonych
stagingu i w `EXEMPT` heartbeatu (opóźnienie nikomu nie szkodzi), a tabelę
sprawdza `/api/health/deep`.

## Włączenie

Po decyzji Artura workflow „Coolify set env” ustawia
`ACCESS_USAGE_COUNTER_ENABLED=true`. Zmienna wymaga wdrożenia, więc zaczyna działać
w najbliższym oknie. Potem sprawdź: `curl -s https://api.nexus.dynaminds.pl/api/health`
ma `usageCounter: true`, a po kilku minutach pracy zespołu tabela ma wiersze
(same liczby, nazwiska niepotrzebne):

```sql
SELECT day, area, COUNT(*) AS osoby, SUM(entries) AS wejscia
  FROM access_usage_daily GROUP BY day, area ORDER BY day DESC, area;
```

Nie włączaj flagi w tym samym oknie co scalenie tego kodu i nie cofaj API poniżej
tej wersji przy włączonym liczniku: karta otwarta przed cofnięciem zna sygnał
i dalej wysyłałaby nagłówek, którego starsze API nie przepuszcza w CORS, aż do
przeładowania. Przed cofnięciem najpierw wyłącz flagę.

Pracownicy powinni wiedzieć o pomiarze przed włączeniem. Co i jak im powiedzieć,
decyduje Artur.

## Lista do przeglądu po czterech tygodniach

Skrypt zamiast trasy, bo aktywność osób to dane pracownicze: bez nowego endpointu
czyta je tylko ten, kto ma dostęp do kontenera. Biegnie w transakcji `READ ONLY`,
więc jest bezpieczny na produkcji, ale odczyt danych osobowych wymaga zgody Artura.

```bash
docker exec <kontener-backendu> python -m scripts.access_usage_review --days 28
docker exec <kontener-backendu> python -m scripts.access_usage_review --days 28 --unused-only
```

CSV na stdout, okres i liczba dni z danymi na stderr. Bez danych skrypt kończy się
kodem 3 i nie wypisuje listy, bo każde „0 wejść” byłoby wtedy fałszywe. Wynik
zawiera nazwiska: tylko terminal, nigdy repo ani logi Actions (są publiczne).

Kolumny: `ma_dostep` to `tak`, `nie` albo `bramka na trasie`. Wiersz `nie` z wejściami
to dostęp odebrany w trakcie okresu albo ekran z luźniejszą bramką; warto go obejrzeć.

## Jak czytać liczby

**„Ma dostęp, 0 wejść” to temat do rozmowy, nie automat do odebrania.**

- `dni_z_wejsciem` mówi więcej niż `wejscia`.
- Licznik mierzy ekrany, a nie zależności między nimi: rekruter z zerem w Kandydatach
  może potrzebować sekcji Sourcing, bo panel osoby na Tablicy czyta przez nią dane.
  Przed odebraniem sprawdź macierz bramek (`tests/data/authz_golden/`).
- Sprawdź `dni z danymi` względem okresu: urlop i krótka współpraca też dają zero.
- Jarvis się nie liczy: osoba, która czyta dane tylko przez niego, wyjdzie z zerem.
- Eksporty mają `bramka na trasie`, bo każdy ma własną bramkę, więc nie trafiają na
  listę `--unused-only`. Liczba eksportów na osobę jest za to w pełnej liście.
- Administracja: `tak` tylko dla admina, reszta podstron ustawień ma różne bramki.
- Kadry nie obejmują własnego ekranu `/my-time`, więc osoba z „Płacami” nie wygląda
  na używającą ich dlatego, że wpisała swój czas pracy.
