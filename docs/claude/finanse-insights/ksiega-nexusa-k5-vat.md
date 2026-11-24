# Księga NEXUSA K5 (15.11.2026): rejestry VAT, JPK_V7M

Etap K5 planu „Księgowość w NEXUSIE” (https://claude.ai/artifact/U9Z3unvSK62Ff5U36hkaar).
K5a: rejestry VAT z dokumentów księgi — kod w `app/services/ledger/vat.py`,
trasy `app/api/ledger_vat.py`, zakładka „VAT” (`/accounting/vat`), moduł `vat`
w Ustawieniach (włącza administrator). Bez migracji: rejestr liczy się
z dokumentów przy każdym otwarciu. K5b-1: plik JPK_V7M(3) — `ledger/jpk.py`,
migracja `0708_ledger_vat_files` (sekcja niżej). K5b-2: zakupy zagraniczne
(import usług) — `ledger/foreign.py` — i znaczniki GTU/TP per kontrahent, bez
migracji (sekcja niżej). K5b-3a: VAT-UE(5) — `ledger/vat_ue.py` (sekcja niżej).
K5b-3b: porównanie z JPK z Symfonii — `ledger/jpk_compare.py` (sekcja niżej).
K5b-3c: dokument rozliczenia VAT — `ledger/vat_settlement.py`; VAT-UEK(5) —
`ledger/vat_uek.py` (sekcje niżej). Dalej art. 86 ust. 10i.

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
- **FVZ z VAT należnym**: netto = kwota od dostawcy (sprzedawca nie doliczył
  VAT; VAT doliczony przez sprzedawcę = naliczony − należny tylko, gdy naliczony
  jest w dekrecie — bez odliczenia netto nie rośnie o VAT, poprawka K5b-2), VAT
  naliczony w rejestrze zakupu, VAT należny jako wiersz rejestru sprzedaży. Z
  formularza zakupu zagranicznego wiersz ma pole JPK (K_27–K_30); z ręcznego
  dekretu E2 w kolejce kosztów — „do sprawdzenia” (zaksięguj fakturę
  formularzem). Bez tego nadwyżka naliczonego była zawyżona o ten VAT. FVS
  z VAT naliczonym — wiersz do sprawdzenia.
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
- **Dostawca zagraniczny** (K5b-2): formularz zakłada go w kartotece kontrahentów
  (nazwa, kraj, VAT UE, opcjonalnie ID Symfonii) z kontem rozrachunkowym pod
  kontem z ustawień VAT; potem wybiera się go z listy.
- **GTU i TP** per kontrahent w zakładce VAT (bez migracji), dla wszystkich jego
  faktur sprzedaży; importu usług GTU nie dotyczy.

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
  oznacza księgowa po wysłaniu bramką MF (z numerem UPO) — także starszą wersję
  (wysłaną, zanim ktoś przygotował nową), byle nie było nowszej wysłanej;
  pozostałe niewysłane wersje miesiąca stają się `void` (unieważnione). Złożenia
  nie oznacza się po wysłanym JPK. „Wysłany” bierze tę samą blokadę co
  „Przygotuj JPK” — cel nowej wersji nie powstaje z nieaktualnego stanu.
  Plik i sumy deklaracji zapisane (bajty + SHA-256), nie liczone na nowo.
- **P_39** = P_62 z JPK poprzedniego miesiąca (ostatni wysłany, inaczej ostatni)
  i wtedy nie wpisuje się jej ręcznie (422); pierwszy miesiąc w NEXUSIE — kwota
  z deklaracji z Symfonii, wpisywana i poprawialna przy każdej wersji (podpowiedź
  = P_39 ostatniej). **Łańcuch korekt**: korekta miesiąca, która zmienia P_62,
  oznacza wysłany JPK następnego miesiąca jako nieaktualny (`stale = surplus`,
  lista zamknięcia: problem).
- **Blokady przygotowania** (422): okres przed lutym 2026 (wzór 2 — Symfonia);
  brak kodu urzędu skarbowego (dane płatnika K7a) albo e-maila do JPK (zakładka
  VAT, admin); wiersz bez pola JPK, faktura sprzedaży z KSeF bez dokumentu,
  FVS/FVZ w buforze; wiersz, którego netto lub VAT nie mieści się w polach JPK
  (np. VAT na stawce np/zw — w rejestrze to „do sprawdzenia”). Kolejka kosztów
  i zapisy na kontach VAT spoza rejestru = ostrzeżenia w odpowiedzi.
- **Kontrahent w pliku**: kraj nadania z rodzaju identyfikatora, nie z adresu
  (NIP = bez kodu, VAT UE = prefiks numeru, PESEL = „BRAK”), Grecja = EL; znaki
  sterujące z nazw i numerów usuwane (lxml odrzucał je błędem 500).
- **Uwagi na karcie JPK**: znaczniki GTU i TP pochodzą z listy kontrahentów
  (K5b-2); pozostałych procedur (MR_T, I_42, WSTO_EE…) NEXUS nie ma. Porównanie
  z JPK z Symfonii w miesiącach równoległych to wyłapie.
- **D2**: plik ma faktury osób zespołu — przygotowuje lista „Księgowi” z Płacami
  albo administrator, pobiera osoba z Płacami albo administrator; reszta widzi
  wersje i stan bez kwot (`totals`), bez P_39.
- **Lista zamknięcia** „JPK_V7M”: do zrobienia do przygotowania i wysłania;
  „problem”, gdy odcisk rejestrów (dokumenty i kwoty) różni się od odcisku
  wysłanej wersji — trzeba korekty.

## Zakup zagraniczny i znaczniki GTU/TP (K5b-2)

- **Formularz** (karta „Zakupy zagraniczne” w zakładce VAT, każdy z modułem
  Finanse — jak PK; zatwierdza lista „Księgowi”): dostawca z kartoteki (bez
  NIP-u i PESEL-u, z kontem rozrachunkowym — kolumna „konto kosztowe”, jak w E2)
  albo nowy: nazwa, kraj (nie PL), numer VAT UE albo zagraniczny (z kraju UE
  prefiks kraju dopisuje się sam, GR → EL), opcjonalnie ID Symfonii (numer albo
  ID wymagane — klucz kartoteki), konto `<konto dostawców zagranicznych>-NNN`
  (pierwszy wolny numer z kartoteki i zapisów księgi, można wpisać inny pod tym
  kontem). Bliźniak nazwy (bez polskich znaków i interpunkcji) = 409.
- **Konto dostawców zagranicznych** (`vat.foreign_account`, admin w „Kontach
  VAT”): konto planu ze słownikiem „kontrahenci” (np. `202-1`); puste =
  formularz nie zakłada dostawców. `PUT /vat/settings` bez pola = bez zmiany.
- **Dokument**: FVZ w buforze, data operacji = wykonanie usługi (obowiązek
  podatkowy, art. 19a — okres VAT i JPK), data dokumentu = wystawienie. Wn koszt
  netto (bez odliczenia: netto + VAT), Wn VAT naliczony, Ma VAT należny, Ma
  dostawca netto w walucie (rozrachunek K4b). Korekta = kwota ujemna, strony
  odwrócone. Kurs: średni NBP z ostatniego dnia roboczego przed wykonaniem
  usługi (art. 31a), dokładnie z `fx_rates` — brak = 422. VAT = netto PLN ×
  stawka (23/8/5), do grosza. Data z przyszłości = 422. Ta sama faktura dostawcy
  (numer bez spacji i wielkości liter) = 409 — źródło `foreign_purchase`
  z id dostawcy i skrótem numeru.
- **Pole JPK**: dostawca z numerem VAT UE (bez XI — Irlandia Północna to VAT UE
  tylko dla towarów) = usługa od podatnika z UE, art. 28b → K_29/K_30; reszta
  (spoza UE, bez numeru VAT UE) → K_27/K_28. Grupa w `meta.jpk_group`. Wiersz
  zakupu (K_42/K_43, środek trwały K_40/K_41) tylko z odliczeniem; data wiersza
  zakupu = data faktury (`DataZakupu`) i data otrzymania z formularza
  (`DataWplywu`, gdy inna; pole domyślnie = data wystawienia, nie wcześniejsza
  niż ona — 422), wiersz sprzedaży — data usługi (DataSprzedazy). Oba z BFK
  (faktura poza KSeF).
- **Odliczenie** w miesiącu usługi, także gdy faktura przyszła po miesiącach.
  Decyzja Artura z 16.11.2026: bez podziału dekretu. Warunek „3 miesięcy od
  końca miesiąca obowiązku” w art. 86 ust. 10b pkt 3 i ust. 10i (odliczenie
  w bieżącym okresie) uchyliła ustawa z 11.08.2021 (Dz.U. 2021 poz. 1626,
  art. 1 pkt 8) od 7.09.2021; tekst jednolity Dz.U. 2026 poz. 1263: „10i.
  (uchylony)”. Prawo do odliczenia powstaje w okresie obowiązku (ust. 10),
  jeśli VAT należny jest w deklaracji za ten okres — spóźniona faktura to
  korekta JPK miesiąca usługi po obu stronach. Nie wracaj do rozdzielania
  należnego i naliczonego na dwa miesiące bez nowej podstawy prawnej.
- **Spóźniona faktura a wysłany JPK**: `GET /vat/foreign` zwraca `jpk_sent`
  (miesiące z wysłanym JPK, do 60), karta ostrzega przed zapisem, że JPK
  miesiąca usługi trzeba skorygować; po zatwierdzeniu FVZ odcisk rejestru
  się zmienia i lista zamknięcia pokazuje problem (`stale = registers`).
  Data otrzymania nie wchodzi do odcisku — zmiana samej daty nie oznacza
  korekty.
- **Import kartoteki z eBI24** nie dubluje dostawcy z formularza: wiersz pliku
  z tą samą nazwą, którego nie da się dopasować po numerze ani ID Symfonii, to
  błąd wiersza (dostawca z formularza = `imported_at` pusty).
- **Znaczniki GTU_01–GTU_13 i TP** (karta „Znaczniki kontrahentów”, zmienia lista
  „Księgowi” albo admin): `app_settings['ledger'].vat_markers` {id kontrahenta:
  znaczniki}, do 500 kontrahentów. Trafiają na każdy wiersz FVS kontrahenta
  (w JPK `1` po NrKSeF/BFK, GTU przed TP — kolejność XSD); importu usług się
  nie oznacza (broszura MF: GTU nie dla nabyć z podatkiem należnym; TP —
  decyzja: tylko faktury sprzedaży). Odcisk rejestru liczy znaczniki tylko, gdy
  są — wersje wysłane przed K5b-2 zostają aktualne; zmiana znaczników po
  wysłaniu = korekta (lista zamknięcia: problem).
- Id kontrahenta w trasach do 2³¹ − 1 (kolumna INTEGER) — większe = 422, nie
  500 z bazy.

## VAT-UE(5) (K5b-3a)

- **Decyzja Artura 15.11.2026**: schemat VAT-UE(5) z crd.gov.pl w repo
  (`app/services/ledger/vat_ue_schema/`, wzór 2021/01/12/10293, wersja 2-0E —
  najnowsza na liście struktur e-Deklaracji; importy przepisane na pliki obok),
  NEXUS składa plik i sprawdza go schematem przy pobraniu. Korekty składa się
  na VAT-UEK(5) (sekcja niżej).
- **Z czego**: wiersze rejestru sprzedaży z grup `np_ue` (usługi, art. 100
  ust. 1 pkt 4 — Grupa3) i `0_wdt` (WDT — Grupa1, bez trójstronnej). Okres =
  okres rejestru. Suma netto PLN per kontrahent i sekcja, w pełnych złotych.
- **Kontrahent**: kraj z prefiksu numeru VAT UE, nie z kartoteki (XI pod GB),
  Grecja = EL; bez numeru VAT UE, z kodem spoza słownika sekcji albo z GB (po
  brexicie) = problem. Suma kontrahenta poniżej zera = problem (to korekta
  wcześniejszego okresu — VAT-UEK).
- **Blokady pliku** (422 z powodem): problemy, listy rejestru blokujące JPK
  (stawki, faktura z KSeF bez dokumentu, bufor), brak NIP-u, nazwy albo kodu
  urzędu w danych płatnika (K7a); miesiąc bez usług UE i WDT = VAT-UE się nie
  składa. Plik nie ma danych osób zespołu — pobiera każdy z modułem VAT.
- **Schemat**: `etd:TRok` w strukturach v6 kończy się na 2030 — testy na bazie
  (lata 2050–2090) sprawdzają pozycje, walidację XSD testy reguł (rok 2026).
  Nowy wzór MF = nowe pliki i zmiana `NS` w `vat_ue.py`.

## Porównanie z JPK z Symfonii (K5b-3b)

- **Decyzja Artura 15.11.2026**: w miesiącach równoległych NEXUS pokazuje
  różnice między swoim JPK a plikiem z Symfonii; prawdziwy plik za październik
  2026 przyśle Finanse. Karta „Porównanie z JPK z Symfonii” w zakładce VAT,
  `POST /vat/jpk/compare?year=&month=` z plikiem XML — **pliku nie zapisujemy**.
- Plik czytany bez sieci, encji i DTD (lxml), po nazwach elementów bez
  przestrzeni nazw; okres z nagłówka musi być miesiącem porównania (422), do
  20 MB (413). Porównuje osoba z Płacami albo administrator (plik ma faktury
  osób zespołu — D2, 403).
- Strona NEXUSA = rejestry pełne i deklaracja jak przy „Przygotuj JPK”, z P_39
  z pliku Symfonii (nadwyżka to wejście). Wiersz = numer dowodu (bez spacji
  i wielkości liter) + numer kontrahenta (bez kodu kraju); różnice: pola `K_`
  w groszach, znaczniki GTU/TP, wiersze tylko po jednej stronie, pola `P_`.

## Decyzje Artura 15.11.2026 (dalsze K5b-3)

- **K5b-3c dokument rozliczenia VAT**: różnica groszy (deklaracja w pełnych
  złotych, konta w groszach) → pozostałe przychody/koszty operacyjne 760/761
  (konta ustawia admin w zakładce VAT); 221/222 zerują się co miesiąc.
- **VAT-UEK**: pobrać XSD VAT-UEK(5) z crd.gov.pl (wzór 2021/01/26/10316),
  NEXUS składa plik korekty za okres faktury pierwotnej.

## Rozliczenie VAT (K5b-3c)

- **Decyzje Artura 15–16.11.2026**: dokument typu VAT przenosi saldo VAT
  należnego (`sales.vat_account`) i naliczonego (`vat.input_account`) okresu na
  „VAT do zapłaty” z Kont wyciągów (`bank.vat_account`, rozrachunek z US), więc
  **221 i 222 zerują się co miesiąc**. Nadwyżka naliczonego do przeniesienia
  (P_62) też idzie na to konto (saldo Wn), nie zostaje na 221 — wariant
  wybrany 16.11 przy dwóch sprzecznych zdaniach briefu. Saldo konta = P_51
  (Ma) albo P_62 (Wn), przelew do US je zamyka.
- **Kwoty z JPK** miesiąca (ostatni wysłany, inaczej ostatni nieunieważniony,
  `totals`): Wn 222 = VAT należny z ewidencji (grosze), Ma 221 = naliczony,
  „VAT do zapłaty” = P_38 − (P_48 − P_39) w złotych (bez nadwyżki z poprzedniego
  okresu — ta już jest saldem Wn konta), różnica groszy: + = Wn konto kosztu,
  − = Ma konto przychodu (`vat.rounding_gain_account` / `rounding_loss_account`,
  np. 760/761, admin w „Kontach VAT”). Puste konto (także `bank.vat_account`)
  = dokument nie powstaje, lista zamknięcia mówi czego brakuje. „VAT do
  zapłaty” na koncie 221/222 = 422.
- **Księga przed dokumentem**: obroty kont 221/222 z analityką w zatwierdzonych
  dokumentach miesiąca (`op_date`), bez typów VAT i BO, bez dokumentów ze stornem
  i storn (jak rejestr — „stan dziś”). Różne od podatku w JPK = problem
  z wyjaśnieniem (zapis spoza rejestru albo zmiana po JPK → korekta JPK),
  dokument nie powstaje. Pozycje 221/222 idą **per konto z obrotów** — analityka
  zeruje się sama.
  **VAT należny to też konto importu usług** (audyt 24.11.2026): FVZ z kolejki
  kosztów z typem IU księguje VAT należny na koncie z dekretu (226, zapisane
  przez źródło w `meta.output_account`), a JPK liczy go w K_27–K_30. Lista kont
  VAT należnego = `vat.output_accounts`: konto sprzedaży z ustawień, 226
  (`DEFAULT_OUTPUT_VAT_ACCOUNT`) i każde `meta.output_account` z księgi. Bierze
  ją rozliczenie (obroty i pozycja Wn 226 jak 222, „VAT do zapłaty” nie może
  być żadnym z tych kont) oraz „Zapisy na kontach VAT spoza rejestru”. Bez
  tego miesiąc z importem usług miał problem „księga X, JPK X + IU” i dokument
  VAT nie powstawał (422).
- **Dokument**: źródło `vat_settlement` / `RRRR-MM`, data = ostatni dzień
  miesiąca, w buforze (zatwierdza lista „Księgowi”, edycja tylko przez
  „Przygotuj” — dokument ze źródła). Ponowne „Przygotuj” podmienia szkic
  (odcisk `sources.fingerprint` — opis bez wersji JPK, więc korekta JPK z tymi
  samymi kwotami nie zmienia dokumentu); zatwierdzonego nie rusza — inne
  kwoty dziś (korekta JPK po rozliczeniu) = `changed`, lista zamknięcia:
  problem, „Przygotuj” = 409; storno i ponowne „Przygotuj”.
- **D2**: obroty z dokumentami płacowymi (faktury osób zespołu) = dokument
  `sensitivity = 'payroll'` (zatwierdza osoba z Płacami). Przygotowuje osoba
  z listy „Księgowi” z Płacami albo admin (`jpk.can_prepare`), kwoty i pozycje
  widzi osoba z Płacami albo admin; reszta — stan, numer i problem bez kwot.
- **Lista zamknięcia** „Rozliczenie VAT”: problem (księga ≠ JPK, zatwierdzony
  ≠ dzisiejsze kwoty), do zrobienia (brak kont, brak JPK, brak dokumentu,
  szkic w buforze), ok (zatwierdzony, miesiąc bez kwot).
- Trasy: `GET /vat/settlement`, `POST /vat/settlement` (blokada `ledger-jpk`
  — wersja JPK nie zmienia się w trakcie). Bez migracji.

## VAT-UEK(5) — korekta VAT-UE

- **Decyzja Artura 15.11.2026**: schemat VAT-UEK(5) z crd.gov.pl w repo
  (`app/services/ledger/vat_uek_schema/`, wzór 2021/01/26/10316, wersja 2-1E —
  najnowsza na liście struktur e-Deklaracji 16.11.2026; importy te same co
  w VAT-UE(5), adresy przepisane na pliki obok, reszta bajt w bajt). Uwaga:
  `kodSystemowy` = „VATUEK (5)” — bez myślnika, inaczej niż VAT-UE.
- **Okres korekty** = miesiąc faktury pierwotnej (`corrected_month` wiersza
  rejestru). Korekta faktury z wcześniejszego okresu nie pomniejsza bieżącego
  VAT-UE: na karcie VAT-UE miesiąca K jest lista „Do VAT-UEK” — blok per okres
  z pozycjami i plikiem (`GET /vat/uek?year=&month=&issued_year=&issued_month=`
  i `/vat/uek/file`; okres = `year`/`month`, miesiąc korekt = `issued_*`).
- **Pozycja** (XSD i MF): „BYŁO” = dane z poprzednio złożonej informacji,
  „JEST” = dane prawidłowe — obie jako łączna wartość za okres, nie różnica.
  Sama „JEST” = kontrahent dopisany, sama „BYŁO” = usunięty; pozycja tylko,
  gdy kwota w pełnych złotych się zmienia. WDT z P_DBd/P_DJd = 1 (bez
  trójstronnej).
- **Skąd „BYŁO” — decyzja Artura 16.11.2026 („per miesiąc korekty”)**: NEXUS
  nie zapisuje złożonych VAT-UE, więc VAT-UEK za okres M składa się z korekt
  zaksięgowanych w miesiącu K. „BYŁO” = suma za M z rejestru M liczona dziś
  (z korektami z tego samego miesiąca, jak VAT-UE) + korekty faktur z M
  z miesięcy między M a K (zakładamy, że ich VAT-UEK złożono — karta to mówi);
  „JEST” = „BYŁO” + korekty z K. Odrzucone warianty: narastająco od VAT-UE
  (błędne przy drugiej korekcie okresu) i zapis złożonych wersji (migracja).
- **Blokady pliku** (422 z powodem): nabywca bez numeru VAT UE, suma okresu
  poniżej zera, faktura pierwotna bez dokumentu w księdze za M (VAT-UE poszedł
  spoza NEXUSA — korekta w Symfonii), listy rejestru K blokujące JPK, brak
  danych płatnika (K7a); brak korekt z K albo bez zmiany w pełnych złotych =
  VAT-UEK się nie składa. Bez danych osób zespołu — pobiera każdy z modułem VAT.
- **Schemat**: `Rok` od 2021, `etd:TRok` do 2030 — jak VAT-UE, testy na bazie
  sprawdzają pozycje, schemat testy reguł. Nowy wzór MF = nowe pliki i zmiana
  `NS` w `vat_uek.py`.

## Testy

`tests/test_ledger_vat_rules.py` (podział stawek, kwoty z dekretu, pola JPK,
pozycja listy zamknięcia), sekcja K5a w `tests/test_ledger_sources_db.py`
(rejestry z FVS/FVZ fixture `books`: 23%, EUR `np II`, korekta, faktura osoby
zespołu — D2, brak FVS dla zaliczki i nabywcy spoza kartoteki, PK na koncie VAT,
lista zamknięcia; ustawienia i bramki), wzorzec `tests/data/authz_golden/ledger_vat.json`,
front: `VatView.test.tsx`, `vat-model.test.ts`. JPK: `tests/test_ledger_jpk_rules.py`
(zaokrąglenie, kontrahent, pola P_, oznaczenia, daty, walidacja XSD, korekta),
`test_jpk_is_prepared_sent_and_corrected` (braki, D2, wersje, „wysłany”, korekta
z P_ORDZU, lista zamknięcia po zmianie rejestru, P_39 z poprzedniego miesiąca)
i po przeglądzie: łańcuch korekt, złożona starsza wersja, „wysłany” czeka na
„Przygotuj JPK”, poprawialna nadwyżka pierwszego miesiąca. K5b-2:
`tests/test_ledger_foreign_rules.py` (grupa JPK, kwoty po kursie, dekret,
korekta, pola formularza i odmowy, numer dostawcy, data otrzymania nie
przesuwa okresu na granicy 3 miesięcy), w `test_ledger_jpk_rules.py`
znaczniki i import usług przez XSD MF oraz odcisk bez znaczników, sekcja K5b-2
w `test_ledger_sources_db.py` (formularz od nowego dostawcy do JPK, odmowy,
strażnik importu eBI24, konto dostawców w ustawieniach, znaczniki na FVS;
`test_late_foreign_invoice_stays_in_the_service_month_and_flags_its_jpk` —
faktura pół roku po usłudze: oba rejestry w marcu, `DataWplywu`, JPK marca do
korekty), front: `VatView.test.tsx` (lista, formularz, znaczniki, data
otrzymania i ostrzeżenie o korekcie), `vat-model.test.ts`. K5b-3a:
`tests/test_ledger_vat_ue_rules.py` (pozycje, zaokrąglenie, problemy, XSD),
`test_vat_ue_lines_come_from_the_sales_register` w `test_ledger_sources_db.py`,
front: karta VAT-UE w `VatView.test.tsx`. K5b-3b: `tests/test_ledger_jpk_compare_rules.py`
(te same rejestry = zero różnic, kwota, wiersz, znacznik, pole P_, złe pliki
i encje), `test_jpk_compare_with_symfonia_file` w `test_ledger_sources_db.py`,
front: karta porównania w `VatView.test.tsx`.
K5b-3c: `tests/test_ledger_vat_settlement_rules.py` (kwoty, grosze, nadwyżka,
analityka, korekta JPK po rozliczeniu, pozycja listy zamknięcia),
`test_vat_settlement_moves_month_vat_to_the_tax_account` w
`test_ledger_sources_db.py` (konta, D2, bufor, salda 221/222 = 0, storno FVS,
korekta JPK, PK spoza rejestru), front: karta rozliczenia w `VatView.test.tsx`.

VAT-UEK:
`tests/test_ledger_vat_uek_rules.py` („było” z wcześniejszymi korektami,
dopisany i usunięty kontrahent, zaokrąglenie bez zmiany, WDT, problemy, XSD),
`test_vat_uek_corrects_the_original_period_from_month_k` w
`test_ledger_sources_db.py`, front: bloki „Do VAT-UEK” w `VatView.test.tsx`.
