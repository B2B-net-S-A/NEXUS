/**
 * Notatki osoby w panelu rekrutacji (12.10.2026): „W tej rekrutacji”
 * i „Wcześniej u nas”. Do tej daty panel pokazywał wyłącznie notatki z
 * `job_id` bieżącej rekrutacji — osoba z historią wyglądała jak nieznana.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ apiGet: vi.fn() }));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: (...a: unknown[]) => mocks.apiGet(...a), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  extractErrorMsg: () => "Błąd",
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn() }),
}));
vi.mock("@/hooks/useMentionableUsers", () => ({
  useMentionableUsers: () => ({ data: [] }),
}));
vi.mock("@/store/auth", () => ({
  useAuthStore: (sel: (s: { user: { id: number; role: string } }) => unknown) =>
    sel({ user: { id: 5, role: "recruiter" } }),
  hasRole: () => false,
}));

import { PersonNotesHistory } from "../PersonNotesHistory";

const JOB = 42;
const CANDIDATE = 6;

const HERE_NOTE = {
  id: 1,
  job_id: JOB,
  job_title: "Analityk biznesowo-systemowy",
  content: "Umówiony telefon na jutro.",
  author_id: 5,
  author_name: "Anna Kowalczyk",
  created_at: "2026-10-12T08:00:00Z",
  group: "talks",
  replies: [],
};

// Kolejność jak z API: od najnowszej. Dane fikcyjne.
const EARLIER_NOTES = [
  {
    id: 2,
    job_id: 7,
    job_title: "Analityk systemowy",
    content: "Feedback klienta: za mało projektów z integracjami.",
    author_name: "Piotr Wrona",
    created_at: "2025-04-02T09:40:00Z",
    group: "talks",
    replies: [],
  },
  {
    id: 4,
    job_id: 7,
    job_title: "Analityk systemowy",
    content: "Notatka Delivery Leada o stawce do klienta — niewidoczna dla Twojej roli.",
    content_hidden: true,
    kind: "dl_rate",
    author_name: "Tomasz Lis",
    created_at: "2025-03-28T08:15:00Z",
    group: "delivery",
    replies: [],
  },
  {
    id: 3,
    job_id: 7,
    job_title: "Analityk systemowy",
    content: "Nie odebrał, zostawiłam SMS.",
    author_name: "Anna Kowalczyk",
    created_at: "2025-03-12T09:05:00Z",
    group: "contact",
    replies: [],
  },
  {
    id: 7,
    job_id: 7,
    job_title: "Analityk systemowy",
    content: "Auto-match 70/100 — dodany automatycznie.",
    author_name: null,
    created_at: "2025-03-01T00:00:00Z",
    is_system: true,
    group: "automat",
    replies: [],
  },
  {
    id: 5,
    job_id: 9,
    job_title: "Business Analyst",
    content: "Prosi o kontakt od października 2025.",
    author_name: "Marta Sikora",
    created_at: "2024-09-18T12:30:00Z",
    group: "talks",
    replies: [],
  },
  {
    id: 6,
    job_id: null,
    content: "Nie dzwonić przed 10:00.",
    author_name: null,
    created_at: "2023-05-11T07:12:00Z",
    group: "talks",
    replies: [],
  },
];

const HISTORY = {
  jobs: [
    {
      job_id: 7,
      job_title: "Analityk systemowy",
      job_status: "published",
      client_name: "Bank Przykładowy",
      latest_stage: "rejected",
      rejection_reason: "Klient — za mało integracji",
      first_seen: "2025-03-01T09:00:00",
      last_seen: "2025-04-02T09:00:00",
      client_rate: { value: 180, unit: "h", currency: "PLN" },
      stages: [
        { stage: "rejected", stage_name: null, moved_at: "2025-04-02T09:00:00" },
        { stage: "client_interview", stage_name: null, moved_at: "2025-03-20T09:00:00" },
        { stage: "new", stage_name: null, moved_at: "2025-03-01T09:00:00" },
      ],
    },
    {
      job_id: 9,
      job_title: "Business Analyst",
      job_status: "closed",
      client_name: "Telekom Przykładowy",
      latest_stage: "withdrawn",
      first_seen: "2024-09-03T08:00:00",
      last_seen: "2024-09-18T12:30:00",
      stages: [{ stage: "withdrawn", stage_name: null, moved_at: "2024-09-18T12:30:00" }],
    },
  ],
};

function respond({ notes, history }: { notes: unknown; history?: unknown }) {
  mocks.apiGet.mockImplementation((url: string) => {
    const answer = url.startsWith("/api/notes") ? notes : url.includes("/history") ? history : { items: [] };
    return answer instanceof Error ? Promise.reject(answer) : Promise.resolve({ data: answer });
  });
}

function wrap(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
  return client;
}

const group = (name: string) => screen.getByRole("article", { name });

beforeEach(() => {
  mocks.apiGet.mockReset();
});

describe("PersonNotesHistory — zakładka „Notatki i historia”", () => {
  it("pyta o WSZYSTKIE notatki osoby i dzieli je na tę rekrutację i wcześniejsze", async () => {
    respond({ notes: { items: [HERE_NOTE, ...EARLIER_NOTES] }, history: HISTORY });
    wrap(<PersonNotesHistory candidateId={CANDIDATE} jobId={JOB} readOnly={false} />);

    const here = await screen.findByRole("region", { name: "Notatki w tej rekrutacji" });
    expect(within(here).getByText("Umówiony telefon na jutro.")).toBeInTheDocument();
    expect(within(here).getByText("1 notatka")).toBeInTheDocument();
    expect(mocks.apiGet).toHaveBeenCalledWith(`/api/notes?candidate_id=${CANDIDATE}`, expect.anything());
    expect(mocks.apiGet.mock.calls.some(([url]) => String(url).includes("job_id="))).toBe(false);

    const earlier = screen.getByRole("region", { name: "Wcześniej u nas" });
    // Notatki ludzi spoza tej rekrutacji; wpis automatu się nie liczy.
    expect(within(earlier).getByText("5 notatek · 2 rekrutacje · od 2023")).toBeInTheDocument();
    // Notatka z innej rekrutacji nie trafia do „W tej rekrutacji”.
    expect(within(here).queryByText(/Feedback klienta/)).toBeNull();

    // Grupy od najświeższej rozmowy; najnowsza otwarta, reszta zwinięta.
    const names = within(earlier)
      .getAllByRole("article")
      .map((el) => el.getAttribute("aria-label"))
      .filter((label) => label !== "Notatka");
    expect(names).toEqual([
      "Rekrutacja: Analityk systemowy",
      "Rekrutacja: Business Analyst",
      "Notatki bez rekrutacji",
    ]);
    expect(within(group("Rekrutacja: Analityk systemowy")).getByText(/Feedback klienta/)).toBeInTheDocument();
    expect(screen.queryByText("Prosi o kontakt od października 2025.")).toBeNull();
    fireEvent.click(within(group("Rekrutacja: Business Analyst")).getByRole("button", { expanded: false }));
    expect(screen.getByText("Prosi o kontakt od października 2025.")).toBeInTheDocument();
  });

  it("grupa mówi, dokąd osoba doszła i czym rekrutacja się skończyła", async () => {
    respond({ notes: { items: [HERE_NOTE, ...EARLIER_NOTES] }, history: HISTORY });
    const client = wrap(<PersonNotesHistory candidateId={CANDIDATE} jobId={JOB} readOnly={false} />);

    const rejected = await screen.findByRole("article", { name: "Rekrutacja: Analityk systemowy" });
    expect(await within(rejected).findByText("Odrzucony")).toBeInTheDocument();
    expect(
      within(rejected).getByText("Najdalej: Rozmowa u klienta · powód: Klient — za mało integracji · 3 notatki"),
    ).toBeInTheDocument();
    expect(within(rejected).getByText(/Bank Przykładowy/)).toBeInTheDocument();
    expect(within(rejected).getByText(/03–04\.2025/)).toBeInTheDocument();
    expect(within(group("Rekrutacja: Business Analyst")).getByText("Zrezygnował")).toBeInTheDocument();
    // „Bez rekrutacji” nie ma wyniku — nie ma czego oceniać.
    expect(within(group("Notatki bez rekrutacji")).queryByText(/Odrzucony|Zrezygnował|zamknięta/)).toBeNull();

    // W cache panelu zostają pola wyniku, nie stawki z odpowiedzi historii.
    const cached = client.getQueryCache().findAll({ queryKey: ["candidate-history", CANDIDATE] });
    expect(cached).toHaveLength(1);
    expect(JSON.stringify(cached[0].state.data)).not.toContain("client_rate");
  });

  it("domyślnie pokazuje rozmowy; „Wszystko” dokłada próby kontaktu, wpisy DL i automaty", async () => {
    respond({ notes: { items: [HERE_NOTE, ...EARLIER_NOTES] }, history: HISTORY });
    wrap(<PersonNotesHistory candidateId={CANDIDATE} jobId={JOB} readOnly={false} />);

    const rejected = await screen.findByRole("article", { name: "Rekrutacja: Analityk systemowy" });
    expect(screen.getByRole("button", { name: "Rozmowy 3" })).toHaveAttribute("aria-pressed", "true");
    expect(within(rejected).queryByText("Nie odebrał, zostawiłam SMS.")).toBeNull();
    expect(within(rejected).queryByText(/Auto-match/)).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Wszystko 6" }));
    expect(within(rejected).getByText("Nie odebrał, zostawiłam SMS.")).toBeInTheDocument();
    expect(within(rejected).getByText(/Auto-match 70\/100/)).toBeInTheDocument();
    // Wpis o stawce do klienta przychodzi z serwera już zakryty — pokazujemy go jak jest.
    expect(within(rejected).getByText(/niewidoczna dla Twojej roli/)).toBeInTheDocument();
    // Jeden filtr sekcji, bez osobnego „Pokaż systemowe” w każdej grupie.
    expect(screen.queryByLabelText(/Pokaż systemowe/)).toBeNull();
  });

  it("grupa bez rozmów podpowiada „Pokaż wszystko” zamiast udawać pustą", async () => {
    const onlyAttempts = EARLIER_NOTES.filter((n) => n.id === 3 || n.id === 5);
    respond({ notes: { items: onlyAttempts }, history: HISTORY });
    wrap(<PersonNotesHistory candidateId={CANDIDATE} jobId={JOB} readOnly={false} />);

    const rejected = await screen.findByRole("article", { name: "Rekrutacja: Analityk systemowy" });
    // Grupa z samą próbą kontaktu nie otwiera się sama — rozwija ją rekruter.
    fireEvent.click(within(rejected).getByRole("button", { expanded: false }));
    expect(within(rejected).getByText(/Brak notatek z rozmów\./)).toBeInTheDocument();
    fireEvent.click(within(rejected).getByRole("button", { name: "Pokaż wszystko (1)" }));
    expect(within(rejected).getByText("Nie odebrał, zostawiłam SMS.")).toBeInTheDocument();
  });

  it("domyślnie otwiera najświeższą grupę, która MA rozmowy — nie tę z samą próbą kontaktu", async () => {
    // Najnowszy wpis to próba kontaktu w rekrutacji 11; rozmowa jest w starszej 9.
    const attempt = {
      id: 30,
      job_id: 11,
      job_title: "Tester",
      content: "Nie odebrał.",
      author_name: "Anna Kowalczyk",
      created_at: "2026-01-10T10:00:00Z",
      group: "contact",
      replies: [],
    };
    respond({ notes: { items: [attempt, EARLIER_NOTES[4]] }, history: { jobs: [] } });
    wrap(<PersonNotesHistory candidateId={CANDIDATE} jobId={JOB} readOnly={false} />);

    const newest = await screen.findByRole("article", { name: "Rekrutacja: Tester" });
    expect(within(newest).getByRole("button")).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText(/Brak notatek z rozmów/)).toBeNull();
    expect(screen.getByText("Prosi o kontakt od października 2025.")).toBeInTheDocument();
  });

  it("bez wyników rekrutacji notatki zostają — grupa po prostu nie ma plakietki", async () => {
    respond({ notes: { items: EARLIER_NOTES }, history: new Error("500") });
    wrap(<PersonNotesHistory candidateId={CANDIDATE} jobId={JOB} readOnly={false} />);

    const rejected = await screen.findByRole("article", { name: "Rekrutacja: Analityk systemowy" });
    await waitFor(() =>
      expect(mocks.apiGet.mock.calls.some(([url]) => String(url).includes("/history"))).toBe(true),
    );
    expect(within(rejected).getByText(/Feedback klienta/)).toBeInTheDocument();
    expect(within(rejected).getByText("3 notatki")).toBeInTheDocument();
    expect(screen.queryByText("Odrzucony")).toBeNull();
    expect(screen.queryByText("Rekrutacja zamknięta")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("osoba bez żadnych notatek: dwa krótkie zdania zamiast pustej zakładki", async () => {
    respond({ notes: { items: [] }, history: { jobs: [] } });
    wrap(<PersonNotesHistory candidateId={CANDIDATE} jobId={JOB} readOnly={false} />);

    expect(
      await screen.findByText("Jeszcze nic nie zapisano. Pierwsza notatka z pola na dole trafi tutaj."),
    ).toBeInTheDocument();
    expect(screen.getByText("Nie ma wcześniejszych notatek o tej osobie.")).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Które notatki pokazać" })).toBeNull();
  });

  it("awaria notatek to jeden komunikat z „Ponów”, nie pusty stan", async () => {
    respond({ notes: new Error("500"), history: HISTORY });
    wrap(<PersonNotesHistory candidateId={CANDIDATE} jobId={JOB} readOnly={false} />);

    expect(await screen.findByText(/Nie udało się wczytać: notatki/)).toBeInTheDocument();
    expect(screen.queryByText(/Jeszcze nic nie zapisano/)).toBeNull();
    expect(screen.queryByText(/Nie ma wcześniejszych notatek/)).toBeNull();
    const calls = mocks.apiGet.mock.calls.filter(([url]) => String(url).startsWith("/api/notes")).length;
    fireEvent.click(screen.getByRole("button", { name: "Ponów" }));
    await waitFor(() =>
      expect(mocks.apiGet.mock.calls.filter(([url]) => String(url).startsWith("/api/notes")).length).toBe(calls + 1),
    );
  });
});

describe("PersonNotesHistory — sekcja „Notatki” wąskiego doku", () => {
  it("pusta rekrutacja nie wygląda jak osoba bez historii: skrót rozmów i „Cała historia”", async () => {
    const onOpenHistory = vi.fn();
    respond({ notes: { items: EARLIER_NOTES }, history: HISTORY });
    wrap(
      <PersonNotesHistory
        variant="dock"
        candidateId={CANDIDATE}
        jobId={JOB}
        readOnly={false}
        onOpenHistory={onOpenHistory}
      />,
    );

    expect(await screen.findByText("W tej rekrutacji jeszcze nic nie zapisano.")).toBeInTheDocument();
    const earlier = screen.getByRole("region", { name: "Wcześniej u nas" });
    // Dwie najświeższe ROZMOWY, każda z plakietką swojej rekrutacji; bez filtra rekrutacji.
    expect(within(earlier).getByText(/Feedback klienta/)).toBeInTheDocument();
    expect(within(earlier).getByText("Prosi o kontakt od października 2025.")).toBeInTheDocument();
    expect(within(earlier).getByText("Analityk systemowy")).toBeInTheDocument();
    expect(within(earlier).getByText("Business Analyst")).toBeInTheDocument();
    expect(within(earlier).queryByText("Nie odebrał, zostawiłam SMS.")).toBeNull();
    expect(within(earlier).queryByText("Nie dzwonić przed 10:00.")).toBeNull();
    expect(screen.queryByLabelText("Pokaż notatki z rekrutacji")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Cała historia (5)" }));
    expect(onOpenHistory).toHaveBeenCalledTimes(1);
    // Dok nie pyta o historię rekrutacji — wynik pokazuje dopiero zakładka.
    expect(mocks.apiGet.mock.calls.some(([url]) => String(url).includes("/history"))).toBe(false);
  });

  it("bez historii poza rekrutacją dok zachowuje się jak dotąd", async () => {
    respond({ notes: { items: [HERE_NOTE] } });
    wrap(<PersonNotesHistory variant="dock" candidateId={CANDIDATE} jobId={JOB} readOnly={false} />);

    expect(await screen.findByText("Umówiony telefon na jutro.")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Wcześniej u nas" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Cała historia/ })).toBeNull();
  });
});
