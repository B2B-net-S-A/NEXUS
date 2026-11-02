# Portal konsultanta — link z maila, sesja poza JWT, SMS przed finansami, jedna karta z dwóch kanałów

Decyzje Artura z 02.11.2026 (projekt „Back office na sprawach”). Konsultant nie ma konta
w NEXUSIE: wchodzi linkiem z maila na `/konsultant`. Kod: `app/api/consultant_portal.py`
(publiczne), `app/api/consultant_portal_staff.py` (back office), `app/services/consultant_portal/`.

## Wyłącznik

`app_settings['consultant_portal']` = `{"state": "off"|"pilot"|"all", "pilot_contract_ids": [...]}`,
zmienia admin przez `PUT /api/back-office/portal/settings`. Brak wiersza = `off`: każda publiczna
trasa odpowiada 404, także przy poprawnej sesji, a pętle nic nie robią. Każdy mail do konsultanta idzie
przez `portal_mail.send`, który sprawdza wyłącznik dla kontraktu, bo to wysyłka do ludzi spoza firmy.

## Reguły bezpieczeństwa, które łatwo cofnąć

- Token linku i sesji tylko jako SHA-256 w bazie. Token z maila idzie we fragmencie adresu
  (`/konsultant/wejscie#…`, `/konsultant/ocena#…`), a do API w ciele żądania, nigdy w ścieżce:
  ścieżka trafia do logów. Sesję zakłada POST, bo skanery poczty otwierają adresy same.
- Sesja jest w nagłówku `X-Portal-Session`, nie w `Authorization` i nie jest JWT. Pracowniczy token
  nie działa w portalu, a portalowy nie działa w `/api/**` pracownika. Sesja pada, gdy kontrakt przestaje
  działać, zmienia adres albo wypada z pilotażu.
- Prośba o link odpowiada tym samym zdaniem dla każdego adresu, a mail idzie w tle. Liczy się wyłącznie
  `contracts.candidate_email`; adres dwóch różnych osób nie otwiera niczego.
- Kod SMS jest HMAC-iem związanym z sesją: 5 prób, 5 minut, nowy kod po minucie, 5 kodów na godzinę.
  Odblokowanie finansów trwa 30 minut.
- „Twoje sprawy” to lista dozwolona (`content.visible_cases_clause`): zgłoszenia z portalu z kluczem
  `portal:` i maile, które konsultant sam napisał. Nigdy obszar `negotiation`, sprawy automatyczne, opis,
  komentarze ani checklista. Pole „Czeka na” z karty konsultant widzi w portalu.
- Moduł publiczny ma `@limiter.limit`, więc nie ma `from __future__ import annotations`.

## SMS

`SmsSender` bez konkretnego dostawcy. `CONSULTANT_PORTAL_SMS_PROVIDER`: `disabled` (domyślnie) albo `log`,
działający tylko przy `NEXUS_ENV=staging` i w testach. Przy `disabled` sekcja finansów mówi po polsku, że jest
chwilowo niedostępna, a reszta portalu działa.

## Rozmowy

Konsultant wybiera osobę z zespołów `care`, `finance`, `contracts` i termin. Organizatorem jest
`CONSULTANT_PORTAL_MAILBOX` przez rejestrację „NEXUS Teams Prep”, więc konto musi być w grupie
`NEXUS-Meetings-Scope`. Termin rezerwuje wiersz `pending` zatwierdzony przed Graphem (częściowy unikat na osobę
i początek). Kalendarz nieczytelny = brak terminów. Własna tabela `cp_meetings`, bo `prep_meetings` wymaga
kandydata i rekrutacji. Transkrypt bez wideo zależy od polityki Teams, której w kodzie nie widać.
Podsumowanie AI (`portal_meeting_summary`) to komentarz w sprawie: awaria modelu niczego nie blokuje.
Transkrypt znika po 365 dniach (`TRANSCRIPT_RETENTION`, termin do potwierdzenia z IOD).

## Oceny

Osoba oceniana nie widzi pojedynczych ocen, także kierownik przy własnej rozmowie. Macierz uprawnień tego nie
pokaże, bo reguła siedzi w treści odpowiedzi, dlatego pilnują jej testy `test_consultant_portal_flows.py`.
Ocena 1–2 zakłada zadanie w wierszu oceny (`followup_*`), a nie sprawę, bo sprawy widzi cały zespół.
Przegląd miesięczny pokazuje zbiorcze liczby od 3 ocen.

## Rozliczenia

Portal (po kodzie SMS) i czytnik `CONSULTANT_PORTAL_SETTLEMENTS_MAILBOX` kończą w `documents.store`. Karta to
(kontrakt, okres, rodzaj), kolumna `invoice` zespołu `finance` (`sources.document_cards`). Ten sam plik z drugiego
kanału to ten sam wiersz. Raport przyjęty przez Finanse daje sygnał „wystaw fakturę”. W pilotażu czytnik bierze
tylko nadawców z pilotażu, a nieznany nadawca dostaje kartę do przypisania dopiero w stanie `all`.
