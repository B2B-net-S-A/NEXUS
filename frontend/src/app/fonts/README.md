# Self-hosted fonts

Te pliki są w repo, żeby **build nie chodził do sieci**. `next/font/google`
pobiera `.woff2` z `fonts.gstatic.com` **w czasie builda**, a Coolify buduje
obraz lokalnie na serwerze przy **każdym** deployu (brak GHCR) — więc awaria
albo throttling Google Fonts wywalał deploy na produkcję, nie tylko CI:

```
src/app/layout.tsx
`next/font` error:
Failed to fetch `Fredoka` from Google Fonts.
```

Wpinane w `src/app/layout.tsx` przez `next/font/local`. Nie dodawaj `<link>`
do CDN-a jako obejścia — to tylko przenosi zależność sieciową z builda na
przeglądarkę użytkownika.

## Co tu leży

| Plik                     | Rodzina | Wagi                | Uwagi                             |
| ------------------------ | ------- | ------------------- | --------------------------------- |
| `Inter-Variable.woff2`   | Inter   | zmienna `100 900`   | oś `wght`; `opsz` przypięta na 14 |
| `Inter-Cyrillic.woff2`   | Inter   | zmienna `100 900`   | **tylko cyrylica**, za `unicode-range` |
| `Poppins-{400..800}.woff2` | Poppins | 400/500/600/700/800 | statyczne (Poppins nie ma VF)     |
| `Baloo2-Variable.woff2`  | Baloo 2 | zmienna `400..800`  | oś `wght` (jedyna); tryb „kids"   |

Pliki łacińskie zawierają **latin + latin-ext w jednym woff2** (Google serwuje
to jako dwa osobne pliki z `unicode-range`; rozbijanie tego u nas nic nie da,
bo interfejs jest po polsku, więc latin-ext i tak jest zawsze potrzebny).
latin-ext jest **wymagany** — polskie znaki `ą ć ę ł ń ś ż ź` (i wersalikowe
odpowiedniki) siedzą wyłącznie w nim; `ó`/`Ó` są w latin. Bez latin-ext polski
tekst leci fallbackiem na font systemowy i renderuje się wizualnie niespójnie.

### Cyrylica jest osobnym plikiem — i to jest cały sens `unicode-range`

`Inter-Cyrillic.woff2` NIE jest doklejony do `Inter-Variable.woff2`. Jest
deklarowany osobnym wywołaniem `localFont` z `declarations: [{ prop:
"unicode-range", … }]` i dopisany **za** rodziną główną w `--font-sans` /
`--font-display`. Dzięki temu przeglądarka pobiera go dopiero wtedy, gdy
faktycznie maluje znak z tego zakresu — sesja wyłącznie polska płaci **zero**.
Wrzucenie cyrylicy do pliku głównego kosztowałoby ~33 KiB **każdego**
użytkownika za glify, których większość nigdy nie zobaczy.

Realny przypadek to nie imiona kandydatów (CV i LinkedIn podają je
transliterowane), tylko `raw_cv_text` i notatki rekruterów — te trzymają tekst
w postaci, w jakiej przyszedł. Jedno CV wklejone po ukraińsku wystarczy, żeby
podgląd rozjechał się fallbackiem w środku akapitu.

Plaster cyryliczny **celowo nie zawiera ani jednego glifu łacińskiego**, więc
nie jest w stanie przejąć znaku należącego do rodziny głównej; kolejność
w stosie pozostaje jednoznaczna niezależnie od `unicode-range`.

### Dlaczego Baloo 2, a nie Fredoka

Fredoce brakuje **14 z 19** polskich znaków — pokrywa wyłącznie `ł Ł ó Ó`.
Nie jest to kosmetyka, bo tryb „kids" (`[data-kids="true"]`) podmienia font
**całego** interfejsu: `globals.css` przepina tam `--font-inter` ORAZ
`--font-poppins` na `--font-kids`. Przeglądarka podstawia zamiennik **per
znak**, więc „Rekrutację", „Ścieżka" czy „Wyślij" renderowały się z pojedynczymi
literami w innym kroju, o innej grubości i szerokości.

Baloo 2 zachowuje ten sam zaokrąglony, gruby charakter i pokrywa polski
komplet (sprawdzone glif po glifie). Oś `wght` ma zakres `400..800`, więc
wszystkie cztery deklarowane wagi (400/500/600/700) mieszczą się w niej —
Fredoka miała `300..700`, ale najniższa waga i tak nie była używana.

## Skąd pochodzą i na jakiej licencji

