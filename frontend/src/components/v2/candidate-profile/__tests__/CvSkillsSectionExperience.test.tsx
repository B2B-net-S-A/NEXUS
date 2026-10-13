import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiGet = vi.fn();

vi.mock("@/lib/api", () => ({
  default: { get: (...args: unknown[]) => apiGet(...args) },
  extractErrorMsg: () => "",
  skillsApi: { list: vi.fn(async () => ({ data: { items: [] } })) },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showError: vi.fn(), showToast: vi.fn(), showSuccess: vi.fn() }),
}));
vi.mock("@/components/v2/files/FilePreviewModal", async () => {
  const actual = await vi.importActual<
    typeof import("@/components/v2/files/FilePreviewModal")
  >("@/components/v2/files/FilePreviewModal");
  return { ...actual, FilePreviewModal: () => null };
});
vi.mock("@/components/candidates/CandidateSourcesPanel", () => ({
  CandidateSourcesPanel: () => <div data-testid="sources-panel" />,
}));

import { CvSkillsSection } from "../CvSkillsSection";

/**
 * Zakładka „CV” (13.10.2026, E5): doświadczenie jako oś „daty · stanowisko ·
 * firma”, opis po rozwinięciu, 4 stanowiska + „+ N wcześniejsze”. Bez
 * „Zaangażowania” i synchronizacji LinkedIn (D3).
 */

const EXPERIENCE = [
  // Placeholder z backfillu Traffita — bez pustego wiersza.
  {},
  {
    role: "Senior Java Developer",
    company: "Bank Polski",
    start: "2021-03",
    end: null,
    desc: "Migracja systemu rozliczeń na mikroserwisy.",
    client: "PKO",
    employment_type: "b2b",
    technologies: ["Kafka", "Spring Boot"],
  },
  { role: "Java Developer", company: "Telekom", start: "2018-01", end: "2021-02" },
  { title: "Programista", company: "Software House", start_date: "2016-05", end_date: "2017-12" },
  { role: "Stażysta", company: "Uczelnia", start: "2015-07", end: "2015-09" },
  { role: "Praktykant", company: "Start-up", start: "2014-07", end: "2014-09" },
  { role: "Wolontariusz", company: "Fundacja", end: "2013-12" },
];

function renderSection(
  candidate: Record<string, unknown> = {},
  props: Partial<Parameters<typeof CvSkillsSection>[0]> = {},
) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrap = (ui: ReactNode) => (
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>
  );
  return render(
    wrap(
      <CvSkillsSection
        candidate={{ id: 42, experience: EXPERIENCE, cv_filename: "cv.pdf", ...candidate }}
        readOnly={false}
        onOpenFiles={vi.fn()}
        {...props}
      />,
    ),
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  apiGet.mockResolvedValue({ data: [] });
});

describe("CvSkillsSection — doświadczenie jako oś", () => {
  it("wiersz to „daty · stanowisko · firma”; 4 pierwsze, reszta pod „+ N wcześniejsze”", async () => {
    const user = userEvent.setup();
    renderSection();

    const section = screen.getByRole("region", { name: "Doświadczenie" });
    let rows = within(section).getAllByTestId("candidate-experience-row");
    expect(rows).toHaveLength(4);
    expect(rows[0]).toHaveTextContent("03.2021 – obecnie·Senior Java Developer·Bank Polski");
    expect(rows[1]).toHaveTextContent("01.2018 – 02.2021·Java Developer·Telekom");
    // `title` i `start_date`/`end_date` z innych odczytów CV.
    expect(rows[2]).toHaveTextContent("05.2016 – 12.2017·Programista·Software House");

    const more = within(section).getByRole("button", { name: "+ 2 wcześniejsze" });
    expect(more).toHaveAttribute("aria-expanded", "false");
    await user.click(more);
    rows = within(section).getAllByTestId("candidate-experience-row");
    expect(rows).toHaveLength(6);
    expect(rows[5]).toHaveTextContent("do 12.2013·Wolontariusz·Fundacja");
    await user.click(within(section).getByRole("button", { name: "Pokaż mniej" }));
    expect(within(section).getAllByTestId("candidate-experience-row")).toHaveLength(4);
  });

  it("opis, klient, forma i technologie dopiero po rozwinięciu „opis”", async () => {
    const user = userEvent.setup();
    renderSection();

    const [first, second] = within(
      screen.getByRole("region", { name: "Doświadczenie" }),
    ).getAllByTestId("candidate-experience-row");
    expect(screen.queryByText("Migracja systemu rozliczeń na mikroserwisy.")).toBeNull();
    expect(screen.queryByText("Kafka")).toBeNull();

    const toggle = within(first).getByRole("button", { name: "opis" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(within(first).getByText("Migracja systemu rozliczeń na mikroserwisy.")).toBeInTheDocument();
    expect(within(first).getByText(/dla: PKO/)).toBeInTheDocument();
    expect(within(first).getByText("Kafka")).toBeInTheDocument();

    // Stanowisko bez opisu i szczegółów nie ma czego rozwijać.
    expect(within(second).queryByRole("button", { name: "opis" })).toBeNull();
  });

  it("bez doświadczenia — bez sekcji", () => {
    renderSection({ experience: [{}, null] });
    expect(screen.queryByRole("region", { name: "Doświadczenie" })).toBeNull();
  });
});

describe("CvSkillsSection — wiersz CV i szczegóły", () => {
  it("„Generuj CV” z prawem zapisu; bez niego i w trybie odczytu — brak", () => {
    const onGenerateCv = vi.fn();
    const view = renderSection({}, { onGenerateCv });
    expect(screen.getByRole("button", { name: /Generuj CV/ })).toBeInTheDocument();
    view.unmount();

    renderSection({}, { onGenerateCv, readOnly: true });
    expect(screen.queryByRole("button", { name: /Generuj CV/ })).toBeNull();
  });

  it("profil bez CV: „Pliki →” przechodzi do plików", async () => {
    const user = userEvent.setup();
    const onOpenFiles = vi.fn();
    renderSection({ cv_filename: null }, { onOpenFiles });

    await user.click(screen.getByRole("button", { name: "Pliki →" }));
    expect(onOpenFiles).toHaveBeenCalledTimes(1);
  });

  it("szczegóły: źródła kandydata zostają, bez „Zaangażowania” i synchronizacji LinkedIn (D3)", async () => {
    const user = userEvent.setup();
    renderSection({ is_ambassador: true, linkedin_url: "https://linkedin.com/in/jan" });

    await user.click(
      screen.getByRole("button", { name: "Wykształcenie, certyfikaty i szczegóły" }),
    );
    expect(screen.getByTestId("sources-panel")).toBeInTheDocument();
    expect(screen.queryByText(/Zaangażowanie/)).toBeNull();
    expect(screen.queryByText(/LinkedIn/i)).toBeNull();
  });
});
