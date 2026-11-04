# Górny pasek przy 1280 px: forma zwarta i „+” zawsze w oknie (04.11.2026)
<!-- indeks: budżet grupy akcji przy 1280 px, forma zwarta do 1799 px, `TOPBAR_ADD_BUTTON_CLASS` przyklejony do krawędzi, przelew paska przewija się w bok -->

Pomiar na stagingu 04.11.2026, okno 1280 × 720, `/jobs/509921`: „+” kończył się
na x=1342 u Delivery Leada i x=1271 u admina, a pasek obcinał go bez żadnego
dostępu do reszty. Pasek rósł po jednej ikonie: „Umowy” 26.10 (44 px),
„P0 teraz” 27.10 (116 px), „Nowości” 28.10, „Nieobecni” i zgody z modułów Ludzi.

**Budżet przy 1280 px z przypiętym menu:** 1040 px paska − 40 px marginesów −
16 px odstępów − 200 px wyszukiwarki = **784 px na grupę akcji**. Na stagingu
pasek Delivery Leada zajmuje teraz 698 px, najciaśniejszy z `/preview/kpi-topbar`
(HoR z rolą DL i pigułką „Rozmowy”) 781 px. Nowy stały element w pasku = najpierw
pomiar na tym harnessie.

- **Forma zwarta do 1799 px** (`min-[1800px]:`), bo przy 1536 px pełne formy
  z pigułką „Zadzwoń: …” przelewały pasek o 86 px: „+” to sama ikona (36 zamiast
  81 px), „P0” nad liczbą (53 zamiast 107 px), odstęp między ikonami 4 px. Pełne
  zdania zostają w `aria-label` i dymku.
- **Wyszukiwarka ma gwarantowane 200 px, nie 220 px:** podpowiedź była ucięta także
  przy 220 px, a tych 20 px brakowało najciaśniejszemu paskowi.
- **Gdy i tego za mało** (P0, Nowości, zgody, nieobecni i pigułki w jednej chwili;
  u Delivery Leada 872 px), pasek przewija się w bok bez widocznego suwaka, a „+”
  zostaje przy prawej krawędzi (`TOPBAR_ADD_BUTTON_CLASS`). Dlatego rzadkie ikony
  stoją za „Rozmowami”: pod „+” chowają się najpierw one, a nie pigułka z telefonem.
  Żadna ikona nie znika, klawiatura też do niej dojdzie.
- **Panel w pasku musi iść przez portal** (`PopoverContent`, `DropdownMenuContent`):
  pasek ma `overflow`, więc panel pozycjonowany `absolute` zostałby ucięty.
- **Grupa nie może zaniżać swojej szerokości:** tekst, który da się złamać, zmniejszał
  jej `min-content` i ostatni przycisk wystawał poza nią (11 px u admina). Pilnuje
  `min-w-max` z `TOPBAR_ACTIONS_CLASS`, nowa ikona nie musi o tym pamiętać.

Pilnuje `e2e/responsive-preview.spec.ts` („górny pasek”, projekt `preview-chromium`):
„+” cały w oknie i klikalny przy 1280, 1366 i 1536 px, w tym na pasku „wszystko
naraz”, a ostatnia ikona po przewinięciu jest osiągalna. Replika paska w harnessie
ma P0 i „Umowy” jak prawdziwy pasek.
