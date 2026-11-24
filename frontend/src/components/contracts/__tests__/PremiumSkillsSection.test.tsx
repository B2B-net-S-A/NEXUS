import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  success: vi.fn(),
  error: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  api: { get: mocks.get, post: mocks.post, put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: mocks.success, showError: mocks.error, showToast: vi.fn() }),
}));

import { PremiumSkillsSection } from "../PremiumSkillsSection";
import type { PremiumClaim, PremiumEvidence } from "@/lib/api/framework-rates";

const KAFKA: PremiumEvidence = { technology: "Kafka", percent: "20.00", knows: true, uses: true, sources: ["CV", "zweryfikowane na screeningu"] };
const RUST: PremiumEvidence = { technology: "Rust", percent: "15.00", knows: true, uses: false, sources: ["CV"] };
const GO: PremiumEvidence = { technology: "Go", percent: "10.00", knows: false, uses: true, sources: ["oś czasu CV: 12 mies."] };

function claim(overrides: Partial<PremiumClaim>): PremiumClaim {
  return {
    id: 1,
    technology: "Kafka",
    status: "approved",
    knows: true,
    uses: true,
    dl_note: null,
    client_confirmed_by: null,
    client_confirmed_on: null,
    outcome_reason: null,
    next_try_on: null,
    created_at: "2026-11-01T10:00:00Z",
    updated_at: "2026-11-01T10:00:00Z",
    ...overrides,
  };
}

function route(data: { evidence: PremiumEvidence[]; claims: PremiumClaim[] } | Error) {
  mocks.get.mockImplementation(async (url: string) => {
    if (url !== "/api/contracts/11/premium-skills") throw new Error(`nieoczekiwane ${url}`);
    if (data instanceof Error) throw data;
    return { data };
  });
}

function renderSection(canEdit = true, category: string | null = "Developer Senior") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <PremiumSkillsSection contractId={11} canEdit={canEdit} category={category} />
    </QueryClientProvider>,
  );
}

function item(technology: string) {
  return screen.getByText(technology, { exact: false, selector: "span.font-medium" }).closest("li") as HTMLElement;
}

