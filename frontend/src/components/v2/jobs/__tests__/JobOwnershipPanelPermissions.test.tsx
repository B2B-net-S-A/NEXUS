/**
 * Wiersz „Rekruter” panelu zespołu (`JobOwnershipPanel`, decyzja Artura
 * 02.10.2026): kto widzi który przycisk i dokąd trafia zapis.
 *
 * Trzy role rekrutacji zamiast „właściciela” i „współpracowników”: Rekruterem
 * jest osoba, która nad rekrutacją pracuje. Automat tylko proponuje — o
 * propozycji decyduje Head of Recruitment albo admin, a do tego czasu nikt nie
 * jest przypisany.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  JobOwnershipPanel,
  type JobOwnershipJob,
} from "@/components/v2/jobs/JobOwnershipPanel";
import { BOARD_TASKS_QUERY_KEY } from "@/lib/api/boardTasks";
import { REQUEST_BOARD_QUERY_KEY } from "@/lib/api/requestAllocation";
import type { JobRecruiter } from "@/lib/job-team";
import { permissionSnapshot } from "@/__tests__/fixtures/permission-snapshot";
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
// Okno ma własny test — tu liczy się, czy panel je otwiera i z kim.
vi.mock("@/components/v2/modals/ReassignOwnerV2", () => ({
  ReassignOwnerV2: ({
    open,
    currentOwner,
  }: {
    open: boolean;
    currentOwner: { name: string } | null;
  }) =>
    open ? (
      <div
        role="dialog"
        aria-label={
          currentOwner ? `Zmień rekrutera: ${currentOwner.name}` : "Przypisz rekrutera"
        }
      />
    ) : null,
}));

const JOB_ID = 11;

function account(
  id: number,
  name: string,
  role: UserRole,
  pipeline: "read" | "write" = "write",
): User {
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
    effective_section_access: { pipeline },
  };
}

const admin = account(1, "Adam Admin", "admin");
const deliveryLead = account(7, "Gosia Delivery", "delivery_lead");
const headOfRecruitment = account(8, "Henryk Pokazowy", "head_of_recruitment");
const recruiter = account(9, "Ewa Fikcyjna", "recruiter");
const communityManager = account(12, "Hanna Wzorcowa", "talent_community_manager");
const viewer = account(13, "Igor Podglądowy", "user", "read");

const proposal: JobRecruiter = {
  user_id: 31,
  name: "Anna Przykładowa",
  via: "assignment",
  proposed: true,
  assigned_by_name: null,
};
const first: JobRecruiter = {
  user_id: 32,
  name: "Bartek Testowy",
  via: "owner",
  proposed: false,
  assigned_by_name: "Gosia Delivery",
};
const second: JobRecruiter = {
  user_id: 33,
  name: "Celina Wzorcowa",
  via: "collaborator",
  proposed: false,
  assigned_by_name: null,
};

const firstAsOwner = {
  id: first.user_id,
  name: first.name,
  email: "bartek@example.com",
  role: "recruiter" as const,
};

/** (a) propozycja automatu, (b) rekruter i druga osoba, (c) nikt. */
const JOBS = {
  proposalOnly: { status: "published", primary_owner: null, recruiters: [proposal] },
  staffed: {
    status: "published",
    primary_owner: firstAsOwner,
    recruiters: [first, second],
  },
  empty: { status: "published", primary_owner: null, recruiters: [] },
} satisfies Record<string, JobOwnershipJob>;

const DIRECTORY = [
  { id: 31, name: "Anna Przykładowa", role: "recruiter", roles: ["recruiter"] },
  { id: 32, name: "Bartek Testowy", role: "recruiter", roles: ["recruiter"] },
  { id: 33, name: "Celina Wzorcowa", role: "recruiter", roles: ["recruiter"] },
  { id: 34, name: "Darek Makietowy", role: "recruiter", roles: ["recruiter"] },
  { id: 35, name: "Tola Tacowa", role: "recruiter", roles: ["recruiter"] },
  { id: 7, name: "Gosia Delivery", role: "delivery_lead", roles: ["delivery_lead"] },
  { id: 8, name: "Henryk Pokazowy", role: "head_of_recruitment", roles: ["head_of_recruitment"] },
  { id: 40, name: "Franek Finansowy", role: "finance", roles: ["finance"] },
];

