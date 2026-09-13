# M00 — Wejście i powłoka aplikacji

| Pole | Wartość |
|---|---|
| Tryb | **R** (tylko odczyt) — wyjątek: S01–S03 logowanie wykonuje CZŁOWIEK |
| Persony | admin + KAŻDA z pozostałych 8 ról (podgląd) — tu sprawdzamy powłokę oczami wszystkich |
| Zależności | Fala 0 zakończona |
| Czas | ~90 min |
| Głębokość | pełna (bez tego nic innego nie da się testować) |
| Akcje AI | nie |

## Zakres

Trasy: `/login`, `/login/forgot-password`, `/login/reset`, `/login/microsoft/callback`,
`/register`, `/register/verify`, `/onboarding`, `/dashboard`, `/dashboard/recruiter`,
`/dashboard/delivery-lead`, `/dashboard/head-of-recruitment`, `/profile`, `/help`, `/403`,
oraz elementy powłoki obecne na każdej stronie: sidebar, pasek górny, wyszukiwarka
globalna, paleta ⌘K, dzwonek powiadomień, przełącznik motywu, pasek podglądu.

## Przed startem

- `wyniki/F0/persony.md` z ID użytkowników per rola.
- Konto admina z hasłem (do S01). Konto SSO (do S02) — CZŁOWIEK.

## NIE KLIKAJ

„Zmień hasło”, „Wyślij link resetu”, „Zarejestruj” z prawdziwym adresem, żadnej odpowiedzi
w powiadomieniach prowadzącej do czatu (patrz stop-lista).

## Scenariusze

