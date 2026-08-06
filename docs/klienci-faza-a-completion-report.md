# Faza A ticketów Klienci — completion report

> Realizacja „szybkich wygranych" z 5 ticketów pracownika (analiza:
> [klienci-tickety-analiza.md](klienci-tickety-analiza.md), weryfikacja audytu Codexa:
> [klienci-tickety-weryfikacja-codex.md](klienci-tickety-weryfikacja-codex.md)).
> Data: 2026-08-06. **Status: WDROŻONE + smoke-tested na prod (`304e146`).**

## Zakres zrealizowany

### PR #1051 — Zamówienia (tickety #2 + #4 pkt 2/3 + bugi z weryfikacji)
`feat(orders): wyszukiwarka zamówień, sprzątanie kart i poprawki stawek`

- **Wyszukiwarka** w Klienci → Zamówienia (`OrdersAndContractsTab`): debounce 300 ms,
  diacritic-insensitive (`foldText`), dopasowanie po nazwisku konsultanta ORAZ numerze
  **każdego** zamówienia (aktywne/przyszłe/historia). Działa w ramach aktywnej piguły
  statusu; trafienie w historii **wymusza rozwinięcie** sekcji; osobny empty state.
  Założenie „endpoint bez paginacji → filtr FE bezpieczny" przypięte komentarzem.
- **Sprzątanie kart:** usunięte „Contract #\<id\>", „z rekrutacji: …" i „Job: …"
  (historia). Info o rekrutacji zostaje w Profil → Obecni konsultanci (to samo źródło).
- **Bug `0`-jako-brak:** `or` → `is not None` w `_compute_monthly_margin`
  i `latest_order_rate_client` — stawka 0 na zamówieniu nie spada już po cichu do
  stawki kontraktu (marża liczona z 0).
- **Etykieta jednostki stawki:** nowe pole `rate_unit` w `ContractWithOrdersRead`
  (jednostka ≠ kwota → bez redakcji finansowej); FE etykietuje `/h`, `/dzień`, `/mc`
  wg jednostki kontraktu zamiast hardkodu „/mc" (Alior ma stawki godzinowe). Marża
  zostaje `/mc` (normalizowana miesięcznie na BE).
- **Spłata długu CI:** `tests/test_dl_portal.py` zdjęty z `--ignore`
  (naprawione: `lastname` NOT NULL w helperze kandydata, FK `activities` przy
  cleanup userów, stęchłe asercje liczbowe na polach Decimal) — 15/15, plik znów
  chroni endpointy DL portalu. Kontrakt pokrycia zaktualizowany.

### PR #1052 — Klient: nazwa → `display_name` (ticket #1 bug 4) + gating
`fix(clients): edycja nazwy klienta zapisuje sync-odporny display_name`

- **Root cause bugu „nazwa się nie zapisuje":** formularz pisał do `Client.name`,
  które (a) przegrywa w wyświetlaniu z `display_name`
  (`coalesce(nullif(btrim(display_name),''), name)`) i (b) jest nadpisywane przez
  daily sync Traffita.
- **Backend:** `ClientUpdate.display_name` (+ walidator `""`/whitespace → `None`);
  `update_client` zwraca `_serialize_client(...)` — odpowiedź PATCH pokazuje nazwę
  efektywną, spójnie z GET.
- **Frontend (decyzja: jedno pole):** `EditClientModal` nie wysyła już `name`;
  `display_name` idzie **tylko przy faktycznej zmianie** (dirty-check — bez niego
  każda edycja np. branży zamroziłaby nazwę względem Traffita); wyczyszczenie pola →
  `null` → powrót nazwy źródłowej (hint w formularzu). `ClientFormFields` dostał
  prop `nameRequired` (Add wymaga, Edit nie).
- **Gating:** capability `client.update` (TacPlus) + bramka przycisku „Edytuj" —
  nie-TAC nie widzi już przycisku wiodącego w 403.
- **Invalidacja:** po edycji dodatkowo `clients-directory` — nazwa od razu na liście.

## Testy / weryfikacja