function renderPanel(
  job: JobOwnershipJob,
  {
    as = deliveryLead,
    canEdit = true,
    previewedBy = null,
  }: {
    as?: User;
    canEdit?: boolean;
    /** Admin w trybie „podgląd jako” — sesja tylko do odczytu. */
    previewedBy?: User | null;
  } = {},
) {
  useAuthStore.setState({
    user: as,
    realUser: previewedBy,
    token: "token",
    hydrated: true,
  });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const invalidateSpy = vi.spyOn(client, "invalidateQueries");
  const view = render(
    <QueryClientProvider client={client}>
      <JobOwnershipPanel
        jobId={JOB_ID}
        jobTitle="Backend Engineer"
        job={job}
        canEdit={canEdit}
      />
    </QueryClientProvider>,
  );
  return {
    ...view,
    invalidatedKeys: () =>
      invalidateSpy.mock.calls.map(
        (call) => (call[0] as { queryKey: unknown[] })?.queryKey,
      ),
  };
}

/** Nazwy przycisków wiersza, w kolejności na ekranie. */
function actions(): string[] {
  return within(screen.getByTestId("job-recruiters"))
    .queryAllByRole("button")
    .map((button) => (button.getAttribute("aria-label") ?? button.textContent ?? "").trim());
}

const TEAM_KEYS = [
  ["job", JOB_ID],
  ["job", String(JOB_ID)],
  ["jobs-v2"],
  ["jobs-quick-counts"],
  REQUEST_BOARD_QUERY_KEY,
  BOARD_TASKS_QUERY_KEY,
];

function expectTeamRefreshed(keys: unknown[][]) {
  for (const key of TEAM_KEYS) expect(keys).toContainEqual(key);
}

const conflict = (detail: string) => ({ response: { status: 409, data: { detail } } });

beforeEach(() => {
  for (const mock of [...Object.values(apiMock), ...Object.values(toast)]) mock.mockReset();
  apiMock.get.mockResolvedValue({ data: DIRECTORY });
  apiMock.post.mockResolvedValue({ data: {} });
  apiMock.delete.mockResolvedValue({ data: {} });
});

