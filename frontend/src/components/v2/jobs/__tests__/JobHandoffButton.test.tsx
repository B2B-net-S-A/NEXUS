import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { JobHandoffButton } from "@/components/v2/jobs/JobHandoffButton";
import { REQUEST_BOARD_QUERY_KEY } from "@/lib/api/requestAllocation";
import type { PriorityLevel } from "@/lib/request-priority";

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  handoff: vi.fn(),
}));

vi.mock("@/lib/api", () => {
  const api = {
    get: (...args: unknown[]) => mocks.apiGet(...args),
    post: (...args: unknown[]) => mocks.apiPost(...args),
  };
  return {
    api,
    default: api,
    jobsApi: { handoff: (...args: unknown[]) => mocks.handoff(...args) },
  };
});

const READY = {
  job_id: 7,
  ready: true,
  blockers: [],
  closed: false,
  already_handed_off: false,
};

const RECRUITERS = [
  { id: 5, name: "Rec One", email: "r@example.com" },
  { id: 6, name: "Rec Two", email: "r2@example.com" },
];

/** Gotowość z automatem przydziału w podanym trybie; lista rekruterów stała. */
function mockApi(readiness: Record<string, unknown> = {}) {
  mocks.apiGet.mockImplementation((url: unknown) =>
    typeof url === "string" && url.includes("/readiness")
      ? Promise.resolve({ data: { ...READY, ...readiness } })
      : Promise.resolve({ data: RECRUITERS }),
  );
}

const AUTOMAT_SHADOW = { allocation_enabled: true, allocation_mode: "shadow" };
const AUTOMAT_AUTO = { allocation_enabled: true, allocation_mode: "auto" };
const AUTOMAT_OFF = { allocation_enabled: true, allocation_mode: "off" };

function renderButton(
  props: {
    priorityLevel?: PriorityLevel;
    recruiter?: { id: number; name?: string | null } | null;
  } = {},
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");
  render(
    <QueryClientProvider client={queryClient}>
      <JobHandoffButton jobId={7} {...props} />
    </QueryClientProvider>,
  );
  return {
    invalidatedKeys: () =>
      invalidateSpy.mock.calls.map(
        (call) => (call[0] as { queryKey: unknown[] })?.queryKey,
      ),
  };
}

async function openForm() {
  await waitFor(() => expect(screen.getByTestId("handoff-open")).toBeEnabled());
  fireEvent.click(screen.getByTestId("handoff-open"));
  return screen.findByRole("radiogroup", { name: "Rekruter" });
}

const option = (group: HTMLElement, name: string) =>
  within(group).getByRole("radio", { name });

beforeEach(() => {
  vi.clearAllMocks();
  // Komponent wykonuje DWA różne zapytania GET: listę rekruterów i gotowość
  // rekrutacji (0270). Jeden wspólny `mockResolvedValue` podawał listę
  // rekruterów także jako odpowiedź gotowości, więc `blockers` było
  // `undefined` — komponent jest na to odporny, ale test przestawał opisywać
  // cokolwiek prawdziwego.
  mockApi();
  mocks.handoff.mockResolvedValue({ data: { status: "handed_off" } });
  mocks.apiPost.mockResolvedValue({ data: { status: "queued" } });
});

