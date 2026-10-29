import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/components/Toast";
import { GenerateInviteLinkV2 } from "@/components/v2/modals/GenerateInviteLinkV2";
import api from "@/lib/api";
import { downloadAuthenticatedFile } from "@/lib/authenticated-files";
import { copyTextToClipboard } from "@/lib/clipboard";
import { useAuthStore } from "@/store/auth";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    default: {
      ...actual.default,
      get: vi.fn(),
      post: vi.fn(),
      put: vi.fn(),
      delete: vi.fn(),
    },
  };
});

vi.mock("@/lib/clipboard", () => ({ copyTextToClipboard: vi.fn() }));
vi.mock("@/lib/authenticated-files", () => ({ downloadAuthenticatedFile: vi.fn() }));

const JOB = { id: 101, title: "Senior Java Developer", status: "published" };

function profile(overrides: Record<string, unknown> = {}) {
  return {
    job_id: 101,
    status: "draft",
    subtitle: "rozwój platformy płatności",
    about: "Zespół przebudowuje platformę płatności. Budżet do 180 zł/h.",
    sections: { must: true, nice: true, params: true, process: true },
    show_on_recruiter_page: true,
    approved_at: null,
    approved_by_name: null,
    approved_content_stale: false,
    findings: [],
    preview: null,
    ...overrides,
  };
}

const LIVE = {
  title: "Senior Java Developer",
  subtitle: "rozwój platformy płatności",
  about: "Zespół przebudowuje platformę płatności.",
  sections: { must: true, nice: true, params: true, process: true },
  pending_changes: false,
};

const CREATED_LINK = {
  token: "t1",
  url: "https://kariera.dynaminds.pl/r/senior-java-7kq2",
  public_url: "https://kariera.dynaminds.pl/r/senior-java-7kq2",
  kind: "job",
  slug: "senior-java-7kq2",
  job: { id: 101, title: JOB.title },
  label: null,
  expires_at: null,
  revoked: false,
  use_count: 0,
  last_used_at: null,
  created_at: "2026-09-21T10:00:00Z",
  status: "active",
};

type Routes = Record<string, unknown | (() => unknown)>;

function routeGet(routes: Routes) {
  vi.mocked(api.get).mockImplementation(async (url: string) => {
    const hit = routes[url];
    if (hit === undefined) throw new Error(`unexpected GET ${url}`);
    const value = typeof hit === "function" ? (hit as () => unknown)() : hit;
    if (value instanceof Error) throw value;
    return { data: value };
  });
}

function renderDialog(props: Partial<React.ComponentProps<typeof GenerateInviteLinkV2>> = {}) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <GenerateInviteLinkV2 open onOpenChange={vi.fn()} defaultJobId={101} {...props} />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

