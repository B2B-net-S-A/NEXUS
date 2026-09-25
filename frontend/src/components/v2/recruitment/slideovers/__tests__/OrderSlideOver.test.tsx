import { fireEvent, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  put: vi.fn(),
  showSuccess: vi.fn(),
  showError: vi.fn(),
  roles: ["admin"] as string[],
}));

vi.mock("@/lib/api", () => ({
  default: {
    get: (...args: unknown[]) => mocks.get(...args),
    put: (...args: unknown[]) => mocks.put(...args),
  },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: mocks.showSuccess, showError: mocks.showError }),
}));
vi.mock("@/store/auth", () => ({
  useAuthStore: (selector: (s: unknown) => unknown) =>
    selector({ user: { id: 1, roles: mocks.roles }, realUser: null }),
  hasRole: (_user: unknown, ...roles: string[]) =>
    roles.some((r) => mocks.roles.includes(r)),
}));
// Ciężkie klocki są osobno przetestowane — tu liczy się, KIEDY się montują
// i jakie propsy dostają.
vi.mock("@/components/v2/jobs/JobOwnershipPanel", () => ({
  JobOwnershipPanel: () => <div data-testid="ownership-panel" />,
}));
vi.mock("@/components/jobs/HiringManagerPicker", () => ({
  HiringManagerPicker: ({ canEdit }: { canEdit: boolean }) => (
    <div data-testid="hm-picker" data-can-edit={String(canEdit)} />
  ),
}));
vi.mock("@/components/v2/jobs/JobSettingsPanel", () => ({
  JobSettingsPanel: ({ canEdit }: { canEdit: boolean }) => (
    <div data-testid="settings-panel" data-can-edit={String(canEdit)} />
  ),
}));
vi.mock("@/components/v2/priority-work", () => ({
  JobPriorityContext: () => <div data-testid="priority-context" />,
}));
vi.mock("@/components/v2/jobs/JobReadinessDock", () => ({
  JobReadinessDock: () => <div data-testid="readiness-dock" />,
}));
vi.mock("@/components/v2/jobs/JobCloseWithReasonDialog", () => ({
  JobCloseWithReasonDialog: ({
    open,
    defaultReason,
  }: {
    open: boolean;
    defaultReason: string;
  }) => (open ? <div data-testid="close-dialog" data-reason={defaultReason} /> : null),
}));

import { OrderSlideOver, type OrderSlideOverProps } from "../OrderSlideOver";
import { renderWithQuery } from "./test-utils";

const JOB = {
  id: 7,
  title: "Java Developer",
  status: "published",
  client_id: 3,
  client_name: "Bank Alfa",
  effective_budget_hourly: 190,
  has_budget_hourly: true,
  location: "Warszawa",
  remote_policy: "hybrid",
  onsite_days_per_week: 2,
  deadline: "2026-10-15",
  must_skills: ["Java 17", "Kafka"],
  nice_skills: ["AWS"],
  primary_owner: { id: 5, name: "Anna Nowicka" },
  collaborators: [],
};

function setup(
  props: Partial<OrderSlideOverProps> = {},
  { job = JOB, readiness }: { job?: unknown; readiness?: unknown } = {},
) {
  mocks.get.mockImplementation((url: string) =>
    url.endsWith("/readiness")
      ? Promise.resolve({
          data: readiness ?? {
            ready: false,
            blockers: ["Brak hiring managera", "Brak terminu dla klienta"],
          },
        })
      : Promise.resolve({ data: job }),
  );
  const handlers = {
    onOpenChange: vi.fn(),
    onNavigate: vi.fn(),
    onOpenSlideOver: vi.fn(),
    onEdit: vi.fn(),
    onOpenAiWriter: vi.fn(),
    onOpenInviteLink: vi.fn(),
  };
  renderWithQuery(
    <OrderSlideOver open jobId={7} canEdit {...handlers} {...props} />,
  );
  return handlers;
}

