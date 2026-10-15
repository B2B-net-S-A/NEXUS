# „Szuka aktywnie” przy żywej umowie — S1–S5 (15.10.2026)

Zgłoszenie rekrutera: konsultant z umową z Nordeą i zamówieniem do 31.01.2027
miał przy nazwisku „Szuka aktywnie” obok „Pracuje u nas”. Dane umowy zgadzały
się z CPro; status wpisał 10.10.2026 automat notatek z „ASAP” w screeningu
z 15.07.2026, czyli sprzed umowy. Propozycja z makietami i decyzjami S1–S5:
https://claude.ai/artifact/LZLL3SdRAyaK3j7GbF2DMb — Artur: „wdróż to”
(rekomendacje, S5 = A). Reguła: `docs/claude/kandydaci-wyszukiwanie/znacznik-pracuje-u-nas.md`,
sekcja „Status „Czy szuka pracy” przy żywej umowie”.

## Skala (pomiar produkcji 15.10.2026, tylko odczyt)

- 132 z 483 osób z żywą umową miało „Szuka aktywnie”; 115 z nich miało w notatkach
  „ASAP / od zaraz”, 130 automat przeczytał już po starcie umowy, 1 ustawił człowiek.
- Wszystkie 132 siedziały w puli Targu kandydatów (19 dzwonków w 30 dni, 6 ze 100
  alertów o 4 pracujących).

## Co weszło

| Decyzja | Zmiana | Pliki |
|---|---|---|
| S1 | Pigułka ukryta przy żywej umowie — zrobione wcześniej w #2251 | `ProfileHeader.tsx`, `CandidatesListV2.tsx` |
| S2 | Automat notatek nie wpisuje „Szuka aktywnie” przy żywej umowie ani z notatki starszej niż start ostatniej umowy | `notes_profile_fill.py`, `notes_insights_extractor.py`, `tasks/notes_insights_sync.py`, `contract_availability.py` (`ContractHistory`, `load_contract_history`) |
| S3 | Ten sam warunek co pigułka po stronie serwera: pula Targu (nie dodaje, zdejmuje wpisy automatyczne, ręczne zostają), źródło B „Dostępnych kontraktorów” (z wyjątkiem osób, które wg znacznika kończą pracę w horyzoncie — źródło A ich nie widzi), licznik „N oznaczonych jako dostępni” w dzwonku podobnych requestów, plakietka „dostępny” w „Kandydatach z podobnych projektów”, wejście AI podsumowania aktywności | `contract_availability.py` (`availability_status_hidden`, `without_live_contract_clause`), `marketplace_service.py`, `api/recommendations.py`, `similar_job_notify.py`, `candidate_activity_summary_service.py` |
| S4 | Zdanie „status „Czy szuka pracy” jest ukryty” w ramce okna „Dostępność kandydata” i ta sama ramka przy „Dyspozycyjności” w „Edytuj dane” | `lib/contract-availability.ts` (`availabilityContractNote`), `CandidateProfileFactsBar.tsx`, `AppShell.tsx` |
| S5 = A | Statusów w bazie nie przepisujemy; wracają po końcu umowy | — |

Bez migracji i bez zmiany dostępu. Przewodnik Jarvisa `candidate.profile`
dostał pół zdania o ukrytym statusie (przestemplowany).

## Testy

- Bez bazy (lokalnie, Python 3.12): reguła i bramka automatu
  (`test_contract_availability_rule.py`, `test_notes_insights_extractor.py`),
  wejście AI (`test_candidate_activity_summary.py`) — 96 przeszło; po wyłączeniu
  bramki S2 cztery nowe testy automatu padają.
- Z bazą (CI): zgodność Python ↔ SQL ↔ znacznik i historia umów
  (`test_contract_availability_db.py`), sync Targu (`test_marketplace_service.py`),
  dzwonek (`test_similar_job_notify.py`), pula B (`test_seeking_contractors.py` —
  także konsultant B2B bez `end_date`, któremu zamówienie kończy się za 10 dni;
  ten przypadek znalazł przegląd kodu przed PR-em).
- Front: `contract-availability.test.ts`, `AppShellModal.test.tsx`,
  `CandidateProfileFactsBar.test.tsx`, strażnicy profilu; `npm run type-check`.
- Przeklikane w harnessie `/preview/candidate-profile?employed=1` przy 1280 × 720:
  jedna pigułka „Pracuje u nas”, ramka w obu oknach, pole edytowalne; bez umowy
  ramki nie ma.

## Poza zakresem

- Targ działa w tle, choć strona zniknęła z menu 21.09.2026 — wyłączenie
  (`MARKETPLACE_ENABLED`) to osobna decyzja.
- Źródło A „Dostępnych kontraktorów” bierze `contracts.end_date`, który umowa
  B2B ma dopiero po ręcznym zakończeniu — kończący po końcu zamówienia tam nie
  trafiają (niesprawdzone na danych).
- „Szuka aktywnie” z notatki sprzed dwóch lat wygląda tak samo u osób, które
  u nas nie pracują; podpis „skąd i z kiedy” przy statusie to osobna propozycja.
- Status wpisany automatem z notatki z czasu współpracy pojawi się po końcu
  umowy dopiero przy następnym odczycie notatek (gdy się zmienią).
