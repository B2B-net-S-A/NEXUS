# Kontrakty i Zamówienia: lista z panelem (wersja B, 29.09.2026)

Zgłoszenie Anny („wszystko jest gigantyczne"), makieta B wybrana przez zespół:
https://claude.ai/artifact/4kiwKRJxukyHVYmWdydUoS. `/contracts` (rejestr, „Obsługa
kontraktorów", rejestr klienta) i zakładka „Zamówienia" klienta to zwarta tabela;
klik w wiersz otwiera panel szczegółów po prawej. **Okna z formularzami i backend
się nie zmieniły** — panel otwiera TE SAME okna co dawne karty.

- **Klocki:** `ds/ListDetailLayout` (≥ 1600 px panel obok tabeli, 768–1599 px
  nachodzi na tabelę z prawej — `fixed`, 400 px — i nie ściska kolumn, < 768 px cały
  ekran; trzy ROZŁĄCZNE zakresy `max-md:` / `md:max-[1599px]:` / `min-[1600px]:`,
  bo Tailwind v4 nie gwarantuje, że `min-[1600px]:w-auto` wygra z `md:w-[400px]`),
  `ds/DetailPanel` (nagłówek, zakładki, treść w kolumnie `minmax(0,1fr)`, stopka
  akcji), `hooks/useRowNavigation` (↑/↓, `rowActivationProps` — klik w link,
  przycisk, kwadracik albo portal nie otwiera panelu), `lib/url-selection.ts`,
  `lib/panel-escape.ts` (Esc nie zamyka panelu przy otwartym oknie, menu ani w polu).
- **Zaznaczenie żyje w adresie:** kontrakty `?contract=`; zamówienia `?group=`,
  `?order=` (linia MD albo zamówienie okresowe — jedno id `ClientOrder`) i `?contract=`
  (karta szkicu). To te same parametry, które niosą linki zapisane w bazie (alerty DL,
  braki zamówień, wygasanie) — link otwiera panel od razu; brak celu = toast.
- **Nie przywracaj kart.** Panele: `contracts/ContractSidePanel.tsx` (bramki
  z `lib/contract-access.ts`, wspólne ze stroną kontraktu; status przez
  `ContractStatusControl`), `OrderGroupPanel`, `OrderLinePanel` (zużycie MD w
  `LineConsumptionTable`, bez osobnego okna), `ContractorOrderPanel` (logika dawnej
  karty okresowej bez zmian w zachowaniu; „Zakończ współpracę" z bramką ról jak na
  stronie kontraktu).
- **Nic nie zginęło — pilnuje test:** `lib/orders-contracts-feature-inventory.json`
  (88 funkcji z makiety, plik + marker) i `lib/__tests__/orders-contracts-feature-parity.test.ts`.
  Przeniesienie funkcji = zmiana `file`; usunięcie wpisu tylko z `removed_reason`.
- Harness `/preview/client-orders` (`?group=501`, `?order=5015`, `?contract=813`),
  `/preview/contracts-consolidation`.
