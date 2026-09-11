# 00 — Zasady dla agenta wykonującego kartę UAT

> Przeczytaj CAŁY ten plik przed pierwszym kliknięciem. Karta modułu zakłada, że go znasz.

## 1. Gdzie testujemy

| Co | Adres |
|---|---|
| Aplikacja | `https://nexus.dynaminds.pl` |
| API | `https://api.nexus.dynaminds.pl` |
| Health | `GET /api/health` (przegląd), `GET /api/health/deep` (schemat bazy), `GET /api/health/live` (proces żyje) |
| Panel Coolify (tylko człowiek) | `https://coolify-nexus.dynaminds.pl` |
| Sentry | projekty `nexus-be`, `nexus-fe` (org `b2bnet-sa`) |

**To jest produkcja.** Nie ma stagingu. Wszystko, co zapiszesz, zobaczy zespół.

## 2. Dwa tryby pracy — karta mówi, który obowiązuje

### Tryb R — tylko odczyt (Fala 1, wszystkie karty `moduly/` i `przekrojowe/`)

- Logujesz się kontem admina (sesję zakłada człowiek — SSO Microsoft z 2FA — i przekazuje
  ci zapisany stan przeglądarki albo zalogowaną kartę Chrome).
- Inne role oglądasz przez **„Podgląd jako ten użytkownik”**: Ustawienia → Administracja →
  Użytkownicy → ikona oka przy wierszu osoby (tytuł przycisku: „Podgląd jako ten
  użytkownik”). Po kliknięciu aplikacja przeładowuje się i widzisz sidebar, dashboard
  i dane tej osoby.
- W podglądzie **backend odrzuca każdą mutację** (POST/PUT/PATCH/DELETE → 403 „Podgląd
  jako użytkownik jest tylko do odczytu”). To jest zamierzone. Jeśli w podglądzie
  klikniesz „Zapisz” i dostaniesz 403 z tym komunikatem — **to nie jest błąd**, nie
  zgłaszaj tego.
- Mimo blokady: **nie klikaj przycisków ze stop-listy (§6) nawet w podglądzie.** Część
  akcji ma potwierdzenie natywne (`window.confirm`), które zamraża automatyzację, a
  część wywołuje zewnętrzne usługi zanim dojdzie do backendu.
- Wyjście z podglądu: pasek u góry ekranu ma przycisk powrotu do własnego konta. Jeśli go
  nie widzisz — w konsoli przeglądarki: `localStorage.removeItem('nexus_impersonate_id'); location.reload()`.

### Tryb W — z zapisem (Fala 2, karty `przeplywy/`)

- Zawsze kontem admina, **nigdy w podglądzie** (podgląd blokuje zapis).
- **Tylko jeden agent naraz** w trybie W. Przed startem sprawdź w `wyniki/LOCK`, że nikt
  inny nie ma otwartego przepływu (plik z nazwą przepływu i czasem startu; po zakończeniu usuń).
- Tworzysz WYŁĄCZNIE dane z prefiksem `[QA-E2E-YYYY-MM-DD]` (patrz [02-dane-testowe.md](02-dane-testowe.md)).
  Każdą utworzoną encję zapisujesz w `wyniki/<przepływ>/utworzone.json` (`{endpoint, id, nazwa}`)
  i sprzątasz na końcu.
- Nie edytujesz i nie usuwasz niczego, co nie ma prefiksu. Jeśli scenariusz wymaga
  „istniejącego klienta” — używasz klienta testowego z Fali 0.
- Akcje ze stop-listy (§6) w trybie W wykonuje **człowiek**, na twoje wyraźne wskazanie
  („teraz kliknij X, sprawdzę wynik”). Ty czekasz i weryfikujesz.

## 3. Narzędzia i sesja

Kolejność preferencji:

1. **Osobna sesja przeglądarki na agenta** (Playwright / `agent-browser`) z zapisanym stanem
   logowania. Wzorzec: `frontend/e2e/auth.setup.ts` zapisuje `e2e/.auth/state.json`.
   Wymagane w Fali 1, bo równolegle działa wiele agentów z **różnymi personami**, a
   podgląd jest zapisany w `localStorage` (klucz `nexus_impersonate_id`) — w jednym
   profilu Chrome wszystkie karty mają naraz tę samą personę.
2. **Chrome MCP** (zalogowany Chrome człowieka) — tylko do eksploracji i do Fali 2, jeden
   agent naraz.

Sesja JWT wygasa po ok. 30 min bezczynności lub po zmianie hasła/uprawnień. Objaw:
wszystkie żądania zaczynają zwracać 401, sidebar się rozsypuje. **To nie jest błąd
aplikacji.** Poproś człowieka o ponowne zalogowanie i wznów od ostatniego scenariusza.

Żądania do API z konsoli robisz ZAWSZE z nagłówkiem Bearer (backend nie czyta cookies):

