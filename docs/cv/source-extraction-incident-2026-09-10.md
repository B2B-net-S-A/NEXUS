# Awaria generacji CV — 10.09.2026

Nowy etap ekstrakcji faktów z PR #1444 zatrzymywał generowanie czytelnych CV. PR #1476 poprawił transport długich odpowiedzi i część obsługi kolumn PDF, ale produkcyjna próba na zgłoszonym czterostronicowym PDF nadal zakończyła się błędem ekstrakcji po około 161 sekundach. Sam zielony healthcheck i otwarcie edytora nie potwierdziły działania generatora.

Potwierdzony problem konstrukcyjny: model przepisywał zarówno fakty, jak i długie cytaty, po czym kod wymagał zgodności tekstowej wszystkich pól. Układ kolumn i dzielenie słów tworzyły fałszywe odrzucenia. Dokładnego kodu wcześniejszej produkcyjnej odmowy nie zapisano w rekordzie zadania; nie należy przedstawiać hipotezy o konkretnym polu jako potwierdzonej diagnozy.

Poprawka zastępuje przepisywanie cytatów wskazaniem numerów oryginalnych wierszy. Kod rozwiązuje zakresy do niezmienionego źródła i zachowuje jego offsety i hash. Walidacja nadal wymaga pokrycia wszystkich faktów. Wąskie reguły obsługują dzielenie słów na końcu wiersza i datę w lewej kolumnie przerywającą opis obowiązków. Nie zmieniają wielkości liter ani końców i precyzji dat. Różne separatory tego samego zakresu dat są dopuszczalne; myślniki wewnątrz słów pozostają znaczące. Przy błędnym przypisaniu model dostaje jedną próbę korekty w tym samym budżecie czasu. Końcowa kontrola semantyczna pozostaje obowiązkowa i również korzysta z numerów wierszy.

Stały kod odmowy trafia do istniejącego pola `cv_generation_jobs.error_code`. Dostępna automatyka GitHuba może odczytać ten kod bez panelu Coolify, treści CV i surowej odpowiedzi modelu. Poprawiono także sprzątanie krótkich zadań diagnostycznych po niejednoznacznym wyniku ich utworzenia.

Walidacja przed CI: 152 testy host-native, w tym oba formaty dowodów, niepoprawne zakresy, daty w kolumnach, podziały słów, ograniczenie liczby prób, wspólny budżet czasu, odrzucanie zmyślonych kompetencji i zachowanie końcowej kontroli. Nie używano lokalnego Dockera. Odbiór produkcyjny pozostaje otwarty do faktycznego utworzenia i sprawdzenia dokumentu; wynik jest aktualizowany w PR.

Rekomendacje do dalszej oceny jakości:

- Warunkiem kolejnego wydania generatora powinien być pełny przebieg na czytelnych CV w różnych układach, językach i trybach, obok testów wykrywania zmyśleń. Sama skuteczność odrzucania błędów nie mierzy użyteczności.
- Mierzyć osobno błędy odczytu, ekstrakcji, redakcji i końcowej kontroli oraz czas do gotowego dokumentu. Alarm powinien wykrywać wzrost fałszywych odmów.
- Ustawienia klienta nadal stosować dopiero po zebraniu pełnego doświadczenia. Zestaw regresyjny powinien obejmować ograniczenie liczby ról bez zmiany całkowitego stażu oraz podsumowania bez dopisywania kompetencji z oferty.
