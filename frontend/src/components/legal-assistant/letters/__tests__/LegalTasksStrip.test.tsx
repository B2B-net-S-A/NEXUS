import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LegalTasksList, LegalTasksStrip } from "@/components/legal-assistant/letters/LegalTasksStrip";
import type { LegalTask } from "@/lib/legal-letters";

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

const mocks = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: { get: mocks.get, post: vi.fn() }, contractsApi: {} }));
const fetchLegalTasks = mocks.get;

const TASK: LegalTask = {
  key: "notice_reply:1:2026-11-12",
  kind: "notice_reply",
  severity: "info",
  title: "Jan Testowy: szkic odpowiedzi na wypowiedzenie czeka",
  detail: "Wypowiedzenie Partnera z 12.11.2026",
  action_label: "Otwórz szkic",
  href: "/contracts/1?pismo=notice_reply",
  client_id: 5,
  contract_id: 1,
  created_at: "2026-11-12T12:00:00",
};

function renderStrip(contractId?: number) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <LegalTasksStrip contractId={contractId} />
    </QueryClientProvider>,
  );
}

describe("pasek zadań asystenta", () => {
  beforeEach(() => {
    fetchLegalTasks.mockReset();
  });

  it("pusty stan to brak paska", () => {
    const { container } = render(<LegalTasksList tasks={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("zadanie z linkiem do szkicu", () => {
    render(<LegalTasksList tasks={[TASK]} />);
    expect(screen.getByText(TASK.title)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Otwórz szkic" })).toHaveAttribute("href", TASK.href);
  });

  it("błąd zapytania nie wygląda jak brak zadań", async () => {
    const failure = Object.assign(new Error("Request failed with status code 500"), {
      response: { status: 500, data: {} },
    });
    fetchLegalTasks.mockRejectedValue(failure);
    renderStrip();
    expect(await screen.findByText(/Nie udało się wczytać zadań/)).toBeInTheDocument();
    expect(screen.getByTestId("legal-tasks-error")).toHaveTextContent("Spróbuj ponownie");
  });

  it("zadania z serwera, zawężone do kontraktu", async () => {
    fetchLegalTasks.mockResolvedValue({ data: { items: [TASK] } });
    renderStrip(1);
    expect(await screen.findByTestId("legal-tasks")).toHaveTextContent("szkic odpowiedzi");
    expect(fetchLegalTasks).toHaveBeenCalledWith("/api/legal/tasks", { params: { contract_id: 1 } });
  });

  it("brak zadań po udanym zapytaniu — nic nie widać", async () => {
    fetchLegalTasks.mockResolvedValue({ data: { items: [] } });
    const { container } = renderStrip();
    await waitFor(() => expect(fetchLegalTasks).toHaveBeenCalled());
    expect(screen.queryByTestId("legal-tasks")).toBeNull();
    expect(screen.queryByTestId("legal-tasks-error")).toBeNull();
    expect(container.textContent).toBe("");
  });
});
