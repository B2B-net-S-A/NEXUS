# Księga NEXUSA K5 (15.11.2026): rejestry VAT, JPK_V7M

Etap K5 planu „Księgowość w NEXUSIE” (https://claude.ai/artifact/U9Z3unvSK62Ff5U36hkaar).
K5a: rejestry VAT z dokumentów księgi — kod w `app/services/ledger/vat.py`,
trasy `app/api/ledger_vat.py`, zakładka „VAT” (`/accounting/vat`), moduł `vat`
w Ustawieniach (włącza administrator). Bez migracji: rejestr liczy się
z dokumentów przy każdym otwarciu. K5b-1: plik JPK_V7M(3) — `ledger/jpk.py`,
migracja `0708_ledger_vat_files` (sekcja niżej). VAT-UE, zakupy zagraniczne
i dokument rozliczenia VAT — dalsze części K5b.

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
    albo korekta zmieniająca stawki = wiersz „do sprawdzenia”, bez podziału —
    ale **z kwotami z dekretu w sumach** (inaczej „do zapłaty” rozjeżdża się
    z kontem VAT należnego; przegląd K5a).
- **Grupy**: 23% (22%) K_19/K_20, 8% (7%) K_17/K_18, 5% K_15/K_16, 0% w kraju
  K_13, WDT K_21, eksport K_22, zw K_10, `np I` K_11, `np II` (usługi dla
  podatników z UE, art. 100 ust. 1 pkt 4) K_11 i „w tym” K_12. Zakup: środki
  trwałe K_40/K_41 (Wn na koncie przyjęcia z K6), pozostałe K_42/K_43.
- **Rejestr zakupu**: zatwierdzone FVZ z VAT naliczonym w dekrecie (obroty
  Wn − Ma konta VAT naliczonego, moduł VAT — admin; domyślnie 221). Faktura bez
  VAT naliczonego (bez odliczenia) do rejestru nie wchodzi. Środek trwały =
  ruch netto na koncie przyjęcia (K6), nie strona — korekta zakupu środka też
  jest K_40/K_41.
- **FVZ z VAT należnym** (ręczny dekret E2: import usług, odwrotne obciążenie):
  netto = brutto od dostawcy (sprzedawca nie doliczył VAT), VAT naliczony
  w rejestrze zakupu, a VAT należny jako wiersz rejestru sprzedaży bez pola JPK
  („do sprawdzenia” — pole K_27–K_32 przypisze K5b). Bez tego nadwyżka
  naliczonego była zawyżona o ten VAT. FVS z VAT naliczonym — wiersz do
  sprawdzenia.
- **Do sprawdzenia** (karta i lista zamknięcia „Rejestry VAT”):
  - stawki bez podziału na pola JPK — problem;
  - faktura sprzedaży z KSeF z tego miesiąca bez dokumentu w księdze — problem
    (VAT jest należny, np. od zaliczki, która czeka na regułę zaliczek K3);
  - FVS i FVZ w buforze, faktura kosztowa z wpływem w tym miesiącu bez FVZ
    (kolejka kosztów, bez odrzuconych i proform), zapisy na kontach VAT
    w dokumentach spoza rejestru (PK; bez rozliczenia VAT, wyciągu i BO;
    dokument ze stornem i samo storno się znoszą) — do zrobienia.
- Saldo miesiąca = VAT należny − naliczony, **bez nadwyżki z poprzedniego
  okresu** (ta przyjdzie z JPK w K5b).

## Decyzje Artura do K5b (15.11.2026)

- **Zakupy zagraniczne bez KSeF** (import usług: LinkedIn, Google, Microsoft,
  Cognism) — ręcznie w Księgowości: formularz w zakładce VAT (sprzedawca, kraj,
  nr VAT UE, kwota w walucie, kurs NBP z dnia przed, VAT 23% po obu stronach) →
  dokument w buforze, rejestr i JPK. Kolejka kosztów E2 zostaje tylko z KSeF.
- **Schematy XSD JPK_V7M(3)** z crd.gov.pl w repo (dane testowe) — walidacja
  w testach i przed pobraniem pliku.

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

## JPK_V7M(3) (K5b-1)

- **Struktura**: wzór 2025/12/19/14090 (crd.gov.pl), obowiązuje od rozliczenia
  za luty 2026. Schematy XSD w `app/services/ledger/jpk_schema/` (pobrane
  15.11.2026 za zgodą Artura; w `schemat.xsd` adresy importów przepisane na pliki
  obok, reszta bajt w bajt) — walidacja przy każdym „Przygotuj JPK”, bez sieci.
  Nowa wersja wzoru MF = nowe pliki i zmiana `NS` w `jpk.py`.
- **Zasady wypełniania** (broszura MF „JPK_VAT z deklaracją od 1 lutego 2026 r.”):
  `NrKontrahenta` bez kodu kraju (kod w `KodKrajuNadaniaTIN`, krajowy NIP bez
  kodu), brak numeru = „BRAK”, brak nazwy = „BRAK”; faktura z numerem KSeF =
  `NrKSeF`, inaczej `BFK`; `DataSprzedazy` i `DataWplywu` tylko, gdy różne od daty
  wystawienia; ewidencja (`K_`) w groszach, deklaracja (`P_`) w pełnych złotych
  (od 50 gr w górę, art. 63 § 1 OP) z sumy pola; P_37, P_38, P_48 i sumy
  kontrolne wg dokumentacji pól w XSD; P_51 do wpłaty, P_53 = P_62 do
  przeniesienia (zwrot P_54 — później). `Rok` w XSD najwyżej 2090 (testy losują
  lata do 2090).
- **Wersje** (`ledger_vat_files`): 1. = złożenie; po wersji oznaczonej jako
  wysłana kolejna to korekta (CelZlozenia 2) z uzasadnieniem P_ORDZU. „Wysłany”
  oznacza księgowa po wysłaniu bramką MF (z numerem UPO) — tylko ostatnią wersję.
  Plik i sumy deklaracji zapisane (bajty + SHA-256), nie liczone na nowo.
- **P_39** = P_62 z JPK poprzedniego miesiąca (ostatni wysłany, inaczej ostatni);
  pierwszy miesiąc w NEXUSIE — kwota wpisana przy przygotowaniu (z deklaracji
  z Symfonii); kolejna wersja tego samego miesiąca bierze P_39 poprzedniej.
- **Blokady przygotowania** (422): brak kodu urzędu skarbowego (dane płatnika
  K7a) albo e-maila do JPK (zakładka VAT, admin); wiersz bez pola JPK, faktura
  sprzedaży z KSeF bez dokumentu, FVS/FVZ w buforze. Kolejka kosztów i zapisy na
  kontach VAT spoza rejestru = ostrzeżenia w odpowiedzi.
- **D2**: plik ma faktury osób zespołu — przygotowuje lista „Księgowi” z Płacami
  albo administrator, pobiera osoba z Płacami albo administrator; reszta widzi
  wersje i stan bez kwot (`totals`), bez P_39.
- **Lista zamknięcia** „JPK_V7M”: do zrobienia do przygotowania i wysłania;
  „problem”, gdy odcisk rejestrów (dokumenty i kwoty) różni się od odcisku
  wysłanej wersji — trzeba korekty.

## Testy

`tests/test_ledger_vat_rules.py` (podział stawek, kwoty z dekretu, pola JPK,
pozycja listy zamknięcia), sekcja K5a w `tests/test_ledger_sources_db.py`
(rejestry z FVS/FVZ fixture `books`: 23%, EUR `np II`, korekta, faktura osoby
zespołu — D2, brak FVS dla zaliczki i nabywcy spoza kartoteki, PK na koncie VAT,
lista zamknięcia; ustawienia i bramki), wzorzec `tests/data/authz_golden/ledger_vat.json`,
front: `VatView.test.tsx`, `vat-model.test.ts`. JPK: `tests/test_ledger_jpk_rules.py`
(zaokrąglenie, kontrahent, pola P_, oznaczenia, daty, walidacja XSD, korekta),
`test_jpk_is_prepared_sent_and_corrected` (braki, D2, wersje, „wysłany”, korekta
z P_ORDZU, lista zamknięcia po zmianie rejestru, P_39 z poprzedniego miesiąca).
