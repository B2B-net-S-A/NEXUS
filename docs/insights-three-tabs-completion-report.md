# Insights — trzy zakładki w układzie DynaReportera

Data: 2026-09-07. Zlecenie Artura: „zaproponuj nowe mockupy zakładki insights…
powinny być 3 zakładki: Rekrutacja, Delivery Lead i Rada Nadzorcza — tak jak
jest w DynaReporterze", a następnie „okay, implementuj to".

Makiety (canvas, trzy pełne artboardy 1440 px + notatki):
<https://claude.ai/code/artifact/fda9a364-4b03-466c-b395-69881c3b8905>

## Co się zmieniło

| Było | Jest |
|---|---|
| `?tab=rekrutacja` · `?tab=klienci` · `?tab=zarzad` | `?tab=rekrutacja` · `?tab=delivery-lead` · `?tab=rada` |
| „Klienci & Delivery" | **Delivery Lead** — ranking DL, placementy wg klientów, hit ratio per klient, hiring managerowie |
| „Zarząd" | **Rada Nadzorcza** — KPI i finanse firmy + **ranking klientów z MRR** |
| Liga Mistrzów w Zarządzie | **Liga Mistrzów w Rekrutacji**, razem z wyścigami i Hall of Fame |
| Linki aplikacyjne w Zarządzie | **Linki aplikacyjne w Rekrutacji**, w sekcji „Źródła" |
| brak spisu sekcji | **pasek sekcji** z kotwicami w każdej z trzech zakładek |

Podział jest treściowy, nie kosmetyczny: ranking klientów i MRR odpowiadają na
pytanie o pieniądze firmy (Rada), a nie o obsadę (Delivery Lead); gamifikacja
i źródła kandydatów to rozmowa o zespole (Rekrutacja).

## Decyzje, które łatwo cofnąć nieświadomie

- **Stare identyfikatory zakładek ŻYJĄ jako aliasy** (`LEGACY_TAB_ALIASES`):
  `klienci` → `delivery-lead`, `zarzad` → `rada`. Bez nich stary link wpadał
  w gałąź „nieznany tab" i po cichu lądował na Rekrutacji — czyli link do
  kokpitu Rady otwierał co innego bez słowa wyjaśnienia. Takie linki są
  w zakładkach przeglądarki i na stronie `/dynareporter` (ta ostatnia
  zaktualizowana; `clients-mrr` prowadzi teraz do Rady, bo tam mieszka MRR).
- **Rozstrzyganie zakładki to CZYSTA funkcja** `resolveInsightsTab`, nie
  warunek w efekcie. Powód jest wprost z PR #1316: test kończący się na
  argumencie callbacka nie dowodzi, że nawigacja działa — dowodem jest
  round-trip przez warstwę, która naprawdę przenosi stan.
- **Domyślne okno Delivery Leada to ROK**, nie miesiąc. Ranking stoi na
  rekrutacjach ZAMKNIĘTYCH w oknie, a tych w miesiącu jest kilkanaście na cały
  zespół — hit ratio z takiej próbki skacze o dziesiątki punktów i czyta się
  jak awaria. DynaReporter pokazywał tu domyślnie wszystkie dane.
- **Trzy zakładki mają trzy różne domyślne okna** (Rekrutacja: poprzedni
  zamknięty miesiąc, Delivery Lead: rok, Rada: kwartał) i to nie jest dług.
- **Eksport CSV Rady to JEDEN arkusz z dwoma blokami** (`buildRadaCsvExport`),
  bo `PeriodPicker` przyjmuje jeden eksport, a zakładka pokazuje dwie tabele.
  Osobny builder na ranking klientów, którego nikt by nie podał, byłby martwym
  kodem ze 100% pokryciem — dawny `buildClientsCsvExport` osierocony
  przeniesieniem rankingu został scalony, a nie zostawiony „na potem".

## Świadomie POZA zakresem tej zmiany

- **Tabele rok-do-roku 2024/2025/2026** z kolumnami Δ i „Ocena" — sedno układu
  DR w zakładce Rady. `GET /api/insights/board` zwraca KPI okna plus trend
  miesięczny, więc trzyletnia siatka miesiąc × rok wymaga pracy po stronie
  backendu (osobne okna dla trzech lat, YTD w wierszu podsumowania,
  porównanie „te same miesiące", nie „cały rok"). Makieta pokazuje docelowy
  kształt; kod go dziś nie ma i zakładka renderuje KPI + trend + ranking.
- **„Zysk" (marża − pozostałe koszty)** — NEXUS nie zna „pozostałych kosztów";
  wymaga źródła spoza systemu. W DR ta tabela była pusta we wszystkich
  36 miesiącach.
- **Priorytety zespołu wg kategorii kompetencji** (1st/2nd priority) — dane
  istnieją wyłącznie w zamrożonych tabelach `dr_*`, nie w modelu operacyjnym.

## Weryfikacja

- `npm run type-check`, `npm run lint`, `npx vitest run` na testach Insights.
- Test kontraktowy `InsightsAccess.test.ts`: identyfikatory trzech zakładek,
  aliasy starych linków, filtr listy dozwolonych zakładek (D7 zostaje).
