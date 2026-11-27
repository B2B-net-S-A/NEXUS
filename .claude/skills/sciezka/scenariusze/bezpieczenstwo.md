# Scenariusz: Ustawienia → Bezpieczeństwo

Reguła: `docs/claude/ui/ekran-bezpieczenstwo.md`.

Kto → co robi → co widzi następny:

1. **Admin** otwiera `/settings?area=sys&item=security`. Widzi cztery kafelki,
   „Czeka na reakcję”, zdarzenia na żywo i tabelę źródeł; źródła bez danych
   mają „nieskonfigurowane”. Dane próbne wysyła kluczem `security:ingest`
   (`POST /api/security/ingest`, format z reguły) — CrowdSec, znalezisko CI.
2. **Admin** otwiera znalezisko: panel z boku (gdzie, dowód, wpływ, kroki),
   ustawia właściciela, „Otwórz sesję naprawy” (brief w schowku), „Wyjątek do…”
   bez powodu → komunikat, z powodem i datą → znalezisko w „Wyjątkach z terminem”.
   Drugie znalezisko: „Zamknij jako naprawione” → potwierdzenie → „zamknięte”.
3. **Admin** przechodzi na Rutyny: kalendarz miesiąc/tydzień, tabela rytmu,
   „Zrobione” przy rutynie → nowy termin. Rutyna po terminie: krok pętli
   `notify_overdue_routines` uruchomiony ręcznie → dzwonek u admina.
4. **Rekruter** (rola, która ma nie widzieć): pozycji nie ma w Ustawieniach,
   adres pokazuje odmowę, `GET /api/security/overview` jego tokenem → 403.
