/**
 * Dziewięć uprawnień z ekranu Ustawienia → Zespół i dostęp → „Osoby i role”
 * (migracja 0409, kontrakt: docs/permissions-nine-switches-contract.md).
 *
 * `@stack`. Trzy rzeczy, które da się sprawdzić tylko na żywym stosie:
 * to, co administrator przełącza NA EKRANIE, decyduje w API; odmowa nazywa
 * brakującą pozycję; domyślne uprawnienia Finansów pozwalają założyć kontrakt
 * i zamówienie (zgłoszenie z 02.10.2026).
 */
import type { APIRequestContext, APIResponse } from "@playwright/test";

import { test, expect, expectStatus, jsonOf, uniqueSuffix } from "./helpers/api";
import { createCandidate, createClient } from "./helpers/entities";

const PANEL = "/api/admin/section-permissions";

interface Denial {
  detail: { code: string; permission?: string; message?: string };
}

/** 403 z nazwą uprawnienia — to samo zdanie widzi użytkownik w toaście. */
async function expectNamedDenial(
  response: APIResponse,
  permission: string,
  label: string,
  context: string
): Promise<void> {
  const body = await jsonOf<Denial>(response, 403, context);
  expect(body.detail.code, context).toBe("permission_denied");
  expect(body.detail.permission, context).toBe(permission);
  expect(body.detail.message, context).toContain(label);
}

async function revision(api: APIRequestContext): Promise<number> {
  const policy = await jsonOf<{ revision: number }>(await api.get(PANEL), 200, "GET panelu");
  return policy.revision;
}

async function setRolePermission(
  api: APIRequestContext,
  role: string,
  action: string,
  granted: boolean
): Promise<void> {
  await expectStatus(
    await api.put(`${PANEL}/roles`, {
      data: {
        revision: await revision(api),
        action_changes: [{ role, action, access: granted ? "manage" : "none" }],
      },
    }),
    200,
    `PUT ${PANEL}/roles (${role}: ${action})`
  );
}

/** Dodatkowe uprawnienie jednej osoby — to samo, co zapisuje okno „Edytuj użytkownika”. */
async function setUserPermission(
  api: APIRequestContext,
  userId: number,
  action: string,
  granted: boolean
): Promise<void> {
  await expectStatus(
    await api.put(`${PANEL}/users/${userId}`, {
      data: {
        revision: await revision(api),
        action_changes: [{ action, access: granted ? "manage" : "inherit" }],
      },
    }),
    200,
    `PUT ${PANEL}/users/${userId} (${action})`
  );
}

function isoDay(offsetDays: number): string {
  const day = new Date();
  day.setUTCDate(day.getUTCDate() + offsetDays);
  return day.toISOString().slice(0, 10);
}

