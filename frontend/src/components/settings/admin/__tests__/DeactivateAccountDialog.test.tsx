import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();

vi.mock("@/lib/api", () => {
  const client = { get: (...a: unknown[]) => get(...a) };
  return { __esModule: true, default: client, api: client };
});

import { DeactivateAccountDialog } from "@/components/settings/admin/DeactivateAccountDialog";

const USER = { id: 227, name: "Anna Przykładowa", email: "anna@example.com" };

function renderDialog(onConfirm = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <DeactivateAccountDialog user={USER} loading={false} onConfirm={onConfirm} onCancel={vi.fn()} />
    </QueryClientProvider>,
  );
  return onConfirm;
}

describe("DeactivateAccountDialog", () => {
  beforeEach(() => vi.clearAllMocks());

  it("pokazuje, ilu kandydatów przejmie który Delivery Lead", async () => {
    get.mockResolvedValue({
      data: {
        user_id: 227,
        pairs: 104,
        jobs: 9,
        unassigned: 0,
        caretakers: [
          {
            user_id: 86,
            name: "Maria Opiekunka",
            via: ["job_dl"],
            pairs: 78,
            jobs: 7,
            clients: ["Bank Przykładowy"],
            columns: { client_interview: 3, new: 75 },
          },
          {
            user_id: 90,
            name: "Head Przykładowy",
            via: ["hor"],
            pairs: 26,
            jobs: 2,
            clients: [],
            columns: { screening: 26 },
          },
        ],
      },
    });
    const onConfirm = renderDialog();
    expect(get).toHaveBeenCalledWith("/api/admin/users/227/departure-preview");
    expect(await screen.findByText("Maria Opiekunka")).toBeInTheDocument();
    expect(screen.getByText(/104 osoby/)).toBeInTheDocument();
    expect(screen.getByText("Bank Przykładowy · 7 rekrutacji")).toBeInTheDocument();
    expect(screen.getByText("3 rozmowa u klienta · 75 nowi")).toBeInTheDocument();
    expect(screen.getByText(/Head of Recruitment — rekrutacje bez DL-a/)).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "Wyłącz konto i przekaż Delivery Leadom" }),
    );
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("konto bez kandydatów dostaje zwykłe potwierdzenie", async () => {
    get.mockResolvedValue({
      data: { user_id: 227, pairs: 0, jobs: 0, unassigned: 0, caretakers: [] },
    });
    renderDialog();
    expect(
      await screen.findByText("Ta osoba nie prowadzi kandydatów w otwartych rekrutacjach."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Wyłącz konto" })).toBeEnabled();
  });

  it("awaria podglądu nie udaje braku kandydatów i nie blokuje wyłączenia", async () => {
    get.mockImplementation(() => Promise.reject(new Error("boom")));
    renderDialog();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Kandydaci i tak przejdą do Delivery Leadów po wyłączeniu.",
    );
    expect(
      screen.queryByText("Ta osoba nie prowadzi kandydatów w otwartych rekrutacjach."),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Wyłącz konto" })).toBeEnabled();
  });
});
