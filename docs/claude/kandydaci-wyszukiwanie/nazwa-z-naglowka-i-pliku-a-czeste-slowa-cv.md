# Nazwa z nagłówka CV i z nazwy pliku: same częste słowa CV to nie osoba

Pomiar z 05.11.2026 na kopii produkcji z 04.11 (68 280 profili, 64 964 tekstów CV).
21 profili miało w `name` i `lastname` nagłówek sekcji, miasto, stanowisko albo
technologię. Nazwę dawał kod, nie model:

- `_split_name_from_header` (model zostawił puste pole albo krok modelu nie dał wyniku),
- `name_from_filename` (w nazwie pliku stanowisko przed nazwą osoby),
- pole z Traffita albo profil testowy.

Model z pewnością większą od zera podał takie słowa w 1 odczycie na 57 724, więc
odczytu modelu ta reguła nie rusza.

## Reguła

- `only_common_cv_words` z `services/cv_common_words.py` odrzuca nazwę tylko wtedy,
  gdy na liście są wszystkie jej słowa. Jedno rzadkie słowo wystarcza, bo częste
  słowo bywa prawdziwym nazwiskiem.
- Reguła nagłówka przechodzi wtedy do kolejnej linii. Nazwa pliku odrzuca częste
  słowa i bierze to, co stoi dalej, a gdy zostaje mniej niż dwa, nie daje nazwy.
- Próg 4,5% wynika z pomiaru. Przy nim zmienia się 6394 odczytów nagłówka i 2645
  nazw z pliku, a strat nazw potwierdzonych mailem albo LinkedInem jest 0. Przy 4%
  jest ich 6.
- `jan` i `maja` są poza listą, bo to przede wszystkim imiona. Nie dopisuj tam imion
  ani nazwisk: repo jest publiczne, a lista ma zawierać wyłącznie słowa z treści CV.

## Czego ta reguła nie załatwia

- Działa na nowe odczyty. Nazw zapisanych w profilach sama nie poprawia.
- Nagłówek daje nadal inne słowa spoza listy, np. nazwę firmy. Kwarantannę w takim
  przypadku opisuje `kwarantanna-czyszczenie-faktow.md`.
- Odcisk nazwy zgodny z innym profilem nie dowodzi, że to ta sama osoba. Najpierw
  policz częstość słów nazwy w tekstach CV.
