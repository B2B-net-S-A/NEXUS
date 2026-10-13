/**
 * Lista rekrutacji pamięta ostatnie filtry osoby (13.10.2026): goły `/jobs`
 * (menu, okruszek, kafel pulpitu) wraca do ostatniego widoku, link
 * z parametrami wygrywa i nie nadpisuje pamięci, dopóki osoba czegoś nie
 * zmieni, a „Wyczyść” kasuje wpis. Reguły:
 * docs/claude/rekrutacja-tablica/lista-rekrutacji-pamieta-ostatnie-filtry.md
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { JobsListV2 } from "@/components/v2/pages/JobsListV2";
import { useAuthStore } from "@/store/auth";

const getMock = vi.fn();
const quickCountsMock = vi.fn();

vi.mock("@/lib/api", () => ({
  default: {
    get: (...args: unknown[]) => getMock(...args),
  },
  jobsApi: {
    quickCounts: (...args: unknown[]) => quickCountsMock(...args),
  },
}));

// Adres widziany przez router Next — czytany leniwie, więc test może go podmienić.
const navState = { search: "" };

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(navState.search),
}));

vi.mock("@/hooks/useCapability", () => ({
  useCapabilities: () => ({
    "job.create": false,
    "invite_link.create": false,
  }),
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({
    showToast: vi.fn(),
    showSuccess: vi.fn(),
    showError: vi.fn(),
    showActionToast: vi.fn(),
  }),
}));

vi.mock("@/components/v2/modals/GenerateInviteLinkV2", () => ({
  GenerateInviteLinkV2: () => null,
}));

vi.mock("@/components/v2/filters/UserMultiSelect", () => ({
  UserMultiSelect: () => null,
}));

vi.mock("@/components/v2/filters/ClientMultiSelect", () => ({
  ClientMultiSelect: () => null,
}));

vi.mock("@/components/v2/filters/CompetenceCategoryMultiSelect", () => ({
  CompetenceCategoryMultiSelect: () => null,
}));

vi.mock("@/components/v2/jobs/JobReadinessDock", () => ({
  JobReadinessDock: () => null,
}));

const memoryKey = (userId: number) => `nexus:jobs-list-filters:${userId}`;
const stored = (userId = 7) => window.localStorage.getItem(memoryKey(userId));

function signInAs(role: string, id = 7) {
  useAuthStore.setState({
    user: { id, name: "Test", email: "t@example.com", role, roles: [role] } as never,
    hydrated: true,
  });
}

/** Adres, pod którym lista się otwiera (to, co widzi router i przeglądarka). */
function setAddress(search: string) {
  navState.search = search;
  window.history.replaceState(null, "", search ? `/jobs?${search}` : "/jobs");
}

function tree(client: QueryClient, props: { memoryKey?: string | null } = {}) {
  return (
    <QueryClientProvider client={client}>
      <JobsListV2 {...props} />
    </QueryClientProvider>
  );
}

function renderJobs(props: { memoryKey?: string | null } = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
  });
  const view = render(tree(client, props));
  return {
    ...view,
    /** Nawigacja routera przy otwartej liście (menu „Rekrutacje”, link). */
    navigate: (search: string) => {
      setAddress(search);
      view.rerender(tree(client, props));
    },
  };
}

function jobsCalls() {
  return getMock.mock.calls.filter((call) => call[0] === "/api/jobs");
}

function latestParams(): Record<string, unknown> {
  const call = jobsCalls().at(-1);
  return (call?.[1] as { params?: Record<string, unknown> } | undefined)?.params ?? {};
}

const scopeButton = (name: RegExp) =>
  within(screen.getByRole("group", { name: "Zakres rekrutacji" })).getByRole("button", { name });
const stagePill = (name: RegExp) =>
  within(screen.getByRole("group", { name: "Stan requestu" })).getByRole("button", { name });