```js
const tok = localStorage.getItem('access_token');
const imp = localStorage.getItem('nexus_impersonate_id');
const h = { Authorization: `Bearer ${tok}`, ...(imp ? { 'X-Impersonate-User-Id': imp } : {}) };
const r = await fetch('https://api.nexus.dynaminds.pl/api/health', { headers: h });
console.log(r.status, await r.json());
```

Zrzuty ekranu rób przy szerokości **1366 px** (najmniejszy laptop w zespole) i raz przy
1920 px. Zrzut jest dowodem — bez zrzutu zgłoszenie UI nie jest kompletne.

## 4. Lista kontrolna na KAŻDYM ekranie

Wykonaj na każdej stronie i każdej zakładce z karty, zanim przejdziesz do scenariuszy:

| # | Sprawdź | Zgłoś jako błąd, gdy |
|---|---|---|
| E1 | Strona ładuje się do końca | biały ekran, „Network Error”, „no available server”, spinner > 15 s |
| E2 | Konsola przeglądarki | jakikolwiek `error` (ostrzeżenia zapisz, nie zgłaszaj) |
| E3 | Żądania sieciowe | jakikolwiek 5xx; 4xx inny niż oczekiwany w karcie; żądanie wiszące > 10 s |
| E4 | Pusta lista / pusty stan | API zwróciło błąd (4xx/5xx), a ekran pokazuje „Brak danych” — **awaria udająca pustkę** |
| E5 | Uprawnienia | link w menu prowadzi do odmowy; odmowa wygląda jak pusta lista; kwota widoczna roli bez finansów |
| E6 | Filtry, sortowanie, paginacja, wyszukiwarka | zmiana nie zmienia wyników; wynik nie przeżywa odświeżenia (F5), gdy stan jest w URL; wyszukiwanie „lodz” nie znajduje „Łódź” |
| E7 | Formularze | komunikat po angielsku lub techniczny (`422 Unprocessable`, `null`, stacktrace); wpisany tekst znika po błędzie |
| E8 | Układ przy 1366 px | ucięta kolumna, przycisk poza ekranem, tekst nachodzący na tekst, poziomy scroll całej strony |
| E9 | Słownictwo | w module `/jobs` słowo „Oferta” zamiast „Rekrutacja” (wyjątki: etap „Oferta wysłana/zaakceptowana”, status „Otwarty na oferty”, mail do kandydata) |
| E10 | Daty i kwoty | format inny niż `DD.MM.RRRR`; kwota bez waluty; `NaN`, `undefined`, `null`, `Invalid Date` |

## 5. Co jest błędem, a co nie

**Nie zgłaszaj:**
- 403 „Podgląd jako użytkownik jest tylko do odczytu” w trybie R.
- 401 po ~30 min — wygasła sesja.
- Pustej listy, gdy API zwróciło `200` i pustą tablicę. Sprawdź to w sieci ZANIM zgłosisz.
- Braku danych u nowego kandydata testowego (brak notatek, brak maili) — to normalne.
- Różnic w nazwach zakładek względem karty, jeśli funkcja jest ta sama. Zapisz prawdziwą nazwę w raporcie.
- `traffit = degraded` w `/api/health` — znany stan, opisany w Fali 0.

**Zgłaszaj zawsze, także gdy „chyba tak ma być”:**
- Dwa ekrany pokazujące różne liczby dla tej samej rzeczy.
- Akcję, która zwraca 200, a nic się nie zmienia po odświeżeniu.
- Link publiczny (CV, karta Championa, podpis), który po odwołaniu nadal działa.
- Kwotę widoczną roli, która wg [03-macierz-rol.md](03-macierz-rol.md) ma widzieć „—”.

**Reguła podwójnego sprawdzenia:** każde P0 i P1 odtwórz drugi raz od zera (nowa karta,
świeże załadowanie) zanim zapiszesz. W sesji QA 27.05.2026 co dziesiąte „zgłoszenie”
było błędem metody (np. żądanie bez Bearer, zgadywany URL zamiast linku z menu).

## 6. STOP-LISTA — akcji, których agent NIE wykonuje w żadnym trybie

Wykonuje je wyłącznie człowiek, na prośbę agenta, gdy karta przepływu tego wymaga.

