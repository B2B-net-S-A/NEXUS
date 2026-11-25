# Rotacja klucza szyfrowania danych (`M365_TOKEN_ENCRYPTION_KEY`) bez utraty danych
<!-- indeks: MultiFernet, M365_TOKEN_ENCRYPTION_KEY_PREVIOUS tylko do odczytu, keep_old_value_in w „Coolify set env”, app.cli.token_cipher_rotate, skróty HMAC rachunku i PESEL-u, sync M365 wyłącza skrzynkę z nieczytelnym tokenem, kolejność kroków, po B2 klucz najpierw do odczytu, kopie bazy sprzed rotacji -->

Od 25.11.2026 (decyzja Artura) klucz da się zmienić bez odłączania skrzynek
i bez utraty danych płacowych. Wcześniej zmiana klucza unieważniała każdy
zaszyfrowany wiersz, a runbook kazał kasować `m365_connections`.

## Co chroni ten klucz

Szyfrowanie (`app/core/encryption.py`, `get_token_cipher()`), pełna lista
w `FERNET_COLUMNS` w `app/cli/token_cipher_rotate.py`:

- `m365_connections.access_token_ct`, `refresh_token_ct` — skrzynki M365,
- `candidate_invite_links.token_ct` — sekret linku zaproszenia (lista linków),
- `employee_billing_details.account_encrypted` — rachunek do przelewu,
- `payroll_person_data.data_encrypted` — PESEL i dane do ZUS/PIT,
- `integration_webhooks.secret_ct`, `job_board_connections.*_token_ct`.

Skróty HMAC z kluczem wyprowadzonym z tego sekretu (`HMAC_COLUMNS`):
`payroll_person_data.pesel_hmac` (unikalność PESEL-u), `account_hmac`,
`payroll_list_lines.payee_hmac` (plik przelewów listy płac),
`payroll_payments.counterparty_hmac` (paczka przelewów rozliczeń).

Nowa kolumna szyfrowana tym kluczem albo nowy skrót = wpis w rejestrze
skryptu. Pilnuje tego `tests/test_token_cipher_rotate.py` po nazwach kolumn
modeli (`*_ct`, `*_encrypted`, `*_hmac`), bo kolumna spoza rejestru po
rotacji przestaje się czytać.

## Jak kod obsługuje kilka kluczy

- `M365_TOKEN_ENCRYPTION_KEY` szyfruje wszystko. `M365_TOKEN_ENCRYPTION_KEY_PREVIOUS`
  (lista po przecinku) tylko odszyfrowuje (`MultiFernet`).
- Skrót zapisuje się bieżącym kluczem, a porównanie bierze wszystkie
  (`TokenCipher.fingerprints`): PESEL sprawdza `pesel_hmac IN (…)`, paczka
  przelewów `_same_account`, plik przelewów listy płac `payee_hmac`. Formuła
  skrótu dla bieżącego klucza jest ta sama co przed 25.11, więc zapisane skróty
  pasują bez przeliczenia.
- Zły format któregokolwiek klucza zatrzymuje całe szyfrowanie
  (`TokenCipherNotConfigured`, w `/api/health` `checks.m365_encryption: unhealthy`).

## Dlaczego kolejność kroków jest ważna

`tasks/microsoft365_sync.py` przy `TokenCipherNotConfigured` wyłącza połączenie
(`is_active=False`, `token_cipher_unreadable_user_must_reconnect`) i właściciel
musi połączyć skrzynkę od nowa. Jeden przebieg synchronizacji po wdrożeniu bez
starego klucza do odczytu wyłącza więc wszystkie skrzynki (25.11.2026 było ich 25),
a dane płacowe odpowiadają 503. Dlatego workflow „Coolify set env”:

- odrzuca zmianę `M365_TOKEN_ENCRYPTION_KEY` bez
  `keep_old_value_in=M365_TOKEN_ENCRYPTION_KEY_PREVIOUS`; z nim najpierw
  dopisuje obecną wartość na początek listy poprzednich kluczy, potem zapisuje
  nowy klucz — wartość przechodzi z API do API, nie przez log ani laptop;
- odrzuca wartość, która nie jest kluczem Fernet (44 znaki, 32 bajty), i pusty
  klucz bieżący.

Testy: `test_public_actions_log_hygiene.py` (`test_set_env_keeps_the_old_encryption_key_for_reading` i sąsiednie).

## Procedura (backend w compose, stan z 25.11.2026)

