# Rdzeń nazwy firmy i wariant, który rozlewa wiersz wymagań (07.11.2026)

Decyzja Artura z 07.11.2026 („Napraw teraz”, makieta M3 w
https://claude.ai/artifact/U5xPzXiKJXixweYv5M8v7n). W 789198 (Dynamics 365)
krytyczny wiersz miał wariant `microsoft*`, który edytor podsunął jednym
kliknięciem przy zdaniu „Microsoft Dynamics 365 CE/CRM”. Wiersz znajdował
21 314 osób zamiast 692, więc bramka krytycznych przepuszczała każdego
z „Microsoft” w CV.

- **Podpowiedź zamiast zdania nie daje rdzenia nazwy firmy**
  (`requirement_phrase._vendor_words`). Słowo, które zaczyna co najmniej
  `_VENDOR_MIN_PRODUCTS` (3) wielowyrazowych haseł słownika („Microsoft”,
  „Apache”, „Azure”), nie dostaje gwiazdki, gdy w zdaniu stoi produkt ze
  słownika. Produkt jest już pierwszą podpowiedzią. Sama nazwa firmy bez
  produktu („projekty dla Microsoftu”) dalej daje `microsoft*`. Lista firm
  bierze się ze słownika, nie z kodu.
- **Ostrzeżenie pod wierszem** (`BroadVariantCallout`, reguła
  `lib/requirement-rows.broadVariant`): wiersz „musi mieć” albo krytyczny, który
  ma rdzeń z gwiazdką i drugie słowo, liczy słowa osobno. Ostrzeżenie pojawia się,
  gdy rdzeń ma co najmniej `BROAD_VARIANT_RATIO` (5) razy więcej osób niż
  najszersze z pozostałych słów i co najmniej 500 osób. „Usuń” zdejmuje sam
  rdzeń, reszta wariantów zostaje. Rdzeń odmiany obok słowa z maila
  („bankow*” przy „bankowości”) nie ostrzega. Zwykłe wiersze bez gwiazdki
  nie wysyłają dodatkowych zapytań o liczby.
- **Słowo z gwiazdką nie dostaje podpowiedzi słownika** („Słownik nie zna
  microsoft*. Może chodzi o Microsoft 365?”). Rdzeń to składnia
  wyszukiwania, a dopisanie hasła tylko poszerzało wiersz.
- Zapisane wiersze się nie zmieniają: ostrzeżenie widać w Profilu Championa
  i decyduje Delivery Lead.
