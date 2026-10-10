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
