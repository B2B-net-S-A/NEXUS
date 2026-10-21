# Powiadomienia dla ról i jeden ekran „Powiadomienia” (0425, 09.10.2026)

Zgłoszenie admina 09.10.2026: „możliwość wybrania, do jakiej roli mają iść
powiadomienia”. Takiego ustawienia nie było — a szukając go, ta osoba wyłączyła
poranny skrót całej firmie (przełącznik maili nie mówił, że działa na
wszystkich). Makiety: https://claude.ai/artifact/TRKAAZX3RcB8AA7LVohkT8, raport
`docs/notification-role-matrix-completion-report.md`.

- **Jeden ekran, cztery zakładki** (`components/settings/NotificationsSettings.tsx`,
  `?sub=moje|role|maile|etapy`): „Moje” (każdy), „Kto co dostaje” i „Maile”
  (admin + `system_admin`), „Reguły etapów” (link do Procesów rekrutacyjnych).
  Oba id rejestru zostają (`my-notifications`, `notifications`) i otwierają ten
  sam ekran na innej zakładce — linki z dzwonka i zakładki przeglądarki działają.
  **Od 21.10.2026 (runda 2 Ustawień):** `my-notifications` to „Moje konto”
  (Microsoft 365 + własne powiadomienia), a System › „Powiadomienia firmy”
  (`notifications`) nie ma zakładki „Moje” (`includeMine` tylko przy
  `defaultTab="moje"`); „tylko sobie” w „Maile” prowadzi linkiem do „Moje konto”.
  Liczba pod przełącznikiem roli ma podpis: powiadomienia z `window_days` dni.
- **„Kto co dostaje” = wyłączenie GRUPY dla ROLI**
  (`services/notification_role_mutes.py`, wiersz
  `app_settings['notification_role_mutes']` = `{revision, roles: {rola:
  {grupa: czas}}}`, trasy `GET/PUT /api/settings/notification-roles`, `AdminUser`).
  Grupa to kategoria albo jej nazwany kawałek (`notification_categories.GROUP_INFO`
  — podzielone są tylko „Kontrakty…” i „Zaległości…”); nowy typ powiadomienia
  bez grupy wywraca `test_notification_role_mutes.py`. Kategorii obowiązkowych
  (Wzmianki, Rozmowy, Konto i system) nie da się wyłączyć.
- **Konto z kilkoma rolami traci grupę dopiero, gdy jest wyłączona w KAŻDEJ
  jego roli** (`role_muted_groups`) — jak sekcje, które liczą się z maksimum ról.
- **Stosuje to to samo miejsce co wyciszenia osoby:** `resolve_effective_access`
  dołącza `user.role_muted_notification_types`, a `notification_access`
  (`user_can_receive_notification`, `notification_visibility_predicate`) sumuje
  je z wyciszeniami osoby. Konto bez policzonej polityki = nic nie wyłączone.
  Wiersz czytamy przy każdym liczeniu dostępu, bez pamięci procesu. Nie dokładaj
  filtra ról w pojedynczym producencie.
- **Zapis ma wersję i ślad:** `PUT` z `revision` (409 `stale_notification_roles`),
  wpis `notifications.role_mutes` w Historii zdarzeń, bez wylogowywania. Ponowne
  włączenie oznacza jako przeczytane powiadomienia grupy z czasu wyłączenia —
  tylko kontom, którym grupa była naprawdę wyłączona.
- **Rola może grupę WYŁĄCZYĆ, nie przejąć.** Dopisania dowolnej roli jako
  odbiorcy nie ma: większość powiadomień jest imienna (rekruter kandydata,
  Delivery Lead rekrutacji). Wybór roli-odbiorcy istnieje tylko w regułach etapów.
- **Dzwonek końca zamówień, umów i umów ramowych nie idzie już do każdego
  admina** (`DeliveryAlertRecipientScope.bell_recipients(client_id, typ)`):
  Delivery Leadzi klienta, a admini tylko jako zapas, gdy ŻADEN z nich nie może
  dostać tego typu — klient bez DL-a, umowa bez klienta, ale też DL z wyciszoną
  kategorią albo grupą wyłączoną dla roli (inaczej alert trafiałby do wiersza,
  którego nikt nie widzi, a skaner uznawałby próg za wysłany). Konto Admin + DL
  przypisane do klienta liczy się jako jego DL. Pomiar przed zmianą: 1 237
  powiadomień w 30 dni na 7 adminów, przeczytane w 8% (DL-e: 43%). `for_client`
  (admini + DL) zostaje wyłącznie bramką maili w
  `dl_alerts.send_pending_alert_emails`.
