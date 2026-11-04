import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CvTopicResponse, CvTransitRow } from "@/lib/api/boardTasks";

const apiMock = vi.hoisted(() => ({ get: vi.fn() }));
const authState = vi.hoisted(() => ({ roles: ["recruiter"] as string[] }));

vi.mock("@/lib/api", () => ({ default: apiMock, api: apiMock }));
vi.mock("@/store/auth", async (orig) => {
  const actual = await orig<typeof import("@/store/auth")>();
  return {
    ...actual,
    useAuthStore: (selector: (state: unknown) => unknown) =>
      selector({
        user: { id: 5, role: authState.roles[0], roles: authState.roles },
      }),
  };
});

import { CvNotificationsDropdown } from "../CvNotificationsDropdown";

function transit(kind: CvTransitRow["kind"], stageId: number, name: string, extra: Partial<CvTransitRow> = {}): CvTransitRow {
  return {
    kind,
    stage_id: stageId,
    candidate_id: stageId,
    candidate_name: name,
    job_id: 11,
    job_title: "Tester",
    job_working_title: null,
    client_name: "Bank Przykładowy",
    since: new Date().toISOString(),
    actor_name: null,
    holder_name: null,
    reason: null,
    remark: null,
    card_edited_by: null,
    card_edited_fields: [],
    fix_labels: [],
    qc_status: null,
    ready_since: null,
    waiting_workdays: 0,
    can_nudge: false,
    ...extra,
  };
}

const RECRUITER: CvTopicResponse = {
  badge: 2,
  dl: null,
  recruiter: {
    to_check: [
      {
        document_id: 1,
        stage_id: 21,
        candidate_id: 21,
        candidate_name: "Ewa Lis",
        job_id: 13,
        job_title: "Analityk danych",
        job_working_title: null,
        client_name: null,
        since: new Date().toISOString(),
      },
    ],
    to_fix: [transit("sent_back", 22, "Jan Wiśniewski", { remark: "dopisz okres wypowiedzenia" })],
    with_dl: [transit("in_review", 23, "Ola Nowak", { qc_status: "passed", holder_name: "Piotr D." })],
    sent: [transit("sent", 24, "Marta Zielińska", { actor_name: "Paweł N." })],
  },
};

const DELIVERY_LEAD: CvTopicResponse = {
  badge: 2,
  recruiter: { to_check: [], to_fix: [], with_dl: [], sent: [] },
  dl: {
    to_send: [
      {
        stage_id: 31,
        candidate_id: 31,
        candidate_name: "Tomasz Mazur",
        job_id: 12,
        job_title: "DevOps Engineer",
        job_working_title: null,
        client_name: "Telekom Zachód",
        ready_since: new Date().toISOString(),
        waiting_workdays: 3,
        urgency: "late",
        handed_over_by_name: "Kasia W.",
        cpro: true,
      },
    ],
    to_send_total: 2,
    worst_urgency: "late",
    with_recruiters_total: 1,
    sent_today: [],
  },
};

function renderDropdown() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <CvNotificationsDropdown />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  apiMock.get.mockReset();
  authState.roles = ["recruiter"];
});

describe("CvNotificationsDropdown — ikona „CV” (16.10.2026)", () => {
  it("rekruter: liczba = do sprawdzenia + do poprawy, sekcje z jego CV", async () => {
    apiMock.get.mockResolvedValue({ data: RECRUITER });
    renderDropdown();
    const button = await screen.findByRole(
      "button",
      { name: "CV — czekają na Ciebie: 2" },
      { timeout: 5_000 },
    );
    expect(apiMock.get).toHaveBeenCalledWith("/api/board-tasks/cv");
    fireEvent.click(button);

    expect(await screen.findByRole("region", { name: "Do sprawdzenia" })).toHaveTextContent("Ewa Lis");
    const fix = screen.getByRole("region", { name: "Do poprawy" });
    expect(fix).toHaveTextContent("Jan Wiśniewski");
    expect(fix).toHaveTextContent("Uwaga: dopisz okres wypowiedzenia");
    expect(screen.getByRole("region", { name: "U Delivery Leada" })).toHaveTextContent(
      "Przegląda: Piotr D.",
    );
    expect(screen.getByRole("region", { name: "Wysłane do klienta" })).toHaveTextContent(
      "Wysłane przez: Paweł N.",
    );
    expect(screen.getByRole("link", { name: /Ewa Lis/ })).toHaveAttribute(
      "href",
      "/jobs/13?candidate=21&panel=cv",
    );
  });

  it("Delivery Lead: pigułka z kolorem pilności i kolejka „Do wysłania”", async () => {
    authState.roles = ["delivery_lead"];
    apiMock.get.mockResolvedValue({ data: DELIVERY_LEAD });
    renderDropdown();
    const pill = await screen.findByRole(
      "button",
      { name: "CV — czekają na Ciebie: 2" },
      { timeout: 5_000 },
    );
    expect(pill.className).toContain("bg-destructive");
    fireEvent.click(pill);
    const send = await screen.findByRole("region", { name: "Do wysłania do klienta" });
    expect(send).toHaveTextContent("Tomasz Mazur");
    expect(screen.getByRole("link", { name: /Tomasz Mazur/ })).toHaveAttribute(
      "href",
      "/jobs/12?candidate=31&review=1",
    );
    // Nordea: plakietka przy nazwisku jak w dawnym okienku „Do wysłania” (#2206).
    expect(send).toHaveTextContent("do Cpro");
    // Serwer tnie listę do 30 — przycięcie widać, nie wygląda jak cała kolejka.
    expect(screen.getByText("Pokazano 1 z 2 — najdłużej czekające.")).toBeInTheDocument();
    expect(screen.getByText(/1 osoba w „QC CV” jeszcze/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Przejrzyj po kolei \(2\)/ })).toBeInTheDocument();
  });

  it("odpowiedź w złym kształcie to awaria, nie wywrotka paska", async () => {
    apiMock.get.mockResolvedValue({ data: [] });
    renderDropdown();
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(apiMock.get).toHaveBeenCalledWith("/api/board-tasks/cv");
    expect(screen.queryByRole("button", { name: /^CV/ })).not.toBeInTheDocument();
  });

  it("konto bez roli rekrutera i DL nie pyta i nie ma ikony", async () => {
    authState.roles = ["finance"];
    renderDropdown();
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(apiMock.get).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /^CV/ })).not.toBeInTheDocument();
  });
});