const baseRoutes: Routes = {
  "/api/jobs": { items: [JOB] },
  "/api/invite-links": [],
  "/api/jobs/101/public-profile": profile(),
};

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("GenerateInviteLinkV2 — Udostępnij rekrutację", () => {
  it("renderuje obie zakładki", async () => {
    routeGet(baseRoutes);
    renderDialog();
    expect(screen.getByRole("tab", { name: "Link do tej rekrutacji" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Mój link ogólny" })).toBeInTheDocument();
    expect(await screen.findByLabelText("O projekcie")).toHaveValue(
      "Zespół przebudowuje platformę płatności. Budżet do 180 zł/h.",
    );
  });

  it("zatwierdzenie odrzucone znaleziskami pokazuje je i zostawia tekst", async () => {
    const user = userEvent.setup();
    routeGet(baseRoutes);
    vi.mocked(api.post).mockImplementation(async (url: string) => {
      if (url === "/api/jobs/101/public-profile/approve") {
        throw {
          response: {
            status: 422,
            data: {
              detail: {
                code: "PUBLIC_PROFILE_FINDINGS",
                message: "Opis zawiera niedozwolone fragmenty.",
                findings: [
                  {
                    code: "money",
                    message: "Wykryto kwotę: „Budżet do 180 zł/h” — stawek nie publikujemy.",
                    excerpt: "Budżet do 180 zł/h",
                  },
                ],
              },
            },
          },
        };
      }
      throw new Error(`unexpected POST ${url}`);
    });
    renderDialog();

    await screen.findByLabelText("O projekcie");
    await user.click(screen.getByRole("button", { name: "Zatwierdź i skopiuj link" }));

    expect(await screen.findByText(/stawek nie publikujemy/)).toBeInTheDocument();
    expect(screen.getByLabelText("O projekcie")).toHaveValue(
      "Zespół przebudowuje platformę płatności. Budżet do 180 zł/h.",
    );
    expect(screen.getByTestId("approve-disabled-reason")).toHaveTextContent(
      "Usuń kwotę z opisu, aby zatwierdzić.",
    );
    expect(screen.getByRole("button", { name: "Zatwierdź i skopiuj link" })).toBeDisabled();
    // Nic nie poszło do schowka i żaden link nie powstał.
    expect(copyTextToClipboard).not.toHaveBeenCalled();
    expect(api.post).not.toHaveBeenCalledWith("/api/invite-links", expect.anything());

    // „Usuń fragment" zdejmuje kwotę i odblokowuje zatwierdzenie.
    await user.click(screen.getByRole("button", { name: "Usuń fragment" }));
    expect(screen.getByLabelText("O projekcie")).toHaveValue(
      "Zespół przebudowuje platformę płatności.",
    );
    expect(screen.getByRole("button", { name: "Zatwierdź i skopiuj link" })).toBeEnabled();
  });

  it("szkic AI wypełnia pola i niczego nie zapisuje", async () => {
    const user = userEvent.setup();
    routeGet(baseRoutes);
    vi.mocked(api.post).mockResolvedValue({
      data: { subtitle: "nowy podtytuł", about: "Nowy opis projektu." },
    });
    renderDialog();

    await screen.findByLabelText("O projekcie");
    await user.click(screen.getByRole("button", { name: "Szkic AI z profilu Championa" }));

    await waitFor(() =>
      expect(screen.getByLabelText("O projekcie")).toHaveValue("Nowy opis projektu."),
    );
    expect(screen.getByLabelText(/Podtytuł/)).toHaveValue("nowy podtytuł");
    expect(api.post).toHaveBeenCalledWith("/api/jobs/101/public-profile/draft");
    expect(api.put).not.toHaveBeenCalled();
    expect(screen.getByText(/niezapisane zmiany/)).toBeInTheDocument();
  });

  it("utworzenie linku kopiuje go, a toast pojawia się tylko przy udanym kopiowaniu", async () => {
    const user = userEvent.setup();
    routeGet({
      ...baseRoutes,
      "/api/jobs/101/public-profile": profile({
        status: "approved",
        live: LIVE,
      }),
    });
    const created = {
      token: "t1",
      url: "https://kariera.dynaminds.pl/r/senior-java-7kq2",
      public_url: "https://kariera.dynaminds.pl/r/senior-java-7kq2",
      kind: "job",
      slug: "senior-java-7kq2",
      job: { id: 101, title: JOB.title },
      label: null,
      expires_at: null,
      revoked: false,
      use_count: 0,
      last_used_at: null,
      created_at: "2026-09-21T10:00:00Z",
      status: "active",
    };
    vi.mocked(api.post).mockResolvedValue({ data: created });
    vi.mocked(copyTextToClipboard).mockResolvedValueOnce(false);
    renderDialog();

    await user.click(await screen.findByRole("button", { name: "Wygeneruj link" }));

    expect(api.post).toHaveBeenCalledWith("/api/invite-links", {
      job_id: 101,
      label: undefined,
      expires_in_days: null,
    });
    expect(await screen.findByTestId("job-link-url")).toHaveTextContent(created.public_url);
    expect(copyTextToClipboard).toHaveBeenCalledWith(created.public_url);
    expect(await screen.findByText(/Nie udało się skopiować/)).toBeInTheDocument();
    expect(screen.queryByText("Skopiowano link.")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Otwórz stronę/ })).toHaveAttribute(
      "href",
      created.public_url,
    );

    vi.mocked(copyTextToClipboard).mockResolvedValueOnce(true);
    await user.click(screen.getByRole("button", { name: "Kopiuj" }));
    expect(await screen.findByText("Skopiowano link.")).toBeInTheDocument();
  });

  it("przed zatwierdzeniem opisu link powstaje, ale nie da się go skopiować ani otworzyć", async () => {
    const user = userEvent.setup();
    routeGet(baseRoutes);
    vi.mocked(api.post).mockResolvedValue({ data: CREATED_LINK });
    renderDialog();

    expect(await screen.findByTestId("career-page-state")).toHaveTextContent(
      "Strona jeszcze nie działa",
    );
    await user.click(await screen.findByRole("button", { name: "Wygeneruj link" }));

    expect(await screen.findByTestId("job-link-url")).toHaveTextContent(CREATED_LINK.public_url);
    expect(copyTextToClipboard).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Kopiuj" })).toBeDisabled();
    expect(screen.queryByRole("link", { name: /Otwórz stronę/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Plakat z QR" })).not.toBeInTheDocument();
    expect(screen.getByTestId("link-not-live")).toHaveTextContent(
      "Link zadziała po zatwierdzeniu opisu",
    );
  });

  it("zatwierdzony i niezmieniony opis: przycisk tylko kopiuje link, bez ponownego zatwierdzenia", async () => {
    const user = userEvent.setup();
    routeGet({
      ...baseRoutes,
      "/api/invite-links": [CREATED_LINK],
      "/api/jobs/101/public-profile": profile({
        status: "approved",
        about: "Zespół przebudowuje platformę płatności.",
        live: LIVE,
      }),
    });
    vi.mocked(copyTextToClipboard).mockResolvedValue(true);
    renderDialog();

    await user.click(await screen.findByRole("button", { name: "Skopiuj link" }));
    await waitFor(() => expect(copyTextToClipboard).toHaveBeenCalledWith(CREATED_LINK.public_url));
    expect(api.post).not.toHaveBeenCalled();
    expect(screen.getByTestId("career-page-state")).toHaveTextContent("Strona działa");

    // Plakat z QR — ten sam link, PDF z opublikowanej wersji opisu.
    await user.click(screen.getByRole("button", { name: "Plakat z QR" }));
    await waitFor(() =>
      expect(downloadAuthenticatedFile).toHaveBeenCalledWith(
        "/api/jobs/101/public-profile/poster.pdf",
        "plakat-senior-java-7kq2.pdf",
      ),
    );
  });

  it("zmiany po zatwierdzeniu: strona działa na starej wersji, „Odrzuć zmiany” ją przywraca", async () => {
    const user = userEvent.setup();
    routeGet({
      ...baseRoutes,
      "/api/invite-links": [CREATED_LINK],
      "/api/jobs/101/public-profile": profile({
        status: "draft",
        about: "Poprawiony opis.",
        approved_at: "2026-10-18T12:20:00Z",
        default_title: "Senior Java Developer",
        effective_title: "Senior Java Developer",
        live: { ...LIVE, pending_changes: true },
      }),
    });
    vi.mocked(api.put).mockResolvedValue({
      data: profile({ status: "approved", about: LIVE.about, live: LIVE }),
    });
    renderDialog();

    const state = await screen.findByTestId("career-page-state");
    expect(state).toHaveTextContent("Strona działa · są zmiany");
    expect(state).toHaveTextContent("Zmiany czekają na zatwierdzenie");
    // Link działa — kopiowanie i „Otwórz stronę” dostępne mimo szkicu.
    expect(screen.getByRole("button", { name: "Kopiuj" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Zatwierdź zmiany" })).toBeInTheDocument();

    await user.click(within(state).getByRole("button", { name: "Odrzuć zmiany" }));
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith(
        "/api/jobs/101/public-profile",
        expect.objectContaining({
          public_title: null,
          subtitle: LIVE.subtitle,
          about: LIVE.about,
          sections: LIVE.sections,
        }),
      ),
    );
  });

  it("kontrola nie świeci na zielono, gdy opis jest pusty albo niezapisany", async () => {
    const user = userEvent.setup();
    routeGet({
      ...baseRoutes,
      "/api/jobs/101/public-profile": profile({ status: "none", subtitle: null, about: null }),
    });
    renderDialog();
    await screen.findByLabelText("O projekcie");
    const list = screen.getByTestId("public-profile-findings");
    expect(within(list).getAllByTestId("finding-unchecked")).toHaveLength(4);
    expect(list).toHaveTextContent("sprawdzę po zapisaniu");
    await user.type(screen.getByLabelText("O projekcie"), "Zespół płatności.");
    expect(within(list).getAllByTestId("finding-unchecked")).toHaveLength(4);
  });

  it("znalezisko spoza pól okna (np. z wymagań) nie znika z listy kontroli", async () => {
    routeGet({
      ...baseRoutes,
      "/api/jobs/101/public-profile": profile({
        about: "Zespół przebudowuje platformę płatności.",
        findings: [
          {
            code: "client_name",
            message: "Wykryto nazwę klienta: „Znajomość systemów Nordea”.",
            excerpt: "Znajomość systemów Nordea",
          },
        ],
      }),
    });
    renderDialog();
    expect(await screen.findByText(/Wykryto nazwę klienta/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Zatwierdź i skopiuj link" })).toBeDisabled();
  });

  it("„Tytuł na stronie”: placeholder = tytuł domyślny, wpis idzie w PUT i do podglądu posta", async () => {
    const user = userEvent.setup();
    routeGet({
      ...baseRoutes,
      "/api/jobs": { items: [{ ...JOB, title: "Nordea: Senior Java Developer (ZOB-3003)" }] },
      "/api/jobs/101/public-profile": profile({
        public_title: null,
        default_title: "Senior Java Developer",
        effective_title: "Senior Java Developer",
      }),
      "/api/me/career-link": {
        link: null,
        stats: null,
        suggested_slug: "marta-n",
        jobs: [],
        base_url: "https://nexus.dynaminds.pl",
        recruiter_base_url: "https://nexus.dynaminds.pl/kariera/p/",
      },
    });
    vi.mocked(api.put).mockImplementation(async (_url: string, body: unknown) => ({
      data: profile({
        ...(body as Record<string, unknown>),
        default_title: "Senior Java Developer",
        effective_title: (body as { public_title: string | null }).public_title ?? "Senior Java Developer",
      }),
    }));
    renderDialog();

    const title = await screen.findByLabelText("Tytuł na stronie");
    expect(title).toHaveValue("");
    expect(title).toHaveAttribute("placeholder", "Senior Java Developer");
    const preview = screen.getByTestId("linkedin-preview");
    // Podgląd bierze tytuł domyślny, nie surowy tytuł z nazwą klienta.
    // Podgląd = prawdziwy post: LinkedIn bierze `og:title` bez dopisku marki.
    expect(preview).toHaveTextContent("Senior Java Developer");
    expect(preview).not.toHaveTextContent("Dynaminds");
    expect(preview).not.toHaveTextContent("Nordea");
    await waitFor(() => expect(preview).toHaveTextContent("nexus.dynaminds.pl"));

    await user.type(title, "Java Developer w bankowości");
    expect(screen.getByText(/niezapisane zmiany/)).toBeInTheDocument();
    expect(preview).toHaveTextContent("Java Developer w bankowości");

    await user.click(screen.getByRole("button", { name: "Zapisz szkic" }));
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith(
        "/api/jobs/101/public-profile",
        expect.objectContaining({ public_title: "Java Developer w bankowości" }),
      ),
    );

    // Wyczyszczenie pola = tytuł domyślny (null), nie pusty napis.
    await user.clear(screen.getByLabelText("Tytuł na stronie"));
    await user.click(screen.getByRole("button", { name: "Zapisz szkic" }));
    await waitFor(() =>
      expect(api.put).toHaveBeenLastCalledWith(
        "/api/jobs/101/public-profile",
        expect.objectContaining({ public_title: null }),
      ),
    );
  });

  it("znalezisko w tytule na stronie znika po usunięciu fragmentu z tytułu", async () => {
    const user = userEvent.setup();
    routeGet({
      ...baseRoutes,
      "/api/jobs/101/public-profile": profile({
        public_title: "Nordea — Java Developer",
        about: "Zespół przebudowuje platformę płatności.",
        findings: [
          { code: "client_name", message: "Wykryto nazwę klienta: „Nordea”.", excerpt: "Nordea" },
        ],
      }),
    });
    renderDialog();
    expect(await screen.findByText(/Wykryto nazwę klienta/)).toBeInTheDocument();
    await user.clear(screen.getByLabelText("Tytuł na stronie"));
    await user.type(screen.getByLabelText("Tytuł na stronie"), "Java Developer");
    expect(screen.queryByText(/Wykryto nazwę klienta/)).not.toBeInTheDocument();
  });

  it("awaria wczytania opisu nie wygląda jak pusty opis", async () => {
    routeGet({
      ...baseRoutes,
      "/api/jobs/101/public-profile": () =>
        Object.assign(new Error("boom"), { response: { status: 500, data: {} } }),
    });
    renderDialog();
    expect(await screen.findByText(/Nie udało się wczytać opisu publicznego/)).toBeInTheDocument();
    expect(screen.queryByLabelText("O projekcie")).not.toBeInTheDocument();
  });
});

describe("GenerateInviteLinkV2 — Mój link ogólny", () => {
  const careerLink = {
    link: {
      slug: "marta-n",
      public_url: "https://kariera.dynaminds.pl/marta-n",
      created_at: "2026-09-01T10:00:00Z",
      visit_count: null,
    },
    stats: { days: 30, applications: 3, new_candidates: null },
    suggested_slug: "marta-n",
    jobs: [
      {
        job_id: 101,
        title: JOB.title,
        profile_status: "approved",
        show_on_recruiter_page: true,
        has_link: true,
      },
      {
        job_id: 102,
        title: "Analityk biznesowy",
        profile_status: "none",
        show_on_recruiter_page: false,
        has_link: true,
      },
    ],
  };

  async function openGeneral(routes: Routes) {
    const user = userEvent.setup();
    routeGet({ ...baseRoutes, ...routes });
    renderDialog();
    await user.click(screen.getByRole("tab", { name: "Mój link ogólny" }));
    return user;
  }

  it("statystyki bez danych pokazują kreskę, a nie zero; widoczność zablokowana bez zatwierdzenia", async () => {
    await openGeneral({ "/api/me/career-link": careerLink });
    expect(await screen.findByText("To Twój obecny adres · działa bez terminu, do odwołania")).toBeInTheDocument();
    const entries = screen.getByText("Wejścia od początku").parentElement as HTMLElement;
    expect(within(entries).getByText("—")).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: `Pokaż na stronie: ${JOB.title}` })).toBeEnabled();
    expect(screen.getByRole("switch", { name: "Pokaż na stronie: Analityk biznesowy" })).toBeDisabled();
    expect(screen.getByText("Najpierw zatwierdź opis publiczny tej rekrutacji.")).toBeInTheDocument();
  });

  it("podgląd posta mówi tym samym językiem co strona: login @b2bnetwork i `og:title` bez marki", async () => {
    useAuthStore.setState({ user: { name: "Łucja Nowak" } } as never);
    try {
      await openGeneral({ "/api/me/career-link": careerLink });
      const preview = await screen.findByTestId("linkedin-preview");
      expect(preview).toHaveTextContent("Łucja · rekrutacje IT w B2B Network");
      expect(preview).toHaveTextContent("Łucja — rekrutacje IT");
      expect(preview).not.toHaveTextContent(/dynaminds\b(?!\.pl)/i);
    } finally {
      useAuthStore.setState({ user: null } as never);
    }
  });

  it("prefiks adresu idzie z `recruiter_base_url` (bez protokołu), nie ze stałej domeny", async () => {
    await openGeneral({
      "/api/me/career-link": {
        ...careerLink,
        link: { ...careerLink.link, public_url: "https://nexus.dynaminds.pl/kariera/p/marta-n" },
        base_url: "https://nexus.dynaminds.pl",
        recruiter_base_url: "https://nexus.dynaminds.pl/kariera/p/",
      },
    });
    expect(await screen.findByTestId("career-slug-prefix")).toHaveTextContent(
      "nexus.dynaminds.pl/kariera/p/",
    );
    expect(screen.getByTestId("linkedin-preview")).toHaveTextContent("nexus.dynaminds.pl");
    expect(screen.getByTestId("linkedin-preview")).not.toHaveTextContent("kariera.dynaminds.pl");
  });

  it("starszy backend bez `recruiter_base_url`: prefiks z adresu linku bez sluga", async () => {
    await openGeneral({
      "/api/me/career-link": {
        ...careerLink,
        link: { ...careerLink.link, public_url: "https://nexus.dynaminds.pl/kariera/p/marta-n" },
      },
    });
    expect(await screen.findByTestId("career-slug-prefix")).toHaveTextContent(
      "nexus.dynaminds.pl/kariera/p/",
    );
  });

  it("sprawdza dostępność adresu z opóźnieniem i pokazuje powód zajętości", async () => {
    const user = await openGeneral({
      "/api/me/career-link": careerLink,
      "/api/me/career-link/slug-available": { available: false, reason: "Ten adres jest już zajęty." },
    });
    const input = await screen.findByLabelText("Twój adres");
    await user.clear(input);
    await user.type(input, "marta-x");
    expect(screen.getByText("Sprawdzam adres…")).toBeInTheDocument();
    expect(await screen.findByText("Ten adres jest już zajęty.", {}, { timeout: 2000 })).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith("/api/me/career-link/slug-available", {
      params: { slug: "marta-x" },
    });
    expect(screen.getByRole("button", { name: "Zapisz adres" })).toBeDisabled();

    await user.clear(input);
    await user.type(input, "Zły adres");
    expect(screen.getByText(/Tylko małe litery, cyfry i myślnik/)).toBeInTheDocument();
  });

  it("wyłączenie linku wymaga drugiego kliknięcia", async () => {
    const user = await openGeneral({ "/api/me/career-link": careerLink });
    vi.mocked(api.delete).mockResolvedValue({ data: null });
    const confirmSpy = vi.spyOn(window, "confirm");

    await user.click(await screen.findByRole("button", { name: /Wyłącz link/ }));
    expect(api.delete).not.toHaveBeenCalled();
    const box = screen.getByRole("alertdialog", { name: "Potwierdź wyłączenie linku" });

    await user.click(within(box).getByRole("button", { name: "Anuluj" }));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Wyłącz link/ }));
    await user.click(screen.getByRole("button", { name: "Tak, wyłącz link" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith("/api/me/career-link"));
    expect(confirmSpy).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  it("awaria wczytania linku ogólnego nie wygląda jak brak linku", async () => {
    await openGeneral({
      "/api/me/career-link": () =>
        Object.assign(new Error("boom"), { response: { status: 503, data: {} } }),
    });
    expect(await screen.findByText(/Nie udało się wczytać Twojego linku ogólnego/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Utwórz link" })).not.toBeInTheDocument();
    await act(async () => {});
  });
});

describe("GenerateInviteLinkV2 — Wyniki", () => {
  const RESULTS = {
    days: 30,
    totals: {
      visits: 212,
      applications: 18,
      new_candidates: 11,
      existing_candidates: 7,
      in_process: 9,
      verified: 4,
      cv_sent: 2,
      hired: 0,
    },
    links: [
      {
        kind: "job",
        slug: "senior-java-7kq2",
        public_url: "https://kariera.example/r/senior-java-7kq2",
        job_id: 101,
        job_title: "Senior Java Developer",
        state: "live",
        visits: 148,
        applications: 12,
        new_candidates: 8,
        existing_candidates: 4,
        in_process: 7,
        verified: 3,
        cv_sent: 2,
        hired: 0,
      },
      {
        kind: "recruiter",
        slug: "marta-n",
        public_url: "https://kariera.example/marta-n",
        job_id: null,
        job_title: null,
        state: "live",
        visits: 64,
        applications: 6,
        new_candidates: 3,
        existing_candidates: 3,
        in_process: 2,
        verified: 1,
        cv_sent: 0,
        hired: 0,
      },
    ],
  };

  it("pokazuje lejek wszystkich linków i wiersz na każdy link; okres idzie do API", async () => {
    const user = userEvent.setup();
    routeGet({ ...baseRoutes, "/api/me/career-link/results": RESULTS });
    renderDialog();
    await user.click(screen.getByRole("tab", { name: "Wyniki" }));

    const funnel = await screen.findByTestId("results-funnel");
    expect(funnel).toHaveTextContent("Zgłoszenia18");
    expect(funnel).toHaveTextContent("już byli w bazie7");
    const table = screen.getByTestId("results-links");
    expect(within(table).getByText("Senior Java Developer")).toBeInTheDocument();
    expect(within(table).getByText("Mój link ogólny")).toBeInTheDocument();
    expect(within(table).getByText("w tym 4 już w bazie")).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith("/api/me/career-link/results", {
      params: { days: 30 },
    });

    await user.click(screen.getByRole("button", { name: "Od początku" }));
    await waitFor(() =>
      expect(api.get).toHaveBeenCalledWith("/api/me/career-link/results", {
        params: { days: 0 },
      }),
    );
  });

  it("awaria wyników nie wygląda jak brak linków", async () => {
    const user = userEvent.setup();
    routeGet({
      ...baseRoutes,
      "/api/me/career-link/results": () =>
        Object.assign(new Error("boom"), { response: { status: 500, data: {} } }),
    });
    renderDialog();
    await user.click(screen.getByRole("tab", { name: "Wyniki" }));
    expect(
      await screen.findByText(/Nie udało się policzyć wyników linków/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Nie masz jeszcze linków/)).not.toBeInTheDocument();
  });
});