- **Maile: przełącznik mówi „cała firma” i pyta przed wyłączeniem**
  (`NotificationDeliverySettings.tsx`), a zmiana zostawia wpis
  `notifications.email_policy` w Historii zdarzeń (`save_policy(actor=…)`).
  Ekran pokazuje, kto i kiedy zmienił ostatnio.
- **Poranny skrót ma własny wyłącznik konta:** `users.daily_digest_email_enabled`
  (0425 + lustro w `entrypoint.sh`), `PATCH /api/users/me/preferences`, filtr
  w `daily_digest_email._recipients`. Nie dokładaj kolejnego wyłącznika „dla
  wszystkich”, gdy ktoś chce wyłączyć coś sobie.
- **„Maile do Ciebie” — każdy widzi i wyłącza swoje maile (0427, decyzja Artura
  09.10.2026).** Do tej daty rekruter nie widział w „Moje”, które maile do
  niego idą (lista była tylko w zakładce admina). Teraz
  `GET/PUT /api/users/me/email-notifications[/{kind}]`
  (`services/notification_email_prefs.py`): `APPLIES` mówi, czy mail w ogóle
  może trafić do konta (lustro reguł odbiorców u nadawców), stan wiersza
  i zdanie wyjaśnienia liczy serwer (`on`, `self_off`, `company_off`,
  `bell_muted`, `role_muted`). Wyłączyć sobie da się KAŻDY mail, także
  mail-zadanie — dzwonek i „Czeka na Ciebie” zostają; zawsze przychodzą tylko
  maile bezpieczeństwa konta. Wyłączenia żyją w `users.email_opt_outs`
  (`{rodzaj: czas}`), skrót zostaje przy swojej kolumnie.
  **Każdy nadawca pyta `notification_delivery.email_opted_out(user, rodzaj)`
  tuż przed wysyłką** — nowy rodzaj maila = wpis w `CATALOG`, reguła
  w `APPLIES` i to pytanie u nadawcy (pilnuje
  `test_notification_email_prefs.py`, strażnik AST). Admin widzi w „Maile”,
  kto wyłączył który mail sobie (`self_disabled`).
  **Nadawca z kolejką (dzwonek → mail: terminy, alerty klientów, maile
  natychmiast, czat) odsiewa takie konta W ZAPYTANIU** —
  `email_queue_clause(rodzaj, kolumna_czasu)`, a w pętli pyta
  `email_wanted(konto, rodzaj, czas_zdarzenia)`. Sam `continue` w Pythonie
  zostawia wiersze bez stempla wysyłki: zajmują paczkę (najstarsze pierwsze)
  i z czasem zatrzymują ten mail wszystkim. Ponowne włączenie zapisuje czas
  w `email_opt_outs["_resumed"]` — zdarzenia z okresu wyłączenia nie wychodzą
  jako zaległości (jak `send_not_before` przy przełączniku firmowym).
- Testy tabeli ról na wspólnej bazie sprzątają wiersz `app_settings` (fixture
  `clean_role_mutes`) — zostawione wyłączenie ucinałoby powiadomienia adminom
  w cudzych testach. Harness `/preview/notification-settings`.

## Alarm o masowym przeglądaniu CV kandydatów (0505, 22.10.2026)

**Skąd.** 12.10.2026 dziewięciu kursantów Akademii Sourcera zalogowało się
pierwszy raz Microsoftem. SSO dawało wtedy rolę Rekruter (od #2339, 19.10,
daje już „Pracownik”). W ciągu trzech godzin otworzyli pliki 181 kandydatów,
a 41 plików zapisali na dysk. Nikt się o tym nie dowiedział, dopóki Artur nie
zobaczył obcych nazwisk w „Ludziach” 22.10.

