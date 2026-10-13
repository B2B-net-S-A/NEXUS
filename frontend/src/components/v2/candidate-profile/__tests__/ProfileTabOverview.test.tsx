/**
 * Zakładka „Przegląd” (od 13.10.2026, decyzja E2): „W skrócie” i „Ostatnio”,
 * główne umiejętności, „Do zrobienia” (tylko ruch po naszej stronie), pasek
 * „Z nami” i „Ostatnia rozmowa”.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const followup = vi.hoisted(() => ({ data: undefined as unknown }));
vi.mock("@/lib/api/candidateFollowups", () => ({
  useCandidateFollowup: () => ({ data: followup.data }),
}));
vi.mock("@/components/v2/followups/CandidateFollowupDialog", () => ({
  CandidateFollowupDialog: () => <div role="dialog" aria-label="Follow-up" />,
}));
vi.mock("@/components/v2/pages/CandidateActivitySummaryCard", () => ({
  CandidateActivitySummaryCard: () => <section aria-label="W skrócie" />,
}));
vi.mock("@/lib/api", () => ({
  skillsApi: { list: vi.fn(() => Promise.resolve({ data: { items: [] } })) },
}));

import { ProfileTab, type ProfileTabProps } from "../ProfileTab";

const HISTORY = [
  {
    job_id: 10,
    job_title: "Java Developer",
    client_name: "Bank X",
    job_status: "published",
    latest_stage: "cv_sent",
    latest_stage_name: "CV wysłane",
    last_seen: new Date(Date.now() - 4 * 86_400_000).toISOString(),
    next_action_owner: "client",
  },
  {
    job_id: 11,
    job_title: "Stara rekrutacja",
    client_name: "Bank Y",
    job_status: "closed",
    latest_stage: "rejected",
    next_action_owner: null,
  },
];

const NOTES = [
  {
    id: 1,
    group: "talks",
    content: "Przypięta, stara rozmowa",
    pinned_at: "2026-09-02T10:00:00Z",
    created_at: "2026-09-01T10:00:00Z",
    author_name: "Ola K",
  },
  {
    id: 2,
    group: "talks",
    content: "Szuka projektu od listopada.",
    created_at: "2026-09-28T10:00:00Z",
    author_name: "Marta Testowa",
    job_title: "Java Developer",
  },
];

function renderTab(overrides: Partial<ProfileTabProps> = {}) {
  const onNavigate = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
    <ProfileTab
      candidate={{
        id: 42,
        created_at: "2026-05-05T10:00:00Z",
        external_source: "traffit",
        experience: [
          { role: "Analityk systemowy", company: "Bank Północny", start: "2024-03", end: null },
          { role: "Business Analyst", company: "Bank Zielony", start: "2021-01", end: "2024-02" },
        ],
        skills: Array.from({ length: 10 }, (_, i) => ({ name: `Skill ${i + 1}`, years: i + 1 })),
      }}
      readOnly={false}
      recruitments={{ items: HISTORY, isPending: false, isError: false, refetch: vi.fn() }}
      notes={{
        items: NOTES,
        groupCounts: { talks: 2, contact: 3 },
        isPending: false,
        isError: false,
        refetch: vi.fn(),
      }}
      onNavigate={onNavigate}
      {...overrides}
    />
    </QueryClientProvider>,
  );
  return { onNavigate };
}

beforeEach(() => {
  followup.data = undefined;
});

describe("Przegląd — Do zrobienia", () => {
  const OUR_MOVE = {
    job_id: 12,
    job_title: "Analityk systemowy",
    client_name: "Kasa Krajowa",
    job_status: "published",
    latest_stage: "screening",
    latest_stage_name: "Screening",
    last_seen: new Date(Date.now() - 25 * 86_400_000).toISOString(),
    next_action_owner: "recruiter",
  };

  it("pokazuje tylko procesy z ruchem po naszej stronie, z etapem, dniami i linkiem do Tablicy", () => {
    renderTab({
      recruitments: {
        items: [...HISTORY, OUR_MOVE],
        isPending: false,
        isError: false,
        refetch: vi.fn(),
      },
    });
    const list = screen.getByTestId("now-recruitments");
    const row = within(list).getByText("Analityk systemowy").closest("li")!;
    expect(row).toHaveTextContent("Kasa Krajowa");
    expect(row).toHaveTextContent("ruch: rekruter · 25 dni");
    expect(within(row).getByRole("link", { name: /Tablica/ })).toHaveAttribute(
      "href",
      "/jobs/12?candidate=42",
    );
    // Ruch klienta i zakończona rekrutacja nie są „do zrobienia”.
    expect(within(list).queryByText("Java Developer")).toBeNull();
    expect(within(list).queryByText("Stara rekrutacja")).toBeNull();
    expect(screen.getByRole("button", { name: /Wszystkie w toku \(2\)/ })).toBeInTheDocument();
  });

  it("gdy ruch jest wszędzie po stronie klienta, mówi to zdaniem z linkiem do Rekrutacji", async () => {
    const user = userEvent.setup();
    const { onNavigate } = renderTab();
    expect(screen.getByTestId("now-nothing-on-us")).toHaveTextContent(
      "W 1 procesie ruch jest po stronie klienta albo kandydata.",
    );
    await user.click(screen.getByRole("button", { name: "Rekrutacje w toku (1)" }));
    expect(onNavigate).toHaveBeenCalledWith({ section: "recruitments" });
  });

  it("bez procesów w toku mówi to zdaniem, z ostatnim wynikiem, i prowadzi do zakończonych", async () => {
    const user = userEvent.setup();
    const { onNavigate } = renderTab({
      recruitments: { items: [HISTORY[1]], isPending: false, isError: false, refetch: vi.fn() },
    });
    expect(screen.getByText(/Nie jest teraz w żadnej rekrutacji/)).toHaveTextContent(
      "Ostatnio: odrzucony · Stara rekrutacja",
    );
    await user.click(screen.getByRole("button", { name: "Zakończone rekrutacje (1)" }));
    expect(onNavigate).toHaveBeenCalledWith({ section: "recruitments" });
  });

  it("awaria historii to komunikat z „Ponów”, nie „brak rekrutacji”", () => {
    renderTab({
      recruitments: { items: [], isPending: false, isError: true, refetch: vi.fn() },
    });
    expect(screen.getByRole("alert")).toHaveTextContent("Nie udało się wczytać rekrutacji.");
    expect(screen.queryByText(/Nie jest teraz/)).toBeNull();
  });

  it("zaległy telefon po ciszy klienta otwiera zapis wyniku", async () => {
    followup.data = {
      followup: {
        state: "overdue",
        overdue_days: 3,
        due_on: "2026-10-01",
        caller_name: "Anna Kowalczyk",
        processes: [{}, {}],
      },
    };
    const user = userEvent.setup();
    renderTab();
    const callout = screen.getByTestId("now-followup");
    expect(callout).toHaveTextContent("Telefon po ciszy klienta: zaległy 3 dni");
    expect(callout).toHaveTextContent("dzwoni Anna K.");
    await user.click(within(callout).getByRole("button", { name: "Zapisz wynik telefonu" }));
    expect(screen.getByRole("dialog", { name: "Follow-up" })).toBeInTheDocument();
  });
});

describe("Przegląd — Ostatnia rozmowa", () => {
  it("pokazuje najnowszą rozmowę (nie przypiętą) i liczbę prób kontaktu", async () => {
    const user = userEvent.setup();
    const { onNavigate } = renderTab();
    const card = screen.getByTestId("last-talk");
    expect(card).toHaveTextContent("Szuka projektu od listopada.");
    expect(card).toHaveTextContent("Marta Testowa");
    expect(screen.getByRole("button", { name: "Prób kontaktu: 3" })).toBeInTheDocument();
    await user.click(within(card).getByRole("button", { name: "Otwórz notatkę" }));
    expect(onNavigate).toHaveBeenCalledWith({ section: "activity", noteId: 2 });
  });

  // Przegląd kodu 13.10.2026: przycisk prowadził na „Rozmowy”, gdzie prób
  // kontaktu nie ma (osobna grupa `contact`).
  it("„Prób kontaktu: N” otwiera filtr prób kontaktu, nie rozmów", async () => {
    const user = userEvent.setup();
    const { onNavigate } = renderTab();
    await user.click(screen.getByRole("button", { name: "Prób kontaktu: 3" }));
    expect(onNavigate).toHaveBeenCalledWith({ section: "activity", activity: "contact" });
  });

  it("bez rozmów mówi to zdaniem", () => {
    renderTab({
      notes: { items: [], groupCounts: {}, isPending: false, isError: false, refetch: vi.fn() },
    });
    expect(screen.getByText("Nikt jeszcze nie zapisał rozmowy z tą osobą.")).toBeInTheDocument();
  });
});

describe("Przegląd — kim jest", () => {
  it("pokazuje ostatnie stanowiska i 8 umiejętności z linkiem do zakładki CV", async () => {
    const user = userEvent.setup();
    const { onNavigate } = renderTab();
    const roles = screen.getByTestId("recent-roles");
    expect(roles).toHaveTextContent("Analityk systemowy · Bank Północny");
    expect(roles).toHaveTextContent("03.2024 – obecnie");
    const skills = screen.getByRole("region", { name: "Główne umiejętności" });
    // Kolejność z `displaySkills`: najdłuższy staż pierwszy.
    expect(within(skills).getByText("Skill 10")).toBeInTheDocument();
    expect(within(skills).queryByText("Skill 2")).toBeNull();
    await user.click(within(skills).getByRole("button", { name: "+2 w zakładce CV" }));
    expect(onNavigate).toHaveBeenCalledWith({ section: "cv" });
  });

  it("pasek „Z nami” liczy procesy i mówi, skąd i od kiedy osoba jest w bazie", () => {
    renderTab();
    const strip = screen.getByLabelText("Z nami");
    expect(within(strip).getByRole("button", { name: "W toku: 1" })).toBeInTheDocument();
    expect(strip).toHaveTextContent("Zakończone: 1");
    expect(strip).toHaveTextContent("W bazie od 5.05.2026 (Traffit)");
  });
});
