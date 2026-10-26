# Maile obowiązkowe — przychodzą zawsze (26.10.2026)
<!-- indeks: REQUIRED_KINDS w notification_delivery; włączają się same przy starcie bez zaległości; konto nie wyłącza; wstrzymuje tylko admin z powodem -->

Decyzja Artura z 26.10.2026. Ludzie nie wyłączali sobie maili (na kopii
produkcji z 22.10 żadne z 38 aktywnych kont), a maile o sprawach, na które ktoś
czeka, i tak nie dochodziły: rodzaje dodane 22.10 nie miały wpisu w polityce
firmy. W 14 dni 47 wpisów o rozmowach u klienta, 29 „Klient zaakceptował”
i 29 „Nowy kontraktor bez zamówienia” nie wyszło mailem ani razu.
Makiety i macierz ról: https://claude.ai/artifact/PPYRVzq7cKrskFgPZdYqrJ.

## Które

`notification_delivery.REQUIRED_KINDS`: nowa rekrutacja dla Ciebie, rozmowy
u klienta, CV czeka na przegląd, CV wróciło do poprawy, klient zaakceptował,
zatrudniony bez zamówienia albo umowy, prośba o potwierdzenie podpisu B2B,
alerty klientów i umów, „Czas i ludzie”, masowe przeglądanie CV, awaria
automatu. Poranny skrót, wzmianki, czat, terminy rekrutacji i zmiany etapów
zostają do wyłączenia przez konto. Nowy rodzaj obowiązkowy = wpis
w `REQUIRED_KINDS`; test pilnuje, że to rodzaj z katalogu.

## Jak działa

- **Włącza się sam przy starcie** (`ensure_required_kinds` w lifespanie,
  czysta reguła `with_required_kinds`): rodzaj obowiązkowy, który nie jest
  włączony i którego admin nie wstrzymał, dostaje `email_enabled` i próg
  `send_not_before` = chwila startu. Zaległości nie wychodzą. Globalny
  wyłącznik „cała firma” zostaje decyzją admina — przy nim nic się nie włącza.
- **Konto nie może go wyłączyć**: `email_opted_out` i `email_wanted` zwracają
  „chce”, `email_queue_clause` daje `true()`, stary wpis w `email_opt_outs`
  nic nie znaczy. `PUT /api/users/me/email-notifications/{rodzaj}` z
  `enabled: false` = 409. W „Moje konto” przełącznik jest zablokowany
  i włączony, z kłódką i zdaniem „przychodzi zawsze, bo ktoś czeka na Twój ruch”
  (ten sam wzorzec co kategorie obowiązkowe dzwonka).
- **Wyciszona kategoria dzwonka go nie zatrzymuje.** Reguła
  `notification_access.user_can_receive_required_mail` (bez wyciszeń osoby)
  działa w dwóch miejscach: `notification_triggers.emit` zapisuje wiersz także
  przy wyciszonej kategorii, gdy typ idzie mailem obowiązkowym, ale bez dymka
  na WebSocket (dzwonek i tak go nie pokazuje), a kolejka
  `notification_email_outbox._can_receive` wysyła z niego mail. Bez zmiany
  w `emit` wiersza by nie było i mail by nie wyszedł (przegląd kodu 26.10).
  Grupa wyłączona dla roli przez admina („Kto co dostaje”) i brak sekcji —
  nadal zatrzymują, także w „Moje konto” (stan `role_muted`).
- **Wstrzymuje tylko admin, dla całej firmy, z powodem**: `PUT
  /api/settings/notification-delivery` z wyłączonym rodzajem obowiązkowym bez
  `reason` = 422. Powód i chwila leżą w polityce (`paused_reason`,
  `paused_at`), trafiają do Historii zdarzeń i do zdania w „Moje konto”.
  Wstrzymanego rodzaju start nie włącza z powrotem; włączenie zdejmuje powód.
- **Uwaga przy alertach DL-a**: `dl_alerts` nie ma limitu wieku jak kolejka
  (24 h), więc konto, które kiedyś wyłączyło `delivery_alert`, dostałoby po
  wdrożeniu stare alerty. Na kopii produkcji z 22.10 nikt nie miał żadnego
  wpisu w `email_opt_outs`.

## Czego tu nie ma (osobne PR-y z planu 26.10)

- Przyciski z gotową akcją w mailu — zrobione 26.10.2026,
  `maile-z-przyciskami-akcji.md`.
- Nowe maile: „Nowa rekrutacja u Twojego klienta” dla DL-a i „Masz nową
  premię” — bez kwoty (decyzja Artura 26.10.2026).
