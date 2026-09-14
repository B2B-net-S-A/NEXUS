import { describe, expect, it, vi } from "vitest";

import {
  CLIENT_OPTIONS_PAGE_SIZE,
  fetchAllClientOptions,
} from "@/lib/admin-client-options";

// B43: picker klienta przy przypisaniu Delivery Leada widział tylko pierwszą
// stronę `GET /api/clients` (`limit=500` nie istnieje po stronie backendu).
describe("fetchAllClientOptions", () => {
  const makeClients = (total: number) =>
    Array.from({ length: total }, (_, i) => ({ id: i + 1, name: `Klient ${i + 1}` }));

  it("przechodzi wszystkie strony aż do `total`", async () => {
    const all = makeClients(250);
    const getPage = vi.fn(async (page: number, pageSize: number) => ({
      items: all.slice((page - 1) * pageSize, page * pageSize),
      total: all.length,
    }));

    const result = await fetchAllClientOptions(getPage);

    expect(result).toHaveLength(250);
    expect(result.at(-1)?.id).toBe(250);
    expect(getPage).toHaveBeenCalledTimes(3);
    expect(getPage).toHaveBeenNthCalledWith(1, 1, CLIENT_OPTIONS_PAGE_SIZE);
    expect(getPage).toHaveBeenNthCalledWith(3, 3, CLIENT_OPTIONS_PAGE_SIZE);
  });

  it("jedna niepełna strona = jedno zapytanie", async () => {
    const getPage = vi.fn(async () => ({ items: makeClients(7), total: 7 }));
    const result = await fetchAllClientOptions(getPage);
    expect(result).toHaveLength(7);
    expect(getPage).toHaveBeenCalledTimes(1);
  });

  it("nie wiesza się, gdy lista zmalała między stronami, i nie dubluje id", async () => {
    // `total` z pierwszej strony mówi 150, ale druga strona przychodzi pusta.
    const first = makeClients(100);
    const getPage = vi.fn(async (page: number) =>
      page === 1 ? { items: first, total: 150 } : { items: [], total: 150 },
    );
    const result = await fetchAllClientOptions(getPage);
    expect(result).toHaveLength(100);
    expect(getPage).toHaveBeenCalledTimes(2);

    // Ten sam klient na dwóch stronach (przesunięcie listy) — jeden wiersz.
    const shifted = vi.fn(async (page: number) =>
      page === 1
        ? { items: makeClients(100), total: 101 }
        : { items: [{ id: 100, name: "Klient 100" }, { id: 101, name: "Klient 101" }], total: 101 },
    );
    const deduped = await fetchAllClientOptions(shifted);
    expect(deduped).toHaveLength(101);
    expect(new Set(deduped.map((c) => c.id)).size).toBe(101);
  });
});