describe("JobOwnershipPanel — kto widzi który przycisk", () => {
  const ACCEPT = ["Akceptuj", "Zmień propozycję: Anna Przykładowa", "Odrzuć"];
  const REMOVE_BOTH = ["Zdejmij Bartek Testowy", "Zdejmij Celina Wzorcowa"];

  it.each<[string, User, Record<keyof typeof JOBS, string[]>]>([
    [
      "Delivery Lead przydziela, zmienia i dokłada ludzi; propozycji nie rozstrzyga",
      deliveryLead,
      {
        proposalOnly: ["Przypisz…", "Biorę"],
        staffed: [...REMOVE_BOTH, "Dołącz", "Zmień rekrutera", "+ Dodaj osobę"],
        empty: ["Przypisz…", "Biorę"],
      },
    ],
    [
      "Head of Recruitment rozstrzyga propozycje i przydziela, ale sam rekrutacji nie bierze",
      headOfRecruitment,
      {
        proposalOnly: [...ACCEPT, "Przypisz…"],
        staffed: [...REMOVE_BOTH, "Zmień rekrutera", "+ Dodaj osobę"],
        empty: ["Przypisz…"],
      },
    ],
    [
      "admin ma wszystko naraz",
      admin,
      {
        proposalOnly: [...ACCEPT, "Przypisz…", "Biorę"],
        staffed: [...REMOVE_BOTH, "Dołącz", "Zmień rekrutera", "+ Dodaj osobę"],
        empty: ["Przypisz…", "Biorę"],
      },
    ],
    [
      "rekruter bierze wolną rekrutację albo dołącza do zajętej; kolejną osobę dopisuje jak każdy redagujący",
      recruiter,
      {
        proposalOnly: ["Biorę", "+ Dodaj osobę"],
        staffed: ["Zdejmij Celina Wzorcowa", "Dołącz", "+ Dodaj osobę"],
        empty: ["Biorę", "+ Dodaj osobę"],
      },
    ],
    [
      "rola redagująca, która sama rekruterem nie zostaje (TCM): tylko kolejne osoby",
      communityManager,
      {
        proposalOnly: ["+ Dodaj osobę"],
        staffed: ["Zdejmij Celina Wzorcowa", "+ Dodaj osobę"],
        empty: ["+ Dodaj osobę"],
      },
    ],
    [
      "konto podglądu (sekcja tylko do odczytu) nie ma żadnej akcji",
      viewer,
      { proposalOnly: [], staffed: [], empty: [] },
    ],
  ])("%s", (_name, as, expected) => {
    for (const key of Object.keys(JOBS) as (keyof typeof JOBS)[]) {
      const view = renderPanel(JOBS[key], { as });
      expect(actions(), key).toEqual(expected[key]);
      view.unmount();
    }
  });

  it("bez prawa edycji rekruter może tylko wziąć wolną rekrutację", () => {
    const free = renderPanel(JOBS.empty, { as: recruiter, canEdit: false });
    expect(actions()).toEqual(["Biorę"]);
    free.unmount();

    // „Dołącz” to dopisanie siebie jako kolejnej osoby — serwer wymaga edycji.
    renderPanel(JOBS.staffed, { as: recruiter, canEdit: false });
    expect(actions()).toEqual([]);
  });

  it("osoba, która już pracuje nad rekrutacją, nie widzi „Dołącz”", () => {
    renderPanel(JOBS.staffed, { as: { ...recruiter, id: second.user_id } });
    expect(actions()).toEqual(["Zdejmij Celina Wzorcowa", "+ Dodaj osobę"]);
  });

  it("`can_staff` z serwera wygrywa z rolą — Delivery Lead spoza zakresu nie przydziela", () => {
    renderPanel({ ...JOBS.staffed, can_staff: false });
    expect(actions()).toEqual(["Zdejmij Celina Wzorcowa", "Dołącz", "+ Dodaj osobę"]);
  });

  // Przydział idzie za uprawnieniem „Rekrutacje: zakładanie, zamykanie,
  // wysyłka CV do klienta” (albo rolą Head of Recruitment), nie za rolą DL.
  it("rekruter z nadanym uprawnieniem do prowadzenia rekrutacji przydziela jak Delivery Lead", () => {
    renderPanel(JOBS.staffed, {
      as: {
        ...recruiter,
        effective_action_access: permissionSnapshot("recruitment_manage"),
      },
    });
    expect(actions()).toEqual([
      "Zdejmij Bartek Testowy",
      "Zdejmij Celina Wzorcowa",
      "Dołącz",
      "Zmień rekrutera",
      "+ Dodaj osobę",
    ]);
  });

  it("Delivery Lead z wyłączonym uprawnieniem nie przydziela — zostaje mu to, co ma każdy redagujący", () => {
    renderPanel(JOBS.staffed, {
      as: {
        ...deliveryLead,
        effective_action_access: permissionSnapshot("delivery_view", "clients_edit"),
      },
    });
    expect(actions()).toEqual(["Zdejmij Celina Wzorcowa", "Dołącz", "+ Dodaj osobę"]);
  });

  it("`can_staff: true` nie daje przydziału bez zapisu w sekcji ani w podglądzie „jako”", () => {
    const readOnly = renderPanel(
      { ...JOBS.empty, can_staff: true },
      { as: { ...deliveryLead, effective_section_access: { pipeline: "read" } } },
    );
    expect(actions()).toEqual([]);
    readOnly.unmount();

    renderPanel(
      { ...JOBS.proposalOnly, can_staff: true },
      { as: headOfRecruitment, previewedBy: admin },
    );
    expect(actions()).toEqual([]);
  });

  it("zamkniętej rekrutacji nikt już nie bierze", () => {
    renderPanel({ ...JOBS.empty, status: "closed" }, { as: recruiter });
    expect(actions()).toEqual(["+ Dodaj osobę"]);
  });
});

