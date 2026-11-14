/**
 * Karta „Dane do listy płac” w kartotece (K7a): wejście dla Administracji
 * współpracy bez Księgowości. Moduł wyłączony albo brak prawa (404/403) =
 * karty nie ma; braki danych widać z nazwy pola; własnych danych nie zmienia
 * się samemu. Dane fikcyjne.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  status: 200 as number,
  data: null as unknown,
}));

vi.mock("@/lib/api", () => ({
  api: {
    get: async (url: string) => {
      if (url === "/api/hr/payroll-lists/people/users/7") {
        if (mocks.status === 200) return { data: mocks.data };
        throw Object.assign(new Error(url), { response: { status: mocks.status } });
      }
      throw Object.assign(new Error(url), { response: { status: 404 } });
    },
    put: vi.fn(),
    post: vi.fn(),
  },
}));
vi.mock("@/components/accounting/payroll/PersonDataDialog", () => ({
  PersonDataDialog: ({ open }: { open: boolean }) => (open ? <div>okno-danych</div> : null),
}));

import { PayrollDataCard } from "../PayrollDataCard";

function person(extra: Record<string, unknown> = {}) {
  return {
    subject: "u7",
    user_id: 7,
    candidate_id: null,
    name: "Osoba Testowa",
    exists: true,
    can_edit: true,
    pesel_masked: "•••••••1234",
    missing: ["address"],
    missing_labels: ["adres zamieszkania"],
    blocks_calculation: [],
    version: 2,
    ...extra,
  };
}

function renderCard() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <PayrollDataCard userId={7} kind="uop" enabled />
    </QueryClientProvider>,
  );
}

describe("PayrollDataCard", () => {
  beforeEach(() => {
    mocks.status = 200;
    mocks.data = person();
  });

  it("shows masked PESEL, missing fields and the edit button", async () => {
    renderCard();
    expect(await screen.findByText("Dane do listy płac (ZUS i PIT)")).toBeTruthy();
    expect(screen.getByText(/PESEL •••••••1234/)).toBeTruthy();
    expect(screen.getByText("Brakuje: adres zamieszkania.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Zmień" })).toBeTruthy();
  });

  it("renders nothing when the module is closed or access is refused", async () => {
    mocks.status = 404;
    const { container } = renderCard();
    await waitFor(() => expect(container.textContent).toBe(""));
  });

  it("own data is read-only", async () => {
    mocks.data = person({ can_edit: false, missing: [], missing_labels: [] });
    renderCard();
    expect(await screen.findByText(/Swoich danych płacowych nie zmieniasz sam/)).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
  });
});
