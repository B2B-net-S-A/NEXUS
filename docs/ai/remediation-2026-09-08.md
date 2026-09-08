# AI: korekty audytu 8 września 2026

Zakres: osiem ustaleń z audytu funkcji AI. Zmiany nie ustawiają nowych limitów,
nie uruchamiają backfillu kandydatów i nie korygują historycznych stawek.

| Ustalenie | Zmiana | Dowód regresji |
| --- | --- | --- |
| AI-01 | Umiejętności z profilu i CV są łączone; ręczna edycja oznacza kompletną listę i blokuje odtwarzanie usuniętych pozycji. Starsze edycje są rozpoznawane z dziennika zmian, bez przepisywania historii. | Dopisanie Kubernetes zachowuje Python/Django w punktacji, chipach i bramce must; ręczna pusta lista pozostaje pusta. |
| AI-02 | Wspólny zapis kwoty/waluty/wersji; ręczny zapis i wyczyszczenie przejmują własność; AI aktualizuje tylko dokładną poprzednią trójkę kwota/waluta/wersja. | AI → ręczna zmiana, potwierdzenie tej samej kwoty i wyczyszczenie → nowa notatka. |
| AI-03 | Tylko jawne PLN/h trafia automatycznie do stawki profilu. Inna/nieznana waluta zostaje w danych źródłowych z oznaczeniem weryfikacji. | EUR → PLN oraz taka sama kwota z inną walutą; brak przelabelowania waluty. |
| AI-04 | Trwała operacja z identyfikatorem UUID zastępuje nullable upsert licznika. Odpowiedzi dostawcy mają osobny, idempotentny rejestr. | Dwie operacje systemowe, retry tego samego response ID, rollback biznesowy i równoległe dopuszczenia w PostgreSQL. |
| AI-05 | Powiadomienia administratorów NEXUS działają bez Slacka; opcjonalna kopia Slack ma outbox i ponowienia. Osobne alarmy tempa tokenów/kosztu z ostatnich 24 h. | Nieudana dostawa Slack jest ponawiana bez drugiego powiadomienia NEXUS. Test w panelu wysyła wyłącznie do klikającego administratora. |
| AI-06 | Wspólna interpretacja must/nice/niewymagane/niejasne, oba poziomy Championa; edytowalny podgląd w Radarze. | PL/EN, nagłówki z punktami, negacja, konflikt i ręczne wyczyszczenie list. |
| AI-07 | Hash obejmuje dokładnie parametry renderowanego promptu i system prompt; rezerwacja generowania między procesami oraz kontrola własności przy zapisie. | Ta sama suma i inny składnik/kara/nice zmienia hash; drugi worker nie uzyskuje rezerwacji, stary nie może zapisać po jej przejęciu. |
| AI-08 | Każda odpowiedź Claude, również w zadaniu w tle i przy ucięciu, zapisuje faktyczny model, usage/cache, identyfikatory i czas. | Rejestr tła, cache read/write/1h, rzeczywisty model fallbacku i koszty. |

## Semantyka pomiaru

`ai_usage_log` zostaje nietknięty jako historia. Jego tokeny są obarczone błędami
poprzedniego mechanizmu i nie są dodawane do nowego pomiaru. Liczba dopuszczonych
operacji nadal obejmuje historyczne liczniki, a po wdrożeniu pochodzi z
`ai_operations`. Aktor systemowy ma stabilny klucz `system`; usunięcie użytkownika
nie scala jego historii z systemem.

`ai_provider_calls` zawiera jeden wiersz na odpowiedź dostawcy. Osobna krótka
transakcja zapisuje odpowiedź bez czekania na commit lub rollback danych
kandydata. Retry zapisu tego samego identyfikatora nie dolicza kosztu. Przy błędzie
bazy zapis jest ponawiany na wyjściu z operacji, a trwała awaria jest logowana
jako błąd; panel pokazuje dopuszczenia bez zapisanej odpowiedzi. Nie uznaje się
ich za zerowe zużycie.

Koszt jest szacunkiem standardowego Anthropic Messages API według cennika
z 2026-09-08, z osobnym naliczaniem wejścia, wyjścia, odczytu cache i zapisu
cache 5m/1h. Rejestruje wersję cennika i model faktycznej odpowiedzi.
Nieznane modele, niepełne usage lub dodatkowe mechanizmy rozliczeniowe pozostają
bez wyceny; panel ujawnia niepełne pokrycie. Nie jest to faktura ani pełne
rozliczenie historyczne.
Źródło: https://platform.claude.com/docs/en/about-claude/pricing

Migracja 0280 jest addytywna. Zmieniona wersja algorytmu punktacji unieważnia
stare wyniki leniwie przy odczycie. Nie przelicza automatycznie całej bazy.
Historyczne podejrzane stawki wymagają osobnego raportu i zatwierdzenia korekt.

## Weryfikacja

Szybkie testy lokalne: test_ai_audit_regressions, notes_insights_extractor,
match_justification, ai_quota_token_accounting, ai_quota_provider_gate,
ai_spend_alerts, ai_provider_health, candidate_profile_rate_contract,
ai_call_outside_transaction, scoring_service i scenariusze Radaru.
Frontend: type-check oraz testy Radaru, sesji, panelu AI i karty faktów z notatek.

CI uruchamia również test_ai_metering_postgres na PostgreSQL, migracje oraz
pozostałe wymagane testy repozytorium. Po wdrożeniu należy potwierdzić dokładny
SHA, health/deep health, podgląd i wyszukiwanie w Radarze, panel pomiaru oraz
kontrolną dostawę powiadomienia do zalogowanego administratora.
