# 03 — Macierz ról: co każda rola ma widzieć

> Źródła prawdy w kodzie: `frontend/src/components/v2/shell/SidebarV2.tsx` (menu),
> `frontend/src/middleware.ts` (trasy), `backend/app/api/deps.py` + `section_access.py`
> (sekcje), `CLAUDE.md` (decyzje produktowe). Uprawnienia sekcji da się nadpisać per rola
> i per użytkownik w Ustawieniach → Administracja → Uprawnienia — **przed testem zapisz
> aktualną konfigurację** (`GET /api/admin/section-permissions`), bo macierz niżej opisuje
> stan domyślny.

## 1. Role

| Rola | Kim jest | Skrót |
|---|---|---|
| `admin` | zarządza systemem; jedyny z prawem podglądu innych | ADM |
| `head_of_recruitment` | nadzór nad rekrutacją, org-wide, BEZ finansów | HoR |
| `delivery_lead` | prowadzi klientów ze swojego portfela; finanse TYLKO swojego portfela | DL |
| `talent_community_manager` | Talent Community; globalny odczyt delivery bez finansów i bez mutacji | TCM |
| `finance` | pełny odczyt biznesowy (decyzje 19.08 i 31.08); zapis finansowy przez capability | FIN |
| `tac` | Talent Acquisition Consultant; w zespole klienta, ale nie prowadzi obsady | TAC |
| `recruiter` | rekruter (domyślna rola nowych kont) | REC |
| `sourcer` | sourcing + ogłoszenia | SRC |
| `user` | legacy viewer, wycofywany; brak nowych kont | USR |

## 2. Sekcje produktu → domyślny dostęp

| Sekcja | ADM | HoR | DL | TCM | FIN | TAC | REC | SRC | USR |
|---|---|---|---|---|---|---|---|---|---|
| sourcing (Kandydaci, CV, Talenty, Targ, Zgłoszenia) | W | W | W | W | R | W | W | W | R |
| pipeline (Rekrutacje, Kalendarz) | W | W | W | R | R | W | W | W | — |
| delivery (Klienci, Kontrakty, Zamówienia, Panel klientów) | W | R* | W (portfel) | R | R | W (zespół) | — | — | — |
| insights (Insights, Cortex) | W | R | R | R | R | R | R | R | R |
| finance (`/finance`) | W | — | — | — | W | — | — | — | — |
| system_admin (Ustawienia → Administracja) | W | — | — | — | — | — | — | — | — |

`W` = odczyt i zapis, `R` = tylko odczyt, `—` = brak (link ukryty, trasa → odmowa).
`R*` HoR przechodzi guardy klienta globalnie, ale bez finansów. Jeśli konfiguracja
na prodzie różni się od tej tabeli — **to konfiguracja jest źródłem prawdy**; zapisz
różnicę w raporcie F0 i testuj według niej.

## 3. Pozycje menu → role (z `SidebarV2.tsx`)

| Pozycja | Trasa | Widzi |
|---|---|---|
| Dashboard | `/dashboard` | wszyscy |
| Kandydaci | `/candidates` | wszyscy poza USR |
| Do przedzwonienia | `/candidates/contact-queue` | TCM, TAC, REC, SRC |
| Generator CV | `/cv-generator` | role sekcji sourcing (bez USR) |
| Generator Umów B2B | `/contracts/b2b-generator` | KAŻDA rola (decyzja 20.08); DL tylko z przypisanym klientem |
| Talenty | `/talents` | wszyscy poza USR |
| Talent Radar | `/talent-radar` | KAŻDA zalogowana rola (decyzja 19.08) |
| Targ / Dostępni | `/sourcing/marketplace` | wszyscy poza USR |
| Zgłoszenia | `/applications` | wszyscy poza USR |
| Rekrutacje | `/jobs` | role sekcji pipeline |
| Kalendarz | `/calendar` | role sekcji pipeline |
| Klienci | `/clients` | role sekcji delivery |
| Panel klientów | `/my-clients` | role sekcji delivery |
| Zamówienia z maila | `/order-mail` | role sekcji delivery (ADM/FIN/DL mogą „Pobierz”; TCM tylko odczyt) |
| Moje relacje | `/my-relationships` | role sekcji delivery |
| Kontrakty | `/contracts` | role sekcji delivery |
| Panel Managera | `/dashboard/delivery-lead` | ADM, DL, HoR |
| Insights | `/insights` | KAŻDA zalogowana rola (D7) |
| Cortex | `/cortex` | role sekcji insights bez USR |
| DynaReporter: Rekrutacja / Delivery Lead | `/dynareporter/…` | role sekcji insights |
| DynaReporter: Rada Nadzorcza | `/dynareporter/board-dashboard` | ADM, DL, HoR |
| DynaReporter: Admin DR | `/dynareporter/admin-dashboard` | ADM |
| Finanse | `/finance` | ADM, FIN |
| Pomoc | `/help` | wszyscy |
| Ustawienia | `/settings` | wszyscy (zakładki różne per rola) |

