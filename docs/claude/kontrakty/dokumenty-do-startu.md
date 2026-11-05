# Dokumenty do startu: rekruter kończy placement z kompletem, etap 1 bez wpływu na liczniki
<!-- indeks: lista per klient (pusta = nic), checklista per para liczona przy odczycie, termin per pozycja (KRK po starcie), plik liczy się od razu i DL może zwrócić, PESEL zwykłe pole, KRK węższy krąg, ikona „Umowy” + plakietka + pulpit + dzwonek zbiorczy, etap 2 placement warunkowy po pomiarze -->

Decyzje Artura z 05.11.2026 (makiety: https://claude.ai/artifact/QUS535egj9c9QinysRF7SN).
Rekruter uznawał pracę za skończoną po podpisie umowy, a Delivery Lead gonił go
potem o NDA, KRK i resztę. Na kopii produkcji z 04.11 z 37 umów Nordei od 01.08
tylko 4 miały przy kontrakcie i NDA, i KRK. DL Nordei w 120 dni napisał 22 notatki
„Poproszę klasyk: … NDA, KRK itp”.

Kod: `services/start_documents.py`, `api/start_documents.py`,
`services/start_documents_fill.py`, `services/start_documents_mail.py`,
`tasks/start_documents_sweeper.py`, `components/v2/start-docs/`,
`lib/api/start-documents.ts`.

## Lista Nordei (wiadomości Delivery Leadów z 05.11.2026)

- **NDA i PESEL** przed startem: bez nich klient nie założy konta w CPro.
- **Oświadczenie o niekaralności** przed startem. To nasz „kwitek”, Nordei nie
  interesuje. Zastępuje wyciąg, dopóki ten nie przyjdzie.
- **Wyciąg z KRK** z terminem po starcie, bo na e-KRK czeka się nawet 2 tygodnie,
  a od podpisu do startu mija w medianie 8 dni. Klient go nie dostaje, ale może
  poprosić w każdej chwili, więc plik zostaje u nas. Opłatę ponosi konsultant.
- **Certyfikaty i dyplomy** opcjonalne. Jak stary może być wyciąg: bez odpowiedzi,
  NEXUS tego nie sprawdza.

## Reguły

- **Etap 1 nie zmienia liczników.** Placement dalej nalicza pierwsze
  „Zatrudniony”. Decyzję o etapie 2 Artur podejmuje po 4 tygodniach pomiaru.
- **Lista klienta jest przełącznikiem.** Klient bez listy: nic się nie pojawia,
  także w trasach (`/pair` zwraca `null`). Listę ustawia Delivery Lead w „Wejście
  u klienta” (uprawnienie „Klienci: dodawanie i edycja”, w swoim portfelu). Nie
  wymaga modułu „Wejście i odejście”. Start: tylko Nordea.
- **Własna tabela zamiast pakietu klienta.** `client_onboarding_pack_items`
  zapisuje się całą sekcją bez stałych identyfikatorów, więc stan pary nie miałby
  czego wskazać, a pozycje trafiałyby do zadań opiekuna przy włączonym module.
- **Pary liczone przy odczycie, bez hooków.** Do „Zatrudnionego” prowadzi kilka
  dróg (podpis, ręczny ruch, Traffit). W zakresie jest para, której najnowszy etap
  to akceptacja, negocjacje, onboarding albo „Zatrudniony”, a na etap weszła
  najwcześniej `SINCE_GRACE_DAYS` (14) dni przed założeniem listy. Tak świeże
  placementy też wchodzą, a stare nie zalewają listy. Kontrakt `void` albo `ended`
  wyjmuje parę.
- **Odpowiada ta sama osoba, która dostaje placement** (`placement_bonuses.load_context`):
  „Prowadzi”, potem pierwszy weryfikujący. Bez rekrutera: Delivery Lead.
- **Plik liczy się od razu po dodaniu.** Delivery Lead klika „Sprawdzone” albo
  zwraca z powodem, wtedy pozycja wraca do braków, a rekruter dostaje dzwonek.
  Inaczej DL byłby wąskim gardłem placementu. Zwrot kasuje odrzucony plik i PESEL.
- **Umowa odhacza się sama** przy podpisie obustronnym albo żywym kontrakcie.
- **„Nie dotyczy”** ustawia DL z powodem, np. NDA z poprzedniego kontraktu.
  Cofnięcie zwraca to, co jest przy pozycji, a bez pliku pozycja wraca do braków.
- **`ix_notif_dedup_daily` nie patrzy na rodzaj encji**, więc każdy rodzaj dzwonka
  ma własny typ, a lista dzienna jest scalana per odbiorca. Druga lista tego samego
  typu przepadłaby po cichu.
- **Nieaktywny odbiorca:** rekruter → DL, DL rekrutacji → aktywny DL klienta,
  a bez nikogo sprawa idzie do Head of Recruitment.
- **Usunięta pozycja listy** dostaje `archived_at`: znika z list, a pliki par zostają.

## Dostęp

| Co | Kto |
|---|---|
| Stan pary, dodanie pliku, wpisanie PESEL-u | jak Tablica: role rekrutacji z dostępem do rekrutacji i odpowiedzialny rekruter |
| Pobranie pliku | odpowiedzialny rekruter, Delivery Lead klienta, Head of Recruitment, admin |
| Odczyt PESEL-u | Delivery Lead klienta, admin |
| „Sprawdzone”, zwrot, „Nie dotyczy”, „Przypomnij” | Delivery Lead klienta, Head of Recruitment, admin |

- **KRK to dane o karalności (art. 10 RODO)**, więc krąg pobrania jest węższy niż
  Tablica, a każde pobranie zostaje w `activities`. Plik zostaje, bo klient może
  o niego poprosić. Ocena IOD, także czasu przechowywania, jest otwarta.
- **PESEL to zwykłe pole** (decyzja Artura 05.11.2026, bez szyfrowania i bez
  kasowania). Nie idzie do odpowiedzi poza `GET …/pesel`, do `activities` ani do
  logów, a `scripts/staging/sanitize.sql` czyści go na kopii. Odczyt jest
  zapisywany. `normalize_pesel` sprawdza sumę kontrolną.
- **Pliki leżą przy parze**, w `start_documents/`, nie w Dokumentach kontraktu,
  które widzi szerszy krąg. Karta jest też w zakładce Dokumenty kontraktu.
- **Wzór NDA Nordei nie trafia do repozytorium** (jest publiczne). DL wgrywa go
  przy pozycji listy.

## Przypomnienia

Raz dziennie po 9:00, w dni robocze, zbiorczo na osobę (`ix_notif_dedup_daily`
pilnuje jednego na dzień):

Liczy się **termin pozycji**, nie sam start. Inaczej brak KRK, który z natury
przychodzi po starcie, alarmowałby przy każdej osobie.

- **Prowadzący:** zawsze dzwonek `start_documents`; od 5 dni roboczych przed
  terminem i po nim `start_documents_due`, który idzie też mailem (rodzaj
  obowiązkowy `start_documents`).
- **Delivery Lead:** od 2 dni roboczych przed terminem.
- **Head of Recruitment:** w dniu startu z zaległością, a po starcie w dniu terminu.
- **Ikona „Umowy” w pasku** ma czerwoną liczbę do kompletu. Kliknięcie jej nie gasi.
  Nie dodawaj nowej ikony: pasek przy 1280 px jest pełny (`ui/` #3015).
- **Pas nad pulpitem z makiety nie powstał.** „Pilne u klientów” stoi nad wszystkim
  i zajmuje pierwszy ekran, więc pas i tak byłby poza nim.

## Mail do konsultanta

„Wyślij listę konsultantowi” idzie ze skrzynki wysyłającego (M365), bez podpisu
w treści i bez myślników, jak maile podpisu umów. NDA ma dane z umowy
(`fill_from_agreement`: nazwa, NIP, adres, telefon, po etykietach w tabeli). PESEL
tylko telefonicznie. Bez połączonej skrzynki zostaje „Skopiuj treść”. Klucz wysyłki
pozwala na jeden mail od osoby dziennie.

## Etap 2 (po decyzji Artura)

Placement warunkowy: po terminie brakującej pozycji wypada z Ligi, celów i premii,
po dostarczeniu wraca ze swoją datą. Termin pozycji, nie start: rekruter nie może
stracić placementu przez wyciąg, na który czeka się 2 tygodnie. Drogą jest
`placement_exclusions` z nowym powodem zdejmowanym przy komplecie, bo tę tabelę
czytają już wszystkie liczniki. Etap 3: konsultant dodaje pliki sam w panelu z #3049.
