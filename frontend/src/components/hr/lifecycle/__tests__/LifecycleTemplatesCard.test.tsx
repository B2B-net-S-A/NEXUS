/**
 * „Ścieżki wejścia i odejścia” (etap 3, M4, O4–O5): ścieżkę zmienia ten, komu
 * pozwala serwer (`can_edit`), zapis to nowa wersja z warunkami pozycji,
 * trwające sprawy dociąga przycisk, bez uprawnień karta znika. Dane fikcyjne.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { LifecycleTemplate } from "@/lib/api/hr-lifecycle";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  toast: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  api: { get: mocks.get, post: mocks.post, put: mocks.put, patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showToast: mocks.toast }) }));

import { LifecycleTemplatesCard } from "../LifecycleTemplatesCard";

const CONSULTANT: LifecycleTemplate = {
  id: 3,
  kind: "onboarding",
  audience: "consultant",
  version: 4,
  name: "Konsultant u klienta",
  is_active: true,
  employment_type: null,
  department: null,
  can_edit: true,
  live_cases_behind: 3,
  items: [
    {
      id: 31,
      title: "Umowa podpisana, dane do faktur",
      category: "documents",
      assignee_kind: "administration",
      due_offset_days: -7,
      description: "Plik umowy w kontrakcie.",
      required: true,
      requires_file: true,
      conditions: { employment_types: ["b2b"] },
      key: null,
    },
    {
      id: 32,
      title: "Mail powitalny do konsultanta",
      category: "other",
      assignee_kind: "care_owner",
      due_offset_days: -3,
      required: true,
      requires_file: false,
      conditions: {},
      key: "welcome_mail",
    },
  ],
};

const TEAM: LifecycleTemplate = {
  id: 1,
  kind: "onboarding",
  audience: "team",
  version: 2,
  name: "Wejście — standard",
  is_active: true,
  employment_type: null,
  department: null,
  can_edit: false,
  live_cases_behind: 0,
  items: [
    {
      id: 11,
      title: "Konto Microsoft 365",
      category: "accounts",
      assignee_kind: "it",
      due_offset_days: -2,
      conditions: {},
    },
  ],
};

function renderCard() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  render(
    <QueryClientProvider client={client}>
      <LifecycleTemplatesCard />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  Object.values(mocks).forEach((mock) => mock.mockReset());
});

describe("LifecycleTemplatesCard", () => {
  it("bez uprawnień do ścieżek karta się nie pokazuje", async () => {
    mocks.get.mockRejectedValue(
      Object.assign(new Error("HTTP 403"), { response: { status: 403, data: {} } }),
    );
    const { container } = render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <LifecycleTemplatesCard />
      </QueryClientProvider>,
    );
    await waitFor(() => expect(mocks.get).toHaveBeenCalled());
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("ścieżka cudza jest tylko do odczytu", async () => {
    mocks.get.mockResolvedValue({ data: { items: [TEAM, CONSULTANT] } });
    renderCard();
    fireEvent.click(await screen.findByRole("button", { name: /Wejście — standard/ }));
    expect(screen.getByText(/tylko do odczytu/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Zapisz jako wersję/ })).not.toBeInTheDocument();
    // Nowej ścieżki zespołu nie zakłada ktoś, kto nie zmienia ścieżek zespołu.
    expect(
      screen.queryByRole("button", { name: /Wejście · zespół wewnętrzny/ }),
    ).not.toBeInTheDocument();
  });

  it("zapis to nowa wersja z warunkami, a stałej pozycji nie da się usunąć", async () => {
    mocks.get.mockResolvedValue({ data: { items: [TEAM, CONSULTANT] } });
    mocks.put.mockResolvedValue({ data: { ...CONSULTANT, version: 5, live_cases_behind: 3 } });
    renderCard();
    fireEvent.click(await screen.findByRole("button", { name: /Konsultant u klienta/ }));
    expect(screen.getByText("3 trwające wejścia są na starszej wersji tej ścieżki.", { exact: false })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Usuń pozycję Mail powitalny do konsultanta" }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "Zlecenie: Umowa podpisana, dane do faktur" }));
    fireEvent.click(screen.getByRole("button", { name: "Zapisz jako wersję 5" }));
    await waitFor(() => expect(mocks.put).toHaveBeenCalled());
    const [url, body] = mocks.put.mock.calls[0];
    expect(url).toBe("/api/hr/lifecycle/templates/3");
    expect(body.audience).toBe("consultant");
    expect(body.items[0]).toMatchObject({
      id: 31,
      requires_file: true,
      conditions: { employment_types: ["b2b", "zlecenie"], equipment: null, student: null },
    });
    expect(body.items[1]).not.toHaveProperty("key");
  });

  it("„Dociągnij do trwających” woła serwer dla tej ścieżki", async () => {
    mocks.get.mockResolvedValue({ data: { items: [CONSULTANT] } });
    mocks.post.mockResolvedValue({ data: { cases: 3, tasks: 4, template: CONSULTANT } });
    renderCard();
    fireEvent.click(await screen.findByRole("button", { name: /Konsultant u klienta/ }));
    fireEvent.click(screen.getByRole("button", { name: "Dociągnij do trwających" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith("/api/hr/lifecycle/templates/3/catch-up"),
    );
  });
});