beforeEach(() => {
  mocks.get.mockReset();
  mocks.post.mockReset();
  mocks.success.mockReset();
  mocks.error.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("Technologie premium — lista", () => {
  it("bez dowodów mówi, że NEXUS nic nie znalazł", async () => {
    route({ evidence: [], claims: [] });
    renderSection();
    expect(await screen.findByText(/NEXUS nie znalazł technologii z umowy/)).toBeInTheDocument();
  });

  it("awaria zapytania nie udaje braku technologii", async () => {
    route(new Error("500"));
    renderSection();
    await waitFor(() => expect(mocks.get).toHaveBeenCalled());
    expect(screen.queryByText(/NEXUS nie znalazł technologii z umowy/)).not.toBeInTheDocument();
  });

  it("propozycja NEXUSA, procent bez zer i źródła dowodu", async () => {
    route({ evidence: [KAFKA, RUST, GO], claims: [] });
    renderSection();
    await screen.findByTestId("premium-skills");
    expect(within(item("Kafka")).getByText("+20%")).toBeInTheDocument();
    expect(within(item("Kafka")).getByText("NEXUS: zna i korzysta")).toBeInTheDocument();
    expect(within(item("Kafka")).getByText("CV · zweryfikowane na screeningu")).toBeInTheDocument();
    expect(within(item("Rust")).getByText("NEXUS: zna, brak dowodu użycia")).toBeInTheDocument();
    expect(within(item("Go")).getByText("NEXUS: korzysta")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Oceń i złóż wniosek" })).toHaveLength(3);
  });

  it("przyznana dopłata blokuje wniosek o niższą; odmowa pokazuje powód i datę ponowienia", async () => {
    route({
      evidence: [KAFKA, RUST, GO],
      claims: [
        claim({ id: 1, technology: "Kafka", status: "granted", client_confirmed_on: "2026-11-05" }),
        claim({ id: 2, technology: "Go", status: "refused", outcome_reason: "używana sporadycznie", next_try_on: "2027-01-01" }),
      ],
    });
    renderSection();
    await screen.findByTestId("premium-skills");
    expect(within(item("Kafka")).getByText("Przyznana 05.11.2026")).toBeInTheDocument();
    expect(within(item("Kafka")).queryByRole("button")).not.toBeInTheDocument();
    expect(within(item("Rust")).getByText("Umowa daje jedną dopłatę — przyznana już za Kafka.")).toBeInTheDocument();
    expect(within(item("Rust")).queryByRole("button", { name: "Oceń i złóż wniosek" })).not.toBeInTheDocument();
    expect(within(item("Go")).getByText("Odmowa klienta: używana sporadycznie · ponów od 01.01.2027")).toBeInTheDocument();
  });

  it("bez prawa edycji nie ma przycisków", async () => {
    route({ evidence: [KAFKA], claims: [claim({ status: "approved" })] });
    renderSection(false);
    await screen.findByTestId("premium-skills");
    expect(within(item("Kafka")).getByText("Zatwierdzony przez DL")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});

describe("Technologie premium — wniosek", () => {
  it("zatwierdzony wniosek: „Wysłane do klienta” i „Wycofaj” wołają akcję wniosku", async () => {
    const data = { evidence: [KAFKA], claims: [claim({ id: 9, status: "approved" })] };
    route(data);
    mocks.post.mockResolvedValue({ data });
    const user = userEvent.setup();
    renderSection();
    await user.click(await screen.findByRole("button", { name: "Wysłane do klienta" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith("/api/contracts/11/premium-skills/claims/9/action", { action: "send" }),
    );
    await user.click(screen.getByRole("button", { name: "Wycofaj" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith("/api/contracts/11/premium-skills/claims/9/action", { action: "drop" }),
    );
  });

  it("wysłany wniosek nie ma już „Wysłane do klienta”; błąd akcji idzie komunikatem", async () => {
    route({ evidence: [KAFKA], claims: [claim({ id: 9, status: "sent" })] });
    mocks.post.mockRejectedValue({ isAxiosError: true, response: { status: 409, data: { detail: "Wniosek jest już zamknięty." } } });
    const user = userEvent.setup();
    renderSection();
    await screen.findByText("Wysłany do klienta");
    expect(screen.queryByRole("button", { name: "Wysłane do klienta" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Wycofaj" }));
    await waitFor(() => expect(mocks.error).toHaveBeenCalledWith("Wniosek jest już zamknięty."));
  });

  it("ocena DL: zna i korzysta = wniosek z notatką; bez „korzysta” = zapis bez wniosku", async () => {
    route({ evidence: [KAFKA, RUST], claims: [] });
    mocks.post.mockResolvedValue({ data: { evidence: [KAFKA, RUST], claims: [] } });
    const user = userEvent.setup();
    renderSection();
    await user.click(within(await screen.findByTestId("premium-skills")).getAllByRole("button", { name: "Oceń i złóż wniosek" })[0]);
    let dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Kafka: zna i korzysta?")).toBeInTheDocument();
    await user.type(within(dialog).getByLabelText("Przykłady z projektu (do uzasadnienia)"), " strumienie płatności ");
    await user.click(within(dialog).getByRole("button", { name: "Zatwierdzam wniosek" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith("/api/contracts/11/premium-skills/claims", {
        technology: "Kafka",
        knows: true,
        uses: true,
        note: "strumienie płatności",
      }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());

    await user.click(within(item("Rust")).getByRole("button", { name: "Oceń i złóż wniosek" }));
    dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("button", { name: "Zapisz: bez wniosku" })).toBeInTheDocument();
    await user.click(within(dialog).getByRole("checkbox", { name: /Korzysta z niej/ }));
    expect(within(dialog).getByRole("button", { name: "Zatwierdzam wniosek" })).toBeInTheDocument();
    await user.click(within(dialog).getByRole("checkbox", { name: /Zna technologię/ }));
    await user.click(within(dialog).getByRole("button", { name: "Zapisz: bez wniosku" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenLastCalledWith("/api/contracts/11/premium-skills/claims", {
        technology: "Rust",
        knows: false,
        uses: true,
        note: null,
      }),
    );
  });

  it("błąd zapisu decyzji zostaje w oknie", async () => {
    route({ evidence: [KAFKA], claims: [] });
    mocks.post.mockRejectedValue(new Error("sieć"));
    const user = userEvent.setup();
    renderSection();
    await user.click(await screen.findByRole("button", { name: "Oceń i złóż wniosek" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Zatwierdzam wniosek" }));
    expect(await within(dialog).findByText(/Nie udało się/)).toBeInTheDocument();
  });

  it("„Klient przyznał” wysyła potwierdzenie z datą z kalendarza firmy i ogłasza podniesiony limit", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-12-31T23:15:00Z"));
    const data = { evidence: [KAFKA], claims: [claim({ id: 9, status: "sent" })] };
    route(data);
    mocks.post.mockResolvedValue({ data });
    const user = userEvent.setup();
    renderSection();
    await user.click(await screen.findByRole("button", { name: "Klient przyznał" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Klient przyznał dopłatę: Kafka")).toBeInTheDocument();
    // 31.12 23:15 UTC to już 1 stycznia w Warszawie.
    expect(within(dialog).getByLabelText("Data potwierdzenia")).toHaveValue("2027-01-01");
    await user.type(within(dialog).getByLabelText("Potwierdził po stronie klienta"), " Anna Przykładowa ");
    await user.click(within(dialog).getByRole("button", { name: "Zapisz" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith("/api/contracts/11/premium-skills/claims/9/action", {
        action: "grant",
        confirmed_by: "Anna Przykładowa",
        confirmed_on: "2027-01-01",
        client_evidence: null,
      }),
    );
    await waitFor(() => expect(mocks.success).toHaveBeenCalledWith("Dopłata za Kafka zapisana — limit podniesiony"));
  });

  it("odmowa: powód i data ponowienia, bez ogłoszenia; błąd zostaje w oknie", async () => {
    const data = { evidence: [KAFKA], claims: [claim({ id: 9, status: "sent" })] };
    route(data);
    mocks.post
      .mockRejectedValueOnce({ isAxiosError: true, response: { status: 422, data: { detail: "Podaj powód odmowy." } } })
      .mockResolvedValueOnce({ data });
    const user = userEvent.setup();
    renderSection();
    await user.click(await screen.findByRole("button", { name: "Odmowa" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Odmowa klienta: Kafka")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Zapisz" }));
    expect(await within(dialog).findByText("Podaj powód odmowy.")).toBeInTheDocument();
    expect(mocks.post).toHaveBeenLastCalledWith("/api/contracts/11/premium-skills/claims/9/action", {
      action: "refuse",
      reason: null,
      next_try_on: null,
    });
    await user.type(within(dialog).getByLabelText("Powód odmowy"), "nice to have");
    await user.type(within(dialog).getByLabelText("Ponów od (opcjonalnie)"), "2027-03-01");
    await user.click(within(dialog).getByRole("button", { name: "Zapisz" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenLastCalledWith("/api/contracts/11/premium-skills/claims/9/action", {
        action: "refuse",
        reason: "nice to have",
        next_try_on: "2027-03-01",
      }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(mocks.success).not.toHaveBeenCalled();
  });

  it("„Uzasadnienie (EN)” składa szkic z kategorii, źródeł i notatki DL", async () => {
    route({ evidence: [KAFKA], claims: [claim({ id: 9, status: "approved", dl_note: "payment streams" })] });
    const user = userEvent.setup();
    renderSection(true, "Developer Senior");
    await user.click(await screen.findByRole("button", { name: "Uzasadnienie (EN)" }));
    const dialog = await screen.findByRole("dialog");
    const text = (within(dialog).getByLabelText("Uzasadnienie po angielsku") as HTMLTextAreaElement).value;
    expect(text).toContain("Examples from the project: payment streams");
    expect(text).toContain("in the Developer Senior competence category");
    expect(text).toContain("20% Premium Technology Price Adder for Kafka");
    expect(text).toContain("verified in our technical screening");
  });
});
