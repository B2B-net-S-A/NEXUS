# Decyzja Delivery Leada po zakończeniu współpracy konsultanta MD

Terminacja kontraktu domyka linię MD (`completed`, `end_date` ucięta do dnia
terminacji) i zakłada sprawę `client_order_offboarding_cases` w stanie
`pending`. Rozstrzygnięcie ma TRZY wartości (migracja `0253`, + lustro DDL
w `entrypoint.sh` — CREATE TABLE dotyczy tylko instalacji od zera, więc
poszerzenie CHECK-a na prodzie WYMAGA jawnego DROP+ADD):

| Decyzja | Co robi z pulą | Co robi z linią |
|---|---|---|
| `remove` | pula per linia przepada (`_reduce_legacy_md_budget`) | osoba znika z aktywnej obsady |
| `transfer` | pula przeliczona na innego konsultanta | jw. + budżet rośnie odbiorcy |
| `restore` | **pula NIETKNIĘTA** | linia wraca na `active`, kontrakt wraca do aktywnych |

- **`restore` powstał, bo bez niego jedynym wyjściem ze sprawy było zapisanie
  decyzji, która się nie wydarzyła.** Zgłoszone przypadki (Płonka 90 MD, Dynek
  120 MD, Krawczyk 85 MD) to współpraca, która trwa dalej — ani nie oddano
  puli, ani jej nikomu nie przekazano.
- **Gałąź `restore` MUSI omijać `_reduce_legacy_md_budget`.** Zdjęcie
  niewykorzystanych MD z wartości zamówienia byłoby zapisaniem faktu, który się
  nie wydarzył, i zabraniem konsultantowi budżetu, na którym właśnie pracuje.
- **Przywrócenie wskrzesza KONTRAKT** (`sync_contract_to_live_order`). Bez tego
  decyzja kasuje samą siebie: konsultant zostaje w „Zakończonych" mimo aktywnej
  linii, a nocny cron widzi `end_date < today`, stawia `ended` i domyka linię
  z powrotem — bez nowej sprawy i bez alertu, bo `_ensure_md_case` trafia
  w istniejący wiersz.
- **Data zakończenia jest DECYZJĄ, nie odtworzeniem.** Oryginalna `end_date`
  linii przepadła przy offboardingu (sprawa snapshotuje pulę, stawki i numer
  zamówienia — nie okres), więc serwer nie ma jej skąd wziąć. Przy zamówieniu
  z datą końca pole jest WYMAGANE i ograniczone do okresu zamówienia; przy
  bezterminowym puste znaczy „bezterminowo". Data z przeszłości jest odrzucana:
  linia ze WSPÓLNEJ puli ma `md_total IS NULL`, więc nie chroni jej
  `sync_md_line_status`, a `dl_portal_expiry_scanner._promote_statuses` domyka
  dokładnie takie linie.
- **Osobny typ zdarzenia `przywrocenie_konsultanta`**, świadomie różny od
  `przywrocenie` (= przywrócenie CAŁEGO zamówienia, `reopen_order_group`).
  Wspólny slug zlałby w historii dwie operacje na dwóch różnych poziomach.
- **Osobny CHECK `ck_..._restore_target`**: dwa istniejące guardy używają
  `IS DISTINCT FROM`, więc trzecia wartość omijała OBA i mogłaby nieść
  `target_order_id`/`rate_basis` bez żadnego ograniczenia.
