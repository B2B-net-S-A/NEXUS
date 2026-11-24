import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CproSettings } from "@/components/settings/CproSettings";
import type { CproLog } from "@/lib/cpro-events-api";

const LOG: CproLog = {
  since: "2026-10-12",
  enabled: true,
  can_edit: true,
  rules: { closed: true, rejected: true, interview: true, invoice_address: true },
  counts: { closed: 0, rejected: 0, interview: 0, manual: 0 },
  mailboxes: [],
  rows: [
    {
      id: 1,
      at: "2026-09-15T08:00:00Z",
      kind: "invoice_address",
      request: "283051",
      job_id: null,
      job_title: null,
      candidate_id: null,
      person: null,
      detail: "F218 Bank Testowy S.A. → F206 Bank Testowy",
      outcome: "done",
      outcome_text: "Nabywca od 09.2026: F206 Bank Testowy; faktury do sprawdzenia: 1, szkice: 0.",
    },
  ],
};

vi.mock("@/lib/cpro-events-api", async (orig) => ({
  ...(await orig<typeof import("@/lib/cpro-events-api")>()),
  fetchCproLog: vi.fn(() => Promise.resolve(LOG)),
}));

describe("dziennik CPro: zmiana adresu faktury kontraktu (24.11.2026)", () => {
  it("pokazuje numer kontraktu zamiast rekrutacji i regułę nabywcy", async () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <CproSettings />
      </QueryClientProvider>,
    );
    expect(await screen.findByText("kontrakt 283051")).toBeInTheDocument();
    expect(screen.queryByText(/brak rekrutacji w NEXUSIE/)).not.toBeInTheDocument();
    expect(screen.getByText("Nowy adres faktury")).toBeInTheDocument();
    expect(screen.getByText(/zmiana w CPro: F218 Bank Testowy S\.A\. → F206/)).toBeInTheDocument();
    expect(screen.getByText("Nowy adres faktury kontraktu")).toBeInTheDocument();
  });
});
