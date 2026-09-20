import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ list: vi.fn() }));

vi.mock("@/lib/api", () => ({
  jobsApi: { list: (...args: unknown[]) => mocks.list(...args) },
}));

import { JobPicker } from "@/components/v2/recruitment/JobPicker";
import { useTabsStore } from "@/store/tabs";

const MINE = [
  { id: 1, title: "Java Developer", client_name: "Bank" },
  { id: 2, title: "QA Engineer", client_name: null },
];

function renderPicker(props: Partial<React.ComponentProps<typeof JobPicker>> = {}) {
  const onChange = vi.fn();
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <JobPicker value={null} onChange={onChange} scope="mine" {...props} />
    </QueryClientProvider>,
  );
  return onChange;
}

describe("JobPicker", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useTabsStore.setState({ tabs: [], activeTabId: null });
    mocks.list.mockImplementation((params: Record<string, unknown>) =>
      Promise.resolve({
        data: params.q
          ? { items: [{ id: 7, title: `Wynik ${String(params.q)}`, client_name: "Klient" }] }
          : { items: MINE },
      }),
    );
  });

  it("pokazuje „Moje otwarte” z zapytania mine+open_only i zwraca wybraną rekrutację", async () => {
    const onChange = renderPicker();
    const section = (await screen.findByRole("heading", { name: "Moje otwarte" })).parentElement!;
    const row = await within(section).findByRole("button", { name: /Java Developer/ });
    expect(mocks.list).toHaveBeenCalledWith({ mine: true, open_only: true, page_size: 20 });
    fireEvent.click(row);
    expect(onChange).toHaveBeenCalledWith(MINE[0]);
  });

  it("zaznacza bieżący wybór", async () => {
    renderPicker({ value: MINE[1] });
    expect(await screen.findByRole("button", { name: /QA Engineer/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /Java Developer/ })).toHaveAttribute("aria-pressed", "false");
  });

  it("„Ostatnio otwierane” przy scope=mine tylko z moich; przy scope=all wszystkie karty rekrutacji", async () => {
    useTabsStore.setState({
      tabs: [
        { id: "job-2", type: "job", entityId: 2, title: "QA Engineer", url: "/jobs/2" },
        { id: "job-9", type: "job", entityId: 9, title: "Cudza rekrutacja", url: "/jobs/9" },
        { id: "candidate-5", type: "candidate", entityId: 5, title: "Anna", url: "/candidates/5" },
      ],
      activeTabId: null,
    });
    renderPicker();
    const recent = (await screen.findByRole("heading", { name: "Ostatnio otwierane" })).parentElement!;
    await waitFor(() => expect(within(recent).getByRole("button", { name: /QA Engineer/ })).toBeInTheDocument());
    expect(within(recent).queryByRole("button", { name: /Cudza rekrutacja/ })).not.toBeInTheDocument();
    expect(within(recent).queryByRole("button", { name: /Anna/ })).not.toBeInTheDocument();
  });

  it("scope=all pokazuje każdą ostatnio otwieraną rekrutację", async () => {
    useTabsStore.setState({
      tabs: [{ id: "job-9", type: "job", entityId: 9, title: "Cudza rekrutacja", url: "/jobs/9" }],
      activeTabId: null,
    });
    renderPicker({ scope: "all" });
    const recent = (await screen.findByRole("heading", { name: "Ostatnio otwierane" })).parentElement!;
    expect(within(recent).getByRole("button", { name: /Cudza rekrutacja/ })).toBeInTheDocument();
  });

  it("szukanie przy scope=mine zawęża do moich; przy scope=all nie", async () => {
    renderPicker();
    fireEvent.change(screen.getByLabelText("Szukaj rekrutacji"), { target: { value: "java" } });
    expect(await screen.findByRole("heading", { name: "Wyniki" })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /Wynik java/ })).toBeInTheDocument();
    expect(mocks.list).toHaveBeenCalledWith({ q: "java", page_size: 20, open_only: true, mine: true });
  });

  it("szukanie przy scope=all nie wysyła mine", async () => {
    renderPicker({ scope: "all" });
    fireEvent.change(screen.getByLabelText("Szukaj rekrutacji"), { target: { value: "qa" } });
    expect(await screen.findByRole("button", { name: /Wynik qa/ })).toBeInTheDocument();
    expect(mocks.list).toHaveBeenCalledWith({ q: "qa", page_size: 20, open_only: true });
  });

  it("błąd wczytania to komunikat, nie pusta lista", async () => {
    mocks.list.mockRejectedValue(Object.assign(new Error("boom"), { response: { status: 500, data: { detail: "Serwer niedostępny" } } }));
    renderPicker();
    expect(await screen.findByRole("alert")).toHaveTextContent("Serwer niedostępny");
    expect(screen.queryByText(/Nie masz otwartych rekrutacji/)).not.toBeInTheDocument();
  });
});
