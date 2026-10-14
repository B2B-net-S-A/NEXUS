/**
 * Kolumna „Rekruter” listy rekrutacji z edycją (prośba Head of Recruitment, 14.10.2026):
 * okienko przy komórce zdejmuje osobę, przypisuje albo dodaje rekrutera
 * i rozstrzyga propozycję automatu — tymi samymi trasami co panel „Zespół”.
 * Komórka stoi w wierszu, którego klik otwiera rekrutację, więc żaden klik
 * w okienku nie może do niego dojść.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { JobRecruiterCell } from "@/components/v2/jobs/JobListCells";
import type { RequestBoard } from "@/lib/api/requestAllocation";
import type { JobRecruiter } from "@/lib/job-team";
import { useAuthStore, type User, type UserRole } from "@/store/auth";

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  delete: vi.fn(),
  patch: vi.fn(),
}));
const toast = vi.hoisted(() => ({
  showSuccess: vi.fn(),
  showError: vi.fn(),
  showInfo: vi.fn(),
}));

vi.mock("@/lib/api", () => ({ default: apiMock, api: apiMock }));
vi.mock("@/components/Toast", () => ({ useToast: () => toast }));

const JOB_ID = 11;
const TITLE = "Backend Engineer";

function account(id: number, name: string, role: UserRole): User {
  return {
    id,
    name,
    email: `${role}@example.com`,
    role,
    roles: [role],
    profile_completed: true,
    profile_completed_at: null,
    force_password_change: false,
    force_password_change_at: null,
    effective_section_access: { pipeline: "write" },
  };
}

const headOfRecruitment = account(8, "Henryk Pokazowy", "head_of_recruitment");
const deliveryLead = account(7, "Gosia Delivery", "delivery_lead");

const proposal: JobRecruiter = {
  user_id: 31,
  name: "Anna Przykładowa",
  via: "assignment",
  proposed: true,
  assigned_by_name: null,
};
const owner: JobRecruiter = {
  user_id: 32,
  name: "Bartek Testowy",
  via: "owner",
  proposed: false,
  assigned_by_name: null,
};

const JOBS = {
  empty: { status: "published", recruiters: [] as JobRecruiter[] },
  proposalOnly: { status: "published", recruiters: [proposal] },
  staffed: { status: "published", recruiters: [owner] },
  staffedWithStaleProposal: { status: "published", recruiters: [owner, proposal] },
};

const DIRECTORY = [
  { id: 31, name: "Anna Przykładowa", role: "recruiter", roles: ["recruiter"] },
  { id: 32, name: "Bartek Testowy", role: "recruiter", roles: ["recruiter"] },
  { id: 34, name: "Michał Makietowy", role: "recruiter", roles: ["recruiter"] },
  { id: 35, name: "Tola Wzorcowa", role: "recruiter", roles: ["recruiter"] },
  // Spoza puli automatu — bez liczby.
  { id: 36, name: "Ula Spozapuli", role: "recruiter", roles: ["recruiter"] },
  { id: 7, name: "Gosia Delivery", role: "delivery_lead", roles: ["delivery_lead"] },
];

const BOARD: RequestBoard = {
  mode: "shadow",
  availability_known: false,
  groups: [],
  requests: [],
  changes: [],
  load: [
    { user_id: 34, name: "Michał Makietowy", count: 3, leave_until: null, requests: [] },
    { user_id: 35, name: "Tola Wzorcowa", count: 1, proposed: 2, leave_until: null, requests: [] },
    { user_id: 31, name: "Anna Przykładowa", count: 0, leave_until: null, requests: [] },
  ],
};

function mockReads({
  directory = DIRECTORY as unknown,
  board = BOARD as unknown,
}: { directory?: unknown; board?: unknown } = {}) {
  apiMock.get.mockImplementation((url: string) => {
    const data = url === "/api/users" ? directory : url === "/api/request-board" ? board : null;
    return data instanceof Error ? Promise.reject(data) : Promise.resolve({ data });
  });
}

function renderCell(
  job: { status: string; recruiters: JobRecruiter[] },
  { as = headOfRecruitment, canDecide = true }: { as?: User; canDecide?: boolean } = {},
) {
  useAuthStore.setState({ user: as, realUser: null, token: "token", hydrated: true });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const rowSpy = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <table>
        <tbody>
          <tr onClick={rowSpy}>
            <td>
              <JobRecruiterCell
                job={job}
                edit={{ jobId: JOB_ID, jobTitle: TITLE, canDecide }}
              />
            </td>
          </tr>
        </tbody>
      </table>
    </QueryClientProvider>,
  );
  return { rowSpy };
}

async function openEditor(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: new RegExp(`Zmień rekrutera: ${TITLE}`) }));
  return screen.findByPlaceholderText("Szukaj rekrutera…");
}

const conflict = (detail: string) => ({ response: { status: 409, data: { detail } } });

beforeEach(() => {
  for (const mock of [...Object.values(apiMock), ...Object.values(toast)]) mock.mockReset();
  mockReads();
  apiMock.post.mockResolvedValue({ data: {} });
  apiMock.delete.mockResolvedValue({ data: {} });
});

describe("RecruiterCellEditor — zapisy", () => {
  it("bez prowadzącego wybór osoby ustawia pierwszego rekrutera; klik nie otwiera wiersza", async () => {
    const user = userEvent.setup();
    const { rowSpy } = renderCell(JOBS.empty);

    const search = await openEditor(user);
    // Fokus w polu szukania — Enter zaraz po otwarciu nie trafia w „×”.
    await waitFor(() => expect(search).toHaveFocus());
    expect(screen.getByText("Przypisz rekrutera")).toBeInTheDocument();
    await user.click(await screen.findByRole("option", { name: /Michał Makietowy/ }));

    await waitFor(() =>
      expect(apiMock.post).toHaveBeenCalledWith(`/api/jobs/${JOB_ID}/owner`, { user_id: 34 }),
    );
    await waitFor(() =>
      expect(toast.showSuccess).toHaveBeenCalledWith("Michał Makietowy: dodano do rekrutacji."),
    );
    expect(rowSpy).not.toHaveBeenCalled();
  });

  it("z prowadzącym kolejna osoba dochodzi jako współpracownik", async () => {
    const user = userEvent.setup();
    renderCell(JOBS.staffed);

    await openEditor(user);
    expect(screen.getByText("Dodaj kolejną osobę")).toBeInTheDocument();
    await user.click(await screen.findByRole("option", { name: /Tola Wzorcowa/ }));

    await waitFor(() =>
      expect(apiMock.post).toHaveBeenCalledWith(`/api/jobs/${JOB_ID}/collaborators`, {
        user_id: 35,
      }),
    );
  });

  it("sama propozycja automatu: Head of Recruitment wybiera osobę zamiast niej (decyzja „replace”)", async () => {
    const user = userEvent.setup();
    renderCell(JOBS.proposalOnly);

    await openEditor(user);
    expect(screen.getByRole("button", { name: "Akceptuj" })).toBeInTheDocument();
    await user.click(await screen.findByRole("option", { name: /Tola Wzorcowa/ }));

    await waitFor(() =>
      expect(apiMock.post).toHaveBeenCalledWith(
        `/api/request-board/jobs/${JOB_ID}/proposals/${proposal.user_id}`,
        { decision: "replace", replacement_user_id: 35 },
      ),
    );
    expect(apiMock.post).not.toHaveBeenCalledWith(`/api/jobs/${JOB_ID}/owner`, expect.anything());
  });

  it("wybór samej proponowanej osoby z listy to akceptacja propozycji", async () => {
    const user = userEvent.setup();
    renderCell(JOBS.proposalOnly);

    await openEditor(user);
    await user.click(await screen.findByRole("option", { name: /Anna Przykładowa/ }));

    await waitFor(() =>
      expect(apiMock.post).toHaveBeenCalledWith(
        `/api/request-board/jobs/${JOB_ID}/proposals/${proposal.user_id}`,
        { decision: "accept" },
      ),
    );
  });

  it("„Akceptuj” wysyła decyzję o propozycji", async () => {
    const user = userEvent.setup();
    renderCell(JOBS.proposalOnly);

    await openEditor(user);
    await user.click(screen.getByRole("button", { name: "Akceptuj" }));

    await waitFor(() =>
      expect(apiMock.post).toHaveBeenCalledWith(
        `/api/request-board/jobs/${JOB_ID}/proposals/${proposal.user_id}`,
        { decision: "accept" },
      ),
    );
  });

  it("Delivery Lead nie rozstrzyga propozycji — widzi, że czeka, a wybór przypisuje rekrutera", async () => {
    const user = userEvent.setup();
    renderCell(JOBS.proposalOnly, { as: deliveryLead, canDecide: false });

    await openEditor(user);
    expect(screen.queryByRole("button", { name: "Akceptuj" })).not.toBeInTheDocument();
    expect(screen.getByText("czeka na akceptację Head of Recruitment")).toBeInTheDocument();
    await user.click(await screen.findByRole("option", { name: /Tola Wzorcowa/ }));

    await waitFor(() =>
      expect(apiMock.post).toHaveBeenCalledWith(`/api/jobs/${JOB_ID}/owner`, { user_id: 35 }),
    );
  });

  it("propozycja przy obsadzonej rekrutacji jest nieaktualna — nie ma jej ani „Akceptuj”", async () => {
    const user = userEvent.setup();
    renderCell(JOBS.staffedWithStaleProposal);

    await openEditor(user);
    const people = screen.getByRole("list", { name: `Rekruter: ${TITLE}` });
    expect(within(people).getByText("Bartek Testowy")).toBeInTheDocument();
    expect(within(people).queryByText("Anna Przykładowa")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Akceptuj" })).not.toBeInTheDocument();
  });

  it("„×” pyta o potwierdzenie nad okienkiem i zdejmuje przez pulpit; klik nie otwiera wiersza", async () => {
    const user = userEvent.setup();
    const { rowSpy } = renderCell(JOBS.staffed);

    const search = await openEditor(user);
    const popover = search.closest("[data-radix-popper-content-wrapper] > *") as HTMLElement;
    await user.click(screen.getByRole("button", { name: "Zdejmij Bartek Testowy" }));

    const question = await screen.findByText("Zdjąć Bartek Testowy z tej rekrutacji?");
    const confirm = question.closest("[role='dialog']") as HTMLElement;
    // Okno potwierdzenia stoi na warstwie okienka i otwiera się później,
    // więc leży nad nim (do 14.10.2026 miało z-50 i chowało się pod spód).
    expect(popover).toHaveClass("z-110");
    expect(confirm).toHaveClass("z-110");
    expect(
      popover.compareDocumentPosition(confirm) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(apiMock.delete).not.toHaveBeenCalled();

    await user.click(within(confirm).getByRole("button", { name: "Zdejmij" }));

    await waitFor(() =>
      expect(apiMock.delete).toHaveBeenCalledWith(
        `/api/request-board/jobs/${JOB_ID}/people/${owner.user_id}`,
      ),
    );
    expect(rowSpy).not.toHaveBeenCalled();
  });

  it("odmowa serwera pokazuje jego zdanie", async () => {
    apiMock.post.mockRejectedValueOnce(conflict("Do requestu można dodać tylko rekrutera."));
    const user = userEvent.setup();
    renderCell(JOBS.empty);

    await openEditor(user);
    await user.click(await screen.findByRole("option", { name: /Tola Wzorcowa/ }));

    await waitFor(() =>
      expect(toast.showError).toHaveBeenCalledWith("Do requestu można dodać tylko rekrutera."),
    );
  });

  it("w trakcie zapisu kolejne osoby są wyłączone", async () => {
    apiMock.post.mockReturnValueOnce(new Promise(() => {}));
    const user = userEvent.setup();
    renderCell(JOBS.empty);

    await openEditor(user);
    await user.click(await screen.findByRole("option", { name: /Tola Wzorcowa/ }));

    await waitFor(() =>
      expect(screen.getByRole("option", { name: /Michał Makietowy/ })).toHaveAttribute(
        "aria-disabled",
        "true",
      ),
    );
  });

  it("zamknięcie i ponowne otwarcie okienka w trakcie zapisu nie zdejmuje blokady", async () => {
    // Bez blokady drugi wybór poszedłby znów jako pierwszy rekruter (`/owner`)
    // i zastąpił osobę z pierwszego zapisu, zamiast ją uzupełnić.
    apiMock.post.mockReturnValueOnce(new Promise(() => {}));
    const user = userEvent.setup();
    renderCell(JOBS.empty);

    await openEditor(user);
    await user.click(await screen.findByRole("option", { name: /Tola Wzorcowa/ }));
    await user.keyboard("{Escape}");
    await waitFor(() =>
      expect(screen.queryByPlaceholderText("Szukaj rekrutera…")).not.toBeInTheDocument(),
    );

    await openEditor(user);
    expect(await screen.findByRole("option", { name: /Michał Makietowy/ })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
  });
});

describe("RecruiterCellEditor — lista wyboru", () => {
  it("obłożenie przy osobach, od najmniej obłożonej; bez już pracujących i bez ról spoza rekrutera", async () => {
    const user = userEvent.setup();
    renderCell(JOBS.staffed);

    await openEditor(user);
    const options = (await screen.findAllByRole("option")).map((o) => o.textContent);
    expect(options).toEqual([
      expect.stringContaining("Anna Przykładowa"),
      expect.stringContaining("Tola Wzorcowa"),
      expect.stringContaining("Michał Makietowy"),
      "Ula Spozapuli",
    ]);
    expect(options[1]).toContain("1 P1");
    expect(options[1]).toContain("+ 2 do akceptacji");
    expect(options[2]).toContain("3 P1");
    expect(screen.getByText("Brak danych o urlopach — lista ich nie uwzględnia.")).toBeInTheDocument();
  });

  it("szuka bez polskich znaków", async () => {
    const user = userEvent.setup();
    renderCell(JOBS.empty);

    const search = await openEditor(user);
    await screen.findAllByRole("option");
    await user.type(search, "michal");

    await waitFor(() =>
      expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual([
        expect.stringContaining("Michał Makietowy"),
      ]),
    );
  });

  it("awaria obłożenia nie blokuje przypisania: lista bez liczb i komunikat", async () => {
    mockReads({ board: new Error("500") });
    const user = userEvent.setup();
    renderCell(JOBS.empty);

    await openEditor(user);
    expect(await screen.findByText(/Nie udało się pobrać obłożenia/)).toBeInTheDocument();
    const options = screen.getAllByRole("option").map((o) => o.textContent);
    expect(options).toContain("Michał Makietowy");
    expect(options.join(" ")).not.toMatch(/request/);
  });

  it("awaria listy osób to błąd, nie „nikogo nie ma”", async () => {
    mockReads({ directory: new Error("500") });
    const user = userEvent.setup();
    renderCell(JOBS.empty);

    await openEditor(user);
    expect(await screen.findByText("Nie udało się pobrać listy osób.")).toBeInTheDocument();
    expect(
      screen.queryByText("Wszyscy rekruterzy już pracują nad tą rekrutacją."),
    ).not.toBeInTheDocument();
  });
});

describe("JobRecruiterCell bez edycji", () => {
  it("bez `edit` komórka nie jest przyciskiem", () => {
    useAuthStore.setState({ user: headOfRecruitment, realUser: null, hydrated: true });
    render(<JobRecruiterCell job={JOBS.staffed} />);
    expect(screen.queryByRole("button", { name: /Zmień rekrutera/ })).not.toBeInTheDocument();
    expect(screen.getByText("Bartek T.")).toBeInTheDocument();
  });
});
