import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { previewOverview } from "@/components/trainee/preview-fixtures";
import { TraineesPanel } from "@/components/trainee/TraineesPanel";
import { traineeApi, traineeKeys } from "@/lib/api/trainee";

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

const REAL = { ...traineeApi };

function renderPanel(seed = true) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity }, mutations: { retry: false } },
  });
  if (seed) client.setQueryData(traineeKeys.overview(), previewOverview());
  return render(
    <QueryClientProvider client={client}>
      <TraineesPanel />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  Object.assign(traineeApi, {
    overview: vi.fn(async () => previewOverview()),
    decision: vi.fn(async () => ({ ok: true })),
  });
});

afterEach(() => {
  Object.assign(traineeApi, REAL);
});

describe("TraineesPanel", () => {
  it("awaria to błąd z ponowieniem, nie pusta tabela", async () => {
    traineeApi.overview = vi.fn(async () => {
      throw new Error("500");
    });
    renderPanel(false);
    expect(await screen.findByRole("alert")).toHaveTextContent("Nie udało się wczytać panelu praktykantów");
  });

  it("baner decyzji; zmiana roli pyta o potwierdzenie z „Moimi ludźmi” domyślnie zaznaczonymi", async () => {
    renderPanel();
    const banner = screen.getByRole("region", { name: "Decyzja: Kasia Wróbel" });
    expect(banner).toHaveTextContent("Kasia Wróbel kończy 40 dni programu. Czas na decyzję.");
    fireEvent.click(within(banner).getByRole("button", { name: "Zmień rolę na sourcera" }));
    const dialog = await screen.findByRole("dialog");
    const checkbox = within(dialog).getByRole("checkbox", { name: /Dodaj rozmówców/ });
    expect(checkbox).toBeChecked();
    fireEvent.click(within(dialog).getByRole("button", { name: "Zmień rolę na sourcera" }));
    await waitFor(() =>
      expect(traineeApi.decision).toHaveBeenCalledWith(7, {
        action: "promote",
        role: "sourcer",
        add_to_my_people: true,
      }),
    );
  });

  it("niski odsetek odebranych ma ikonę, tekst i zdanie pod wierszem — nie sam kolor", () => {
    renderPanel();
    expect(screen.getByText("(nisko)")).toBeInTheDocument();
    expect(screen.getByText(/Natalia Król: odebrane 6% przy średniej 35%/)).toBeInTheDocument();
    expect(screen.getByText("Do sprawdzenia")).toBeInTheDocument();
    expect(screen.getByText("Poniżej normy")).toBeInTheDocument();
  });
});
