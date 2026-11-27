# Krajowy Rejestr Zadłużonych przed podpisem umowy B2B (0800, 27.11.2026)
<!-- indeks: KRZ, krz.ms.gov.pl, półautomat, NIP i PESEL, PESEL nie trafia do bazy, `b2b_generated_contracts.krz_check` (JSONB), `services/b2b_contract_generator/krz.py`, `api/b2b_krz.py`, PUT /generated/{id}/krz, POST /generated/{id}/krz/decision, bramka wysyłki i „Oznacz jako podpisaną”, decyzja DL klienta, Head of Recruitment, anulowanie, dzwonki `b2b_krz_entry` i `b2b_krz_allowed`, wysyłka do aktywnych poza bramką, MGBI -->

Prośba Błażeja z 27.11.2026: „Niech nam Nexus sprawdza tych ludzi w Krajowym
Rejestrze Zadłużonych zanim podpiszemy umowę”. Decyzje Artura z 27.11.2026,
makiety: https://claude.ai/artifact/52333FTbcTvAGNovhQ4Rs3.

Kod: `backend/app/services/b2b_contract_generator/krz.py` (reguła, zapis,
dzwonki), `backend/app/api/b2b_krz.py` (trasy), serializer rejestru
`_krz_state` w `api/b2b_contract_generator.py`, front
`components/v2/b2b-generator/krz/` i `lib/b2b-krz.ts`. Testy:
`tests/test_b2b_krz.py`, `src/lib/__tests__/b2b-krz.test.ts`,
`krz/__tests__/KrzGate.test.tsx`, opis KRZ w `B2BContractGeneratorForm.test.tsx`.

## Dlaczego półautomat

- **KRZ nie ma API.** FAQ Ministerstwa Sprawiedliwości (pyt. 8): API jest
  „zaplanowane do realizacji w fazie rozwoju systemu”, bez daty. Portal stoi
  za zaporą Imperva i nie ma regulaminu dla automatów, więc wołania ukrytych
  adresów portalu (projekty na GitHubie) nie wchodzą w grę.
- NEXUS otwiera wyszukiwarkę portalu i kopiuje numer do schowka, a człowiek
  zaznacza wynik. NEXUS zapisuje wynik, kto i kiedy. Zaświadczenia o braku
  wpisu KRZ nie wydaje, więc dowodem jest ten zapis.
- **Wycena pośrednika:** MGBI („KRZ – Wyszukiwarka Podmiotów”, NIP i PESEL),
  zapytanie wysłane 27.11.2026 formularzem na mgbi.pl. Gdy przyjdzie umowa,
  automat zastępuje tylko kliknięcie człowieka (`krz.new_check` z wynikiem
  z API), a bramka, ekrany i decyzja DL zostają.

## Reguły

- **NIP i PESEL.** Firmę JDG znajdzie się po NIP-ie; upadłość konsumencka
  i dłużnicy alimentacyjni są przypięci do PESEL-u. **PESEL nie opuszcza
  przeglądarki** (`KrzSearchPanel`): nie ma go w schemacie API
  (`B2BKrzCheckIn`), w `render_payload` ani w bazie. Zapisujemy sam wynik
  (RODO; NSA III OSK 1109/25 — jawność rejestru nie jest podstawą przetwarzania).
- **Zapis:** `b2b_generated_contracts.krz_check` (JSONB): `result`
  (`clear`/`entry`), `entry_kind` (rodzaje z art. 2 ustawy o KRZ),
  `entry_note` (sygnatura, do 300 znaków), `nip` z chwili sprawdzenia,
  `checked_at/by`, `decision` (`allowed`/`rejected`), `decision_reason`,
  `decided_at/by`. Wynik z Generatora idzie w `/render` i `/rerender`
  (`krz_check`), ale **nie do `render_payload`** — formularz „Popraw” bierze go
  z wiersza (`GET /generated/{id}/form`).
- **Inny NIP to inna firma:** poprawka umowy ze zmienionym NIP-em unieważnia
  wynik (`krz.current_check`), wiersz pokazuje „KRZ: NIP zmieniony”, a formularz
  kasuje zaznaczenie przy zmianie NIP-u. Ten sam wynik drugi raz nie dokłada
  wpisu w historii ani dzwonka (`krz.same_result`).
- **Bramka** (`krz.block_reason`): bez wyniku, z wpisem bez decyzji albo
  z decyzją „nie podpisujemy” nie ma „Wyślij do podpisu” (`send_for_esign`),
  „Oznacz jako podpisaną” (tylko trasa przycisku, nie koniec e-podpisu) ani
  prośby do DL o potwierdzenie podpisu (409 z komunikatem). Serializer zeruje
  `can_send_esign` i `can_confirm_signed` i daje komunikat w `blocked_reason`.
  **DOCX pobiera się zawsze**; okno przed pobraniem tylko przypomina o KRZ.
- **Poza bramką:** umowa zlecenia, wiersz z Excela, wiersz podpisany i umowa
  z wysyłki nowej umowy do aktywnych (`b2b_mass_send_items`) — trwające
  kontrakty są „na później, z API” (decyzja 27.11.2026). Umowy wygenerowane
  przed wdrożeniem, jeszcze niepodpisane, czekają na wynik jak nowe; wysyłki
  już otwarte kończą się bez zmian.
- **Kto zapisuje wynik:** ten, kto wysyła umowę do podpisu albo potwierdza jej
  podpis (`may_confirm_row_signature` albo `_assert_row_sender`), tylko przy
  umowie „W trakcie”.
- **Kto rozstrzyga wpis** (`krz.decider_ids`): Delivery Lead rekrutacji i DL
  z portfela klienta (aktywni, z rolą DL), a bez nich Head of Recruitment;
  admin i Head of Recruitment zawsze. Decyzja wymaga uzasadnienia.
  „Nie podpisujemy” ustawia „Anulowana” (numer zostaje w rejestrze),
  „Dopuść” zdejmuje bramkę. Ponowne sprawdzenie zeruje decyzję.
- **Dzwonki:** `b2b_krz_entry` do osób, które rozstrzygają (sekcja Sourcing,
  link do rejestru z numerem; zastępca przy urlopie), `b2b_krz_allowed` do
  Finansów po dopuszczeniu mimo wpisu (ryzyko zajęcia faktur przez komornika).
- **Historia umowy:** wpisy w `b2b_generated_contract_status_events` z
  `details.source = "krz"` i gotową treścią w `details.label`; dialog
  „Historia statusów” pokazuje je jako „Krajowy Rejestr Zadłużonych”.

## Testy innych obszarów

Testy podpisu, wysyłki i automatyki zatrudnienia zakładają umowę już
sprawdzoną: wiersze w ich seedach mają `krz_check=KRZ_CLEAR`
(`tests/_krz.py`). Nowy test, który wysyła albo potwierdza podpis umowy
z Generatora, robi to samo, a samą bramkę sprawdza `tests/test_b2b_krz.py`.