| Warstwa | Wynik |
|---|---|
| FE `tsc --noEmit` + `next lint` | ✓ czysto (oba PR-y) |
| FE vitest | PR1: 27/27 (`OrdersAndContractsTab` + `ExtendOrderDialog`); PR2: 175/175 (w tym nowe `EditClientModal.test.tsx` 3, macierz capabilities) |
| BE ruff `check` + `format --check` | ✓ (obie bramki) |
| BE pytest (docker, alembic heads) | PR1: `test_dl_portal` 15/15, `test_reaudit_backend_guards` 11/11, `test_ci_coverage_contract` 3/3; PR2: `test_client_update` 4/4 (nowy, w tym kontrakt „PATCH name ignorowane"), `test_client_directory` 18/18 |
| Deploy + smoke UI | ✅ oba PR-y wdrożone (`c8b2517` → `304e146`, `/api/health` healthy) + smoke klikaniem przez Chrome — szczegóły niżej |

## Wyniki smoke na produkcji (2026-08-06, wersja `304e146`)

**PR #1051 — Zamówienia:**
- Wyszukiwarka: „izdeb" zawęża 9 kart do 1 (Centrum e-Zdrowia); częściowy numer
  zamówienia „RITM0813" zawęża 47 kart do 1 (BNP Paribas, order „…RITM0813656");
  pusty stan „Brak zamówień pasujących do wyszukiwania." (≠ „brak kontraktorów").
- Karty: brak „Contract #", brak „z rekrutacji"/„Job:".
- Jednostki stawek: Centrum e-Zdrowia `115/h`, Bank Pocztowy `100/h`–`165/h`,
  BNP Paribas `50/h`–`125/h` — trzej klienci godzinowi pokazują `/h` zamiast
  błędnego `/mc`; znormalizowana marża w Profilu dalej `/mc` (bez regresji).
- Stawka przychodowa: placeholder „ustaw stawkę" obecny na każdej karcie z zamówieniem.

**PR #1052 — nazwa klienta** (na kontrolowanym rekordzie testowym, po teście usuniętym):
- Modal edycji: pole „Nazwa firmy" bez gwiazdki + hint „Wyczyść pole, aby przywrócić
  nazwę źródłową"; Add nadal wymaga nazwy.
- Zmiana nazwy → persystuje po pełnym przeładowaniu strony (nagłówek + breadcrumb) —
  to był zgłoszony bug.
- Wyczyszczenie pola → zapis przechodzi → nazwa wraca do źródłowej (display_name→NULL).
- Review-hardening: `name` usunięte z `ClientUpdate` (surowe API nie odtworzy buga).
- Bramka „Edytuj" dla nie-TAC: pokryta testami jednostkowymi (macierz capabilities
  175/175) — na prod dostępna była tylko sesja admina.
- Bonus obserwacja: nowo utworzony klient testowy miał status **Prospekt** w sekcji
  **Aktywni** — żywe potwierdzenie tezy analizy (sekcja = `scope.category` ≠ status).

## Świadomie POZA zakresem (Faza B/C)

- **Masowy backfill statusów — ODRZUCONY** (sekcje sterowane `ClientPortfolioScope.category`, nie `Client.status`; fix statusów nic by nie przeniósł i cofnąłby się na Traffit).
- Sekcje vs status (decyzja produktowa), ochrona `status` przed sync Traffita.
- Usunięcie listy „Otwarte rekrutacje" — wymaga wcześniejszego przeniesienia akcji `CloseJobAsLostModal` (jedyny caller `POST /jobs/{id}/close`).
- `project_part` dla Centrum e-Zdrowia (#3) — najpierw scalenie duplikatów klienta (id 115/5257) i bramka po `client_id`.
- Epic „Zakończenie projektu" (#5) — dwukierunkowy serwis sync Contract↔Order.
- Drobne bugi z weryfikacji do wzięcia przy #5: duplikat `Activity('terminated')`, `required` na dacie terminacji, limit 100 archiwum, snapshot stawki historycznej, granica dnia Warsaw.

## Znane ograniczenia

- Wyszukiwarka filtruje po stronie FE — bezpieczne, dopóki `GET /orders` zwraca pełną
  listę; przy wprowadzeniu paginacji przenieść do `?q=` (komentarz w kodzie).
- Diakrytyki: fold obejmuje NFD + `ł→l` (współdzielony `foldText`).
- `rate_unit` w typie FE jest wymagany — starsze zserializowane cache klienta mogą go
  nie mieć do czasu refetch (nieszkodliwe: fallback `?? "monthly"` w helperze etykiety).