describe("JobHandoffButton", () => {
  it("assigns the chosen recruiter and starts the search", async () => {
    const { invalidatedKeys } = renderButton();
    await openForm();
    await screen.findByText("Rec One");
    fireEvent.change(screen.getByTestId("handoff-recruiter-select"), {
      target: { value: "5" },
    });
    fireEvent.click(screen.getByTestId("handoff-submit"));

    await waitFor(() => expect(mocks.handoff).toHaveBeenCalledWith(7, 5, undefined, "linkedin"));
    expect(await screen.findByTestId("handoff-done")).toHaveTextContent(
      "Rekruter dostał dostęp do rekrutacji.",
    );
    // Przekazanie zmienia obsadę i bramkę — oba odczyty idą od nowa.
    const keys = invalidatedKeys();
    for (const key of [["job", "7"], ["jobs-v2"], REQUEST_BOARD_QUERY_KEY, ["job-readiness", 7]]) {
      expect(keys).toContainEqual(key);
    }
  });

  it("shows readiness blockers on a 422 instead of starting the search", async () => {
    mocks.handoff.mockRejectedValue({
      response: {
        status: 422,
        data: {
          detail: {
            message: "Rekrutacja nie jest gotowa.",
            blockers: ["Dodaj co najmniej 2 pytania screeningowe w Profilu Championa."],
          },
        },
      },
    });

    renderButton();
    await openForm();
    await screen.findByText("Rec One");
    fireEvent.change(screen.getByTestId("handoff-recruiter-select"), {
      target: { value: "5" },
    });
    fireEvent.click(screen.getByTestId("handoff-submit"));

    expect(await screen.findByTestId("handoff-blockers")).toHaveTextContent(
      "pytania screeningowe",
    );
    expect(screen.queryByTestId("handoff-done")).not.toBeInTheDocument();
  });

  it("pokazuje braki gotowości bez klikania i blokuje przycisk", async () => {
    // Sedno zmiany 0270: na próbce 100 rekrutacji z produkcji bramkę
    // przechodzą 23, więc trzy na cztery kliknięcia kończyły się 422 z listą,
    // którą dało się pokazać od razu.
    mocks.apiGet.mockImplementation((url: unknown) =>
      typeof url === "string" && url.includes("/readiness")
        ? Promise.resolve({
            data: {
              job_id: 1,
              ready: false,
              blockers: ["Dodaj co najmniej 2 pytania screeningowe."],
              closed: false,
              already_handed_off: false,
            },
          })
        : Promise.resolve({ data: [] }),
    );

    renderButton();

    await screen.findByTestId("handoff-readiness-blockers");
    expect(
      screen.getByText("Dodaj co najmniej 2 pytania screeningowe."),
    ).toBeInTheDocument();
    expect(screen.getByTestId("handoff-open")).toBeDisabled();
  });

  it("odmowa odczytu gotowości (403) blokuje przycisk i mówi, kto może przekazać", async () => {
    mocks.apiGet.mockImplementation((url: unknown) =>
      typeof url === "string" && url.includes("/readiness")
        ? Promise.reject({ response: { status: 403, data: { detail: "Requires one of roles: ['admin', 'delivery_lead']" } } })
        : Promise.resolve({ data: [] }),
    );

    renderButton();

    expect(await screen.findByTestId("handoff-readiness-error")).toHaveTextContent(
      "Przekazać do searchu może admin albo Delivery Lead tej rekrutacji.",
    );
    expect(screen.getByTestId("handoff-open")).toBeDisabled();
    expect(screen.queryByTestId("handoff-readiness-blockers")).not.toBeInTheDocument();
  });

  it("awaria odczytu gotowości to nie „brak braków” — przycisk zablokowany, jest „Ponów”", async () => {
    mocks.apiGet.mockImplementation((url: unknown) =>
      typeof url === "string" && url.includes("/readiness")
        ? Promise.reject({ response: { status: 503 } })
        : Promise.resolve({ data: [] }),
    );

    renderButton();

    expect(await screen.findByTestId("handoff-readiness-error")).toHaveTextContent(
      "Nie udało się sprawdzić, czy rekrutacja jest gotowa.",
    );
    expect(screen.getByTestId("handoff-open")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Ponów" })).toBeInTheDocument();
  });

  it("dopóki gotowość się wczytuje, przycisk jest zablokowany", () => {
    mocks.apiGet.mockImplementation(() => new Promise(() => {}));
    renderButton();
    expect(screen.getByTestId("handoff-open")).toBeDisabled();
  });
});

describe("JobHandoffButton — „Rekruter”: automat albo konkretna osoba (02.10.2026)", () => {
  it("przy włączonym automacie domyślnie „Zaproponuje automat” — bez żadnego kliknięcia", async () => {
    mockApi(AUTOMAT_SHADOW);
    renderButton();
    const group = await openForm();

    expect(
      within(group)
        .getAllByRole("radio")
        .map((radio) => radio.textContent),
    ).toEqual(["Zaproponuje automat", "Wybieram sam"]);
    expect(option(group, "Zaproponuje automat")).toBeChecked();
    expect(option(group, "Zaproponuje automat")).toBeEnabled();
    expect(
      screen.getByText(
        "Automat zaproponuje osobę według kategorii i obłożenia. Propozycję zatwierdza Head of Recruitment — do tego czasu nikt nie jest przypisany.",
      ),
    ).toBeInTheDocument();
    // Listy osób nie ma, dopóki nikt nie wybierze „Wybieram sam”.
    expect(screen.queryByTestId("handoff-recruiter-select")).not.toBeInTheDocument();
    expect(screen.getByTestId("handoff-submit")).toBeEnabled();
  });

  it("przekazanie automatowi wysyła `assignment_mode: automatic` i mówi, że rekrutacja czeka na akceptację", async () => {
    mockApi(AUTOMAT_SHADOW);
    const { invalidatedKeys } = renderButton();
    await openForm();

    fireEvent.click(screen.getByTestId("handoff-submit"));

    await waitFor(() =>
      expect(mocks.apiPost).toHaveBeenCalledWith("/api/jobs/7/handoff", {
        assignment_mode: "automatic",
        channel: "linkedin",
      }),
    );
    expect(mocks.handoff).not.toHaveBeenCalled();
    expect(await screen.findByTestId("handoff-done")).toHaveTextContent(
      "Przekazano do searchu. Rekrutera zaproponuje automat, a zatwierdzi Head of Recruitment. Do tego czasu rekrutacja jest bez rekrutera.",
    );
    expect(invalidatedKeys()).toContainEqual(["job", "7"]);
  });

  it("w trybie „auto” opcja nazywa się „Przydzieli automat” i mówi, że automat przydzieli osobę sam", async () => {
    mockApi(AUTOMAT_AUTO);
    renderButton();
    const group = await openForm();

    expect(
      within(group)
        .getAllByRole("radio")
        .map((radio) => radio.textContent),
    ).toEqual(["Przydzieli automat", "Wybieram sam"]);
    expect(option(group, "Przydzieli automat")).toBeChecked();
    expect(
      screen.getByText(
        "Automat przydzieli jedną osobę z kategorii — tę z najmniejszą liczbą requestów. Head rekrutacji zobaczy to na pulpicie i może zmienić.",
      ),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("handoff-submit"));

    const done = await screen.findByTestId("handoff-done");
    expect(done).toHaveTextContent(
      "Przekazano do searchu. Rekrutera prowadzącego przydzieli automat — zwykle w ciągu minuty.",
    );
    expect(done).not.toHaveTextContent("bez rekrutera");
  });

  it("„Wybieram sam” pokazuje listę osób i przypisuje wskazaną od razu", async () => {
    mockApi(AUTOMAT_SHADOW);
    renderButton();
    const group = await openForm();

    fireEvent.click(option(group, "Wybieram sam"));

    expect(option(group, "Wybieram sam")).toBeChecked();
    const select = await screen.findByRole("combobox", { name: "Wybierz rekrutera" });
    expect(screen.getByTestId("handoff-submit")).toBeDisabled();
    await screen.findByText("Rec Two");
    fireEvent.change(select, { target: { value: "6" } });
    fireEvent.click(screen.getByTestId("handoff-submit"));

    await waitFor(() =>
      expect(mocks.handoff).toHaveBeenCalledWith(7, 6, undefined, "linkedin"),
    );
    expect(mocks.apiPost).not.toHaveBeenCalled();
  });

  it.each([
    ["flaga wyłączona", { allocation_enabled: false, allocation_mode: "off" }],
    ["tryb „off”", AUTOMAT_OFF],
    ["starszy serwer bez pól automatu", {}],
  ])("automat niedostępny (%s): opcja nieaktywna z wyjaśnieniem, domyślnie wybór osoby", async (_name, readiness) => {
    mockApi(readiness);
    renderButton();
    const group = await openForm();

    const automat = option(group, "Zaproponuje automat");
    expect(automat).toBeDisabled();
    expect(automat).not.toBeChecked();
    expect(automat).toHaveAccessibleDescription(
      "Automatyczny przydział jest wyłączony — włącza go administrator.",
    );
    expect(option(group, "Wybieram sam")).toBeChecked();
    expect(screen.getByTestId("handoff-recruiter-select")).toBeInTheDocument();
    expect(screen.getByTestId("handoff-submit")).toBeDisabled();
  });

  it("priorytet „Przyjmujemy kandydatów”: nie obiecuje propozycji — automat takim requestom nikogo nie proponuje", async () => {
    mockApi(AUTOMAT_SHADOW);
    renderButton({ priorityLevel: "accepting" });
    await openForm();

    expect(
      screen.getByText(
        "Przy priorytecie „Przyjmujemy kandydatów” automat nikogo nie proponuje — rekrutacja zostanie bez rekrutera, dopóki ktoś jej nie weźmie albo nie wskażesz osoby.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/Propozycję zatwierdza Head of Recruitment/),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("handoff-submit"));

    expect(await screen.findByTestId("handoff-done")).toHaveTextContent(
      "Przekazano do searchu. Rekrutacja zostaje bez rekrutera — przy priorytecie „Przyjmujemy kandydatów” automat nikogo nie proponuje.",
    );
  });

  it("rekrutacja ma już rekrutera: automat jest nieaktywny (serwer odmówiłby 409), a ta osoba jest zaznaczona z góry", async () => {
    mockApi(AUTOMAT_SHADOW);
    renderButton({ recruiter: { id: 6, name: "Rec Two" } });
    const group = await openForm();

    const automat = option(group, "Zaproponuje automat");
    expect(automat).toBeDisabled();
    expect(automat).toHaveAccessibleDescription(
      "Do tej rekrutacji jest już przypisana osoba (Rec Two), więc automat nikogo nie zaproponuje. Wybierz rekrutera z listy.",
    );
    expect(option(group, "Wybieram sam")).toBeChecked();
    await screen.findByText("Rec Two");
    await waitFor(() =>
      expect(screen.getByTestId("handoff-recruiter-select")).toHaveValue("6"),
    );

    fireEvent.click(screen.getByTestId("handoff-submit"));

    await waitFor(() =>
      expect(mocks.handoff).toHaveBeenCalledWith(7, 6, undefined, "linkedin"),
    );
    expect(mocks.apiPost).not.toHaveBeenCalled();
  });

  it("obecny rekruter spoza listy (np. Delivery Lead) nie jest zaznaczany — trzeba wskazać osobę", async () => {
    mockApi(AUTOMAT_SHADOW);
    renderButton({ recruiter: { id: 99, name: "Gosia Delivery" } });
    await openForm();
    await screen.findByText("Rec One");

    expect(screen.getByTestId("handoff-recruiter-select")).toHaveValue("");
    expect(screen.getByTestId("handoff-submit")).toBeDisabled();
  });

  it("zaznaczoną z góry osobę da się odznaczyć — wybór użytkownika wygrywa z podpowiedzią", async () => {
    mockApi(AUTOMAT_SHADOW);
    renderButton({ recruiter: { id: 6, name: "Rec Two" } });
    await openForm();
    await waitFor(() =>
      expect(screen.getByTestId("handoff-recruiter-select")).toHaveValue("6"),
    );

    fireEvent.change(screen.getByTestId("handoff-recruiter-select"), {
      target: { value: "" },
    });

    expect(screen.getByTestId("handoff-recruiter-select")).toHaveValue("");
    expect(screen.getByTestId("handoff-submit")).toBeDisabled();
  });

  it("409 przy automacie (wyłączono go w międzyczasie) pokazuje zdanie serwera i odświeża gotowość", async () => {
    mockApi(AUTOMAT_SHADOW);
    mocks.apiPost.mockRejectedValue({
      response: {
        status: 409,
        data: { detail: "Automat przydziału jest wyłączony — wybierz rekrutera ręcznie." },
      },
    });
    const { invalidatedKeys } = renderButton();
    await openForm();

    fireEvent.click(screen.getByTestId("handoff-submit"));

    expect(await screen.findByTestId("handoff-error")).toHaveTextContent(
      "Automat przydziału jest wyłączony — wybierz rekrutera ręcznie.",
    );
    expect(screen.queryByTestId("handoff-done")).not.toBeInTheDocument();
    expect(invalidatedKeys()).toContainEqual(["job-readiness", 7]);
  });

  it("awaria listy rekruterów to błąd z „Ponów”, nie pusta lista", async () => {
    mocks.apiGet.mockImplementation((url: unknown) =>
      typeof url === "string" && url.includes("/readiness")
        ? Promise.resolve({ data: READY })
        : Promise.reject({ response: { status: 500 } }),
    );
    renderButton();
    await openForm();

    expect(await screen.findByText(/Nie udało się wczytać listy rekruterów\./)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ponów" })).toBeInTheDocument();
  });

  it("nie używa dawnych nazw", async () => {
    mockApi(AUTOMAT_SHADOW);
    renderButton();
    await openForm();

    for (const gone of [/Przydziel automatycznie/, /Rekruter prowadzący/, /Prowadzi/]) {
      expect(screen.queryByText(gone)).not.toBeInTheDocument();
    }
  });
});

describe("JobHandoffButton — stary szkic (04.10.2026)", () => {
  it("przy szkicu mówi „Przekaż i opublikuj”, poza nim „Przekaż do searchu”", async () => {
    mockApi();
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { unmount } = render(
      <QueryClientProvider client={queryClient}>
        <JobHandoffButton jobId={7} jobStatus="draft" />
      </QueryClientProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("handoff-open")).toBeEnabled());
    expect(screen.getByTestId("handoff-open")).toHaveTextContent("Przekaż i opublikuj");
    fireEvent.click(screen.getByTestId("handoff-open"));
    expect(await screen.findByTestId("handoff-submit")).toHaveTextContent("Przekaż i opublikuj");
    unmount();

    // Status z rekrutacji w cache'u, gdy dok go nie podaje.
    const cached = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    cached.setQueryData(["job", "7"], { status: "published" });
    render(
      <QueryClientProvider client={cached}>
        <JobHandoffButton jobId={7} />
      </QueryClientProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("handoff-open")).toBeEnabled());
    expect(screen.getByTestId("handoff-open")).toHaveTextContent("Przekaż do searchu");
  });
});

describe("JobHandoffButton — rekrutacja już przekazana (04.10.2026)", () => {
  it("nie pokazuje przycisku przekazania, tylko zdanie, że rekrutacja jest przekazana", async () => {
    // Panel „Gotowość” pokazywał „Zlecenie przekazane do searchu” i obok
    // aktywne „Przekaż do searchu” — ponowne kliknięcie przestawiało rekrutera.
    mockApi({ already_handed_off: true });
    renderButton();

    expect(await screen.findByTestId("handoff-already")).toHaveTextContent(
      "Przekazana do searchu",
    );
    expect(screen.queryByTestId("handoff-open")).not.toBeInTheDocument();
  });
});
