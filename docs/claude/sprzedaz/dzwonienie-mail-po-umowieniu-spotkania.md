# Dzwonienie: mail do klienta po umówieniu spotkania — decyzje Artura 17.11.2026
<!-- indeks: Mail do klienta, Umów i wyślij mail, booking_mail, POST /api/sales/handoffs/{id}/booking-mail, DW prowadzący, skrzynka osoby dzwoniącej Mail.Send, Wyślij ponownie, Zamknij bez maila, mail na osi szansy, Teams dalej wysyła prowadzący, piąte sales_ok -->

Prośba osób dzwoniących (17.11.2026): po „Umówione spotkanie” w kolejce mail ma wyjść
ze skrzynki Outlook osoby, która umówiła spotkanie, do klienta i do prowadzącego.
Na kopii z 16.11: 31 rekordów „Umówione spotkanie” (11–13.11), 28 z adresem klienta,
obie osoby dzwoniące mają skrzynkę ze zgodą `Mail.Send`, a prowadzący nie wysłał z NEXUSA
żadnego zaproszenia. Makiety: https://claude.ai/artifact/V4WSECrstL1vpHxwTiWcwV (prywatny
artefakt). Artur wybrał wszystkie rekomendowane warianty.

Kod: `backend/app/services/sales/booking_mail.py`, trasa w `api/sales_handoffs.py`,
wysyłka i zapis maila wspólne z mailem po spotkaniu (`meeting_client_mail.deliver`,
`record_email`), front `handoff/BookMeetingForm.tsx` (sekcja „Mail do klienta”, gdy
formularz dostaje `invite` z kolejki), szablony w `handoff/helpers.ts`. Bez migracji.

## Co zmienia wcześniejsze decyzje

- „Formularz „Umów spotkanie” niczego nie wysyła” (10.11 i 13.11) ma jeden wyjątek:
  **z kolejki dzwonienia, kliknięciem „Umów … i wyślij mail”**, osoba, która umawia,
  wysyła mail ze swojej skrzynki. Zasada „nic nie wychodzi z cudzej skrzynki” zostaje.
- **Spotkanie Teams dalej wysyła prowadzący** (`handoff_invite.py`), żeby to on był
  organizatorem (transkrypt i mail po spotkaniu). Wariantów „.ics w mailu” i „Teams
  z kalendarza dzwoniącego” Artur nie wybrał: pierwszy daje klientowi dwa wpisy
  w kalendarzu, drugi oddaje transkrypt dzwoniącemu.

## Jak działa

- Sekcja „Mail do klienta”: Od (skrzynka osoby), DW (prowadzący z pola „Prowadzący”
  i jego adres z konta NEXUSA), adres klienta z rekordu do poprawienia, tytuł i treść.
  Tytuł i treść idą za terminem, czasem, usługą i prowadzącym, dopóki dzwoniący ich
  nie poprawi. Bez adresu klienta albo po odznaczeniu „Wyślij po zapisie” przycisk
  tylko zapisuje. Stopkę dokleja Outlook (`stopka-outlooka-w-mailach-z-nexusa.md`).
- Najpierw zapis przekazania (`POST /api/sales/handoffs`), potem mail
  (`POST /api/sales/handoffs/{id}/booking-mail`). **Mail nie wyszedł → spotkanie
  zostaje**, okno mówi to i daje „Wyślij ponownie” albo „Zamknij bez maila”. Wynik
  rozmowy w kolejce zapisuje się przy zamknięciu okna, jak dotąd.
- Adres klienta trafia też do bloku przekazania (`invite_to`), więc okno „Wyślij
  zaproszenie” prowadzącego ma go w podpowiedzi. `invite_message` to dalej podpowiedź
  zaproszenia (`inviteTemplate`), nie treść maila: zdanie „zaproszenie w Teams przyjdzie
  osobno” nie pasuje do samego zaproszenia.

## Bramki (kolejność ma znaczenie)

- Wysyła **osoba, która umówiła** (`booked_by`) albo admin, z własnej skrzynki; prowadzący
  i obcy dostają 403, zanim serwer powie cokolwiek o adresach.
- Adres z bazy kandydatów: 422 bez wymieniania adresu. Kontakt sprzedaży ze sprzeciwem
  („Nie kontaktować”): 409. Skrzynka niepodłączona albo bez `Mail.Send`: 409.
- To **piąte dozwolone użycie `GraphClient(..., sales_ok=True)`** (przez
  `meeting_client_mail.deliver`, `outlook-handlowcow-w-sprzedazy.md`).
- **Jeden mail na przekazanie:** klucz w bloku przekazania (`booking_mail`) zapisany
  przed Graph. Drugi mail to 409 („wyślij z Outlooka”). Odmowa Graph 4xx albo
  połączenie, które nie powstało (także zapora wyjścia na stagingu), zwalnia klucz: 502,
  nic nie wyszło. Błąd po utworzeniu szkicu trzyma klucz 10 minut: 409 „sprawdź Wysłane”.
  Klient API (`lib/api.ts`) powtarza zapis po 502 dwa razy; tu to bezpieczne, bo klucz
  jest wtedy zwolniony i nic nie wyszło (na stagingu widać trzy próby na jedno kliknięcie).
- Przekazanie po werdykcie albo zamknięta szansa: 409 (`handoff.pending`).

## Ślad

- Mail na osi szansy i firmy jako `email`/`out` z `internetMessageId`, więc kopia
  z „Wysłanych” z synchronizacji skleja się z nim (ten sam klucz co
  `ux_sales_activities_outlook`). Autor = osoba, która wysłała; kontakt = osoba ze spotkania.
- Historia szansy: krok `handoff` → `booking_mail`, bez adresów i tytułu.

## Staging i testy

Na stagingu `graph.microsoft.com` jest za zaporą wyjścia (`app/core/staging.py`), a skrzynki
z kopii są nieaktywne, więc nic nie wychodzi; próba kończy się „Outlook nie przyjął maila”.
Testy podstawiają Graph: `backend/tests/test_sales_booking_mail.py`; front
`sales-handoff.test.tsx` („mail do klienta po umówieniu”).