test.describe("Uprawnienia z ekranu Osoby i role @stack", () => {
  test("Finanse zakładają kontrakt i zamówienie, statusu kontraktu nie zmieniają", async ({
    admin,
    apiAs,
  }) => {
    const finance = await apiAs("finance");
    const client = await createClient(admin.api);
    const candidate = await createCandidate(admin.api);
    const start = isoDay(-5);

    const contract = await jsonOf<{ id: number; status: string }>(
      await finance.api.post("/api/contracts", {
        data: {
          candidate_id: candidate.id,
          client_id: client.id,
          contract_type: "b2b",
          start_date: start,
          rate_candidate: 120,
          rate_unit: "hourly",
        },
      }),
      201,
      "Finanse: POST /api/contracts"
    );
    expect(contract.status).toBe("draft");

    await jsonOf<{ id: number }>(
      await finance.api.post(`/api/clients/${client.id}/orders`, {
        multipart: {
          contract_id: String(contract.id),
          title: `E2E-FIN-${contract.id}`,
          order_type: "periodic",
          order_status: "active",
          start_date: start,
          end_date: isoDay(60),
          rate_client: "160",
          rate_unit: "hourly",
        },
      }),
      201,
      "Finanse: POST /api/clients/{id}/orders"
    );

    // Status kontraktu i dane klienta to osobne pozycje — Finanse ich nie mają.
    await expectNamedDenial(
      await finance.api.patch(`/api/contracts/${contract.id}/status`, {
        data: { status: "ended" },
      }),
      "contract_status",
      "Zakończenie współpracy, zmiana statusu kontraktu",
      "Finanse: PATCH /api/contracts/{id}/status"
    );
    await expectNamedDenial(
      await finance.api.post("/api/clients", { data: { name: "E2E bez uprawnienia" } }),
      "clients_edit",
      "Klienci: dodawanie i edycja",
      "Finanse: POST /api/clients"
    );
  });

  test("uprawnienie nadane jednej osobie: kontrakt bez kwot tak, stawka — nazwana odmowa", async ({
    admin,
    apiAs,
  }) => {
    const client = await createClient(admin.api);
    const candidate = await createCandidate(admin.api);
    const draft = (extra: Record<string, unknown> = {}) => ({
      candidate_id: candidate.id,
      client_id: client.id,
      contract_type: "b2b",
      start_date: isoDay(-3),
      ...extra,
    });

    const before = await apiAs("recruiter");
    await expectNamedDenial(
      await before.api.post("/api/contracts", { data: draft() }),
      "contracts_orders_edit",
      "Kontrakty i zamówienia: tworzenie i edycja",
      "rekruter bez nadania: POST /api/contracts"
    );

    try {
      await setUserPermission(admin.api, before.userId, "contracts_orders_edit", true);
      // Panel mówi, skąd osoba ma uprawnienie: z nadania, nie z roli.
      const panel = await jsonOf<{ grants: string[]; effective: string[] }>(
        await admin.api.get(`${PANEL}/users/${before.userId}`),
        200,
        "GET panelu osoby"
      );
      expect(panel.grants).toContain("contracts_orders_edit");
      // Edycja pociąga podgląd Delivery, ale nie kwoty.
      expect(panel.effective).toContain("delivery_view");
      expect(panel.effective).not.toContain("amounts_view");

      const granted = await apiAs("recruiter");
      const contract = await jsonOf<{ id: number; status: string }>(
        await granted.api.post("/api/contracts", { data: draft() }),
        201,
        "rekruter z nadaniem: POST /api/contracts bez kwot"
      );
      expect(contract.status).toBe("draft");

      // Stawka to osobna pozycja — odmowa wymienia pola i nazywa uprawnienie.
      const refused = await jsonOf<{
        detail: { code: string; permission?: string; fields?: string[]; message?: string };
      }>(
        await granted.api.post("/api/contracts", {
          data: draft({ rate_candidate: 120, rate_unit: "hourly" }),
        }),
        403,
        "rekruter z nadaniem: POST /api/contracts ze stawką"
      );
      expect(refused.detail.code).toBe("finance_fields_forbidden");
      expect(refused.detail.permission).toBe("amounts_edit");
      expect(refused.detail.fields).toContain("rate_candidate");
      expect(refused.detail.message).toContain("Stawki i kwoty: zmiana");
    } finally {
      await setUserPermission(admin.api, before.userId, "contracts_orders_edit", false);
    }

    const after = await apiAs("recruiter");
    await expectNamedDenial(
      await after.api.post("/api/contracts", { data: draft() }),
      "contracts_orders_edit",
      "Kontrakty i zamówienia: tworzenie i edycja",
      "rekruter po cofnięciu nadania: POST /api/contracts"
    );
  });

  test("przełącznik roli na ekranie otwiera i zamyka trasę, a odmowa nazywa uprawnienie", async ({
    admin,
    apiAs,
    page,
  }) => {
    const newClient = () => ({ name: `E2E Klient ${uniqueSuffix()}`, status: "active" });

    const before = await apiAs("recruiter");
    await expectNamedDenial(
      await before.api.post("/api/clients", { data: newClient() }),
      "clients_edit",
      "Klienci: dodawanie i edycja",
      "rekruter przed włączeniem: POST /api/clients"
    );

    try {
      await page.goto("/settings?area=team&item=people&sub=permissions");
      await page
        .getByRole("group", { name: "Rola" })
        .getByRole("button", { name: "Rekruter", exact: true })
        .click();
      const edit = page.getByRole("switch", { name: "Rekruter: Klienci: dodawanie i edycja" });
      await expect(edit).not.toBeChecked();
      await edit.click();
      await expect(edit).toBeChecked();
      // Edycja pociąga podgląd — ekran pokazuje go jako włączony i zablokowany.
      const view = page.getByRole("switch", {
        name: "Rekruter: Klienci, kontrakty i zamówienia: podgląd",
      });
      await expect(view).toBeChecked();
      await expect(view).toBeDisabled();

      await page.getByRole("button", { name: "Zapisz zmiany" }).click();
      await page.getByRole("button", { name: "Potwierdź i zapisz" }).click();
      await expect(page.getByText(/Zapisano uprawnienia roli Rekruter/)).toBeVisible();

      // Zapis wylogował rekruterów; nowa sesja ma już uprawnienie.
      await expectStatus(
        await before.api.get("/api/auth/me"),
        401,
        "sesja rekrutera sprzed zmiany uprawnień"
      );
      const granted = await apiAs("recruiter");
      await jsonOf<{ id: number }>(
        await granted.api.post("/api/clients", { data: newClient() }),
        201,
        "rekruter po włączeniu: POST /api/clients"
      );
    } finally {
      await setRolePermission(admin.api, "recruiter", "clients_edit", false);
    }

    const after = await apiAs("recruiter");
    await expectNamedDenial(
      await after.api.post("/api/clients", { data: newClient() }),
      "clients_edit",
      "Klienci: dodawanie i edycja",
      "rekruter po wyłączeniu: POST /api/clients"
    );
  });
});
