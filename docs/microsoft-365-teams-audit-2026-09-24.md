# NEXUS × Microsoft 365 / Teams — stan i plan uruchomienia

**Odczyt:** 24.09.2026, 20:24 CEST. **Wersja produkcyjna:** `106b357d9a00bb74decbd6a4d1e04786e4432042` (`origin/main`). Audyt wyłącznie odczytowy: kod, publiczne sondy API i zalogowane UI konta Artura. Nie zakładano spotkania ani nie wysłano maila; nie udzielano uprawnień w Entra/Teams.

**Dodatkowy odczyt administracyjny:** Teams admin center → Meetings → Meeting settings pokazuje `Transcript API access → Microsoft Graph access = Off` oraz `Include speaker attribution = Off`. To bezpośrednia przyczyna, dla której aplikacja nie pobierze VTT po samym nadaniu uprawnienia Graph.

**Polityka Teams (odczyt):** globalne `Meeting recording = On`, `Transcription = On`, `Require participant agreement = Off`, automatyczne wygaśnięcie nagrań/transkryptów po 120 dniach. W Entra jest 20 rejestracji aplikacji, bez „NEXUS Teams Prep”. Rejestracja „NEXUS ATS - Mailbox and Login” ma `Application Mail.Read`, natomiast `Mail.Send` tylko typu `Delegated` — aplikacyjna wysyłka systemowa nie może korzystać z tego grantu.

## Werdykt

| Obszar | Stan potwierdzony | Co to oznacza |
| --- | --- | --- |
| Osobisty Outlook Artura | UI „Połączony”, `artur.twardowski@b2bnetwork.pl`, synchronizacja 3 min temu; `checks.m365=healthy` | Osobiste konto jest podłączone i ostatnia synchronizacja nie zgłasza błędu. To nie dowodzi skutecznego wysłania maila ani utworzenia spotkania. |
| Zaproszenia Outlook/Teams | Ścieżka kodowa działa przez `POST /me/events`, z opcjonalnym `isOnlineMeeting=true`, `teamsForBusiness`; formularz przy kandydacie używa tej trasy. Szybkie „Zaplanuj spotkanie” w menu tworzyło tylko lokalny wpis NEXUS. | Funkcja istnieje dla połączonego organizatora; w tym PR szybki formularz dostaje jawny wybór Outlook/Teams i uczestników. Rzeczywistego utworzenia i doręczenia zaproszenia dziś nie sprawdzono. |
| Osobiste maile do kandydatów | Kompozytor `POST /api/candidates/{id}/emails/compose` używa skrzynki połączonego użytkownika i Microsoft Graph | Ścieżka istnieje; bez kontrolowanego maila i potwierdzenia w „Wysłane”/u odbiorcy nie ma dowodu dostawy. Stary endpoint `/api/emails/send` zwraca 410. |
| Maile systemowe | `checks.m365_mail=degraded`, `notification_email_policy=disabled` | Automatyczne powiadomienia nie są potwierdzonym sprawnym kanałem. Stan ten jest odrębny od osobistej skrzynki Artura. W poprzedniej obserwacji Graph zwracał 403; bieżąca sonda nie podaje kodu ostatniego błędu. |
| Prep 1 / Prep 2 w Teams | `checks.teams_prep=unconfigured`; trasa app-only zwraca 503, gdy brak konfiguracji | Kod do założenia spotkania w kalendarzu DL/rekrutera, włączenia nagrania i pobrania VTT jest wdrożony, ale produkcyjnie nieuruchomiony. Zwykłe zaproszenie z połączonego konta jest inną ścieżką i samo nie zasila oceny prepu. |
| Follow up | Follow up zapisuje wynik telefonu i czas oddzwonienia; CloudTalk osobno pobiera transkrypty połączeń | Nie ma automatycznego powiązania konkretnego follow upu z nagraniem/transkryptem. Dla follow upu w Teams trzeba dodać osobny wariant spotkania; telefon wymaga spięcia z identyfikatorem połączenia CloudTalk. |

## Co już jest w kodzie

- `backend/app/services/m365/calendar.py` tworzy wydarzenie Graph z linkiem Teams; `backend/app/api/calendar.py` obsługuje zaproszenie, aktualizację i odwołanie. Ogólny „prep_call” nie włącza automatycznego nagrania.
- `backend/app/api/email_threads.py` i `backend/app/services/m365/sender.py` wysyłają z konta rekrutera. Niezależny nadawca systemowy jest w `backend/app/services/m365/app_mail.py`.
- `backend/app/services/prep_meetings.py`, `backend/app/services/m365/teams_prep_graph.py` i `backend/app/services/prep_transcripts.py` tworzą Prep 1/2 w kalendarzu wskazanego organizatora, ustawiają `recordAutomatically` i `allowTranscription`, pobierają VTT, zapisują transkrypt i ocenę. Przełączniki są domyślnie wyłączone (`TEAMS_PREP_APP_ONLY_ENABLED`, `TEAMS_PREP_TRANSCRIPTS_ENABLED`). Aktualna sonda wskazuje `unconfigured`.
- `backend/app/tasks/microsoft365_sync.py` ma osobne wykrywanie linku do pliku nagrania w OneDrive. `M365_RECORDING_DISCOVERY_ENABLED` jest domyślnie wyłączone. Link do nagrania to nie transkrypt ani dowód, że nagranie rzeczywiście wystartowało.
- `backend/app/api/candidate_followups.py` zapisuje wynik rozmowy jako notatkę/dziennik; `backend/app/tasks/cloudtalk_sync.py` synchronizuje nagrania i transkrypty rozmów telefonicznych, ale modele nie zawierają relacji follow up → call. Stare wzmianki o Fireflies w notatkach/kodzie nie oznaczają aktywnego modułu Fireflies: bieżący `origin/main` nie ma jego API ani synchronizatora.

