import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  fetch: vi.fn(),
  prepare: vi.fn(),
  showError: vi.fn(),
  showSuccess: vi.fn(),
}));

vi.mock("@/lib/api/clientWait", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/clientWait")>("@/lib/api/clientWait");
  return { ...actual, fetchClientWait: mocks.fetch, prepareClientReminder: mocks.prepare };
});

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: mocks.showSuccess, showError: mocks.showError }),
}));

import { ClientWaitStrip } from "@/components/v2/jobs/ClientWaitStrip";

const PERSON = {
  candidate_id: 11,
  name: "Anna Nowak",
  column: "cv_sent" as const,
  entered_at: "2026-10-12T10:00:00+00:00",
  silent_since: "2026-10-12T10:00:00+00:00",
  workdays: 19,
  needs_action: true,
  panel_state: "viewed" as const,
  panel_label: "Panel: otwarty 3× · ostatnio 05.11 · bez decyzji",
  reminded_at: null,
  closes_on: null,
  added_by: "Rekruter",
};
const WAIT = {
  after_workdays: 5,
  count: 1,
  longest_workdays: 19,
  panel_enabled: true,
  auto_close: false,
  auto_close_days: 30,
  nearest_close_on: null,
  nearest_close_in: null,
  people: [PERSON, { ...PERSON, candidate_id: 12, name: "Świeża Osoba", workdays: 2, needs_action: false }],
};

function renderStrip() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ClientWaitStrip jobId={7} />
    </QueryClientProvider>,
  );
}

describe("ClientWaitStrip", () => {
  beforeEach(() => vi.clearAllMocks());

  it("nikt nie czeka ponad próg: pasa nie ma", async () => {
    mocks.fetch.mockResolvedValue({ ...WAIT, count: 0, longest_workdays: 0, people: [] });
    const { container } = renderStrip();
    await waitFor(() => expect(mocks.fetch).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("mówi, ile osób czeka i kto najdłużej", async () => {
    mocks.fetch.mockResolvedValue(WAIT);
    renderStrip();
    expect(await screen.findByTestId("client-wait-strip")).toHaveTextContent(
      "Czeka na odpowiedź klienta: 1 osoba · najdłużej 19 dni roboczych",
    );
  });

  it("„Pokaż osoby” listuje tylko tych ponad próg, ze stanem panelu", async () => {
    mocks.fetch.mockResolvedValue(WAIT);
    renderStrip();
    fireEvent.click(await screen.findByRole("button", { name: "Pokaż osoby" }));
    expect(screen.getByRole("link", { name: "Anna Nowak" })).toHaveAttribute(
      "href",
      "/jobs/7?candidate=11",
    );
    expect(screen.getByText("Panel: otwarty 3× · ostatnio 05.11 · bez decyzji")).toBeInTheDocument();
    expect(screen.queryByText("Świeża Osoba")).not.toBeInTheDocument();
  });

  it("„Przypomnij klientowi” przygotowuje treść, a NEXUS jej nie wysyła", async () => {
    mocks.fetch.mockResolvedValue(WAIT);
    mocks.prepare.mockResolvedValue({
      subject: "Prośba o informację zwrotną: Java",
      body: "Dzień dobry",
      to_email: "hm@example.com",
      panel_url: null,
      people: 1,
    });
    renderStrip();
    fireEvent.click(await screen.findByRole("button", { name: "Przypomnij klientowi" }));
    expect(await screen.findByDisplayValue("Prośba o informację zwrotną: Java")).toBeInTheDocument();
    expect(mocks.prepare).toHaveBeenCalledWith(7, undefined);
    expect(screen.getByText(/NEXUS nie wyśle tej wiadomości/)).toBeInTheDocument();
    expect(screen.getByText(/Panel klienta jest wyłączony/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Otwórz w poczcie" })).toHaveAttribute(
      "href",
      expect.stringContaining("mailto:hm%40example.com"),
    );
  });

  it("awaria odczytu to komunikat z „Spróbuj ponownie”, nie pustka", async () => {
    mocks.fetch.mockRejectedValue(new Error("boom"));
    renderStrip();
    expect(await screen.findByTestId("client-wait-error", {}, { timeout: 5000 })).toHaveTextContent(
      "Nie udało się sprawdzić, kto czeka na odpowiedź klienta.",
    );
  });
});