**Decyzja Artura 22.10.2026.** Tylko alarm, bez blokady i bez znaku wodnego na
plikach. Alarm dostają admin i Head of Recruitment (rola główna albo dodatkowa)
jako dymek w NEXUSIE i mail od razu.

### Co liczymy

`services/candidate_data_access_alerts.py` co 5 minut (pętla
`candidate_data_access_alerts`, heartbeat) czyta `activities` z
`entity_type='candidate'`. Każda droga do pliku kandydata już tam zapisuje
zdarzenie (`candidate_audit`):

- podgląd i zapis na dysk: `document_downloaded`, `disposition` `inline` albo `attachment`,
- link do pliku: `document_url_issued`,
- pobranie CV: `cv_downloaded`,
- paczka ZIP: `bulk_cv_downloaded`, `included_count`,
- eksport: `export_requested`, `row_count` albo `selected_count`.

Zdarzenia API integracji mają `user_id` puste i nie są liczone.

### Progi (zmienne env, wartości domyślne)

| Co | Próg | Nowe konto (< 14 dni) |
|---|---|---|
| różnych kandydatów w ostatniej godzinie | > 40 | > 20 |
| plików na dysk dziś (kalendarz firmy) | > 25 | > 12 |
| osób w eksportach dziś | > 200 | > 100 |
| nowe konta otwierające CV w tej samej godzinie | ≥ 3 | — |

Źródło progów to ruch produkcji z 30 dni do 22.10.2026, bez juniorów:
99. percentyl to 33 kandydatów na godzinę (maksimum 61), na dysk najwyżej 20
plików dziennie. Te progi dałyby w tych 30 dniach 3 alarmy, wszystkie
o liczbie kandydatów na godzinę u dwóch najaktywniejszych osób.

Odtworzenie 12.10 na danych produkcji: o 12:30 alarm „nowe konta naraz”
(6 kont), o 14:00 alarm za pliki na dysk (20 przy progu 12), o 15:00 alarm
za liczbę kandydatów (25 w godzinę przy progu 20).

Zmienne: `DATA_ACCESS_ALERT_HOUR_CANDIDATES`, `…_DAY_DISK_FILES`,
`…_DAY_EXPORT_ROWS`, `…_NEW_ACCOUNT_DAYS`, `…_NEW_ACCOUNTS_BURST`,
`…_INTERVAL_SECONDS` oraz wyłącznik `DATA_ACCESS_ALERTS_ENABLED`. Na produkcji
zmienia się je wyłącznie workflowem „Coolify set env”.

### Reguły, które łatwo cofnąć

- **Bez blokady.** Alarm niczego nie wstrzymuje. Wstrzymanie pobierania to
  osobna decyzja Artura, która jeszcze nie zapadła.
- **Najwyżej jeden alarm dziennie na osobę i odbiorcę.** Dzienny dedup `emit`
  (`ix_notif_dedup_daily`) patrzy na odbiorcę, typ i `related_entity_id`, ale
  nie na `related_entity_type`. Alarm o osobie niesie więc id konta, a alarm
  „nowe konta naraz” (raz dziennie) ma id 0. Przy id 1 zdusiłby alarm o koncie 1.
- **Bez nazwisk kandydatów w treści**, bo idzie mailem. Treść zawiera imię
  i nazwisko osoby, liczby, datę założenia konta (gdy jest nowe) i zdanie, że
  NEXUS niczego nie zablokował. Link prowadzi do Ustawienia → Osoby i role.
- **Widoczność.** Typ `candidate_data_access_alert` jest w
  `HEAD_OF_RECRUITMENT_ALERT_TYPES` (`notification_access.py`): widzi go admin
  i konto z rolą Head of Recruitment, niezależnie od sekcji. Należy do kategorii
  „Konto i system” (obowiązkowej). Na pasku jest tematem „inne”, czyli dymek
  i mail.
- **Mail** to rodzaj `data_access_alert` w kolejce maili od razu
  (`notification_email_outbox`). Jak każdy mail z katalogu wychodzi dopiero
  po włączeniu w Ustawienia → Powiadomienia → Maile. Włączenie nie wysyła
  zaległych alarmów.