Źródło: **[github.com/google/fonts](https://github.com/google/fonts)**, gałąź
`main` (kanoniczne repo dystrybucyjne Google Fonts):

- `ofl/inter/Inter[opsz,wght].ttf` + `ofl/inter/OFL.txt` → `Inter-OFL.txt`
  (ten sam plik źródłowy daje `Inter-Variable.woff2` i `Inter-Cyrillic.woff2`,
  więc licencja jest jedna)
- `ofl/poppins/Poppins-{Regular,Medium,SemiBold,Bold,ExtraBold}.ttf` + `ofl/poppins/OFL.txt` → `Poppins-OFL.txt`
- `ofl/baloo2/Baloo2[wght].ttf` + `ofl/baloo2/OFL.txt` → `Baloo2-OFL.txt`

Wszystkie trzy: **SIL Open Font License 1.1** (potwierdzone w `METADATA.pb`:
`license: "OFL"` oraz w nagłówkach dołączonych plików `*-OFL.txt`). OFL 1.1
pozwala na redystrybucję plików fontów — także zmodyfikowanych (subset) — pod
warunkiem dołączenia treści licencji i noty o prawach autorskich, i zabrania
sprzedaży samych fontów. Dlatego pliki `*-OFL.txt` **muszą** zostać obok
`.woff2`. Nazwy rodzin nie zostały zmienione, bo Reserved Font Name nie jest
zastrzeżony w żadnej z tych trzech licencji (sekcja „with Reserved Font Name"
jest pusta).

## Jak zostały wygenerowane (i jak je odtworzyć)

Pliki są instancjonowane i subsetowane tak, **żeby były binarnie zgodne z tym,
co dziś serwuje `fonts.gstatic.com`** dla URL-i, które buduje `next/font/google`:

- `https://fonts.googleapis.com/css2?family=Inter:wght@100..900&display=swap`
- `https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700;800&display=swap`
- `https://fonts.googleapis.com/css2?family=Baloo+2:wght@400;500;600;700&display=swap`

Google w tych odpowiedziach przypina osie inne niż `wght` (Inter: `opsz`=14),
zrzuca hinting (`prep`) i zostawia wąski zestaw feature'ów OpenType — to samo
robi poniższy przepis. Baloo 2 ma tylko oś `wght`, więc nie ma czego przypinać.

```bash
pip install 'fonttools>=4.60' brotli
```

```python
from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

# unicode-range dla latin + latin-ext, przepisane z odpowiedzi Google Fonts,
# + 5 znaków łączących, które gstatic i tak trzyma w tych plastrach.
LATIN = ",".join("""
0000-00FF 0131 0152-0153 02BB-02BC 02C6 02DA 02DC 0304 0308 0329 2000-206F
20AC 2122 2191 2193 2212 2215 FEFF FFFD
0100-02BA 02BD-02C5 02C7-02CC 02CE-02D7 02DD-02FF 1D00-1DBF 1E00-1E9F
1EF2-1EFF 2020 20A0-20AB 20AD-20C0 2113 2C60-2C7F A720-A7FF
0300 0301 0303 0309 0323
""".split())

# cyrillic + cyrillic-ext, też z plastrów Google. Ukraińskie `і ї є` siedzą
# w 0400-045F, `ґ` w 0490-0491 — i to one, nie rosyjskie, są tu realnym
# przypadkiem. Ta sama lista MUSI wylądować w `unicode-range` w layout.tsx:
# rozjazd między plikiem a deklaracją znaczy albo pobieranie pliku bez potrzeby,
# albo znak bez glifu mimo pobranego pliku.
CYRILLIC = ",".join("""
0301 0400-045F 0490-0491 04B0-04B1 2116
0460-052F 1C80-1C88 20B4 2DE0-2DFF A640-A69F FE2E-FE2F
""".split())

FEATURES = "calt,ccmp,dnom,frac,locl,numr,pnum,tnum,liga,kern,mark,mkmk".split(",")

def build(src, dest, unicodes=LATIN, pin=None):
    font = TTFont(src)
    if pin:
        font = instancer.instantiateVariableFont(font, pin, updateFontNames=False)
        if "gvar" in font:  # instancer zostawia gvar bez wpisów dla części glifów
            gvar = font["gvar"]
            gvar.variations = {g: list(gvar.variations.get(g, []))
                               for g in font.getGlyphOrder()}
    o = subset.Options()
    o.layout_features = FEATURES
    o.hinting = False
    o.name_IDs, o.name_languages, o.name_legacy = ["*"], ["*"], True
    o.notdef_outline = o.glyph_names = o.legacy_kern = False
    o.recalc_bounds = o.recalc_timestamp = False
    o.drop_tables += ["DSIG"]
    s = subset.Subsetter(options=o)
    s.populate(unicodes=subset.parse_unicodes(unicodes))
    s.subset(font)
    font.flavor = "woff2"
    font.save(dest)

build("Inter[opsz,wght].ttf", "Inter-Variable.woff2", LATIN,    pin={"opsz": 14})
build("Inter[opsz,wght].ttf", "Inter-Cyrillic.woff2", CYRILLIC, pin={"opsz": 14})
build("Baloo2[wght].ttf",     "Baloo2-Variable.woff2", LATIN)
for weight, style in [(400,"Regular"),(500,"Medium"),(600,"SemiBold"),
                      (700,"Bold"),(800,"ExtraBold")]:
    build(f"Poppins-{style}.ttf", f"Poppins-{weight}.woff2")
```

Wynik zweryfikowany wobec plastrów z `fonts.gstatic.com`: identyczne `unitsPerEm`,
metryki `OS/2`/`hhea`, zestaw tabel i feature'ów GSUB/GPOS, oraz **identyczne
kontury i szerokości** wszystkich wspólnych glifów (po dekompozycji glifów
złożonych) — dla fontów zmiennych sprawdzone na wielu pozycjach osi `wght`.
Zasięg znaków lokalnych plików jest nadzbiorem tego, co gstatic serwuje w
plastrach latin + latin-ext.