Wszystko w oknie wdrożeń (`deploy.md`). W compose Coolify zatrzymuje wszystkie
kontenery przed startem nowych, więc stary i nowy klucz nie żyją w dwóch
kontenerach naraz. Każdy Deploy to przerwa API ok. 1,5 min.

1. **Stan przed:** `prod_readonly.py health` (`m365_encryption`, `m365`), liczby
   połączeń M365 po `is_active` i `last_sync_status`, w kontenerze backendu
   `python -m app.cli.token_cipher_rotate` (na sucho). Zapisz `unreadable` —
   wartości, których nie czyta żaden klucz, są stare i zostaną nieczytelne.
2. **Nowy klucz prosto do sekretu repo**, nigdy na ekran:
   `python3 -c 'import base64,os,sys; sys.stdout.write(base64.urlsafe_b64encode(os.urandom(32)).decode())' | env -u GH_TOKEN gh secret set M365_TOKEN_ENCRYPTION_KEY_VALUE --repo B2B-net-S-A/NEXUS`
   (tak samo generuje klucz `Fernet.generate_key()`). Sekret zostaje jako kopia
   bieżącego klucza do odtworzenia zmiennej workflowem.
3. **Odcisk zmiennych na serwerze przed zmianą** (skrypt odcisków z rotacji
   sekretów, wypisuje tylko „zmienił się: tak/nie”).
4. **„Coolify set env”**: `key=M365_TOKEN_ENCRYPTION_KEY`,
   `value_from_secret=M365_TOKEN_ENCRYPTION_KEY_VALUE`,
   `keep_old_value_in=M365_TOKEN_ENCRYPTION_KEY_PREVIOUS`, `redeploy=false`.
5. **Deploy** (ręczny, `force_rebuild=false` wystarcza: zmienna jest nowsza niż
   ostatnie wdrożenie). Po nim `checks.m365_encryption: healthy`.
6. **Przeszyfrowanie** w kontenerze backendu (rola `web`):
   `python -m app.cli.token_cipher_rotate` (na sucho: `previous` = liczba wierszy
   do przeszyfrowania), potem `--apply`. Wynik to same liczby; kod wyjścia 0
   i `ready_to_drop_previous: true` = nic nie jest czytelne tylko starym kluczem,
   `unreadable` jak w kroku 1. `conflict` > 0 (ten sam PESEL u dwóch osób)
   albo `previous_only` > 0 = stop, stary klucz zostaje, sprawa do Artura.
7. **Skrzynki:** te same liczby połączeń co w kroku 1, bez nowego
   `token_cipher_unreadable_user_must_reconnect`.
8. **Usunięcie starego klucza:** „Coolify set env” z
   `key=M365_TOKEN_ENCRYPTION_KEY_PREVIOUS`, pustą wartością, `redeploy=false`,
   potem Deploy. Po nim skrypt na sucho: `previous_keys: 0`, `unreadable` jak
   w kroku 1; health jak w kroku 5; odcisk: klucz bieżący zmieniony, lista
   poprzednich pusta.

## Po etapie B2 (backend i worker z rolling update)

Przy nakładaniu kontenerów (`nakladanie-kontenerow-backendu.md`) stary worker
chodzi jeszcze kilka minut ze starym kluczem i nie czyta tokenów, które nowy
kontener zapisał nowym — wyłączyłby skrzynki. Wtedy przed krokiem 4 osobne
wdrożenie z nowym kluczem tylko do odczytu: „Coolify set env”
`key=M365_TOKEN_ENCRYPTION_KEY_PREVIOUS`,
`value_from_secret=M365_TOKEN_ENCRYPTION_KEY_VALUE`, Deploy. Krok 4 zostawia na
liście poprzednich kluczy tylko stary klucz (nowy usuwa z niej sam workflow).

## Kopie bazy sprzed rotacji

Nocne zrzuty (14 dni, `backup-bazy-0630-utc.md`) z dni przed rotacją mają dane
zaszyfrowane starym kluczem. Odtworzone po usunięciu starego klucza dają
skrzynki M365 do ponownego połączenia, linki zaproszeń bez adresu na liście
(działają dalej po skrócie SHA-256) i nieczytelne dane płacowe. Czy stary klucz
zostaje gdzieś do wygaśnięcia ostatniej takiej kopii, decyduje Artur przy
każdej rotacji, bo zależy to od tego, ile danych płacowych jest w bazie.
