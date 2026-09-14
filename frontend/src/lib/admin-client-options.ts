// Pełna lista klientów do pickera (B43 — przypisanie Delivery Leada).
//
// Strona struktury zespołu wysyłała `limit=500`, którego `GET /api/clients`
// nie zna — endpoint stronicuje po `page`/`page_size` (sufit 100) i oddawał
// domyślne 20 firm, więc klientów spoza pierwszej strony nie dało się wybrać.
// Zamiast podnosić sufit backendu, przechodzimy strony do `total`.
export interface ClientOption {
  id: number;
  name: string;
}

export interface ClientOptionsPage {
  items: ClientOption[];
  total: number;
}

/** Sufit `page_size` w `GET /api/clients`. */
export const CLIENT_OPTIONS_PAGE_SIZE = 100;

export async function fetchAllClientOptions(
  getPage: (page: number, pageSize: number) => Promise<ClientOptionsPage>,
  pageSize: number = CLIENT_OPTIONS_PAGE_SIZE,
): Promise<ClientOption[]> {
  const all: ClientOption[] = [];
  const seen = new Set<number>();
  let page = 1;
  for (;;) {
    const { items, total } = await getPage(page, pageSize);
    for (const item of items) {
      if (seen.has(item.id)) continue;
      seen.add(item.id);
      all.push(item);
    }
    // Pusta albo niepełna strona = koniec; `total` jest kotwicą, a nie jedynym
    // warunkiem — lista może zmaleć między stronami i pętla nie może się wieszać.
    if (items.length === 0 || items.length < pageSize || all.length >= total) break;
    page += 1;
  }
  return all;
}
