# Backlog scenariuszy E2E (po usunięciu `flow-stubs-todo.spec.ts`)

> Plan poprawy QA po audycie 14.09.2026 (B4). Do 15.09 te pozycje żyły jako
> 27 przypadków `test.fixme` w `frontend/e2e/flow-stubs-todo.spec.ts`.
> Playwright je listował, ale nie wykonywał, więc zawyżały licznik „przypadków
> E2E” i nie chroniły niczego. Teraz są katalogiem z priorytetem i właścicielem.
> Scenariusz wraca do kodu dopiero jako prawdziwy test `@stack` z dokładnymi
> asercjami i ponownym odczytem.

**Właściciel domyślny:** Tech Lead QA (do przypisania przez Artura). Pozycja P0/P1
bez imiennego właściciela jest otwarta w rozumieniu QA-12.

## Pokryte scenariuszami `@stack` (15.09.2026)

| Scenariusz | Spec |
|---|---|
| Kandydat: utworzenie → ponowny odczyt → UI; duplikat e-maila → 409 | `flow-create-candidate.spec.ts` |
| Pipeline: screening → konflikt wersji (409) → odrzucenie z powodem; odmowa rekrutera spoza zespołu | `flow-stage-transition.spec.ts` |
| Notatka z @wzmianką → powiadomienie `note_mention` | `flow-write-note-mention.spec.ts` |
| Uprawnienia: rekruter 403 w API i strona `/403` w UI, admin dozwolony | `rbac-deny.spec.ts` |
| Kontrakt + zamówienie okresowe → aktywacja szkicu i okres zamówienia na kontrakcie | `contract-order.spec.ts` |
| Klient tworzony przez API (NIP/branża poza zakresem) | pośrednio we wszystkich scenariuszach |
| Dostępność: logowanie, lista kandydatów, tablica rekrutacji (tylko `critical`) | `a11y.spec.ts` |

## Otwarte

| Pri | Scenariusz | Uwagi do automatyzacji |
|---|---|---|
| P0 | Umowa: szkic → edycja treści → finalizacja → status aktywny | stack; bez Autenti |
| P0 | Podgląd PDF umowy (`render-pdf`) — typ i rozmiar > 1 KB | stack |
| P1 | Import CSV 5 kandydatów → liczniki zgodne | stack; `sampleCandidatesCsv()` w `helpers/test-entities.ts` |
| P1 | Import z CV (PDF) → kandydat utworzony | wymaga AI — stub dostawcy albo test backendu zamiast E2E |
| P1 | Pobranie wielu CV (ZIP) | stack; wymaga plików w object storage stacku |
| P1 | Nowa rekrutacja → automatyczne TAC/DL z przypisań klienta | stack |
| P1 | Edycja rekrutacji (PATCH) → ponowny odczyt i UI | stack |
| P1 | Dodanie 3 kandydatów do rekrutacji z modala | stack, UI |
| P1 | Zamknięcie rekrutacji z powodem | stack |
| P1 | Zaplanowanie rozmowy → wydarzenie w kalendarzu | stack; bez M365 |
| P1 | Wysyłka e-maila do kandydata przez M365 | poza stackiem (sandbox M365) |
| P1 | Kontakt klienta z flagą decydenta | stack |
| P1 | Umowa ramowa (MSA) | stack; wysyłka Autenti poza zakresem |
| P1 | Połączenie OAuth M365 | poza stackiem (mock callback) |
| P1 | Weryfikacja kandydata oczekującego (akceptuj/odrzuć) | stack |
| P1 | Wysyłka umowy przez Autenti | poza stackiem (sandbox dostawcy) |
| P1 | Publiczny formularz aplikacji `/apply/{token}` | stack; wymaga rekrutacji przekazanej do searchu (Champion + handoff), dopiero wtedy link jest aktywny |
| P2 | Wyszukiwanie z górnego paska → szuflada kandydata | stack, UI |
| P2 | Kandydat na Targ z TTL | stack |
| P2 | Ogłoszenie AI z opisu rekrutacji | wymaga AI |
| P2 | Feedback po rozmowie | stack |
| P2 | Upload PDF do kandydata | stack |
| P2 | Kandydat do puli talentów | stack |
| P2 | Dopasowanie AI puli do rekrutacji | wymaga AI i Qdranta z embeddingami |
| P2 | Zamówienie SOW z referencją MSA | stack |
| P2 | Kanał powiadomień Teams | poza stackiem |
| P2 | Przypisanie DL do klienta (zakładka Zespół) | stack |