| Akcja | Dlaczego |
|---|---|
| Wysłanie maila do kandydata lub klienta (odrzucenie z mailem, „Wyślij”, zaproszenie z kalendarza, przypomnienie) | M365 jest podłączone — mail naprawdę wyjdzie do prawdziwej osoby |
| Przekazanie komukolwiek linku publicznego (CV `/cv/…`, `/cv/i/…`, karta Championa `/share/…`, podpis `/sign/…`) | link daje obcym dostęp do danych osobowych |
| „Potwierdź podpis” / `confirm-fully-signed` w Generatorze Umów B2B na prawdziwych danych | uruchamia zatrudnienie, zamówienie, kontrakt — audytowane, jednokierunkowe |
| Wypowiedzenie umowy, „Zakończ zamówienie”, „Zakończ współpracę”, decyzje offboardingowe na prawdziwych danych | zmienia MRR i alerty dla całego zespołu |
| Usunięcie kandydata, klienta, kontraktu, umowy | usunięcie kandydata kasuje CV i notatki; klienta — kaskady w 5 miejscach |
| „Czyszczenie listy” w Nieaktywnych klientach | operacja **jednorazowa** — drugi raz zwraca 409, nie ma cofnięcia |
| „Pobierz zamówienia z maila”, „Przelicz plan”, „Zastosuj”, „Odrzuć” w `/order-mail` | zapisuje prawdziwe zamówienia klientów; odczyt PDF testuj przez „Nowe zamówienie” bez „Zapisz” |
| Zmiany w Ustawieniach: role, uprawnienia sekcji, AI (limity, wyłączenia), reguły CV, szablony pipeline'u, słowniki, konta serwisowe | wpływa natychmiast na wszystkich użytkowników |
| Ręczne uruchomienie synchronizacji Traffita, backfilli, napraw indeksu (`/api/admin/…/sync`, `backfill-*`, `index-cleanup` POST) | godziny pracy w tle, restart przy deployu |
| Odpowiedzi w czacie kandydata / rekrutacji, które trafiają do prawdziwych osób | jw. mail/Teams |
| Zmiana hasła, resetowanie hasła innym, wysłanie linku resetu | wylogowuje prawdziwe osoby |

Jeśli karta scenariusza wymaga kliknięcia czegoś z tej listy, karta mówi to wprost
(„**CZŁOWIEK**: …”). W przeciwnym razie zatrzymaj się i zapisz scenariusz jako „pominięty —
stop-lista”.

## 7. Budżet AI

Generowanie CV, Talent Radar, pełny przegląd bazy, podsumowania AI i czat kandydata
zużywają te same **miesięczne limity** co zespół (Ustawienia → AI). Zanim zaczniesz kartę
z akcjami AI (M02, M05, M04), zapisz stan zużycia (`GET /api/settings/ai`), a po karcie
zapisz go ponownie i podaj różnicę w raporcie. Limity na całe UAT ustala Fala 0
(domyślnie: 10 generacji CV, 3 pełne przeglądy bazy, 5 podsumowań aktywności).

## 8. Priorytety zgłoszeń

| Priorytet | Definicja | Przykłady |
|---|---|---|
| **P0** | bezpieczeństwo lub utrata danych | dane innej roli widoczne bez uprawnień; odwołany link publiczny działa; zapis kasuje cudze dane; kwoty roli bez finansów |
| **P1** | przepływ MUST nie działa lub liczby się nie zgadzają | nie da się przenieść kandydata na etap; kontrakt nie aktywuje się po podpisie; kafel ≠ suma kolumny; awaria udaje pustkę na ekranie z pieniędzmi |
| **P2** | funkcja z karty nie działa, jest obejście | filtr nie filtruje; eksport pada; formularz gubi tekst; przycisk niewidoczny przy 1366 px |
| **P3** | kosmetyka | literówka, „Oferta” zamiast „Rekrutacja”, brak waluty przy kwocie, angielski komunikat |

## 9. Anty-wzorce (z poprzednich sesji QA)

1. **Klikanie zamiast Sentry.** Zanim klikniesz, przejrzyj Sentry dla testowanego SHA
   (karta [przekrojowe/C-sentry.md](przekrojowe/C-sentry.md)). Sentry pokazuje, co pada
   prawdziwym ludziom TERAZ.
2. **Żądanie bez Bearer** → wszystko 401 → fałszywe „RBAC nie działa”.
3. **Zgadywanie URL-a.** Testujesz linki z menu i z ekranów, nie własne domysły
   (`/manager-panel` zwraca 404, bo prawdziwa trasa to `/dashboard/delivery-lead`).
4. **Zgłoszenie bez dowodu.** Każde zgłoszenie ma zrzut albo status HTTP z treścią odpowiedzi.
5. **Sesja > 4 h bez przerwy.** Po 4 h zamknij kartę raportem częściowym; kolejny agent wznawia.
6. **Naprawianie w trakcie testu.** Agent testujący NIE naprawia kodu. Zgłasza. Naprawy są w Fali 3.

## 10. Raport z karty — minimum

Na końcu karty zapisz `wyniki/<ID-karty>/raport.md` według [05-szablon-zgloszenia.md](05-szablon-zgloszenia.md):
SHA, persony, lista scenariuszy ze statusem (PASS / FAIL / SKIP + powód), zgłoszenia
z priorytetami, zużycie AI (jeśli dotyczy), czas trwania, co pominięto i dlaczego.

Repo jest **publiczne**. W raportach nie ma nazwisk, e-maili, numerów telefonów ani
nazw plików CV prawdziwych osób. Kandydatów opisujesz przez ID (`candidate 12345`),
osoby z zespołu przez rolę i ID użytkownika.