| ID | Persona | Kroki | Oczekiwane | Prio |
|---|---|---|---|---|
| S01 | CZŁOWIEK | `/login`, hasło błędne, potem poprawne | błędne: komunikat PL, pole hasła wyczyszczone, e-mail zostaje; poprawne: przekierowanie na `/dashboard` lub `/onboarding` (jeśli profil nieukończony) | P1 |
| S02 | CZŁOWIEK | `/login` → „Zaloguj przez Microsoft” → 2FA | powrót na `/dashboard`; rola zgodna z grupą AAD; brak pętli przekierowań | P1 |
| S03 | CZŁOWIEK | `/login/forgot-password` z adresem `nikt@example.invalid` | zawsze ten sam komunikat „jeśli konto istnieje, wysłaliśmy…” (anty-enumeracja); brak 404/409 | P0 |
| S04 | admin | wylogowany: wejdź w `/candidates`, `/clients/1`, `/settings/ai` | przekierowanie na `/login` (z `next=`), nie biały ekran, nie 403 | P1 |
| S05 | admin | po zalogowaniu wróć na `/login` | przekierowanie na `/dashboard` (nie pokazuje formularza) | P2 |
| S06 | każda rola | zrzut sidebaru w podglądzie | zgodny z [03-macierz-rol.md §3](../03-macierz-rol.md); sekcje zwinięte/rozwinięte konsekwentnie; badge „Rekrutacje” pokazuje liczbę ≥ 0 | P1 |
| S07 | każda rola | kliknij KAŻDĄ pozycję sidebaru | każda strona ładuje się (E1–E3); żaden link nie prowadzi na `/403` ani na 404 | P1 |
| S08 | admin | ⌘K (Ctrl+K): wpisz „kand”, „rekr”, „klien”, „ustaw” | podpowiedzi nawigacji; Enter przenosi; pozycje zgodne z rolami (w podglądzie REC nie ma „Klienci”) | P2 |
| S09 | admin | ⌘K: wpisz nazwisko kandydata testowego D5, potem e-mail, potem telefon `000 000 001` | znaleziony jako kandydat; klik otwiera profil/quick view | P1 |
| S10 | admin | wyszukiwarka globalna: „Testowa” (bez polskich znaków „Probny” dla „Próbny”) | oba znajdują; brak rozróżnienia wielkości liter | P2 |
| S11 | admin | dzwonek powiadomień: otwórz, przewiń, kliknij jedno powiadomienie z linkiem | lista ładuje się; klik prowadzi na właściwą trasę (`/jobs/{id}`, `/clients/{id}?tab=…`); licznik nieprzeczytanych maleje; **nie klikaj „Odpowiedz”** | P2 |
| S12 | admin | `/dashboard` — każdy kafel/wykres | brak `NaN`/`undefined`; lejek rekrutacji NIE pokazuje stałych 120/78/45/18/9 (regresja z 27.05); kliknięcie kafla prowadzi na listę z odpowiednim filtrem | P1 |
| S13 | recruiter (podgląd) | `/dashboard/recruiter` | KPI osoby (nie całej firmy); „moje rekrutacje” = rekrutacje, w których persona jest w zespole | P1 |
| S14 | delivery_lead (podgląd) | `/dashboard/delivery-lead` („Panel Managera”) | klienci tylko z portfela persony; kwoty widoczne (własny portfel) | P1 |
| S15 | head_of_recruitment (podgląd) | `/dashboard/head-of-recruitment` | agregaty org-wide; BEZ kwot finansowych | P1 |
| S16 | recruiter (podgląd) | ręcznie: `/dashboard/delivery-lead`, `/finance`, `/settings/ai`, `/clients` | `/403` lub czytelna odmowa PL; nie pusta strona | P1 |
| S17 | admin | `/profile` | dane własne; zmiana motywu (jasny/ciemny/soft) działa i przeżywa F5; **nie zmieniaj hasła** | P2 |
| S18 | admin | `/help` | lista procedur ładuje się; „Zamówienia — instrukcja dla Delivery Leada” otwiera się, spis treści działa (klik → scroll do nagłówka); data w treści = data „ostatnia aktualizacja” | P2 |
| S19 | admin | `/help?tab=clients&client={{D1}}` | karta klienta D1 z Fali 0 renderuje się (SLA 5 dni, min 3 kandydatów) | P2 |
| S20 | admin | podgląd → wybierz personę → pasek u góry → „Wróć” | powrót do własnego konta; `localStorage.nexus_impersonate_id` usunięty; sidebar admina | P1 |
| S21 | admin | w podglądzie REC spróbuj `POST /api/notes` (konsola, Bearer + `X-Impersonate-User-Id`) | 403 „Podgląd jako użytkownik jest tylko do odczytu” | P0 |
| S22 | admin | przy 1366 px: sidebar zwinięty/rozwinięty, strona z szeroką tabelą (`/candidates`) | brak poziomego scrolla całej strony; tabela scrolluje wewnątrz; przyciski akcji widoczne | P2 |
| S23 | admin | odśwież (F5) na `/candidates?stage=…&sort=…` i na `/clients/{{D1}}?tab=zamowienia` | filtr i zakładka odtworzone z URL | P2 |
| S24 | admin | `/onboarding` jako admin z ukończonym profilem | przekierowanie na dashboard (nie formularz) | P3 |
| S25 | admin | 404: `/nie-ma-takiej-strony` | strona 404 aplikacji (PL), link „Wróć”; nie biały ekran Next.js | P3 |

## Kontrole API

```js
// w konsoli, zalogowany admin
const tok = localStorage.getItem('access_token');
for (const p of ['/api/auth/me','/api/notifications?limit=5','/api/dashboard/summary']) {
  const r = await fetch('https://api.nexus.dynaminds.pl'+p,{headers:{Authorization:`Bearer ${tok}`}});
  console.log(p, r.status);
}
```
Oczekiwane: 200 × 3. `/api/auth/me` zwraca `role`, `roles`, `data_scope`,
`effective_permissions` — zapisz je dla persony do raportu (karta A ich potrzebuje).

## Znane pułapki

- Overlay onboardingu „Pomiń przewodnik” może pojawić się po pierwszym logowaniu i przykryć
  sidebar — kliknij „Pomiń”, to nie błąd.
- „no available server” (Traefik) = kontener frontu się restartuje (deploy). Poczekaj 60 s,
  sprawdź `/api/health.version`; jeśli SHA się zmienił — zapisz w raporcie.
- Podgląd jest w `localStorage` — inna karta tego samego profilu też jest w podglądzie.

## Do raportu

Zrzuty sidebaru dla każdej z ról (9 plików), tabela `role → pozycje widoczne`, wynik S21.
