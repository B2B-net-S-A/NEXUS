# Księga NEXUSA K5 (15.11.2026): rejestry VAT, JPK_V7M

Etap K5 planu „Księgowość w NEXUSIE” (https://claude.ai/artifact/U9Z3unvSK62Ff5U36hkaar).
K5a (ten plik): rejestry VAT z dokumentów księgi — kod w
`app/services/ledger/vat.py`, trasy `app/api/ledger_vat.py`, zakładka „VAT”
(`/accounting/vat`), moduł `vat` w Ustawieniach (włącza administrator). Bez
migracji: rejestr liczy się z dokumentów przy każdym otwarciu. JPK_V7M, VAT-UE
i dokument rozliczenia VAT — K5b (osobny dopisek).

## Co jest

- **Okres VAT = okres dokumentu w księdze** (K2): FVS — miesiąc sprzedaży
  (korekta — wystawienia), FVZ — miesiąc wpływu faktury do KSeF. Rejestr to stan
  dziś: dokument ze stornem wypada, jego nowa wersja wchodzi.
- **Rejestr sprzedaży**: zatwierdzone FVS. VAT = obroty Ma − Wn konta VAT
  należnego (Ustawienia → konta faktur sprzedaży), brutto = rozrachunek
  z odbiorcą, netto = brutto − VAT — w PLN z dekretu, czyli po kursie dokumentu.
- **Podział na stawki** (pola JPK_V7M) z pozycji faktury w KSeF (`items`: P_11
  netto, P_12 stawka; wiersz „StanPrzed” korekty ze znakiem minus):
  - jedna stawka = całe kwoty dokumentu;
  - kilka stawek = netto w proporcji pozycji, VAT tylko na stawkach z podatkiem,
    w proporcji netto × stawka (ostatnia grupa bierze resztę groszy);
  - stawka spoza słownika (np. `oo`), pozycje bez stawki, kilka stawek bez netto
    albo korekta zmieniająca stawki = wiersz „do sprawdzenia”, bez podziału.
- **Grupy**: 23% (22%) K_19/K_20, 8% (7%) K_17/K_18, 5% K_15/K_16, 0% w kraju
  K_13, WDT K_21, eksport K_22, zw K_10, `np I` K_11, `np II` (usługi dla
  podatników z UE, art. 100 ust. 1 pkt 4) K_11 i „w tym” K_12. Zakup: środki
  trwałe K_40/K_41 (Wn na koncie przyjęcia z K6), pozostałe K_42/K_43.
- **Rejestr zakupu**: zatwierdzone FVZ z VAT naliczonym w dekrecie (obroty
  Wn − Ma konta VAT naliczonego, moduł VAT — admin; domyślnie 221). Faktura bez
  VAT naliczonego (bez odliczenia) do rejestru nie wchodzi.
- **Do sprawdzenia** (karta i lista zamknięcia „Rejestry VAT”):
  - stawki bez podziału na pola JPK — problem;
  - faktura sprzedaży z KSeF z tego miesiąca bez dokumentu w księdze — problem
    (VAT jest należny, np. od zaliczki, która czeka na regułę zaliczek K3);
  - FVS i FVZ w buforze, faktura kosztowa z wpływem w tym miesiącu bez FVZ
    (kolejka kosztów, bez odrzuconych i proform), zapisy na kontach VAT
    w dokumentach spoza rejestru (PK; bez rozliczenia VAT, wyciągu i BO) —
    do zrobienia.
- Saldo miesiąca = VAT należny − naliczony, **bez nadwyżki z poprzedniego
  okresu** (ta przyjdzie z JPK w K5b).

## Zasady, których łatwo nie zauważyć

- **D2**: faktury osób zespołu widzi tylko Płace i admin. Osoba bez Płac dostaje
  rejestry, sumy i listy „do sprawdzenia” bez nich, a `payroll_hidden` mówi
  tylko, że są — bez liczby (licznik ukrytych pozycji był wyciekiem w K4a).
  JPK (K5b) musi zawierać wszystkie faktury, więc wygeneruje go tylko osoba
  z Płacami albo admin.
- Warunki `NOT IN (podzapytanie)` na kolumnie, która bywa NULL, zawsze z `IS
  NULL` wprost (`source_type`, `reverses_id`) — inaczej warunek daje NULL
  i wiersz po cichu wypada (przegląd K4c-2).
- Konto VAT należnego jest jedno dla dekretu FVS i rejestru
  (`sales.vat_account`); konto naliczonego — `vat.input_account`. Analityka
  (`221-1`) należy do konta, `2210` — nie.

## Testy

`tests/test_ledger_vat_rules.py` (podział stawek, kwoty z dekretu, pola JPK,
pozycja listy zamknięcia), sekcja K5a w `tests/test_ledger_sources_db.py`
(rejestry z FVS/FVZ fixture `books`: 23%, EUR `np II`, korekta, faktura osoby
zespołu — D2, brak FVS dla zaliczki i nabywcy spoza kartoteki, PK na koncie VAT,
lista zamknięcia; ustawienia i bramki), wzorzec `tests/data/authz_golden/ledger_vat.json`,
front: `VatView.test.tsx`, `vat-model.test.ts`.
