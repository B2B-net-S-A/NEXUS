/**
 * Kandydat: utworzenie przez API → ponowny odczyt → widoczny w UI → duplikat.
 *
 * `@stack` — działa wyłącznie na efemerycznym stacku E2E (zapisuje dane).
 * Dawna wersja wołała API bez tokena (401 spełniało `status < 500`) i
 * akceptowała dowolny kod poniżej 500 dla duplikatu, który w rzeczywistości
 * kończył się 500. Backend zwraca teraz 409 (test pytest obok tej poprawki).
 */
import { test, expect, expectStatus, jsonOf } from "./helpers/api";
import { createCandidate } from "./helpers/entities";

test.describe("Kandydat @stack", () => {
  test("utworzony kandydat zgadza się przy ponownym odczycie i otwiera się w UI", async ({
    admin,
    page,
  }) => {
    const created = await createCandidate(admin.api, { phone: "+48500000099" });

    const reread = await jsonOf<{ id: number; email: string; lastname: string; phone: string }>(
      await admin.api.get(`/api/candidates/${created.id}`),
      200,
      "GET /api/candidates/{id}"
    );
    expect(reread).toMatchObject({
      id: created.id,
      email: created.email,
      lastname: created.lastname,
      phone: "+48500000099",
    });

    await page.goto(`/candidates/${created.id}`);
    await expect(page.getByText(created.lastname).first()).toBeVisible();
  });

  test("drugi kandydat z tym samym e-mailem dostaje 409 i nie powstaje", async ({ admin }) => {
    const first = await createCandidate(admin.api);

    const duplicate = await admin.api.post("/api/candidates", {
      data: { name: "Ewa", lastname: "Duplikat", email: first.email },
    });
    await expectStatus(duplicate, 409, "duplikat e-maila");
    expect((await duplicate.json()).detail).toBe("Kandydat z tym adresem e-mail już istnieje.");

    // `q` to wyszukiwanie rozmyte (zwraca też podobnych kandydatów), więc
    // liczymy wyłącznie rekordy z DOKŁADNIE tym adresem.
    const search = await jsonOf<{ items: Array<{ id: number; email: string | null }> }>(
      await admin.api.get(`/api/candidates?q=${encodeURIComponent(first.email)}&page_size=100`),
      200,
      "GET /api/candidates?q"
    );
    const sameEmail = search.items.filter((item) => item.email === first.email);
    expect(sameEmail.map((item) => item.id)).toEqual([first.id]);
  });
});
