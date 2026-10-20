import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { HrConfig } from "@/lib/api/hr";

import { HrSettings, availableHrSettingsTabs } from "../HrSettings";

const nav = vi.hoisted(() => ({ params: new URLSearchParams(), replaceUrl: vi.fn() }));

vi.mock("next/navigation", () => ({
  useSearchParams: () => nav.params,
  usePathname: () => "/settings/hr",
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));
vi.mock("@/lib/url-selection", () => ({ useUrlWriter: () => ({ replaceUrl: nav.replaceUrl }) }));
vi.mock("@/components/hr/lifecycle/LifecycleTemplatesCard", () => ({
  LifecycleTemplatesCard: () => <div>Karta: ścieżki wejścia i odejścia</div>,
}));
vi.mock("@/components/hr/people/agreements/AgreementTemplatesCard", () => ({
  AgreementTemplatesCard: () => <div>Karta: wzory umów z pracownikami</div>,
}));
vi.mock("@/components/hr/people/documents/DocumentsRetentionCard", () => ({
  DocumentsRetentionCard: () => <div>Karta: retencja</div>,
}));
vi.mock("../M365Card", () => ({ M365Card: () => <div>Karta: Microsoft 365 — urlopy</div> }));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn() }) }));
vi.mock("@/components/v2/modals/ConfirmV2", () => ({ useConfirmV2: () => ({ askConfirm: vi.fn(), confirmDialog: null }) }));
vi.mock("@/lib/api/hr", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/hr")>();
  const idle = { isPending: false, mutate: vi.fn(), mutateAsync: vi.fn() };
  return {
    ...actual,
    useCompanyDaysOff: () => ({ isLoading: false, isError: false, isSuccess: true, data: [], refetch: vi.fn() }),
    useAvailabilitySource: () => ({ data: "compass" }),
    useAddDayOff: () => idle,
    useRemoveDayOff: () => idle,
    useSetAvailabilitySource: () => idle,
    useSetHrModules: () => idle,
  };
});
vi.mock("../RoleDefaultsCard", () => ({ RoleDefaultsCard: () => <div>Karta: domyślne opisy godzin</div> }));
vi.mock("@/components/hr/approvals/ApprovalRulesCard", () => ({
  ApprovalRulesCard: () => <div>Karta: zgody — kto zatwierdza</div>,
}));

const ALL_OPEN = {
  people: true, leave: true, time: true, payroll: true, lifecycle: true,
  care: true, cases: true, equipment: true, settlements: true,
} as unknown as HrConfig["open_modules"];

const config = (me: Partial<HrConfig["me"]>, open: Partial<HrConfig["open_modules"]> = {}): HrConfig =>
  ({
    program: true,
    modules: ALL_OPEN,
    open_modules: { ...ALL_OPEN, ...open },
    me: {
      has_profile: true, employment_status: null, is_manager: false, direct_reports: 0,
      is_admin: false, people_admin: false, payroll: false, equipment: false, cases: false,
      ...me,
    },
  }) as HrConfig;

describe("availableHrSettingsTabs — te same warunki co karty przed zakładkami", () => {
  it("admin widzi wszystkie pięć, Kadry bez admina — bez modułów", () => {
    expect(availableHrSettingsTabs(config({ is_admin: true, people_admin: true }))).toEqual([
      "kalendarz", "wejscie-odejscie", "urlopy", "dokumenty", "moduly",
    ]);
    expect(availableHrSettingsTabs(config({ people_admin: true }))).toEqual([
      "kalendarz", "wejscie-odejscie", "urlopy", "dokumenty",
    ]);
  });

  it("head back office widzi tylko ścieżki wejścia i odejścia", () => {
    expect(availableHrSettingsTabs(config({ back_office_head: true }))).toEqual(["wejscie-odejscie"]);
    expect(availableHrSettingsTabs(config({ back_office_head: true }, { lifecycle: false }))).toEqual([]);
  });

  it("zamknięty moduł chowa zakładkę", () => {
    expect(
      availableHrSettingsTabs(config({ people_admin: true }, { lifecycle: false, people: false })),
    ).toEqual(["kalendarz", "urlopy"]);
  });
});

describe("HrSettings — zakładki zamiast ośmiu kart (20.10.2026)", () => {
  beforeEach(() => {
    nav.params = new URLSearchParams();
    nav.replaceUrl.mockReset();
  });

  it("pierwsza dostępna zakładka bez parametru, zmiana zapisuje się w adresie", async () => {
    const user = userEvent.setup();
    render(<HrSettings config={config({ people_admin: true })} />);
    expect(screen.getByText("Karta: domyślne opisy godzin")).toBeInTheDocument();
    expect(screen.queryByText("Karta: Microsoft 365 — urlopy")).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Urlopy i M365" }));
    expect(nav.replaceUrl).toHaveBeenCalledWith("/settings/hr?zakladka=urlopy");
  });

  it("otwiera zakładkę z adresu; niedostępna wraca do pierwszej", () => {
    nav.params = new URLSearchParams("zakladka=dokumenty");
    const { unmount } = render(<HrSettings config={config({ people_admin: true })} />);
    expect(screen.getByText("Karta: wzory umów z pracownikami")).toBeInTheDocument();
    expect(screen.getByText("Karta: retencja")).toBeInTheDocument();
    unmount();

    nav.params = new URLSearchParams("zakladka=moduly");
    render(<HrSettings config={config({ people_admin: true })} />);
    expect(screen.queryByRole("tab", { name: "Moduły" })).not.toBeInTheDocument();
    expect(screen.getByText("Karta: domyślne opisy godzin")).toBeInTheDocument();
  });

  it("drogowskaz do Płac zostaje — z linkiem tylko przy uprawnieniu „Płace”", () => {
    const { unmount } = render(<HrSettings config={config({ people_admin: true })} />);
    expect(screen.getByText(/Reguły premii są w Ustawienia → Płace/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Ustawienia → Płace" })).not.toBeInTheDocument();
    unmount();
    render(<HrSettings config={config({ people_admin: true, payroll: true })} />);
    expect(screen.getByRole("link", { name: "Ustawienia → Płace" })).toHaveAttribute("href", "/settings/payroll");
  });

  it("zasady zgód tylko przy włączonym module „Zgody” (21.10.2026: wyłączony = ukryty także adminowi)", () => {
    nav.params = new URLSearchParams("zakladka=moduly");
    const off = { ...config({ is_admin: true }), modules: { ...ALL_OPEN, approvals: false } } as HrConfig;
    const { unmount } = render(<HrSettings config={off} />);
    expect(screen.queryByText("Karta: zgody — kto zatwierdza")).not.toBeInTheDocument();
    unmount();
    const on = { ...config({ is_admin: true }), modules: { ...ALL_OPEN, approvals: true } } as HrConfig;
    render(<HrSettings config={on} />);
    expect(screen.getByText("Karta: zgody — kto zatwierdza")).toBeInTheDocument();
  });

  it("jedna zakładka = bez paska zakładek", () => {
    render(<HrSettings config={config({ back_office_head: true })} />);
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
    expect(screen.getByText("Karta: ścieżki wejścia i odejścia")).toBeInTheDocument();
  });
});