describe("OrderSlideOver", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.roles = ["admin"];
  });

  it("zamknięte okno nie montuje treści i nie pyta o zlecenie", () => {
    setup({ open: false });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(mocks.get).not.toHaveBeenCalled();
  });

  it("otwarte: tytuł, braki z serwera, fakty i chipy wymagań", async () => {
    setup();
    const dialog = await screen.findByRole("dialog", { name: "Zlecenie" });
    const missing = await within(dialog).findByRole("region", {
      name: "Braki w zleceniu",
    });
    // 10 pozycji bramki (hybryda → także dni i miasto biura; od 25.09.2026
    // także wymagania do wyszukiwania) + 2 zdania spoza lustra — te zostają
    // brakami z własną treścią.
    expect(within(missing).getByText("10 z 12 gotowe")).toBeInTheDocument();
    expect(within(missing).getByText("Brak hiring managera")).toBeInTheDocument();
    expect(within(dialog).getByText("do 190,00 PLN/h")).toBeInTheDocument();
    expect(within(dialog).getByText("Warszawa / hybryda 2 dni")).toBeInTheDocument();
    expect(within(dialog).getByText("Java 17")).toBeInTheDocument();
    expect(within(dialog).getByText("AWS — mile widziane")).toBeInTheDocument();
    // Karta klienta prowadzi do Pomocy (czyta ją każda rola), nie do /clients/*.
    expect(within(dialog).getByRole("link", { name: /Karta klienta Bank Alfa/ })).toHaveAttribute(
      "href",
      "/help?tab=clients&client=3",
    );
  });

  it("rola spoza bramki nie wysyła zapytania o gotowość i nie widzi bloku braków", async () => {
    mocks.roles = ["recruiter"];
    setup();
    await screen.findByText("Java 17");
    expect(screen.queryByTestId("order-missing-block")).not.toBeInTheDocument();
    expect(mocks.get).not.toHaveBeenCalledWith("/api/jobs/7/readiness");
  });

  it("zredagowany budżet mówi, że kwota jest ukryta — nie że jej nie ma", async () => {
    setup({}, { job: { ...JOB, effective_budget_hourly: null } });
    expect(
      await screen.findByText("ustawiony (kwota niewidoczna dla Twojej roli)"),
    ).toBeInTheDocument();
  });

  it("akcje strony najpierw zamykają okno (modal obok otwartego dialogu byłby nieklikalny)", async () => {
    const h = setup();
    fireEvent.click(await screen.findByRole("button", { name: "Edytuj rekrutację" }));
    expect(h.onOpenChange).toHaveBeenCalledWith(false);
    expect(h.onEdit).toHaveBeenCalled();

    fireEvent.click(
      screen.getByRole("button", {
        name: "Profil Championa i pytania na screening — Otwórz pełne",
      }),
    );
    expect(h.onNavigate).toHaveBeenCalledWith("champion");

    fireEvent.click(screen.getByRole("button", { name: "Baza pytań — Otwórz" }));
    expect(h.onOpenSlideOver).toHaveBeenCalledWith("questions");
  });

  it("sekcje montują klocki dopiero po rozwinięciu", async () => {
    const h = setup();
    // Blok „Zespół" pokazuje właściciela od razu; panele montują się po „Zmień".
    const teamBlock = await screen.findByRole("region", { name: "Zespół" });
    expect(teamBlock).toHaveTextContent("Anna Nowicka");
    const team = screen.getByRole("button", { name: /Zmień zespół i hiring managera/ });
    expect(screen.queryByTestId("ownership-panel")).not.toBeInTheDocument();
    fireEvent.click(team);
    expect(screen.getByTestId("ownership-panel")).toBeInTheDocument();
    expect(screen.getByTestId("hm-picker")).toHaveAttribute("data-can-edit", "true");

    fireEvent.click(screen.getByRole("button", { name: /Ustawienia rekrutacji/ }));
    expect(screen.getByTestId("settings-panel")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^Priorytet/ }));
    expect(screen.getByTestId("priority-context")).toBeInTheDocument();

    // Symulowane portale ogłoszeniowe usunięte 23.09.2026.
    expect(screen.queryByRole("button", { name: /Portale ogłoszeniowe/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Napisz ogłoszenie z AI" }));
    expect(h.onOpenAiWriter).toHaveBeenCalled();
  });

  it("canEdit=false chowa edycję i zamknięcie, a klocki dostają tryb odczytu", async () => {
    setup({ canEdit: false, onOpenAiWriter: undefined, onOpenInviteLink: undefined });
    await screen.findByText("Java 17");
    expect(screen.queryByRole("button", { name: "Edytuj rekrutację" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Zamknij rekrutację" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Zmień zespół i hiring managera/ }));
    expect(screen.getByTestId("hm-picker")).toHaveAttribute("data-can-edit", "false");
  });

  it("rekruter prowadzący (canEditContent): edycja treści, bez zespołu i zamknięcia", async () => {
    setup({ canEdit: false, canEditContent: true });
    expect(await screen.findByRole("button", { name: "Edytuj rekrutację" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Zamknij rekrutację" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Zmień zespół i hiring managera/ }));
    expect(screen.getByTestId("hm-picker")).toHaveAttribute("data-can-edit", "false");
  });

  it("„Zamknij rekrutację” otwiera istniejący dialog z podpowiedzią powodu", async () => {
    setup({ hiredCount: 1 });
    fireEvent.click(await screen.findByRole("button", { name: "Zamknij rekrutację" }));
    expect(screen.getByTestId("close-dialog")).toHaveAttribute("data-reason", "filled_by_us");
  });

  it("initialSection=close (podpowiedź „Obsada kompletna”) otwiera od razu dialog zamknięcia z „Obsadzone przez nas”", async () => {
    setup({ initialSection: "close", hiredCount: 2 });
    expect(await screen.findByTestId("close-dialog")).toHaveAttribute("data-reason", "filled_by_us");
  });

  it("initialSection=close bez prawa edycji niczego nie otwiera (bramka zostaje w oknie)", async () => {
    setup({ initialSection: "close", hiredCount: 2, canEdit: false });
    await screen.findByText("Java 17");
    expect(screen.queryByTestId("close-dialog")).not.toBeInTheDocument();
  });

  it("zamknięta rekrutacja nie pokazuje przycisku zamknięcia", async () => {
    setup({}, { job: { ...JOB, status: "closed" }, readiness: { closed: true } });
    await screen.findByText("Java 17");
    expect(screen.queryByRole("button", { name: "Zamknij rekrutację" })).not.toBeInTheDocument();
  });
});

// ── Braki z działaniem (24.09.2026) ──────────────────────────────────────────

describe("OrderSlideOver — braki z działaniem", () => {
  const MSG = {
    context:
      "Uzupełnij kontekst projektu (o projekcie / obowiązki) w Profilu Championa.",
    budget:
      "Uzupełnij budżet stawki kandydata w PLN/h (pole oferty lub stawka w Profilu Championa).",
    workMode: "Określ tryb pracy: zdalnie, hybrydowo albo stacjonarnie.",
  };
  const OPEN_JOB = {
    ...JOB,
    remote_policy: null,
    effective_budget_hourly: null,
    has_budget_hourly: false,
  };

  beforeEach(() => {
    vi.clearAllMocks();
    mocks.roles = ["admin"];
    mocks.put.mockResolvedValue({ data: {} });
  });

  it("pasek postępu i sekcja „Gotowe” z tej samej listy braków", async () => {
    setup({}, { job: OPEN_JOB, readiness: { ready: false, blockers: [MSG.context, MSG.budget, MSG.workMode] } });
    const missing = await screen.findByRole("region", { name: "Braki w zleceniu" });
    // Zdalność nieznana → bez dni i miasta biura: 8 pozycji (z wymaganiami
    // do wyszukiwania), 3 brakuje.
    expect(within(missing).getByText("5 z 8 gotowe")).toBeInTheDocument();
    expect(within(missing).getByRole("progressbar")).toHaveAttribute("aria-valuenow", "5");
    const done = within(missing).getByRole("list", { name: "Gotowe" });
    expect(within(done).getByText("Klient: Bank Alfa")).toBeInTheDocument();
    expect(within(done).getByText("Rola: Java Developer")).toBeInTheDocument();
    expect(within(done).getByText(/Must-have: Java 17, Kafka/)).toBeInTheDocument();
  });

  it("budżet zapisuje się na miejscu przez Profil Championa i odświeża gotowość", async () => {
    setup({}, { job: OPEN_JOB, readiness: { ready: false, blockers: [MSG.budget] } });
    const input = await screen.findByLabelText("Budżet stawki kandydata w PLN/h");
    fireEvent.change(input, { target: { value: "abc" } });
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Wpisz samą liczbę");
    expect(mocks.put).not.toHaveBeenCalled();

    fireEvent.change(input, { target: { value: "150" } });
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    await vi.waitFor(() =>
      expect(mocks.put).toHaveBeenCalledWith("/api/jobs/7/champion-profile", {
        basics: { rate_value: 150, rate_raw: null },
      }),
    );
    await vi.waitFor(() => expect(mocks.showSuccess).toHaveBeenCalledWith("Budżet zapisany."));
    // Po zapisie gotowość czytana jest od nowa.
    await vi.waitFor(() =>
      expect(mocks.get.mock.calls.filter(([url]) => url === "/api/jobs/7/readiness").length).toBeGreaterThan(1),
    );
  });

  it("tryb pracy: trzy przyciski, zapis w Championie", async () => {
    setup({}, { job: OPEN_JOB, readiness: { ready: false, blockers: [MSG.workMode] } });
    const group = await screen.findByRole("group", { name: "Tryb pracy" });
    expect(within(group).getAllByRole("button").map((b) => b.textContent)).toEqual([
      "Zdalnie",
      "Hybrydowo",
      "W biurze",
    ]);
    fireEvent.click(within(group).getByRole("button", { name: "W biurze" }));
    await vi.waitFor(() =>
      expect(mocks.put).toHaveBeenCalledWith("/api/jobs/7/champion-profile", {
        basics: { work_mode: "stacjonarnie" },
      }),
    );
  });

  it("kontekst projektu prowadzi do Profilu Championa (i zamyka okno)", async () => {
    const handlers = setup({}, { job: OPEN_JOB, readiness: { ready: false, blockers: [MSG.context] } });
    fireEvent.click(await screen.findByRole("button", { name: /Uzupełnij w Championie/ }));
    expect(handlers.onOpenChange).toHaveBeenCalledWith(false);
    expect(handlers.onNavigate).toHaveBeenCalledWith("champion");
  });

  it("bez prawa edycji treści budżet i tryb są tylko linkiem do Championa", async () => {
    setup(
      { canEdit: false, canEditContent: false },
      { job: OPEN_JOB, readiness: { ready: false, blockers: [MSG.budget, MSG.workMode] } },
    );
    await screen.findByRole("region", { name: "Braki w zleceniu" });
    expect(screen.queryByLabelText("Budżet stawki kandydata w PLN/h")).not.toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Tryb pracy" })).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /Zobacz w Championie/ })).toHaveLength(2);
  });
});
