# Punkt 1 podsumowania: staż w branży klienta i firma z tej branży

Zgłoszenie zespołu rekrutacji z 12.11.2026: w punkcie 1 „Dlaczego nasz
kandydat” generator dodatkowo podkreśla doświadczenie kandydata w branży
klienta (jeśli je ma) i wymienia firmę z tej branży.

- **Kształt:** „[X] lat doświadczenia jako [Stanowisko], w tym [Y] lat
  w sektorze [branża] ([Firma])”. Gdy Y > X (punkt 1 mówi o stażu w roli,
  a bank był wcześniej): „…; [Y] lat w sektorze [branża] ([Firma])”.
  Najwyżej dwie firmy, od najdłuższego stażu. Blind CV: bez nazw firm.
  Kandydat bez stażu w tej branży: punkt 1 jak dotąd, bez wzmianki o braku.
- **Dopisek składa kod, nie model** (`legacy_v7/client_sector.py`). Model
  zwraca tylko pole `client_sector_experience` (branża, stanowiska z tej
  branży, firma z tej branży). Kod liczy Y z dat tych stanowisk, a firmę
  wpisuje tylko, gdy jej nazwa stoi w CV. Prośba o sam kształt punktu 1
  przegrała na stagingu 0 do 4 z regułą neutralności zamrożonego promptu v7;
  z polem 6 z 6 generacji bankowych dostało dopisek, kandydat spoza
  bankowości — nie.
- **Skąd branża klienta:** blok `<client_sector>` w treści użytkownika z nazwą
  klienta i `clients.industry`. Pole na karcie klienta jest puste u 22 z 24
  klientów z rekrutacjami, `jobs.industry` u wszystkich (staging 12.11.2026),
  więc model ustala branżę także z nazwy klienta i Profilu Championa.
- **Tylko tryb „tailored”** (97% CV w 30 dniach) — poniżej niego klient nie
  kształtuje CV. Prompt systemowy v7 zostaje bajt w bajt (cache dostawcy).
- **Wyjątek od neutralności** (22.06.2026): zakaz wymieniania branży docelowej
  w `why_points` nie obejmuje tego dopisku, bo to fakt z kariery kandydata,
  nie dopasowanie do klienta. Nie przenoś tej reguły do promptu systemowego.
- Ścieżka v10 (`CV_GENERATION_PIPELINE=v10`) tej reguły nie ma.