## Kolejność poprawek

1. **Uruchomić jeden kontrolowany przepływ prepu.** Skonfigurować osobną rejestrację Entra „NEXUS Teams Prep” według `docs/teams-prep-setup.md`, z `Calendars.ReadWrite`, `OnlineMeetings.ReadWrite.All`, `OnlineMeetingTranscript.Read.All`, `User.ReadBasic.All`, zgodą administratora i zakresem tylko dla organizatorów prepów. Dla kalendarzy preferować aktualny Exchange App RBAC z zakresem skrzynek; instrukcja w repo opiera się na starszej Application Access Policy. Polityka Teams dla dostępu do spotkań/transkryptów jest osobna. Zanim włączy się przełączniki, sprawdzić na dopuszczonej i niedopuszczonej skrzynce, że zakres rzeczywiście działa. Ten krok zmienia dostęp do wrażliwych danych i wymaga świadomej decyzji administratora.
2. **Włączyć dostęp API do transkryptów w Teams.** Microsoft opisuje obecnie osobny przełącznik Teams Admin Center → Meetings → Meeting settings → Transcript API access (domyślnie wyłączony), oprócz uprawnień Graph i polityk spotkań. Ustawić transkrypcję, automatyczne nagrywanie oraz język polski dla organizatora testowego. Sam sukces `PATCH onlineMeeting` nie dowodzi powstania nagrania lub VTT.
3. **Zweryfikować zgodę i retencję.** Zaproszenie prepu zawiera obecnie komunikat „powiedz na początku, jeśli nie chcesz nagrania”, lecz nagranie ma startować automatycznie. Przed włączeniem zadbać o właściwą informację i mechanizm sprzeciwu/zgody przed rozpoczęciem nagrywania, dostęp do transkryptu w NEXUS, retencję w NEXUS i M365 oraz obsługę odmowy. Microsoft oferuje politykę wymagającą zgody uczestnika w Teams. Treść komunikatu w kodzie oznaczono jako roboczą do akceptacji prawnej.
4. **Osobno naprawić pocztę systemową.** Dedykowana rejestracja Entra z samym `Application Mail.Send`, zakres Exchange tylko dla `nexus-powiadomienia@b2bnetwork.pl`, nowe `M365_APP_MAIL_CLIENT_ID/SECRET` w Coolify i przełączenie nadawcy. Nie dokładać `Mail.Send` do istniejącej aplikacji z `Mail.Read`. Następnie jeden zatwierdzony test dostawy; nie włączać rutynowych powiadomień na podstawie samego `checks.m365=healthy`.
5. **Dodać przepływ follow up.** Zdefiniować, czy follow up oznacza rozmowę telefoniczną CloudTalk, czy spotkanie Teams. Dla telefonu zapisać trwały identyfikator połączenia i powiązać właściwy transkrypt z konkretnym wpisem follow up, z obsługą kolizji numerów i kontroli dostępu. Dla Teams użyć osobnego typu wydarzenia i tej samej kolejki transkryptów co prep, z wyraźnym wyborem nagrywania przy planowaniu. Nie nagrywać automatycznie każdego follow upu bez ustalonej polityki.

## Kryteria odbioru produkcyjnego

- Jeden kontrolowany Prep 1: wydarzenie w Outlooku właściwego DL-a, zaproszenie u kandydata, link Teams, widoczna zgoda/komunikat, automatyczny start nagrania i transkrypcji, następnie VTT oraz ocena w NEXUS. Powtórzyć dla Prep 2 z rekruterem. Sprawdzić także odmowę nagrywania i brak transkryptu.
- Osobny mail osobisty: widoczny w „Wysłane” organizatora i dostarczony do testowego odbiorcy. Osobny mail systemowy: potwierdzony u odbiorcy, `checks.m365_mail=healthy`, dopiero potem decyzja o ponownym włączeniu powiadomień.
- Follow up: wpis w NEXUS wskazuje dokładnie właściwe połączenie/spotkanie i transkrypt; użytkownik bez uprawnienia do kandydata nie odczyta treści.
- Potwierdzić wdrożony SHA, CI, sondy, ustawienia tenanta i realny przepływ. Dziś potwierdzono SHA, sondy i osobisty status UI, lecz nie wysłano maila ani nie utworzono spotkania.

## Źródła Microsoft

- [Wydarzenie Outlook z Teams](https://learn.microsoft.com/en-us/graph/outlook-calendar-online-meetings)
- [Aktualizacja onlineMeeting: recordAutomatically / allowTranscription i uprawnienia aplikacji](https://learn.microsoft.com/en-us/graph/api/onlinemeeting-update?view=graph-rest-1.0)
- [Odczyt transkryptów i application access policy](https://learn.microsoft.com/en-us/graph/api/onlinemeeting-list-transcripts?view=graph-rest-1.0)
- [Dostęp API do transkryptów Teams](https://learn.microsoft.com/en-us/microsoftteams/meeting-transcript-api-access)
- [Opcje nagrywania i transkrypcji](https://learn.microsoft.com/en-us/microsoftteams/manage-meeting-recording-options)
- [Zgoda uczestników na nagranie](https://learn.microsoft.com/en-us/microsoftteams/participant-agreement-recording-transcription)
- [Exchange App RBAC](https://learn.microsoft.com/en-us/exchange/permissions-exo/application-rbac)
