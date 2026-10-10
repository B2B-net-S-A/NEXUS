# Moje powiadomienia — kategorie i wyciszenia per osoba (0349, 22.09.2026)

Każdy sam wybiera w **Ustawienia → Moje konto → Moje powiadomienia** (albo ikoną
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
