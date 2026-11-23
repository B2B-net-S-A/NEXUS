# Dzwonienie: zaproszenie Teams wysyła osoba, która umawia — decyzja Artura 23.11.2026
<!-- indeks: Zaproszenie na spotkanie (Teams), Umów i wyślij zaproszenie Teams, booking_invite, POST /api/sales/handoffs/{id}/booking-invite, kalendarz prowadzącego, organizator prowadzący, NEXUS Sales Invite, SALES_INVITE_CLIENT_ID, app-only Calendars.ReadWrite, Exchange App RBAC, teams_invite w /form, Zamknij bez zaproszenia -->

Zgłoszenie Bianki i Marcela z 23.11.2026: po „Umówione spotkanie” zaproszenie ma trafić
do kalendarza Teams klienta, prowadzącego i osoby, która umawia. Na kopii produkcji
z 23.11: 24 przekazania z kolejki (21 Krystian, 2 Rafał), 10 maili do klienta od
dzwoniących, **0 zaproszeń wysłanych z NEXUSA przez prowadzącego**, 17 z 24 spotkań
założonych w Outlooku ręcznie. Makiety: https://claude.ai/artifact/Gxjj6erDvtVBijP4S73g6p
(prywatny artefakt, „Punkt 1”). Artur wybrał wariant A.

Kod: `backend/app/services/sales/booking_invite.py`, trasa w `api/sales_handoffs.py`,
token `services/m365/sales_invite_auth.py`; rezerwacja, oś szansy i historia wspólne
z `handoff_invite.py`. Front `handoff/BookMeetingForm.tsx` (sekcja „Zaproszenie na
spotkanie (Teams)”), szablony `teamsInviteSubject` / `teamsInviteBody` w `handoff/helpers.ts`.
Bez migracji.

## Co zmienia wcześniejsze decyzje

- 10.11 („zaproszenie wysyła tylko prowadzący, ze swojej skrzynki”) i 17.11 („z kolejki
  dzwoniący wysyła tylko mail”): **z kolejki dzwonienia zaproszenie wysyła osoba, która
  umawia, jednym kliknięciem w formularzu**. Organizatorem dalej jest prowadzący, więc
  transkrypt i mail po spotkaniu działają jak dotąd. Powód: 0 z 24.
- Ścieżka prowadzącego (`POST …/invite`) zostaje dla przekazań spoza kolejki i dla
  przypadku, gdy umawiający zaproszenia nie wysłał.
- Mail do klienta (`booking_mail`) zostaje jako zapas: formularz pokazuje go, dopóki
  aplikacja w Microsoft 365 nie jest ustawiona (`teams_invite: false` w `GET …/form`).

## Jak działa

- Najpierw zapis przekazania (`POST /api/sales/handoffs`), potem
  `POST /api/sales/handoffs/{id}/booking-invite`. Spotkanie powstaje przez
  `POST /users/{adres prowadzącego}/events` z `isOnlineMeeting` i
  `onlineMeetingProvider: teamsForBusiness`; Outlook rozsyła zaproszenia.
- Uczestnicy: adres klienta z pola (do poprawienia) i osoba, która umawia (pole „Ty”,
  domyślnie zaznaczone). Organizatora nie dopisujemy jako uczestnika.
- Tytuł „B2Bnetwork × {firma}: {usługa}”, treść bez terminu (termin i link Teams
  dokłada Outlook). Oba idą za firmą, usługą i prowadzącym, dopóki dzwoniący ich nie poprawi.
- Bez terminu zaproszenie nie wychodzi (formularz mówi to pod polami), spotkanie się zapisuje.
- **Nie wyszło → spotkanie zostaje**: okno daje „Wyślij ponownie” albo „Zamknij bez
  zaproszenia”, jak przy mailu.

## Bramki (kolejność ma znaczenie)

- Wysyła `booked_by` albo admin; prowadzący i obcy dostają 403, zanim serwer powie
  cokolwiek o adresach (`booking_mail.ensure_sender`).