describe("JobOwnershipPanel — co widać w wierszu", () => {
  it("nikt nie pracuje: „Bez rekrutera” i zdanie, co dalej — inne dla każdej roli", () => {
    const staff = renderPanel(JOBS.empty, { as: headOfRecruitment });
    expect(screen.getByText("Bez rekrutera")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Przypisz osobę albo poczekaj na propozycję automatu (jeśli jest włączony).",
      ),
    ).toBeInTheDocument();
    staff.unmount();

    const taker = renderPanel(JOBS.empty, { as: recruiter });
    expect(
      screen.getByText("Możesz wziąć tę rekrutację — kliknij „Biorę”."),
    ).toBeInTheDocument();
    taker.unmount();

    renderPanel(JOBS.empty, { as: viewer });
    expect(
      screen.getByText("Rekrutera przydziela Delivery Lead albo Head of Recruitment."),
    ).toBeInTheDocument();
  });

  it("przy priorytecie „Przyjmujemy kandydatów” nie obiecuje propozycji automatu", () => {
    renderPanel({ ...JOBS.empty, priority_level: "accepting" });
    expect(
      screen.getByText(
        "Przypisz osobę — przy priorytecie „Przyjmujemy kandydatów” automat nikogo nie proponuje.",
      ),
    ).toBeInTheDocument();
  });

  it("propozycja automatu to jeszcze nie rekruter: przerywana ramka i „Czeka na akceptację…”", () => {
    renderPanel(JOBS.proposalOnly, { as: recruiter });
    const list = screen.getByRole("list", { name: "Rekruter" });
    expect(within(list).getByText("Anna Przykładowa").closest("[data-proposed]")).toHaveAttribute(
      "data-proposed",
      "true",
    );
    expect(
      within(list).getByText("Czeka na akceptację Head of Recruitment"),
    ).toBeInTheDocument();
    // Propozycja mówi sama za siebie — bez „Bez rekrutera” i bez zdania „co dalej”.
    expect(screen.queryByText("Bez rekrutera")).not.toBeInTheDocument();
    expect(screen.queryByText(/Możesz wziąć tę rekrutację/)).not.toBeInTheDocument();
  });

  it("pod osobą stoi, kto ją przydzielił", () => {
    renderPanel(JOBS.staffed, { as: viewer });
    expect(screen.getByText("przydzielił(a) Gosia D.")).toBeInTheDocument();
    expect(screen.getByText("Bartek Testowy")).toBeInTheDocument();
    expect(screen.getByText("Celina Wzorcowa")).toBeInTheDocument();
  });

  it("pierwszy rekruter z nieaktywnym kontem = rekrutacja wolna, z wyjaśnieniem", () => {
    renderPanel(
      {
        status: "published",
        primary_owner: { ...firstAsOwner, name: "Była Rekruterka", is_active: false },
        recruiters: [],
      },
      { as: recruiter },
    );
    expect(
      screen.getByText(
        "Była Rekruterka ma nieaktywne konto. Możesz wziąć tę rekrutację — kliknij „Biorę”.",
      ),
    ).toBeInTheDocument();
    expect(actions()).toContain("Biorę");
  });

  it("starszy serwer bez `recruiters`: pierwszy rekruter i osoby dopisane ręcznie, bez całej kategorii", () => {
    renderPanel(
      {
        status: "published",
        primary_owner: firstAsOwner,
        collaborators: [
          { id: 33, name: "Celina Wzorcowa", role: "recruiter", source: "manual" },
          { id: 50, name: "Cała Kategoria", role: "recruiter", source: "auto_cc" },
        ],
      },
      { as: viewer },
    );
    const list = screen.getByRole("list", { name: "Rekruter" });
    expect(within(list).getByText("Bartek Testowy")).toBeInTheDocument();
    expect(within(list).getByText("Celina Wzorcowa")).toBeInTheDocument();
    expect(within(list).queryByText("Cała Kategoria")).not.toBeInTheDocument();
  });

  it("nie używa dawnych nazw ról", () => {
    renderPanel(JOBS.staffed);
    for (const gone of [/Właściciel projektu/, /Współpracownicy/, /Prowadzi/, /Przejmij rekrutację/]) {
      expect(screen.queryByText(gone)).not.toBeInTheDocument();
    }
  });
});

