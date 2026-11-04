# Konto E2E na produkcji — rola „Automatyzacje”, lista break-glass, sekrety, co znaczy szary bieg

Decyzja Artura z 04.11.2026 (#1551). Jedyny automatyczny test dotykający produkcji
to job `Playwright against production` w `e2e.yml` (projekt `prod-smoke`): nocny
i po każdym udanym Deployu. Do 04.11 nie testował nic, bo konta nie było.

## Rola: `automation`, nic większego

Hasło konta leży w sekretach repo i omija SSO, więc rola jest jedyną ochroną danych,
gdyby wyciekło. „Automatyzacje” to podgląd bez kwot, bez zapisu na ekranach
i bez eksportu, a konto nie dostaje kartoteki HR (`NON_STAFF_ROLES`) ani nie trafia
na listy rekruterów. `e2e/read-only-account.spec.ts` pada, gdy ktoś podniesie kontu
uprawnienia. Nowy przypadek `prod-smoke` ma działać na tej roli. Przypadek z zapisem
albo eksportem dostaje `@stack`, bo produkcja ma być tylko czytana.

Rekruter by nie wystarczył jako „mniejsza” rola: ma zapis i eksport danych osobowych.

## Założenie albo odtworzenie konta

1. **Ustawienia → użytkownicy → „Dodaj użytkownika”**: adres w domenie firmy (alias,
   bez skrzynki osoby), rola „Automatyzacje”, hasło tymczasowe.
2. **Lista break-glass.** `Coolify set env` nadpisuje całą wartość, a na liście
   `PASSWORD_LOGIN_BREAK_GLASS_EMAILS` jest już konto awaryjne (1 adres na
   04.11.2026). Wpisanie samego adresu E2E odcięłoby je, więc nowa wartość to stara
   plus adres E2E, przez sekret, bo inputy workflow są publiczne. `test -n` chroni
   przed nieudanym odczytem: pusta wartość odcięłaby konto awaryjne.

   ```bash
   printf 'Adres konta E2E: '; read -r EMAIL
   CURRENT=$(ssh -i ~/.ssh/nexus_prod_root_ed25519 root@91.99.199.112 'docker exec $(docker ps --format "{{.Names}}" | grep "^backend-ocgkw" | head -1) printenv PASSWORD_LOGIN_BREAK_GLASS_EMAILS')
   printf '%s' "$EMAIL" | env -u GH_TOKEN gh secret set E2E_USER_EMAIL --repo B2B-net-S-A/NEXUS
   test -n "$CURRENT" && printf '%s,%s' "$CURRENT" "$EMAIL" | env -u GH_TOKEN gh secret set BREAK_GLASS_EMAILS_VALUE --repo B2B-net-S-A/NEXUS
   ```

3. **W oknie wdrożeń** (`deploy.md`) ustaw zmienną i wdróż:

   ```bash
   env -u GH_TOKEN gh workflow run "Coolify set env" --repo B2B-net-S-A/NEXUS -f key=PASSWORD_LOGIN_BREAK_GLASS_EMAILS -f value_from_secret=BREAK_GLASS_EMAILS_VALUE -f redeploy=true
   ```

4. **Po wdrożeniu** hasło: `bash scripts/e2e_account_set_password.sh`. Skrypt loguje
   się hasłem tymczasowym, zdejmuje wymuszoną zmianę hasła, losuje nowe i zapisuje je
   w `E2E_USER_PASSWORD`, więc nikt go nie widzi. Tak samo przy rotacji.
5. **Próba:** `env -u GH_TOKEN gh workflow run e2e.yml --repo B2B-net-S-A/NEXUS --ref main`.
   W podsumowaniu joba „przypadki wykonane” ma być większe od 0.
6. **Włącznik po deployu:** `env -u GH_TOKEN gh variable set E2E_POST_DEPLOY_ENABLED --repo B2B-net-S-A/NEXUS --body true`.

`E2E_BASE_URL` i `E2E_API_URL` nie są potrzebne: domyślne adresy w `e2e.yml` to
`nexus.b2bnetwork.pl`. Stary front `nexus.dynaminds.pl` odpowiada 200, ale API odrzuca
jego Origin, więc każdy test UI przeciw niemu pada.

## Jak czytać wynik

- **Job `Playwright against production` szary (`skipped`)**: brak sekretów, czyli
  brak testu. Do 04.11 był wtedy zielony przy 0 z 25 przypadków.
- **Zielony**: wykonał co najmniej 1 przypadek. Liczba stoi w podsumowaniu joba;
  `valid login` jest pominięty w trybie SSO-only, bo sesję zakłada setup przez API.
- **Czerwony przy 0 wykonanych**: pominięty setup. Playwright kończy się wtedy kodem 0,
  dlatego `e2e.yml` sam sprawdza liczbę.
- **Czerwony po deployu bez sekretów**: włącznik włączony, sekrety zniknęły. Otwiera alarm.
- Zielony bieg po deployu sam zamyka alarm „E2E po deployu (prod-smoke) jest czerwony”.

## Próba bez produkcji

`prod-smoke` puszczasz na stagingu z laptopa, na koncie `automation` założonym tam przez
`POST /api/admin/users` (token admina z `scripts.staging_login_as`), z
`E2E_BASE_URL=http://localhost:3100` i `E2E_API_URL=http://localhost:8100`. Lokalnie
Playwright zapisuje zrzuty i ślady z kopii produkcji w `frontend/test-results/`,
więc po biegu usuń ten katalog.