- Adres z bazy kandydatów: 422 bez wymieniania adresu. Kontakt ze sprzeciwem: 409.
- Brak poświadczeń aplikacji: 409 z prośbą o mail (`NOT_CONFIGURED_DETAIL`).
- Opiekun szansy bez aktywnego konta z „Sprzedaż: edycja” albo bez adresu: 409. Opiekuna
  da się zmienić po umówieniu na dowolne konto, więc bramka prowadzącego z „Umów spotkanie”
  (`handoff_hosts.ensure_host`) idzie jeszcze raz przed Graph; aplikacja nie polega tylko
  na zakresie w Exchange (przegląd 23.11.2026).
- **Jedno zaproszenie na przekazanie, bez względu na to, kto je wysyła**: ten sam klucz
  `invite` w bloku przekazania i ten sam `transactionId` (`sales-handoff-{id}-{termin}`)
  co w `handoff_invite`, zapisany przed Graph. Po zaproszeniu od umawiającego prowadzący
  dostaje 409 („już w kalendarzu”), i odwrotnie.
- Odmowa Graph 403/404 (skrzynka poza zakresem aplikacji): 409 „NEXUS nie ma dostępu do
  kalendarza tego prowadzącego”, rezerwacja znika. Inne 4xx, brak tokenu i połączenie,
  które nie powstało (zapora na stagingu `StagingEgressBlocked`): 502, rezerwacja znika.
  Każdy błąd MSAL przy tokenie (Entra nieosiągalne, zły tenant) to „brak tokenu”, bo
  MSAL idzie przez `requests`, a nie httpx, i inaczej wpadłby do „nie wiadomo”. 5xx i zerwana odpowiedź:
  409 „nie wiadomo”, rezerwacja trzyma 10 minut.

## Ślad

- Na osi szansy spotkanie z Outlooka (`msgraph-event`, `iCalUId`) zamiast wpisu terminu;
  **autorem jest prowadzący** (organizator), bo po autorze liczą KPI i „Mój dzień”.
  Kopia z synchronizacji kalendarza skleja się z nim.
- W bloku przekazania `invite.by` = osoba, która kliknęła; historia `handoff` → `invited`,
  bez adresów i tematu.

## Microsoft 365 (raz, administrator)

Osobna rejestracja **NEXUS Sales Invite**, nie „NEXUS Teams Prep”: tamta ma transkrypty
i kalendarze DL-i i rekruterów, a Exchange zawęża aplikację do skrzynek, nie do uprawnień.

1. Entra ID → App registrations → New registration „NEXUS Sales Invite” (single tenant),
   sekret klienta. **Bez** uprawnień aplikacyjnych w Entra: kalendarze nadaje Exchange.
2. Exchange Online: grupa mail-enabled security `NEXUS-Sales-Invite-Scope` (Krystian, Rafał),
   zakres zarządzania po członkostwie w grupie i rola `Application Calendars.ReadWrite`
   dla aplikacji (App RBAC). `Test-ServicePrincipalAuthorization` = `InScope True` dla
   prowadzącego i `False` dla innej skrzynki.
3. Spotkanie Teams z `isOnlineMeeting` w `/users/{upn}/events` wymaga tylko zapisu
   kalendarza; `OnlineMeetings.ReadWrite.All` nie jest potrzebne. Niepotwierdzone na
   naszym tenancie do pierwszego spotkania testowego.
4. Workflow „Coolify set env”: `SALES_INVITE_CLIENT_ID` (wartość) i
   `SALES_INVITE_CLIENT_SECRET` (`value_from_secret`), potem Deploy w oknie wdrożeń.
   Tenant = `M365_MAIL_TENANT_ID`. Od tej chwili formularz pokazuje sekcję Teams.

Nowy prowadzący = dopisanie do grupy; bez tego wysyłka kończy się 409 „nie ma dostępu
do kalendarza”, a dzwoniący wraca do maila z innego okna albo do prowadzącego.

## Staging i testy

Na stagingu `graph.microsoft.com` jest za zaporą wyjścia i nie ma poświadczeń, więc
sekcja Teams pokazuje się tylko z ustawionymi fikcyjnymi zmiennymi, a wysyłka kończy
się 502 „nic nie wyszło”. Testy podstawiają Graph: `backend/tests/test_sales_booking_invite.py`;
front `sales-handoff.test.tsx` („zaproszenie Teams od umawiającego”).
