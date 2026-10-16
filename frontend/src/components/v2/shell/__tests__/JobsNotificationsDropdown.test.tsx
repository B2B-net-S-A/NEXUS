import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { JobThreadList } from "@/lib/api/jobTopic";

const push = vi.hoisted(() => vi.fn());
const apiMock = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }));

vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/lib/api", () => ({ api: apiMock }));
vi.mock("@/store/auth", () => ({
  useAuthStore: (selector: (state: unknown) => unknown) =>
    selector({ user: { id: 5, authorization_version: 1 } }),
}));

import { JobsNotificationsDropdown } from "../JobsNotificationsDropdown";
import { useClearJobTopic } from "@/lib/api/jobTopic";

const THREADS: JobThreadList = {
  unread_jobs: 2,
  items: [
    {
      job_id: 13,
      title: "Analityk danych",
      subtitle: "Bank Przykładowy",
      unread_count: 1,
      has_task: true,
      last_title: "Nowy request do pracy",
      last_message: "Analityk danych · Bank Przykładowy",
      last_at: new Date().toISOString(),
      link: "/jobs/13",
    },
    {
      job_id: null,
      title: "Twoje requesty na dziś",
      subtitle: null,
      unread_count: 1,
      has_task: true,
      last_title: "Twoje requesty na dziś",
      last_message: "Nowe do przejrzenia: 2.",
      last_at: new Date().toISOString(),
      link: "/dashboard",
    },
    {
      job_id: 14,
      title: "Frontend Developer",
      subtitle: "Klient Alfa",
      unread_count: 0,
      has_task: false,
      last_title: "Umowa podpisana: Ewa Lis",
      last_message: "Kandydat Ewa Lis jest na etapie „Umowa podpisana”.",
      last_at: new Date().toISOString(),
      link: "/jobs/14",
    },
  ],
};

function wrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

function renderDropdown() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<JobsNotificationsDropdown />, { wrapper: wrapper(client) });
}

function findTrigger(name: string | RegExp = /^Rekrutacje/) {
  return screen.findByRole("button", { name }, { timeout: 5_000 });
}

beforeEach(() => {
  push.mockReset();
  apiMock.get.mockReset();
  apiMock.put.mockReset();
  apiMock.get.mockResolvedValue({ data: THREADS });
  apiMock.put.mockResolvedValue({ data: { success: true, updated: 1 } });
});

describe("JobsNotificationsDropdown — ikona „Rekrutacje” (16.10.2026)", () => {
  it("liczba na ikonie to rekrutacje z nowościami, nie wiersze", async () => {
    renderDropdown();
    const button = await findTrigger("Rekrutacje — z nowościami: 2");
    expect(button).toHaveTextContent("2");
    expect(apiMock.get).toHaveBeenCalledWith("/api/notifications/jobs");
  });

  it("jedna pozycja na rekrutację: nazwa, klient i ostatnia nowość", async () => {
    renderDropdown();
    fireEvent.click(await findTrigger());
    const job = await screen.findByRole("button", {
      name: "Rekrutacja: Analityk danych — nowe: 1, coś dla Ciebie",
    });
    expect(job).toHaveTextContent("Bank Przykładowy");
    expect(job).toHaveTextContent("Nowy request do pracy");
    expect(job).toHaveTextContent("dla Ciebie");
    // Przeczytana rekrutacja zostaje w oknie 7 dni, bez licznika.
    expect(
      screen.getByRole("button", { name: "Rekrutacja: Frontend Developer" }),
    ).toBeInTheDocument();
  });

  it("klik gasi nowości tej rekrutacji i otwiera ją", async () => {
    renderDropdown();
    fireEvent.click(await findTrigger());
    fireEvent.click(await screen.findByRole("button", { name: /Rekrutacja: Analityk danych/ }));
    expect(push).toHaveBeenCalledWith("/jobs/13");
    await waitFor(() =>
      expect(apiMock.put).toHaveBeenCalledWith("/api/notifications/topics/read", {
        topic: "jobs",
        job_id: 13,
      }),
    );
  });

  it("pozycja bez rekrutacji gaśnie po swoim linku", async () => {
    renderDropdown();
    fireEvent.click(await findTrigger());
    fireEvent.click(
      await screen.findByRole("button", { name: /Rekrutacja: Twoje requesty na dziś/ }),
    );
    expect(push).toHaveBeenCalledWith("/dashboard");
    await waitFor(() =>
      expect(apiMock.put).toHaveBeenCalledWith("/api/notifications/topics/read", {
        topic: "jobs",
        link: "/dashboard",
      }),
    );
  });

  it("„Oznacz wszystkie” gasi cały temat", async () => {
    renderDropdown();
    fireEvent.click(await findTrigger());
    fireEvent.click(
      await screen.findByRole("button", { name: "Oznacz wszystkie jako przeczytane" }),
    );
    await waitFor(() =>
      expect(apiMock.put).toHaveBeenCalledWith("/api/notifications/topics/read", {
        topic: "jobs",
      }),
    );
  });

  it("awaria nie wygląda jak „nic nowego”", async () => {
    apiMock.get.mockRejectedValue(new Error("503"));
    renderDropdown();
    fireEvent.click(screen.getByRole("button", { name: "Rekrutacje" }));
    expect(await screen.findByText("Nie udało się wczytać rekrutacji.")).toBeInTheDocument();
    expect(screen.queryByText(/nic nowego/)).not.toBeInTheDocument();
  });
});

describe("useClearJobTopic — wejście na ekran rekrutacji", () => {
  it("gasi tylko własne nowości tej rekrutacji, gdy okienko je pokazuje", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderHook(() => useClearJobTopic(13), { wrapper: wrapper(client) });
    await waitFor(() =>
      expect(apiMock.put).toHaveBeenCalledWith("/api/notifications/topics/read", {
        topic: "jobs",
        job_id: 13,
        include_covered: false,
      }),
    );
  });

  it("rekrutacja bez nowości nie wysyła nic", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderHook(() => useClearJobTopic(14), { wrapper: wrapper(client) });
    await waitFor(() => expect(apiMock.get).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(apiMock.put).not.toHaveBeenCalled();
  });
});
