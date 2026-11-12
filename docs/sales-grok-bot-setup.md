# Grok Bot dla Sprzedaży: konfiguracja rutyny i próba

Reguły kanału: `docs/claude/sprzedaz/sygnaly-grok-bot.md`. Ten plik mówi, co ustawić
po stronie bota i jak sprawdzić, że rutyna sama odsyła raport. Klucze wpisujesz
tylko w ustawieniach bota i w sekretach repo, nigdy w czacie bota ani w plikach.

## Dwa poświadczenia, żadnego stałego klucza NEXUSA u bota

- **NEXUS → bot:** klucz webhooka rutyny (`crsr_…`, nagłówek `Authorization: Bearer`)
  i jej adres (`https://api2.cursor.sh/automations/webhook/<id rutyny>`). Daje je
  Grok Bot, trafiają do NEXUSA jako `GROK_BOT_WEBHOOK_KEY` i `GROK_BOT_WEBHOOK_URL`.
- **Bot → NEXUS:** jednorazowy token biegu. NEXUS sam go losuje przy każdym biegu
  i wysyła w treści webhooka (`token`, `callback_url`), a treść webhooka jest wejściem
  biegu, które bot czyta. Stałego klucza API NEXUSA bot nie dostaje, bo Vault bota
  wypełnia tylko pola na stronach (nie podstawia wartości do `curl`), więc stały klucz
  leżałby jawnie w czacie albo w plikach bota, widoczny dla modelu i każdego bota na
  koncie. Token biegu działa raz i najwyżej 2 godziny, więc jego widoczność nie szkodzi.

Źródła (09.11.2026): docs.x.ai/grok-bot/approvals-security-and-privacy, opis webhooków
rutyn (hookdeck.com, „Using Hookdeck with Grok Bot”), forum.cursor.com: wątki
„Webhook-triggered Grok Bot routine should count as user intent…” (27.08.2026)
i „Webhook credentials; in-app links” (09.10.2026).

## 1. Rutyna w Grok Bocie (konto Artura)

1. Nowa rutyna z wyzwalaczem **„When a webhook fires”**. Adres, klucz i nagłówek
   pokazuje **tylko aplikacja desktopowa** Grok Bota (Mac, Windows, Linux), nie
   telefon: otwórz rutynę z linii „Created routine” w czacie, gdzie ją założyłeś,
   i skopiuj pola kliknięciem. Od razu wpisz je jako sekrety repo (krok 2), nie do
   czatu ani notatek.
2. **Zgoda na wysyłkę do NEXUSA.** Auto Review ocenia wychodzące żądanie w biegu
   z webhooka według ostatniej rozmowy w czacie bota, a nie według polecenia rutyny,
   i może je zatrzymać kartą zgody (zgłoszenie na forum z 27.08.2026, bez poprawki).
   Karta z biegu w tle wygasa po 30 minutach. Przy pierwszej karcie dla
   `POST https://api.nexus.dynaminds.pl/api/integrations/sales-signals/runs/…` wybierz
   **„Always allow”**, co zapisze regułę Allow (limit 20 reguł, najstarsza wypada).
   Wbudowanych kontroli bota reguła nie wyłącza, więc dopiero próba z kroku 3 pokaże,
   czy bieg przejdzie bez człowieka.
3. Polecenie rutyny (treść do wklejenia):

