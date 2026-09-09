# CV-09: rozliczenie wywołań drugiej wersji językowej

Generowanie drugiego języka otrzymywało osobny zapis limitu, ale wywołania
modelu pozostawały w kontekście operacji pierwszego języka. Utrudniało to
przypisanie kosztów do konkretnej operacji; nie dowodziło błędnej sumy opłat.

Oba workery zachowują teraz rzeczywisty QuotaState drugiego przyjęcia i używają
go podczas generowania. Po zakończeniu lub błędzie przywracany jest kontekst
pierwszej operacji. Odmowa limitu nie uruchamia drugiego modelu ani nie usuwa
gotowej pierwszej wersji.

Weryfikacja: 11 testów źródeł i rozliczania drugiego języka przeszło lokalnie;
Ruff bez uwag. Testy obejmują oba workery, sukces, błąd dostawcy i odmowę limitu,
w tym propagację kontekstu do rzeczywistego threadpoolu. Nie wywołują modelu.
Wdrożenie i dowód produkcyjny pozostają do zebrania.