## 4. Kwoty — kto widzi pieniądze

| Powierzchnia | Widzi kwoty | Widzi „—” |
|---|---|---|
| Profil klienta → Konsultanci / Archiwum (stawki, marża, MRR) | ADM, FIN, **DL tylko swojego klienta** | HoR, TAC, TCM, DL obcego klienta |
| Profil klienta → Analityka (przychód, marża/mc) | ADM, FIN, DL swojego | reszta (kafle finansowe w ogóle się nie renderują) |
| Lista `/my-clients` (przychody) | ADM, FIN, DL (swoje) | — |
| Zamówienia → stawki linii MD | ADM, DL przypisany | reszta (pasek MD widoczny, stawka „—”) |
| Kontrakty → stawki | role z `view_finance` (ADM, FIN) | reszta |
| Talent Radar / wyniki wyszukiwania | nikt (radar nie niesie stawek ani kontaktu) | wszyscy |
| Insights → Rada Nadzorcza → KPI i finanse | KAŻDA rola (D7) — dane zagregowane | — |

Reguła kontrolna: **redakcja jest całościowa albo żadna** na jednym ekranie. Jeśli rola
widzi kafel „Aktywne MRR” z liczbą, a kolumnę „Marża” jako „—” (albo odwrotnie) — P1.

## 5. Zapisy zakazane mimo odczytu

| Rola | Może czytać | Nie może zapisać (oczekiwane 403 lub brak przycisku) |
|---|---|---|
| FIN | wszystko biznesowe | użytkownicy/role/konfiguracja; kuratela Cortexa; sekcja `admin` DynaReportera; ruch kandydatów (zostaje prawo sprzed 31.08) |
| HoR | klienci, kontrakty, zamówienia | stawki linii MD; zmiany w Ustawieniach → Administracja |
| TCM | delivery globalnie | jakakolwiek mutacja delivery; `confirm-fully-signed` (wyjątek: TCM ma zmianę statusu kontraktu i potwierdzenie podpisu wg decyzji 10.09 — sprawdź w karcie M08) |
| DL | swój portfel | klienci spoza portfela (403 z nazwą powodu, nie pusta lista) |
| REC/SRC | kandydaci, rekrutacje | kontrakty, klienci, zamówienia (link ukryty; trasa `/clients` → odmowa) |
| każdy w podglądzie admina | wszystko, co widzi persona | **nic** — każda mutacja 403 |

## 6. Jak testować macierz (dla karty A)

Dla każdej roli z §1, w podglądzie:

1. Zrób zrzut sidebaru. Porównaj z §3: pozycja widoczna ↔ rola na liście. Odstępstwo = P2
   (link ukryty, a rola ma prawo) albo P0 (link widoczny i strona działa, a rola NIE ma prawa).
2. Wejdź w każdą widoczną pozycję. Strona musi się załadować (E1–E3). Odmowa na widocznym linku = P1.
3. Wejdź RĘCZNIE w 3 trasy, których rola nie powinna widzieć (np. REC → `/clients`,
   `/finance`, `/settings/ai`). Oczekiwane: przekierowanie na `/403` albo czytelna odmowa
   po polsku. Pusta lista lub biały ekran = P1. Załadowane dane = P0.
4. Sprawdź kwoty według §4 na: profilu klienta testowego D1 (DL przypisany) i D2 (DL nieprzypisany),
   `/contracts`, `/my-clients`.
5. Wykonaj jedną mutację przez API w podglądzie (np. `POST /api/notes` z treścią
   `[QA-E2E] test`) — oczekiwane 403 „Podgląd jako użytkownik jest tylko do odczytu”.
   Cokolwiek innego = P0.