```text
Dostajesz w wejściu webhooka JSON z polami: run_id, kind ("signals" albo "briefing"),
callback_url, token, expires_at, window_days, max_signals, max_points, signal_types,
firms (ref, name, domain, opcjonalnie mode), rejected (ref, title, reason), seen_urls.

Dla każdej firmy z listy firms zrób research: strona firmy i jej strona kariery,
komunikaty prasowe, prasa branżowa, serwis X. Nie otwieraj portali z ogłoszeniami
o pracę ani LinkedIna. Bierz tylko informacje opublikowane w ostatnich window_days
dniach. Każdą informację potwierdź otwarciem źródła i podaj jego adres i datę.
Nie zapisuj nazwisk osób prywatnych ani danych kontaktowych.

Gdy kind = "signals": szukaj sygnałów, że firma może potrzebować specjalistów IT
z zewnątrz (zatrudnianie, restrukturyzacja, nowy program, kontrakt, inwestycja,
zmiana zarządu). Pomiń adresy z seen_urls i tematy podobne do rejected.
Siła: strong tylko gdy źródło wprost mówi o potrzebie ludzi do projektu IT,
medium gdy to rozsądny wniosek, weak gdy to tylko temat do wzmianki.

Gdy kind = "briefing": dla każdej firmy przygotuj od 1 do max_points krótkich
punktów, do których handlowiec może nawiązać w rozmowie. mode = "first_call":
co się dzieje w firmie ogólnie; mode = "ongoing": zmiany od ostatnich tygodni,
które mogą dotyczyć prowadzonego tematu. Gdy przy mode = "ongoing" nie ma nic
nowego, nie dopisuj punktów na siłę: wpisz firmę do no_signal.

Na koniec wyślij JEDNO żądanie:
POST {callback_url}
Content-Type: application/json
X-Run-Token: {token}
z treścią:
{
  "checked_firms": <liczba sprawdzonych firm>,
  "signals": [{"company_ref": <ref>, "type": <jedno z signal_types>,
               "title": "...", "summary": "...", "why_now": "...",
               "url": "https://...", "published": "RRRR-MM-DD",
               "strength": "strong|medium|weak"}],
  "briefings": [{"company_ref": <ref>,
                 "points": [{"text": "...", "url": "https://...", "published": "RRRR-MM-DD"}]}],
  "no_signal": [<ref firm bez sygnału>]
}
Nie dodawaj innych pól. Najwyżej max_signals sygnałów. Token jest jednorazowy
i ważny do expires_at; nie zapisuj go w plikach.
```

## 2. Ustawienia w NEXUSIE

Wyłącznie workflow „Coolify set env” (sekrety repo wpisuje Artur):

| Zmienna | Wartość |
|---|---|
| `GROK_BOT_WEBHOOK_URL` | adres webhooka rutyny (`https://api2.cursor.sh/automations/webhook/…`) |
| `GROK_BOT_WEBHOOK_KEY` | klucz webhooka `crsr_…` (sekret repo, wpisuje Artur) |
| `SALES_SIGNALS_TAG` | tag firm pilota, domyślnie `sygnały` |
| `SALES_SIGNALS_ENABLED` | `false` do udanej próby, potem `true` |

Firmy pilota: tag `sygnały` na karcie firmy i opiekun firmy ustawiony na handlowca,
który ma dostać sygnał w „Moim dniu” (bez opiekuna sygnał jest tylko w Leadach).

## 3. Próba (ok. 30 minut)

1. Z ustawionym adresem i kluczem, przy wyłączonej fladze, w kontenerze backendu:
   `python -m scripts.sales_signals_run --kind signals --company-ids <id1>,<id2>,<id3>`
   Wynik `{"started": true, "status": "started", ...}` znaczy, że webhook przyjął bieg
   (Grok odpowiada `200` z `runUuid` od razu, nie czekając na koniec biegu).
   `failed` z `webhook HTTP 401` to zły klucz, `400` to wyłączona rutyna.
2. Poczekaj na koniec rutyny w bocie, nie klikając zgód.
3. Sprawdź bieg (read-only): `SELECT status, error, report->>'leads' FROM sales_signal_runs ORDER BY id DESC LIMIT 1;`
   - `received`: bot sam odesłał raport. Można włączyć flagę.
   - `started` po 2 godzinach przechodzi w `expired` (ostrzeżenie w logu `worker`):
     rutyna czekała na zgodę albo nie umiała wysłać żądania. Popraw krok 1.2.
   - `failed`: webhook odrzucił start (`error` mówi, jaki kod HTTP).
4. Powtórz z `--kind briefing` dla jednej firmy z otwartą szansą.
