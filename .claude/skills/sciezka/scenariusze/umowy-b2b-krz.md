# Scenariusz: umowa B2B z Generatora — KRZ przed podpisem

Reguły: `docs/claude/kontrakty/krz-przed-podpisem-umowy.md`,
`docs/claude/kontrakty/podpis-umowy-b2b-w-nexusie.md`.

Wybierz umowę „W trakcie” z rekrutacji, której autor jest rekruterem, a klient
ma przypisanego Delivery Leada (rejestr Generatora, „Bieżące”). Zapisz id
umowy i osób w paragonie, bez nazwisk.

| # | Kto | Co robi | Co widzi następna osoba |
|---|---|---|---|
| 1 | Rekruter (autor) | Rejestr → wiersz bez wyniku: plakietka „KRZ: nie sprawdzono”, brak „Wyślij do podpisu” | — |
| 2 | Rekruter | Generator → Nowa umowa → krok „Partner”: panel KRZ, „Otwórz KRZ: NIP …” (nowa karta z portalem, NIP w schowku), PESEL tylko w polu | — |
| 3 | Rekruter | Rejestr → „Sprawdź w KRZ” → „Jest wpis”, rodzaj, sygnatura → „Zapisz wynik” | DL klienta: dzwonek „Wpis w KRZ: umowa …” z linkiem do rejestru |
| 4 | Delivery Lead | Rejestr z dzwonka → „Zdecyduj o wpisie” → uzasadnienie → „Dopuść do podpisu” | Finanse: dzwonek „dopuszczona mimo wpisu”; autor: „Wyślij do podpisu” wraca |
| 5 | Rekruter | Próba „Zdecyduj” na cudzej umowie z wpisem — brak przycisku i 403 z API | — |
| 6 | Rekruter | Panel osoby w rekrutacji (sekcja „Do „Zatrudnionego””): umowa bez wyniku pokazuje bramkę KRZ zamiast prośby do DL | — |

Rola, która ma czegoś nie zrobić: Rekruter nie rozstrzyga wpisu (krok 5).
Na stagingu poczta idzie do Mailpita, a dzwonki sprawdzasz w bazie kopii
(`notifications`, typy `b2b_krz_entry` / `b2b_krz_allowed`).
