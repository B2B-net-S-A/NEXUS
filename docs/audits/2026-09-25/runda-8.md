# Audyt NEXUS — runda 8 (27.09.2026)

Baza: `66b016c46` (main po rundzie 6 + PR rundy 7 #1864). Naprawa: PR rundy 8 (gałąź `claude/audit-r8-fixes`).

## Przebieg

- **Audyt:** 20 agentów tylko do odczytu. Trzech sprawdzało poprawki rundy 7 (V1 pieniądze, V2 rekrutacja, V3 logi/CV/M365), piętnastu obszary dotąd płytko audytowane (N1–N15), dwóch przekrojowo (X1 wzorce, X2 generator B2B).
- **Znaleziska:** 149, w tym 7 wysokich (N5-1, N9-1, N10-1, N11-1, N14-1, X2-1, X2-2). 12 było lukami poprawek z poprzednich rund (R4-11, R4-22/23, R6-J2, R7-V2-5, R7-X4-2/4/5, R7-V1-7, R7-V5-2, R7-X5, IC-1, A6-4).
- **Naprawa:** 17 agentów, każdy we własnym worktree i obszarze. Scalenie dało konflikty wyłącznie w stemplach instrukcji zamówień i przewodników (4 gałęzie ruszały instrukcję zamówień); rozwiązane jednym przestemplowaniem.
- **Po scaleniu:** 4 przeglądy kodu (pieniądze, rekrutacja, integracje, frontend) i pełne CI. Przeglądy złapały 3 problemy w samych poprawkach, pełne CI — 5 testów (4 nieaktualne kontrakty testów po zamierzonej zmianie zachowania + 1 błąd poprawki).
- **Druga fala:** trzy decyzje Artura (niżej) wdrożone osobnymi agentami na tej samej gałęzi.

## Decyzje Artura

| Temat | Decyzja |
|---|---|
| Akademia: rezygnacja po podpisie umowy (N2-7) | Pozwól „Zrezygnował sam”; „Przywróć” czyści podpis i edycję |
| Import MD: nowy numer SAP u klienta kosztowego (V1-5) | Numer w kształcie zamówień tego klienta wiąże wiersz, także gdy zamówienia nie ma |
| Liga Mistrzów: punkty za rozmowę | Z rozmów u klienta (`client_interview`), od razu — także bieżący kwartał |
| Kalendarz: runda 1 bez debriefu, runda 2 zaplanowana | Oba przypomnienia równolegle (debrief rundy 1 i prep do rundy 2) |
| Strona kariery: sekcje wyłączone przełącznikiem | Całkiem znikają z danych publicznych, grafiki, meta i portali |
| Nazwiska w skryptach wzorów (N2-4, X2-10) | Zostają (decyzja z rundy 7) |

## Najważniejsze poprawki

- **Pieniądze i kontrakty:** dzień zakończenia = data końca umowy (nie pierwsze wypowiedzenie) w archiwum, analizie odejść, rok do roku, kampaniach i kreatorze metryk; kontraktu usuniętego lub scalonego klienta nie da się wznowić żadną drogą; scalanie kontraktów nie gubi zaplanowanego wypowiedzenia; prognoza z datą startu zamówienia; zera zamiast pustych kwot tam, gdzie klient nie ma kontraktów.
- **Zamówienia MD:** druga zaplanowana zamiana tej samej osoby = 409 (wcześniej podwójna pula); nieudane przeniesienie anuluje zastępstwo; „Przywróć anulowane” nie wskrzesza zakończonych umów; pasek MD bez opcji nie gubi przekroczenia.
- **Generator B2B:** podpis i „Zatrudniony” podpinają istniejący kontrakt osoby u klienta zamiast zakładać drugi; przywrócenie z zawieszenia wymaga wglądu w stawki; numer porządkowy zajęty we wszystkich latach; czytelne 409/422 zamiast 500.
- **Rekrutacja:** jedna reguła wyboru CV spoza NEXUSA dla QC i Cpro; reguła osoby od Cpro poza wyłącznikiem QC; blokada 12 h bez przedłużania; przydział requestów zwalnia prowadzącego z automatu za urlop i działa w trybie `off`; follow-up i dzwonki omijają nieaktywne konta.
- **Kalendarz i prepy:** ocena prepu zgodna z prep-kitem, awaria modelu ≠ „słaby”; rozmowa u klienta nie znika po usunięciu blokady w Outlooku; przypomnienie po przełożeniu; transkrypt odbytego prepu mimo usunięcia spotkania.
- **Indeks i przeglądy:** intencja naprawy po nieudanym embedzie; status ofert w Qdrancie aktualny po każdej zmianie; jednorazowe wznowienie martwych intencji; niepełny nocny przegląd nie zamyka tematu.
- **Pulpit, alerty, metryki:** skaner zapisanych wyszukiwań nie przerywa się na jednym zepsutym zapisie i pisze dziennik paczkami; kreator metryk sprawdza uprawnienia przed cache; linki w kafelkach przez `safeInternalPath`.
- **Front:** stany awarii zamiast pustki w 6 miejscach; LinkedIn w profilu; brak własnych `retry`.
- **Logi, M365, integracje:** nazwy plików poza logami; e-mail w CV i podpisie Outlooka w czasie liniowym (4 s → < 1 ms na 16 KB); prywatne spotkania bez powiązania z kandydatem; nagrobki Talent Radaru; okna pól CV w Traffit bez dziur.
- **Jarvis:** połączenie DB oddane przed turą; pełna karta akcji; czas polski; akcje nie wiszą w `confirmed`.
- **Migracje:** downgrade 0381/0383/0388 odmawia zamiast kasować dane.

## Znalezione, poza zakresem tej rundy

- Podgląd pliku Word w Finansach → „Zamówienia PDF” (`OrderPdfViewer`) nadal czyta go jako PDF; ZIP ma już właściwe rozszerzenie.
- `request_matching_context.py` liczy odcisk rankingu z surowego profilu Championa — pierwszy zapis profilu w starym kształcie może dać 409 przy odczycie istniejącego pełnego przeglądu.
- Notatki z telefonów follow-up nadal trafiają do promptów oceny prepu, podsumowania aktywności i pakietów CV (w QC CV już nie).
- `contract_termination_sync.py:528` i `contract_termination_reversal.py:683` nadal biorą datę pierwszego wypowiedzenia; `insights_clients` zamienia przychód 0 na „—”.
- Stany ogłoszeń u dostawcy RocketJobs/JustJoin.IT (moderacja, zamknięte) — do potwierdzenia na pierwszym prawdziwym ogłoszeniu.
- `SCREENING_VERSION=3` w Akademii: po wdrożeniu wszystkie „Luna odłożyła” wracają raz do sortowania (jedno wywołanie Luny na osobę).
- Zmiana adresu linku rekrutacji z nazwą klienta łamie wpis już wrzucony na LinkedIna (bez powiadomienia).

## Sprawdzone i czyste

Lustro DDL w `entrypoint.sh`, CHECK-i i JSON `null` (N15); płacące konkursy poza punktacją za rozmowę (kolejność nagród, remisy, migawki progów); kolejność blokad kontrakt → zamówienia w nowych ścieżkach; redakcja kwot DL w nowych polach; `client_safe_screening` na białej liście dla share portalu i generatora CV.
