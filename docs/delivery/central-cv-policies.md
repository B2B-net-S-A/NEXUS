# Centralne reguły CV

## Zakres

Jeden katalog `backend/app/data/cv_policies.json`, publikowany do istniejących tabel reguł, publikacji i historii. Flaga wdrożenia `CV_CENTRAL_POLICIES_ENABLED` włącza publikację na starcie, wspólny resolver oraz blokadę zapisów DL. Starsze dokumenty bez `central_policy` zachowują dotychczasowy kontrakt.

Przypisania zweryfikowano względem `client_id`, `external_source=traffit` i `external_id` w produkcji. Santander korzysta z kanonicznego rekordu ERSTE (ex Santander), ID 103. Duplikaty importu i spółki zależne nie dziedziczą polityki po nazwie. Szablony Aliora i KIR sprawdzono w źródłowych dokumentach SharePoint. KIR nie wymienia osobnego wymogu notatki rekomendacyjnej.

Synchronizacja jest idempotentna i serializowana blokadą klienta. Zachowuje poprzednią publikację i archiwizuje szkic w historii; nie aktywuje instrukcji szkicu. Nie zmienia istniejącego ograniczenia dopasowania treści klienta.

## Przepływ

- Serwer ustala klienta z rekrutacji, wymusza język i automatyczny tryb. Kompletny Profil Championa pozwala na dopasowanie, niekompletny kontekst daje CV ogólne. Ograniczenie klienta pozostaje nadrzędne.
- Nazwa pliku i jedyny nagłówek dokumentu korzystają z jednej tłumaczonej wartości. Historyczne stanowiska kandydata są osobnymi faktami. Oznaczenie „CV ogólne” pozostaje w interfejsie; dokument nie zawiera etykiet „General CV” ani „Considered for”.
- Obie wersje językowe korzystają z tych samych zapisanych źródeł. Ponowienie pomija gotowy dokument i wykorzystuje istniejący zapis nieudanej wersji. Prywatne fakty podlegają retencji źródeł zadania.
- Wersje dokumentów zatwierdza istniejący edytor. Osobne potwierdzenie pakietu zapisuje wersje dokumentów, politykę, wersję wskazanej notatki i potwierdzenie sprawdzenia źródeł. Odcisk podglądu zapobiega zatwierdzeniu zmiany, której użytkownik nie widział.
- Nowe linki wymagają gotowego pakietu. Publiczny widok otrzymuje wyłącznie zatwierdzone wersje zamrożone w linku. Notatka nie jest automatycznie publikowana.
- Zgoda PKO jest związana ze źródłem CV, klientem, rekrutacją i numerem zapytania. Numer musi odpowiadać jednoznacznemu identyfikatorowi ZOB rekrutacji (w tytule lub polu referencji); wewnętrzny numer ATS nie jest numerem zapytania PKO. Prefiks ZOB jest normalizowany. Czytelność treści zgody potwierdza użytkownik; backend weryfikuje przypisanie oraz poprawność obrazu.

## Odbiór

Host-native: testy katalogu, nazewnictwa, migracji, blokady zapisów, pakietów, ponawiania i regresji generatora; type-check i testy interfejsu. Transakcyjny test synchronizacji wymaga PostgreSQL i wykonuje się w hosted CI. Bez lokalnego Dockera.

Przed odbiorem wymagane: zielone CI PR, merge, standardowe wdrożenie Coolify, włączenie flagi, dokładna rewizja i health/deep/Alembic oraz sprawdzenie generatora samodzielnego i rekrutacji w Chrome, w tym pobranych dokumentów. Nie wysyłać wiadomości klientom.