describe("JobOwnershipPanel — zapisy", () => {
  it("„Biorę” woła /claim i odświeża obsadę na wszystkich ekranach", async () => {
    const user = userEvent.setup();
    const { invalidatedKeys } = renderPanel(JOBS.empty, { as: recruiter });

    await user.click(screen.getByRole("button", { name: "Biorę" }));

    await waitFor(() =>
      expect(apiMock.post).toHaveBeenCalledWith(`/api/jobs/${JOB_ID}/claim`),
    );
    await waitFor(() =>
      expect(toast.showSuccess).toHaveBeenCalledWith("Od teraz pracujesz nad tą rekrutacją."),
    );
    expectTeamRefreshed(invalidatedKeys());
  });

  it("409 przy „Biorę” pokazuje zdanie serwera i też odświeża (ktoś był szybszy)", async () => {
    apiMock.post.mockRejectedValueOnce(conflict("Ta rekrutacja ma już rekrutera"));
    const user = userEvent.setup();
    const { invalidatedKeys } = renderPanel(JOBS.empty, { as: recruiter });

    await user.click(screen.getByRole("button", { name: "Biorę" }));

    await waitFor(() =>
      expect(toast.showError).toHaveBeenCalledWith("Ta rekrutacja ma już rekrutera"),
    );
    expect(toast.showSuccess).not.toHaveBeenCalled();
    expectTeamRefreshed(invalidatedKeys());
  });

  it("„Dołącz” dopisuje zalogowaną osobę jako kolejną", async () => {
    const user = userEvent.setup();
    renderPanel(JOBS.staffed, { as: recruiter });

    await user.click(screen.getByRole("button", { name: "Dołącz" }));

    await waitFor(() =>
      expect(apiMock.post).toHaveBeenCalledWith(`/api/jobs/${JOB_ID}/collaborators`, {
        user_id: recruiter.id,
      }),
    );
  });

  it("„Akceptuj” i „Odrzuć” wysyłają decyzję o propozycji", async () => {
    const user = userEvent.setup();
    const accepted = renderPanel(JOBS.proposalOnly, { as: headOfRecruitment });
    await user.click(screen.getByRole("button", { name: "Akceptuj" }));
    await waitFor(() =>
      expect(apiMock.post).toHaveBeenCalledWith(
        `/api/request-board/jobs/${JOB_ID}/proposals/${proposal.user_id}`,
        { decision: "accept" },
      ),
    );
    await waitFor(() =>
      expect(toast.showSuccess).toHaveBeenCalledWith(
        "Anna Przykładowa pracuje nad tą rekrutacją.",
      ),
    );
    expectTeamRefreshed(accepted.invalidatedKeys());
    accepted.unmount();

    renderPanel(JOBS.proposalOnly, { as: headOfRecruitment });
    await user.click(screen.getByRole("button", { name: "Odrzuć" }));
    await waitFor(() =>
      expect(apiMock.post).toHaveBeenLastCalledWith(
        `/api/request-board/jobs/${JOB_ID}/proposals/${proposal.user_id}`,
        { decision: "reject" },
      ),
    );
  });

  it("409 przy akceptacji = propozycja nieaktualna: zdanie serwera i odświeżenie", async () => {
    apiMock.post.mockRejectedValueOnce(
      conflict("Ta propozycja jest już nieaktualna — odśwież listę."),
    );
    const user = userEvent.setup();
    const { invalidatedKeys } = renderPanel(JOBS.proposalOnly, { as: headOfRecruitment });

    await user.click(screen.getByRole("button", { name: "Akceptuj" }));

    await waitFor(() =>
      expect(toast.showError).toHaveBeenCalledWith(
        "Ta propozycja jest już nieaktualna — odśwież listę.",
      ),
    );
    expect(toast.showSuccess).not.toHaveBeenCalled();
    expectTeamRefreshed(invalidatedKeys());
  });

  it("„Zmień” przy propozycji: lista bez proponowanej osoby i bez ról, których serwer nie przyjmie", async () => {
    const user = userEvent.setup();
    renderPanel(JOBS.proposalOnly, { as: headOfRecruitment });

    await user.click(
      screen.getByRole("button", { name: "Zmień propozycję: Anna Przykładowa" }),
    );
    const options = (await screen.findAllByRole("option")).map((option) => option.textContent);
    expect(options).toEqual([
      expect.stringContaining("Bartek Testowy"),
      expect.stringContaining("Celina Wzorcowa"),
      expect.stringContaining("Darek Makietowy"),
      expect.stringContaining("Tola Tacowa"),
    ]);

    await user.click(screen.getByRole("option", { name: /Darek Makietowy/ }));

    await waitFor(() =>
      expect(apiMock.post).toHaveBeenCalledWith(
        `/api/request-board/jobs/${JOB_ID}/proposals/${proposal.user_id}`,
        { decision: "replace", replacement_user_id: 34 },
      ),
    );
  });

  it("zdjęcie osoby pyta o potwierdzenie; rola przydzielająca zdejmuje przez pulpit", async () => {
    const user = userEvent.setup();
    const { invalidatedKeys } = renderPanel(JOBS.staffed, { as: headOfRecruitment });

    await user.click(screen.getByRole("button", { name: "Zdejmij Bartek Testowy" }));
    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByText("Zdjąć Bartek Testowy z tej rekrutacji?"),
    ).toBeInTheDocument();
    expect(apiMock.delete).not.toHaveBeenCalled();

    await user.click(within(dialog).getByRole("button", { name: "Zdejmij" }));

    await waitFor(() =>
      expect(apiMock.delete).toHaveBeenCalledWith(
        `/api/request-board/jobs/${JOB_ID}/people/${first.user_id}`,
      ),
    );
    await waitFor(() => expectTeamRefreshed(invalidatedKeys()));
  });

  it("anulowanie potwierdzenia niczego nie zdejmuje", async () => {
    const user = userEvent.setup();
    renderPanel(JOBS.staffed, { as: headOfRecruitment });

    await user.click(screen.getByRole("button", { name: "Zdejmij Celina Wzorcowa" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Anuluj" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(apiMock.delete).not.toHaveBeenCalled();
  });

  it("redagujący bez prawa przydziału zdejmuje dopisaną osobę trasą rekrutacji", async () => {
    const user = userEvent.setup();
    renderPanel(JOBS.staffed, { as: recruiter });

    await user.click(screen.getByRole("button", { name: "Zdejmij Celina Wzorcowa" }));
    await user.click(
      within(await screen.findByRole("dialog")).getByRole("button", { name: "Zdejmij" }),
    );

    await waitFor(() =>
      expect(apiMock.delete).toHaveBeenCalledWith(
        `/api/jobs/${JOB_ID}/collaborators/${second.user_id}`,
      ),
    );
  });

  it("odmowa przy zdejmowaniu (np. rekrutacja zamknięta) pokazuje zdanie serwera", async () => {
    apiMock.delete.mockRejectedValueOnce(
      conflict("Rekrutacja jest zamknięta — obsady nie da się już zmienić."),
    );
    const user = userEvent.setup();
    renderPanel(JOBS.staffed, { as: headOfRecruitment });

    await user.click(screen.getByRole("button", { name: "Zdejmij Celina Wzorcowa" }));
    await user.click(
      within(await screen.findByRole("dialog")).getByRole("button", { name: "Zdejmij" }),
    );

    await waitFor(() =>
      expect(toast.showError).toHaveBeenCalledWith(
        "Rekrutacja jest zamknięta — obsady nie da się już zmienić.",
      ),
    );
  });

  it("„+ Dodaj osobę”: bez osób już pracujących i bez ról, które rekruterem nie zostają", async () => {
    const user = userEvent.setup();
    renderPanel(JOBS.staffed, { as: headOfRecruitment });

    await user.click(screen.getByRole("button", { name: "+ Dodaj osobę" }));
    const options = (await screen.findAllByRole("option")).map((option) => option.textContent);
    expect(options).toEqual([
      expect.stringContaining("Anna Przykładowa"),
      expect.stringContaining("Darek Makietowy"),
      expect.stringContaining("Tola Tacowa"),
      expect.stringContaining("Gosia Delivery"),
    ]);

    await user.click(screen.getByRole("option", { name: /Anna Przykładowa/ }));

    // Pierwszy rekruter już pracuje, więc nowa osoba dochodzi jako kolejna.
    await waitFor(() =>
      expect(apiMock.post).toHaveBeenCalledWith(`/api/jobs/${JOB_ID}/collaborators`, {
        user_id: 31,
      }),
    );
    await waitFor(() =>
      expect(toast.showSuccess).toHaveBeenCalledWith("Anna Przykładowa: dodano do rekrutacji."),
    );
  });

  it("awaria listy osób to błąd z „Ponów”, nie „nikogo nie ma”", async () => {
    apiMock.get.mockRejectedValue({ response: { status: 500, data: {} } });
    const user = userEvent.setup();
    renderPanel(JOBS.staffed, { as: headOfRecruitment });

    await user.click(screen.getByRole("button", { name: "+ Dodaj osobę" }));

    expect(await screen.findByText("Nie udało się pobrać listy osób.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Ponów/ })).toBeInTheDocument();
    expect(
      screen.queryByText("Wszyscy już pracują nad tą rekrutacją."),
    ).not.toBeInTheDocument();
  });

  it("„Przypisz…” otwiera okno bez obecnego rekrutera, „Zmień” — z nim", async () => {
    const user = userEvent.setup();
    const empty = renderPanel(JOBS.empty, { as: headOfRecruitment });
    await user.click(screen.getByRole("button", { name: "Przypisz…" }));
    expect(screen.getByRole("dialog", { name: "Przypisz rekrutera" })).toBeInTheDocument();
    empty.unmount();

    // Sama propozycja to nie rekruter — okno też startuje bez osoby.
    const proposed = renderPanel(JOBS.proposalOnly, { as: headOfRecruitment });
    await user.click(screen.getByRole("button", { name: "Przypisz…" }));
    expect(screen.getByRole("dialog", { name: "Przypisz rekrutera" })).toBeInTheDocument();
    proposed.unmount();

    renderPanel(JOBS.staffed, { as: deliveryLead });
    await user.click(screen.getByRole("button", { name: "Zmień rekrutera" }));
    expect(
      screen.getByRole("dialog", { name: "Zmień rekrutera: Bartek Testowy" }),
    ).toBeInTheDocument();
  });
});
