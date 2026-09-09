# CV-08: gotowość zależna od trybu — 9 września, 17:44 CEST

Lista rekrutacji, walidacja przed kwotą i worker rozróżniają Przepisanie/Redakcję od trybu Pod rekrutację. Neutralne tryby nie wymagają Championa ani notatek, chyba że opublikowana reguła klienta nakłada taki wymóg. Tryb dopasowany wymaga Championa. Lista stosuje najpierw blokadę reguły, następnie sufit klienta; przekazuje konkretne braki i minimalną długość notatek. Oba formularze odświeżają gotowość po zmianie trybu i pokazują opcjonalne źródła bez ostrzeżenia.

Weryfikacja: 78 testów backendu (w tym 15 nowych przypadków gotowości/workera/polityki), 15 testów strony, TypeScript i Ruff. Brak lokalnej bazy lub wywołań modeli. CI i odbiór produkcyjny jeszcze wymagane. Pakiet zależy od preflight uploadu #1459 i historii/kontekstu #1450.

CV-08 nadal częściowe: jawny wybór i zamrożenie pełnych źródeł do zadania pozostają otwarte. Minimalna liczba znaków jest istniejącym kontraktem klienta; nie stanowi potwierdzenia jakości screeningu. Nowe ustalenia audytu o podsumowaniach AI i pytaniach jako dowodach wymagają osobnej poprawy źródeł oraz bramki faktów.
