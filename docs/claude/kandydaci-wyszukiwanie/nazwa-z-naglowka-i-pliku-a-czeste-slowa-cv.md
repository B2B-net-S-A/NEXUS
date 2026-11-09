# Nazwa z nagłówka CV i z nazwy pliku: same częste słowa CV to nie osoba

Pomiar z 05.11.2026 na kopii produkcji z 04.11 (68 280 profili, 64 964 tekstów CV).
21 profili miało w `name` i `lastname` nagłówek sekcji, miasto, stanowisko albo
technologię. Nazwę dawał kod, nie model:

- `_split_name_from_header` (model zostawił puste pole albo krok modelu nie dał wyniku),
- `name_from_filename` (w nazwie pliku stanowisko przed nazwą osoby),
- pole z Traffita albo profil testowy.

Model z pewnością większą od zera podał takie słowa w 1 odczycie na 57 724 przy
liście z progu 5% i w 6 przy progu 4%, z czego 5 to nazwy potwierdzone mailem albo
LinkedInem. Dlatego odczytu modelu ta reguła nie rusza.

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

## Taka nazwa już w profilu: bramka tożsamości nie ma z czym porównać

`evaluate_identity_match` traktuje nazwę profilu z samych częstych słów jak `?`:
`candidate_identity_complete = false`, wynik `inconclusive`, także gdy odczyt podaje te
same słowa. `evidence.candidate_name_only_common_cv_words` pozwala policzyć takie decyzje.

Pomiar z 05.11.2026 na kopii z 04.11: 25 z 68 280 profili ma taką nazwę, a słowo nazwy
jest w mailu tylko w 2 profilach testowych. `confirmed_mismatch` mają 2 ze 191 decyzji:

- 529068 powstał z pliku, który 11 godzin później trafił do kwarantanny. Profil osoby
  z tego pliku założył Traffit 12 godzin po decyzji.
- 334057 to pusty profil z Traffita. Człowiek wgrał na niego plik osoby, której profil
  powstał 11 godzin po decyzji. Nie da się ustalić, czy plik był cudzy.

Porównanie maila w pliku z mailem w profilu nie rozstrzyga takich przypadków, bo
kwarantanna czyści kontakt z profilu (tu 7 i 5 pól). Sprawdź oś czasu: `created_from_cv`,
`cv_uploaded` i datę założenia drugiego profilu.

Narażone były też 6 profili z własnym mailem i telefonem w tekście CV. Przy 2 z nich
zapisany odczyt modelu dawał `confirmed_mismatch` na własnym CV, a 4 były w zasięgu
`backfill_cv_fields`, który od #3046 idzie przez bramkę.

- Koszt: cudzy plik wgrany na taki profil nie trafi do kwarantanny. Tak samo jest
  z profilem `?` i `Not Provided`.
- Reguła dotyczy tylko nazwy w profilu. Odczyt z samych częstych słów nadal daje
  `confirmed_mismatch`, bo tej strony pilnuje parser, a odczytu modelu reguła nie rusza.
- Decyzja `confirmed_mismatch` zapisana wcześniej zostaje. Zwalnia ją tylko człowiek.

## Czego ta reguła nie załatwia

- Działa na nowe odczyty. Nazw zapisanych w profilach sama nie poprawia.
- Nagłówek daje nadal inne słowa spoza listy, np. nazwę firmy. Kwarantannę w takim
  przypadku opisuje `kwarantanna-czyszczenie-faktow.md`.
- Odcisk nazwy zgodny z innym profilem nie dowodzi, że to ta sama osoba. Najpierw
  policz częstość słów nazwy w tekstach CV.