- Przegląd wizualny zakładek przez przeglądarkę po deployu.

---

## Uzupełnienie: tabele rok-do-roku w Radzie Nadzorczej (07.09.2026)

Pierwsze wydanie zakładek zostawiło jedną rzecz z makiety poza kodem — sedno
układu DynaReportera dla Rady. Ta zmiana ją domyka.

### Co powstało

`GET /api/insights/board/yoy` (`end_year`, `years` 2–5, domyślnie 3) →
sekcja **„Rok do roku"** między KPI a rankingiem klientów.

Trzynaście metryk w czterech grupach, każda jako tabela dwanaście miesięcy ×
trzy lata z deltami i kolumną „Ocena":

| Grupa | Metryki |
|---|---|
| Finanse | Przychody (MRR) · Koszty konsultantów · Marża · Marża % |
| HR | Liczba konsultantów · Zejścia · Rezygnacje · Placementy |
| Dywersyfikacja | Unikalni klienci · Udział top klienta |
| Operacyjne | Marża na godzinę · Hit ratio |

Plus osobna tabela „Rozbicie placementów na klientów", której suma domyka się
do wiersza „Liczba placementów".

### Podział odpowiedzialności

Backend zwraca **wyłącznie liczby**. Delta, „Ocena" i wiersz podsumowania są
przekształceniem tych liczb i mieszkają w `frontend/src/lib/insights-yoy.ts` —
czyste funkcje, dwadzieścia testów na wartościach. Liczenie ich na serwerze
oznaczałoby, że zmiana sposobu porównania wymaga deployu backendu, a przy
okazji drugą definicję „lepiej" (front i tak musi umieć pokolorować komórkę).

### Decyzje, których nie wolno cofnąć nieświadomie

- **`aggregate` i `lower_is_better` jadą z serwera.** Bez pierwszego widok
  potrzebuje własnej listy „co się sumuje, a co uśrednia" — w DynaReporterze
  jej nie było i wiersz „Suma" pod kolumną procentów pokazywał **874%**. Bez
  drugiego wzrost zejść dostaje zieloną strzałkę w górę.
- **Miesiąc przyszły to `null`; miesiąc bieżący jest oznaczony.** Dwanaście zer
  w kolumnie bieżącego roku czyta się jak awaria systemu, a siedem dni danych —
  jak załamanie wyniku.
- **Podsumowanie niepełnego roku porównuje się z tymi samymi miesiącami roku
  poprzedniego.** Dziewięć miesięcy obok dwunastu pokazywało spadek, którego
  nie ma. Komórka nadal podaje wartość za CAŁY rok; zawężony jest tylko
  mianownik porównania — i wiersz o tym pisze.
- **`+0,0%` to „Bez zmian", nie „Lepiej".** DynaReporter oceniał dwie identyczne
  liczby jako poprawę.
- **Zmiana wskaźnika procentowego liczy się w punktach procentowych.** „Hit
  ratio wzrosło o 50%" przy 20% → 30% jest prawdą arytmetyczną i myli każdego.
- **Udział top klienta nie może przekroczyć 100%** — w DynaReporterze ta kolumna
  pokazywała 114,3% w czerwcu 2026, bo licznik i mianownik pochodziły z różnych
  populacji.

### Jedna implementacja pieniędzy

`fold_money`, `running_on` i `MoneyFold` wyniesione z `app/api/insights_board.py`
do `app/services/insights_board_money.py` w chwili, gdy pojawił się drugi
konsument. Kopia przechodziłaby każdy test wartości do dnia, w którym ktoś
poprawi jedną z nich — wtedy kafel „Marża / mc" i komórka „Marża" w tabeli obok
zaczynają pokazywać dwie różne kwoty pod jedną nazwą, na jednym ekranie.
Broni tego test **tożsamości obiektu funkcji**, nie zachowania.

### Świadomie poza zakresem

- **„Zysk" (marża − pozostałe koszty)** — NEXUS nie zna „pozostałych kosztów".
  W DynaReporterze ta tabela była pusta we wszystkich 36 miesiącach, więc nie ma
  czego odtwarzać; wymaga źródła z Finansów.
- **Eksport CSV siatki** — eksport zakładki jest przycinany oknem z paska,
  a siatka jest latami. Jeden plik pod jedną nazwą oznaczałby dwa różne
  zakresy; `PeriodPicker` przyjmuje jeden eksport.
- **Marża na godzinę dla kontraktów ryczałtowych** — kwota miesięczna nie niesie
  godzin. Takie kontrakty wypadają z licznika I mianownika naraz, a ich liczba
  wraca w `degraded`.

### Koszt

Trzy lata to 36 wycen wszystkich kontraktów żywych danego dnia, każda przez
harmonogramy stawek. Kontrakty ładowane są RAZ na odpowiedź, kursy NBP jednym
zapytaniem na wszystkie dni wyceny, a wynik cache'owany na 15 minut (trzy razy
dłużej niż kafle — siatka opisuje zamknięte miesiące, które się nie zmienią).
Limit `years` ≤ 5 jest sufitem kosztu, nie kaprysem.
