# Pracuj.pl mailem do opiekuna konta (27.10.2026)

<!-- indeks: „Wyślij do Pracuj.pl”, job_ad.pracuj_mail, opiekun w stałych częściach, stan requested, ?wyslij=opiekun -->

Pracuj.pl nie ma u nas API: ogłoszenie wstawia opiekun konta po mailu.
Delivery Leadzi pisali te maile ręcznie, z rozjazdami (w jednym mailu stawka
170–190 zł/h w nagłówku i 190 zł/h w „co oferujemy”). Kierunek z 21.10
(`ogloszenie-jedna-tresc-strona-kariery.md`), decyzje Artura 27.10.2026
(makiety https://claude.ai/artifact/6cgqm3LhTM7t8MzMXazmEe).

Kod: `services/job_ad/pracuj_mail.py`, trasy
`POST /api/jobs/{id}/portal-ad/pracuj-mail/preview` i `POST …/pracuj-mail`
(`api/job_ads.py`), opiekun w `fixed_blocks.PracujCaretaker`; front
`components/v2/job-ad/PracujMailDialog.tsx`, karta w `AdPublications`.

- **Treść maila to zakładka Pracuj.pl po kontroli.** `compose` bierze pola
  `render.pracuj_view` i fakty rekrutacji (tryb, miasto, współpraca, język,
  start, długość) — ten sam materiał, który okno kopiuje. Skład jest po
  stronie serwera; okno pokazuje `body_text` z podglądu i to samo kopiuje
  „Kopiuj treść maila”. Znalezisko blokujące = 409 `job_ad_blocked`, jak przy
  kopiowaniu i stronie kariery. Nie dokładaj do maila pól, których kontrola
  nie czyta.
- **Stawkę wpisuje DL przy wysyłce** (decyzja 27.10). W treści ogłoszenia
  kwot nadal nie ma (25.09); mail niesie stawkę raz, w nagłówku, jako
  „110–125 zł/h netto (B2B)”. Nigdy nie podpowiadaj jej z budżetu rekrutacji
  ani z Championa — to stawka klienta. Odwrócona, zerowa albo ponad
  trzykrotna rozpiętość = 422. Stawki nie zapisujemy w Historii zdarzeń.
- **Mail wychodzi ze skrzynki M365 wysyłającego** (`m365/sender.send_new`,
  klucz żądania z okna = ponowienie nie wysyła drugi raz). Bez aktywnej
  skrzynki 412 `mailbox_missing`: okno prosi o podłączenie i daje „Kopiuj
  treść maila”. Nie wysyłamy z adresu aplikacji (decyzja 27.10) — odpowiedź
  opiekuna ma trafić do DL-a.
- **Wysyła DL rekrutacji, Head of Recruitment albo admin**
  (`reminders.can_manage`, otwarta rekrutacja). Rekruter widzi tylko stan.
- **Opiekun** (imię do powitania i adres) jest w Ustawienia → Rekrutacja →
  „Stałe części ogłoszenia”, `app_settings['job_ad_fixed_blocks']
  .pracuj_caretaker`. Bez wpisu: `ogloszenia@pracuj.pl` i „Dzień dobry,”.
  Zapis bez tego pola (okno sprzed 27.10) zostawia zapisanego opiekuna.
- **Ślad = wiersz Historii zdarzeń** `job_ad_pracuj_requested` (`to`,
  `email_id`), bez nowej tabeli. Z niego `pracuj_request` w odpowiedzi okna
  i stan kanału `requested` w przypomnieniach: przez dzień wysyłki
  i `QUIET_BUSINESS_DAYS` (3) dni robocze kalendarza firmy Pracuj.pl nie jest
  brakiem, potem wraca. Ogłoszenie oznaczone jako wiszące = 409 `pracuj_live`.
- **Link wkleja DL** („Oznacz jako opublikowane”) — NEXUS nie czyta
  odpowiedzi opiekuna ze skrzynki (decyzja 27.10).
- **Wejścia:** karta Pracuj.pl w oknie „Ogłoszenie”; przycisk „Wyślij do
  Pracuj.pl” w codziennym mailu o brakach (`?ogloszenie=pracuj&wyslij=opiekun`
  otwiera od razu okno maila); komunikat po utworzeniu rekrutacji
  w `/jobs/new`. W samym `/jobs/new` pola wyboru nie ma — ogłoszenie powstaje
  dopiero z utworzonej rekrutacji.