describe("JobsListV2 — pamięć ostatnich filtrów", () => {
  beforeAll(() => {
    Object.defineProperty(HTMLElement.prototype, "hasPointerCapture", {
      configurable: true,
      value: () => false,
    });
    Object.defineProperty(HTMLElement.prototype, "setPointerCapture", {
      configurable: true,
      value: () => undefined,
    });
    Object.defineProperty(HTMLElement.prototype, "releasePointerCapture", {
      configurable: true,
      value: () => undefined,
    });
  });

  beforeEach(() => {
    window.localStorage.clear();
    getMock.mockReset();
    quickCountsMock.mockReset();
    quickCountsMock.mockResolvedValue({
      data: {
        all: 4241,
        mine: 12,
        open: 318,
        attention: { overdue: 4, nobody_working: 7, nobody_sent: 11 },
        attention_mine: { overdue: 1, nobody_working: 0, nobody_sent: 2 },
      },
    });
    getMock.mockResolvedValue({
      data: {
        items: [{ id: 101, title: "Senior Java Developer", status: "published", headcount: 1 }],
        total: 1,
        page: 1,
        page_size: 20,
      },
    });
    setAddress("");
    signInAs("recruiter");
  });

  it("po wyjściu i powrocie gołym adresem lista otwiera się z ostatnimi filtrami", async () => {
    const user = userEvent.setup();
    const first = renderJobs();
    await waitFor(() => expect(jobsCalls()).toHaveLength(1));
    await user.click(scopeButton(/Otwarte/));
    await user.click(stagePill(/Szukamy/));
    await waitFor(() =>
      expect(latestParams()).toMatchObject({ open_only: true, request_stage: ["searching"] }),
    );
    first.unmount();

    // Menu „Rekrutacje” z innej strony: świeże montowanie na gołym adresie.
    getMock.mockClear();
    setAddress("");
    renderJobs();
    await waitFor(() => expect(jobsCalls()).toHaveLength(1));
    expect(latestParams()).toMatchObject({ open_only: true, request_stage: ["searching"] });
    expect(latestParams().mine).toBeUndefined();
    await waitFor(() => {
      const params = new URLSearchParams(window.location.search);
      expect(params.get("open")).toBe("1");
      expect(params.getAll("stage")).toEqual(["searching"]);
    });
    // Jedno zapytanie — nie „domyślne, a potem zapamiętane”.
    await new Promise((r) => setTimeout(r, 30));
    expect(jobsCalls()).toHaveLength(1);
  });

  it("bez pamięci goły adres daje domyślny widok roli", async () => {
    renderJobs();
    await waitFor(() => expect(jobsCalls()).toHaveLength(1));
    expect(latestParams()).toMatchObject({ mine: true, open_only: true, sort: "attention" });
    expect(window.location.search).toBe("");
    expect(stored()).toBeNull();
  });

  it("store zhydratowany po montowaniu: pierwsze zapytanie już niesie pamięć, a wpisany tekst zostaje", async () => {
    window.localStorage.setItem(memoryKey(7), "open=1&stage=searching");
    useAuthStore.setState({ user: null, hydrated: false });
    const user = userEvent.setup();
    renderJobs();
    await user.type(screen.getByPlaceholderText("Tytuł, klient, technologia…"), "ja");
    await new Promise((r) => setTimeout(r, 30));
    expect(jobsCalls()).toHaveLength(0);

    act(() => signInAs("recruiter"));
    await waitFor(() => expect(jobsCalls().length).toBeGreaterThan(0));
    expect(jobsCalls()[0][1].params).toMatchObject({
      open_only: true,
      request_stage: ["searching"],
    });
    expect(screen.getByPlaceholderText("Tytuł, klient, technologia…")).toHaveValue("ja");
  });

  it("link z parametrami wygrywa i nie nadpisuje pamięci, dopóki osoba czegoś nie zmieni", async () => {
    window.localStorage.setItem(memoryKey(7), "open=1");
    setAddress("stage=client_silent");
    const user = userEvent.setup();
    renderJobs();
    await waitFor(() => expect(jobsCalls()).toHaveLength(1));
    expect(latestParams()).toMatchObject({ mine: true, request_stage: ["client_silent"] });
    expect(stored()).toBe("open=1");

    await user.click(stagePill(/Szukamy/));
    await waitFor(() => expect(stored()).toBe("stage=client_silent&stage=searching"));

    // Cofnięcie zmiany: w pamięci ma stać widok z ekranu, nie pośredni.
    await user.click(stagePill(/Szukamy/));
    await waitFor(() => expect(stored()).toBe("stage=client_silent"));
  });

  it("nietknięty link z zakresem równym domyślnemu roli trzyma zakres w adresie", async () => {
    // Inaczej adres stałby się goły i „Wstecz” z rekrutacji przywracałby pamięć.
    window.localStorage.setItem(memoryKey(7), "open=1");
    setAddress("mine=1");
    const user = userEvent.setup();
    renderJobs();
    await waitFor(() => expect(jobsCalls()).toHaveLength(1));
    expect(latestParams()).toMatchObject({ mine: true });
    await new Promise((r) => setTimeout(r, 30));
    expect(window.location.search).toBe("?mine=1");
    expect(stored()).toBe("open=1");

    await user.click(stagePill(/Szukamy/));
    await waitFor(() => expect(window.location.search).toBe("?stage=searching"));
    expect(stored()).toBe("stage=searching");
  });

  it("„Rekrutacje” w menu na otwartej liście zostawia filtry osoby i wpisuje je z powrotem do adresu", async () => {
    setAddress("stage=champion");
    const user = userEvent.setup();
    const view = renderJobs();
    await waitFor(() => expect(jobsCalls()).toHaveLength(1));
    await user.click(stagePill(/Szukamy/));
    await waitFor(() =>
      expect(latestParams()).toMatchObject({ request_stage: ["champion", "searching"] }),
    );

    view.navigate("");
    await waitFor(() =>
      expect(new URLSearchParams(window.location.search).getAll("stage")).toEqual([
        "champion",
        "searching",
      ]),
    );
    expect(latestParams()).toMatchObject({ request_stage: ["champion", "searching"] });
    expect(stagePill(/Szukamy/)).toHaveAttribute("aria-pressed", "true");
  });

  it("„Rekrutacje” w menu po nietkniętym linku wraca do zapamiętanego widoku", async () => {
    window.localStorage.setItem(memoryKey(7), "open=1");
    setAddress("stage=champion");
    const view = renderJobs();
    await waitFor(() => expect(latestParams()).toMatchObject({ request_stage: ["champion"] }));

    view.navigate("");
    await waitFor(() => expect(latestParams().request_stage).toBeUndefined());
    expect(latestParams()).toMatchObject({ open_only: true });
    expect(latestParams().mine).toBeUndefined();
    expect(stored()).toBe("open=1");
  });

  it("link z parametrami kliknięty na otwartej liście pokazuje widok z linku", async () => {
    const user = userEvent.setup();
    const view = renderJobs();
    await waitFor(() => expect(jobsCalls()).toHaveLength(1));
    await user.click(scopeButton(/Otwarte/));
    await waitFor(() => expect(stored()).toBe("open=1"));

    view.navigate("stage=champion");
    await waitFor(() => expect(latestParams()).toMatchObject({ request_stage: ["champion"] }));
    expect(latestParams()).toMatchObject({ mine: true });
    expect(stored()).toBe("open=1");
  });

  it("„Wyczyść” kasuje wpis, a szukajka nigdy do niego nie trafia", async () => {
    const user = userEvent.setup();
    renderJobs();
    await waitFor(() => expect(jobsCalls()).toHaveLength(1));
    await user.type(screen.getByPlaceholderText("Tytuł, klient, technologia…"), "java");
    await user.click(scopeButton(/Otwarte/));
    await waitFor(() => expect(stored()).toBe("open=1"));
    await waitFor(() => expect(latestParams()).toMatchObject({ q: "java" }));
    expect(stored()).toBe("open=1");

    await user.click(screen.getByRole("button", { name: /Wyczyść filtry/ }));
    await waitFor(() => expect(stored()).toBeNull());
  });

  it("pamięć jest osobna dla każdej osoby", async () => {
    window.localStorage.setItem(memoryKey(7), "open=1");
    signInAs("recruiter", 8);
    const user = userEvent.setup();
    renderJobs();
    await waitFor(() => expect(jobsCalls()).toHaveLength(1));
    expect(latestParams()).toMatchObject({ mine: true });

    await user.click(scopeButton(/Wszystkie/));
    await waitFor(() => expect(stored(8)).toBe("mine=0"));
    expect(stored(7)).toBe("open=1");
  });

  it("zmiana osoby przy otwartej liście („podgląd jako”) nie przenosi cudzego widoku", async () => {
    const user = userEvent.setup();
    renderJobs();
    await waitFor(() => expect(jobsCalls()).toHaveLength(1));
    await user.click(scopeButton(/Otwarte/));
    await waitFor(() => expect(stored(7)).toBe("open=1"));

    act(() => signInAs("recruiter", 8));
    await waitFor(() => expect(latestParams()).toMatchObject({ mine: true }));
    expect(stored(8)).toBeNull();
    expect(stored(7)).toBe("open=1");
  });

  it("zmiana osoby razem z nawigacją na goły adres też nie zapisuje jej cudzego widoku", async () => {
    const user = userEvent.setup();
    const view = renderJobs();
    await waitFor(() => expect(jobsCalls()).toHaveLength(1));
    await user.click(scopeButton(/Otwarte/));
    await waitFor(() => expect(stored(7)).toBe("open=1"));

    act(() => {
      signInAs("recruiter", 8);
      view.navigate("");
    });
    await waitFor(() => expect(latestParams()).toMatchObject({ mine: true }));
    expect(stored(8)).toBeNull();
    expect(stored(7)).toBe("open=1");
  });

  it("zapamiętana „Moja kategoria” u osoby bez kategorii daje zakres roli", async () => {
    window.localStorage.setItem(memoryKey(7), "mycat=1");
    renderJobs();
    await waitFor(() => expect(jobsCalls()).toHaveLength(1));
    expect(latestParams()).toMatchObject({ mine: true });
    expect(latestParams().my_category).toBeUndefined();
  });

  it("adres z samymi martwymi kluczami sprzed 25.09 nie jest linkiem — wchodzi pamięć", async () => {
    window.localStorage.setItem(memoryKey(7), "open=1");
    setAddress("status=published");
    renderJobs();
    await waitFor(() => expect(jobsCalls()).toHaveLength(1));
    expect(latestParams()).toMatchObject({ open_only: true });
    expect(latestParams().mine).toBeUndefined();
  });

  it("`memoryKey={null}` wyłącza pamięć (harness bez własnego klucza)", async () => {
    window.localStorage.setItem(memoryKey(7), "open=1");
    const user = userEvent.setup();
    renderJobs({ memoryKey: null });
    await waitFor(() => expect(jobsCalls()).toHaveLength(1));
    expect(latestParams()).toMatchObject({ mine: true });

    await user.click(scopeButton(/Wszystkie/));
    await waitFor(() => expect(latestParams().mine).toBeUndefined());
    expect(stored(7)).toBe("open=1");
  });
});
