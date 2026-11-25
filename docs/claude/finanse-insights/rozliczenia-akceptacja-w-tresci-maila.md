# Rozliczenia: akceptacja klienta w samej treści maila to sprawa i dokument

<!-- indeks: akceptacja mailowa, sprawa i dokument, akceptacja w treści, mail bez załącznika, router E8, support_mail_route, is_client_acceptance_mail, acceptance_clients, proof.accept_has_hours, proof.excel_with_mail, cl.client_acceptance, PKO, BIK, osoba z tematu, resolve_named_for_clients, .eml -->

Od 23.11.2026. Klient bez własnego systemu (PKO, BIK i inni) akceptuje godziny odpowiedzią
w wątku z TS, zwykle bez załącznika: „łączna liczba godzin: 112, październik 2026”. Do tej pory
router jednej skrzynki (`app/services/support_mail_route.py`) oddawał czytnikowi rozliczeń tylko
maile z załącznikiem. Taka akceptacja była więc wyłącznie sprawą, a kontrola
`proof.accept_has_hours` nie miała czego sprawdzić. W próbie IX–X 2026 dało to fałszywe uwagi
i regułę wyłączoną u kilku klientów.

## Reguła

Decyzja Artura z 23.11.2026: „sprawa i dokument”. Router nie zabiera takiego maila sprawom
(`is_settlements_mail` bez załącznika zwraca `False`), więc sprawa powstaje jak dotąd.
Czytnik rozliczeń (`consultant_portal/mailbox.run_once`) czyta go mimo to i zapisuje jako
dokument. Ten sam wzorzec ma mail z adresu firmy z tematem rozliczenia
(`mailbox.is_body_only_settlement`).

Czytnik rozliczeń czyta mail **bez załącznika** (`is_client_acceptance_mail`), gdy spełnia
oba warunki:

- adres rozliczeń (`CONSULTANT_PORTAL_SETTLEMENTS_ADDRESSES`) stoi w „Do” albo „DW”;
- domena nadawcy jest dokładnie domeną klienta z regułą akceptacji mailowej, bez poddomen.
  Konsultant BNP pisze z `external.` w domenie banku i nie jest klientem.

Domeny klientów (`acceptance_clients`) pochodzą z reguł bieżącego i poprzedniego miesiąca.
Bierzemy dwa miesiące, bo akceptacja za miesiąc przychodzi na jego końcu albo na początku
następnego. Źródła domen:

| Reguła klienta | Domena |
|---|---|
| `proof.excel_with_mail` włączona | jej parametr „domena” (pusty = nic) |
| `proof.accept_has_hours` włączona | parametr „domena” z `proof.excel_with_mail`, a bez niego domeny adresów kontaktów klienta. Dziś tak jest u PKO: reguła bez domeny |
| `cl.client_acceptance` włączona | domena jej adresu. Odpowiedź Banku Pocztowego na paczkę KCP wcześniej też zostawała sprawą |

Każdy inny mail bez załącznika jest tylko sprawą, także od klienta bez tych reguł i od klienta
spoza adresu rozliczeń. Maili z załącznikiem i raportów T4T (`is_time_report_mail`) ta reguła
nie zmienia.

## Co robi czytnik rozliczeń

`consultant_portal/mailbox.py` (`_store_client_acceptance`) zapisuje mail jako dokument
`report` w `.eml`. Z tego pliku czytają `proof.accept_has_hours` i `proof.excel_with_mail`.

- **Osoba** pochodzi z tematu wątku, wyłącznie spośród kontraktów klientów z tej domeny
  (`identity.resolve_named_for_clients`). Każdy człon nazwiska musi stać w temacie, a imię
  pełne albo jego inicjałem, np. „Akceptacja godzin wrzesień 2026 - P. Nowak”
  albo „Odbiór usług za 10.2026: Nowak Piotr”.
- **Okres** pochodzi z tematu, a bez niego z daty maila (`period_for`).
- **Bez jednej osoby** (brak nazwiska, dwie osoby, osoba z dwoma kontraktami) w `internal`
  i `all` powstaje karta do ręcznego przypisania, a w pilotażu mail jest pomijany. Sprawa
  powstaje w każdym z tych przypadków.

Odpowiedź na paczkę KCP (`mailbox._store_client_reply`, domena z `cl.client_acceptance`)
kończy czytanie maila tylko wtedy, gdy mail zapisano jako akceptację klienta. Każdy inny
mail z tej domeny idzie dalej zwykłą ścieżką: konsultant ze skrzynką u klienta wysyła KCP
w załączniku, a odmowa klienta („W KCP jest błąd”) staje się dokumentem albo kartą.
Do 24.11.2026 oba przepadały bez śladu (audyt czytnika skrzynki).

Skutek uboczny: pytanie od pracownika takiego klienta na rozliczenia@ bez załącznika daje
sprawę i dodatkowo kartę w rozliczeniach. W archiwum IX–X był jeden taki mail (BNP, odpowiedź
o numer faktury).

## Skala (archiwum rozliczenia@ 01.09–31.10.2026, reguły produkcji z 23.11)

24 maile bez załącznika na rozliczenia@ od domen klientów z regułą akceptacji: PKO 11, BIK 10,
Plus, KIR i BNP po 1. 18 z nich ma osobę w temacie (BIK 10, PKO 8). Pozostałe 6 to karty do
przypisania. Wszystkie 24 nadal są też sprawami; dotąd były wyłącznie sprawami.

Szczegóły jednej skrzynki: `ludzie/jedna-skrzynka-wsparcie.md` (sekcja „Router E8”).
