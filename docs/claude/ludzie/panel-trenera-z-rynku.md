# Panel trenera z rynku — osobne wejście, własny włącznik, dane firmy od TCM (0807)
<!-- indeks: trener z rynku, panel trenera, mt_portal_links, mt_portal_sessions, trainer_market_id, market_trainer_portal, otwórz panel trenera, Biała Lista, dane do umowy, /api/public/trainer-portal, #trener= -->

Decyzje Artura z 28.11.2026: trener z rynku z bazy trenerów
(`market_trainer_applications`, status `accepted`, → `integracje/strona-www-trener-i-polecenie.md`)
dostaje **osobne wejście** do panelu. Loguje się tym samym ekranem `/konsultant` co
konsultant, ale widzi tylko „Szkolenia” i „Dane do umowy”. Dane firmy do umowy
szkoleniowej wpisuje **TCM z Białej Listy**. Wejście ma **własny włącznik**,
niezależny od panelu konsultanta (ten 28.11 stał w `internal`).

Kod: `app/services/market_trainer_portal/` (`switch`, `mail`, `auth`, `panel`),
trasy trenera `app/api/market_trainer_portal.py` (`/api/public/trainer-portal`),
trasy TCM i admina w `app/api/trainings.py` (`/market-applications/{id}/panel`,
`/panel/close`, `/market-applications/company-lookup`, `/market-portal`), schemat
`services/market_trainer_portal_schema.py` (migracja 0807). Front: `LoginForm`,
`konsultant/(panel)/layout.tsx`, `konsultant/wejscie`, `PanelNav`,
`MarketTrainerScreen`, `MarketPanelDialog`, `NewTrainingScreen` (`?market=`).
Testy: `tests/test_market_trainer_portal.py`, `portal-screens.test.tsx`,
`market-trainer-candidates.test.tsx`.

## Reguły, które łatwo cofnąć

- **Osobne tabele linku i sesji** (`mt_portal_links`, `mt_portal_sessions`). Token
  trenera nie pasuje do `cp_sessions`, więc nie otwiera żadnej trasy konsultanta,
  a router trenera ma wyłącznie trasy szkoleń (logowanie, `/me`, `/trainer`, własne
  szkolenia i pliki). Nie dopisuj do niego rozliczeń, spraw, rozmów ani biblioteki.
  Pilnuje `test_trainer_session_does_not_open_consultant_routes`.
- **Włącznik `app_settings['market_trainer_portal']` = `{"enabled": bool}`**, brak
  wiersza = wyłączony. Wyłączony: każda trasa trenera 404, żaden mail (także
  powiadomienia o szkoleniu, `notify._send_market`) i brak adresu do zaproszenia
  w Teams; wyłączenie kasuje sesje. Przełącza wyłącznie admin (`PUT /market-portal`),
  TCM widzi stan. Panel można otworzyć przy wyłączonym włączniku, link wtedy nie wychodzi.
- **Panel otwiera TCM tylko trenerowi `accepted`**, z poprawnym NIP-em (suma
  kontrolna), nazwą, adresem i e-mailem logowania. Ponowne otwarcie (poprawka danych,
  nowy adres) zamyka stare sesje i wysyła nowy link. Zamknięcie panelu, wycofanie
  z bazy albo zmiana adresu = sesja pada przy następnym żądaniu. Ten sam adres
  u dwóch trenerów nie otwiera niczego.
- **Szkolenie trenera z rynku** = `trainer_kind = 'consultant'`, `trainer_contract_id
  IS NULL`, `trainer_market_id` = trener (CHECK `ck_trainings_trainer_market`). Cały
  obieg trenera B2B działa bez zmian: wycena A–E, umowa z podpisem kwalifikowanym,
  pliki, faktura, „Zapłacone” od Finansów, biblioteka dopiero po zapłacie. Dane
  strony umowy (`/{id}/partner`) z karty firmy (`panel.partner`), nie z kontraktu.
  Pliki trenera mają `uploaded_by_market_id`.
- **Zamówienie tylko dla trenera z otwartym panelem** (`core.create`, 422
  `market_trainer_not_ready`), inaczej trener nie zobaczyłby zamówienia.
- **Link z maila** to `/konsultant/wejscie#trener=<token>`: fragment, jak u
  konsultanta, a prefiks mówi ekranowi wejścia, którą trasą założyć sesję. Rodzaj sesji
  trzyma `sessionStorage` (`nexus_consultant_portal_kind`); trener na ekranie
  konsultanta wraca do „Szkoleń”.
- Maile do trenera z rynku bez myślników „—” (jak cały panel), log bez adresu i treści.

## Poza zakresem (28.11.2026)

Biblioteka nagrań i zapisy na szkolenia na żywo dla trenera z rynku, samodzielna
zmiana danych firmy przez trenera, umowa premii za polecenie, przepięcie strony
na endpointy zgłoszeń.
