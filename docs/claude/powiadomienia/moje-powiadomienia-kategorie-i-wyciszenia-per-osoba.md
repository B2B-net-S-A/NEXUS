# Moje powiadomienia — kategorie i wyciszenia per osoba (0349, 22.09.2026)

Każdy sam wybiera w **Ustawienia → Moje konto** (od 20.10.2026 jeden ekran ze
skrzynką Microsoft 365, `?item=my-notifications`; albo ikoną
dzwonka z kreską prosto w dzwonku), które KATEGORIE powiadomień do niego trafiają.

- **Kategorie zna wyłącznie backend** (`services/notification_categories.py`):
  11 grup, mapa typ → kategoria jest wyczerpująca (`test_notification_categories.py`
  — nowy `NotificationType` bez kategorii wywraca CI). Obowiązkowe (nie da się
  wyłączyć): Wzmianki, Rozmowy, Konto i system. Front bierze nazwy z API.
- **Wyciszenia żyją w `users.muted_notification_categories`** (`{kategoria: czas
  wyciszenia}`) i są stosowane w `notification_access` — w
  `user_can_receive_notification` (emit, WebSocket, maile z fallbacku czatu)
  i w `notification_visibility_predicate` (lista, licznik, oznaczanie). Dotyczy
  też admina. Nie dokładaj filtra wyciszeń w pojedynczym producencie.
- Producenci, którzy wstawiają `Notification(` bez pytania o odbiorcę, dalej
  zapisują wiersz — ale dzwonek i licznik go nie pokazują. Ponowne włączenie
  kategorii oznacza jako przeczytane powiadomienia z CZASU wyciszenia (starsze
  nieprzeczytane zostają — „Cofnij" niczego nie gasi).
- Testy wyciszeń na wspólnej bazie MUSZĄ sprzątać po sobie (fixture `admin_id`):
  admin z `app_client` jest odbiorcą w cudzych testach („komplet obsady").
- **`cv_ready` (0440, 14.10.2026)** — „CV gotowe do sprawdzenia” i „Automat
  nie zrobił CV” z automatu auto-CV (`services/cv_auto_generate.py`) do osoby,
  która przesunęła kartę. Kategoria „Ruchy w rekrutacjach” (jak `stage_rule`,
  do wyciszenia), sekcja Rekrutacje, bez maila. Front potrzebuje ikony typu
  w `NotificationsDropdown.tsx`.
- **`client_report_due` (0710, 15.11.2026)** — „Raport dla klienta — termin
  za N dni / termin minął” z katalogu raportów klienta (decyzja Artura:
  przypomnienie DL-a kilka dni przed terminem). Własna kategoria „Raporty dla
  klientów” (do wyciszenia), sekcja Delivery, praca bieżąca (idzie do
  zastępcy), temat paska `other` (dymek), bez maila. Odbiorca:
  `preparer_user_id` definicji, inaczej przy `preparer='dl'` DL-e klienta;
  Finanse/Zarząd/IOD/konsultanci/klient bez wskazanej osoby nie dostają nic.
  Pasmo: termin w ciągu 3 dni roboczych (z dziś), „po terminie” do 3 dni
  roboczych po nim, gdy okres nie ma wysyłki; okresy sprzed
  `catalog.tracking_start` pomijane. Plan liczy czysta funkcja
  `services/client_reports/reminders.py`, pętla `tasks/client_report_reminders.py`
  (co godzinę, od 9:00 w dni robocze, przez `emit`).
