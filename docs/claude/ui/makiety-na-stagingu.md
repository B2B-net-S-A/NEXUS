# Makiety i „jak to teraz wygląda” — ze stagingu na laptopie, nie z wyobraźni
<!-- indeks: „przed” = zrzut ze stagingu 3100, „po” = kod z gałęzi na porcie 3101 na danych stagingu, rysunek tylko jako uzupełnienie -->

Decyzja Artura z 23.10.2026. Gdy Artur prosi o makiety, o „zweryfikuj, jak to
teraz wygląda” albo o pokazanie, jak coś będzie wyglądać, pokazujesz prawdziwy
NEXUS ze stałego stagingu na laptopie (`podstawy/staging-na-laptopie.md`),
a nie rysunek od zera. Bo makieta narysowana obok aplikacji ma inne odstępy,
inne dane i inną gęstość niż ekran, na którym ludzie pracują: Artur akceptował
plansze, które po wdrożeniu wyglądały inaczej, i nie mógł z nich ocenić,
czy coś się zmieści przy 1280 × 720 z prawdziwymi nazwami i liczbami.

## „Jak to teraz wygląda” (stan „przed”)

- Staging: front `http://localhost:3100`, API `http://localhost:8100`
  (`docker ps | grep nexus-staging`). Nie działa → powiedz to i podaj komendę
  z `staging-na-laptopie.md`; nie zastępuj go produkcją ani harnessem `/preview/*`.
- Wbudowana przeglądarka, rozmiar 1280 × 720, logowanie hasłem na koncie
  o roli, której dotyczy pytanie (rekruter, Delivery Lead, finanse…) — ekran
  admina wygląda inaczej niż ekran rekrutera. Hasło podaje Artur w czacie albo
  jest w `.env.staging.local`; nie zgadujesz i nie zmieniasz haseł.
- Zrzut każdego stanu, o który chodzi: pusty, pełny, błąd, otwarte okno, wąski
  ekran. Wybierz prawdziwy rekord, na którym problem widać (długa nazwa, dużo
  kart), i napisz, który to (id, nie nazwisko).
- Co różni staging od produkcji (pętle stoją, poczta w Mailpicie, dane
  z dnia kopii), napisz jednym zdaniem przy zrzucie, gdy ma to znaczenie.

## „Jak to będzie wyglądać” (stan „po”)

Kolejność, od najlepszego:

1. **Kod na gałęzi, front na danych stagingu.** Zmiana UI w worktree, potem
   `cd frontend && NEXT_PUBLIC_API_URL=http://localhost:8100 npm run dev -- -p 3101`
   (CORS stagingu przyjmuje 3101; token jest w `localStorage` per port, więc
   na 3101 logujesz się osobno). Zrzuty „przed” (3100) i „po” (3101) na tym
   samym rekordzie, w tym samym rozmiarze, obok siebie. Gałąź z samą
   makietą może zostać szkicem PR-a (draft) albo zniknąć po decyzji.
   Zmiana wymagająca nowego API: zaślep odpowiedź na froncie wartościami
   wyliczonymi z prawdziwych danych stagingu (zapytanie read-only) i powiedz,
   które pola są zaślepione.
2. **Rysunek na zrzucie ze stagingu.** Gdy wariantów jest kilka albo kod
   byłby duży jak cała funkcja: plansza zbudowana na zrzucie prawdziwego
   ekranu, z prawdziwymi liczbami z bazy stagingu i komponentami z
   `components/ds/` (te same tokeny, czcionki, gęstość). Zaznacz, co jest
   nowe, a co jest dzisiejszym ekranem.
3. **Czysty szkic** (plansza w kanwie Design, artefakt bez zrzutu) tylko na
   wyraźną prośbę o szybki szkic albo dla ekranu, którego jeszcze nie ma;
   wtedy obok zrzut najbliższego istniejącego ekranu ze stagingu jako punkt
   odniesienia.

Wymyślone dane („Jan Kowalski”, „Acme”, okrągłe 100 %) w makiecie ekranu,
który już istnieje, to błąd, nie uproszczenie.

## Dane osobowe na zrzutach

Staging to kopia produkcji z prawdziwymi kandydatami i stawkami
(`sanitize.sql` czyści tokeny i hasła, nie nazwiska). Decyzja Artura
z 23.10.2026: zrzuty idą do **prywatnego artefaktu na claude.ai** na koncie
Artura, „przed” i „po” obok siebie, jak dotychczasowe makiety — bez
zamazywania, bo to wewnętrzny materiał do decyzji. Pliki zrzutów trzymasz
w scratchpadzie sesji. Do repo, PR-ów, logów Actions i publicznych miejsc
nie trafiają (reguła z `staging-na-laptopie.md`); w opisie PR-a słowny opis
zmiany, zrzut tylko z harnessu `/preview/*` z danymi fikcyjnymi.
