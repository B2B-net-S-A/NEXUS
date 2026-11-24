# Rozliczenia kontraktorów: reguły z praktyki (korespondencja rozliczenia@ IX–X 2026)

<!-- indeks: niepisane reguły rozliczeń, korespondencja z kontraktorami, korekty faktur, Nordea T4T, stawka z aneksu, zmiana stawki w trakcie miesiąca, biała lista VAT, kompensata benefitów, wstrzymanie płatności, data sprzedaży, co NEXUS sprawdza, a co zostaje człowiekowi -->

Przegląd 790 maili wysłanych z rozliczenia@ (15.09–20.11.2026) i porównanie zapłat z eBI24 (stan
16.11) z fakturami sprzedaży Finansów. Wynik: żadna z 30 wrześniowych rozbieżności „zapłacono ≠
godziny × stawka” nie była otwartym sporem. Każda ma przyczynę w danych albo w mailu. Tam, gdzie
przyczyna jest znana, zapłacona kwota zgadza się z wersją ustaloną w korespondencji. Gdy NEXUS
wylicza koszt, trafia w kwotę zapłaconą w 66 z 70 przypadków IX (próba Klodko).

Poniższe reguły obowiązują przy zmianach w rozliczeniach (`client_settlements/`, czytnik
rozliczeń, reguły klientów). „NEXUS” w kolumnie znaczy, że kontrola już istnieje.

## Sprawdzane automatycznie

| Reguła z praktyki | Gdzie w NEXUS-ie |
|---|---|
| Nordea płaci tylko godziny zaakceptowane w T4T (status 2); faktura kontraktora ma się równać tej sumie, inaczej pytanie, a potem korekta (ok. 60 wątków) | `report.time_for_teams`, `time_reports` (stan „inne godziny”); „Do faktury dla klienta” tylko z godzin zatwierdzonych w ostatniej wersji (`rozliczenia-faktura-klienta-z-zatwierdzonych-t4t.md`, od 23.11.2026) |
| Stawka obowiązująca w danym miesiącu to stawka z aneksu (`contract_candidate_rates.effective_from`), nie bieżąca | harmonogram stawek kontraktu |
| Zmiana stawki w trakcie miesiąca: płatność po dwóch stawkach, rozliczenie dzielone („podziel TS”) | uwaga „Zmiana stawki DD.MM” na rozliczeniu (`service._rate_change_checks`, od 23.11.2026); kwota z jednej stawki zamówienia wymaga poprawy przez Finanse |
| Akceptacja mailowa klienta podaje liczbę godzin i miesiąc (PKO, BIK). Akceptuje tylko adres z domeny klienta, sam albo w cytacie; nasze zestawienie godzin nie jest akceptacją. Samo „Akceptuję” od klienta bez liczby wystarcza, gdy godziny są w TS za rozliczany miesiąc (decyzja Artura z 23.11.2026, „Akceptacja bez liczby, godziny z TS”); bez TS albo z TS za inny miesiąc zostaje uwaga | `proof.accept_has_hours` (`mail_text.judge`), `rozliczenia-akceptacja-od-klienta-orlen-cez.md` |
| Zamówienie w MD ogranicza fakturę sprzedaży (BIK, BNP) | `order.no_md_holds_invoice` |
| Faktura kontraktora na B2B.net S.A. w KSeF, termin 14 dni od nadania numeru KSeF | `ci.ksef`, `ci.buyer_nip`, `ci.payment_days` |
| Biała lista VAT dla faktur powyżej 15 tys. zł brutto | `contractor_details` (status z wykazu MF) |
| Łańcuch korekt: faktura, korekta −, korekta + liczone razem; duplikat i korekta korekty | `invoice_chain` |
| Nadgodziny BNP po 120% i tylko z wcześniejszą akceptacją klienta | `extra.multiplier`, `extra.mail_accept`, `extra.mail_before` |

## Pola tylko z XML-a faktury (od 23.11.2026 reguły, domyślnie wyłączone)

Metadane z zapytania KSeF nie mają daty sprzedaży, nazw pozycji ani formy płatności, więc
NEXUS pobiera XML faktury kontraktora raz, po przypięciu jej do kontraktu. Finanse włączają
kontrolę per klient (`faktura-kontraktora-pola-z-xml-ksef.md`):

- data sprzedaży (wykonania) = ostatni dzień rozliczanego miesiąca (16 korekt we wrześniu
  i październiku) → `ci.sale_date`;
- nazwa pozycji bez innego miesiąca niż rozliczany (5) → `ci.item_month`;
- forma płatności przelew i numer rachunku; „ZAPŁACONO” albo gotówka oznacza korektę (13 maili)
  → `ci.payment_form`.

## Zostaje człowiekowi

- **Kompensata benefitów:** faktura za benefity nie jest opłacana przez kontraktora, kwota jest
  potrącana z najbliższej płatności. Zapłata ≠ faktura i to jest poprawne.
- **Wstrzymanie płatności:** zwrot sprzętu na końcu współpracy, zajęcie komornicze albo skarbowe.
  Automat może najwyżej zatrzymać płatność do decyzji człowieka.
- **Godziny ponad raport klienta:** godzina pracy dla B2B (warsztat), dzień płatnego urlopu,
  delegacje i koszty refakturowane doliczone do faktury. Każda z nich wymaga potwierdzenia rozliczeń.
- **Jedna osoba u dwóch klientów:** jedna faktura na oba kontrakty; kwotę dzieli człowiek.
- **Stawka zależna od miejsca pracy** (wyższa „u klienta” w aneksie): decyzja przy aneksie.

## Do decyzji Finansów

Przenoszenie godzin w T4T Nordei. Gdy przedział T4T jest zamknięty, godziny przechodzą do
ostatniego przedziału albo do następnego miesiąca. W części wątków kontraktorowi zapłacono
faktyczne godziny, a w części musiał skorygować fakturę w dół i doliczyć resztę w kolejnym
miesiącu. Dopóki Finanse nie wybiorą jednej praktyki, automat jej nie przesądza: różnica godzin
w T4T zostaje uwagą do decyzji.
