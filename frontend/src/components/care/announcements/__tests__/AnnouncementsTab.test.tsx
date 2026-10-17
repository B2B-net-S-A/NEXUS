/**
 * Zakładka „Komunikaty”: awaria listy to komunikat o błędzie, nie „Nie ma
 * jeszcze komunikatów”; pusty stan dopiero przy sukcesie; szkic autora
 * z `?announcement=<id>` otwiera edytor. Dane fikcyjne.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn() }));
vi.mock("@/lib/api", () => ({ api }));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast: vi.fn(), showError: vi.fn() }),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/care",
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

import { DRAFT_ID, detail, list, options, preview } from "@/app/preview/hr-announcements/fixtures";
import { announcementKeys } from "@/lib/api/care-announcements";

import { AnnouncementsTab } from "../AnnouncementsTab";

function renderTab(client: QueryClient) {
  return render(
    <QueryClientProvider client={client}>
      <AnnouncementsTab />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  for (const fn of Object.values(api)) fn.mockReset();
  window.history.replaceState({}, "", "/");
});

describe("AnnouncementsTab", () => {
  it("awaria listy nie wygląda jak pusta lista", async () => {
    api.get.mockRejectedValue({ response: { status: 500, data: { detail: "boom" } } });
    renderTab(new QueryClient({ defaultOptions: { queries: { retry: false } } }));
    expect(await screen.findByText("Nie udało się pobrać danych")).toBeInTheDocument();
    expect(screen.queryByText("Nie ma jeszcze komunikatów")).not.toBeInTheDocument();
  });

  it("pusty stan dopiero po udanym odczycie", async () => {
    api.get.mockResolvedValue({ data: { ...list("author"), items: [] } });
    renderTab(new QueryClient({ defaultOptions: { queries: { retry: false } } }));
    expect(await screen.findByText("Nie ma jeszcze komunikatów")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Nowy komunikat" })).toBeInTheDocument();
  });

  it("szkic autora z adresu otwiera edytor", async () => {
    window.history.replaceState({}, "", `/care?tab=announcements&announcement=${DRAFT_ID}`);
    const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } });
    client.setQueryData(announcementKeys.list, list("author"));
    client.setQueryData(announcementKeys.detail(DRAFT_ID), detail(DRAFT_ID, "author"));
    client.setQueryData(announcementKeys.options, options());
    client.setQueryData(announcementKeys.preview("mandatory", { group: "all" }), preview());
    renderTab(client);
    expect(await screen.findByRole("heading", { name: "Szkic komunikatu" })).toBeInTheDocument();
    expect(screen.getByLabelText("Temat")).toHaveValue("Ankieta o sprzęcie od klienta");
    expect(api.get).not.toHaveBeenCalled();
  });
});
