import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/components/v2/CandidateNav", () => ({ CandidateNav: () => null }));
vi.mock("@/components/v2/presence/ActiveViewers", () => ({ ActiveViewers: () => null }));
vi.mock("@/components/v2/CompetenceCategoryBadge", () => ({
  CompetenceCategoryBadge: () => null,
}));
const conflicts = vi.hoisted(() => ({ rows: [] as unknown[] }));
vi.mock("@/lib/api", () => ({
  phase5Api: {
    conflicts: { list: vi.fn(() => Promise.resolve({ data: conflicts.rows })) },
  },
}));
const toast = vi.hoisted(() => ({ showSuccess: vi.fn(), showError: vi.fn() }));
vi.mock("@/components/Toast", () => ({ useToast: () => toast }));

import { ProfilePersonBar, type ProfilePersonBarActions } from "../ProfileHeader";
import { linkedinHref } from "../profile-helpers";

const noop = () => {};

function renderBar(
  candidate: Record<string, unknown>,
  canWrite = false,
  overrides: Partial<ProfilePersonBarActions> = {},
) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const actions: ProfilePersonBarActions = {
    onAssign: noop,
    onAddNote: noop,
    onEmail: noop,
    onScheduleInterview: noop,
    onPrepInvite: noop,
    onEdit: noop,
    onTagsPools: noop,
    onConflicts: noop,
    ...overrides,
  };
  return render(
    <QueryClientProvider client={client}>
      <ProfilePersonBar
        candidate={{ id: 5, name: "Anna", lastname: "Nowak", status: "active", ...candidate }}
        candidateId={5}
        canWrite={canWrite}
        viewers={[]}
        actions={actions}
      />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  conflicts.rows = [];
  toast.showSuccess.mockReset();
  toast.showError.mockReset();
});

// Runda 8 (R8-N14-3): `GET /api/candidates/{id}` zwraca pole `linkedin`,
// a nagłówek czytał `linkedin_url` — link nie pokazywał się nigdy.
describe("ProfilePersonBar — link do LinkedIna", () => {
  it("czyta pole `linkedin` z odpowiedzi kandydata", () => {
    renderBar({ linkedin: "https://www.linkedin.com/in/przyklad" });
    const link = screen.getByRole("link", { name: /LinkedIn/ });
    expect(link.getAttribute("href")).toBe("https://www.linkedin.com/in/przyklad");
  });

  it("adres bez schematu dostaje https, niebezpieczny schemat — brak linku", () => {
    expect(linkedinHref("linkedin.com/in/przyklad")).toBe("https://linkedin.com/in/przyklad");
    expect(linkedinHref("javascript:alert(1)")).toBeNull();
    expect(linkedinHref("  ")).toBeNull();
    renderBar({ linkedin: "javascript:alert(1)" });
    expect(screen.queryByRole("link", { name: /LinkedIn/ })).toBeNull();
  });
});

describe("ProfilePersonBar — tożsamość i pigułki (E1, D4, 13.10.2026)", () => {
  it("pokazuje „Szuka aktywnie” zamiast plakietki statusu „Aktywny”", () => {
    renderBar({ availability_status: "actively_looking" });
    expect(screen.getByRole("heading", { level: 1, name: "Anna Nowak" })).toBeInTheDocument();
    expect(screen.getByText("Szuka aktywnie")).toBeInTheDocument();
    expect(screen.queryByText("Aktywny")).toBeNull();
  });

  it("przy żywej umowie „Pracuje u nas” zastępuje „Szuka aktywnie” ze screeningu (D3, 15.10.2026)", () => {
    renderBar({
      availability_status: "actively_looking",
      employment_marker: {
        phase: "working",
        source: "contract",
        clients: [{ client_id: 3, client_name: "Bank Przykładowy", phase: "working" }],
        free_from: null,
        free_from_basis: "no_end_date",
      },
    });
    expect(screen.queryByText("Szuka aktywnie")).toBeNull();
    expect(screen.getByText(/Pracuje u nas/)).toBeInTheDocument();
  });

  it("czarna lista nie jest pigułką w pasku — mówi o niej baner pod paskiem (17.10.2026)", () => {
    renderBar({ status: "blacklisted" });
    expect(screen.queryByText("Czarna lista")).toBeNull();
  });

  it("inicjały biorą litery, nie nawias z dopiskiem", () => {
    renderBar({ name: "[ACTIVE] Anna" });
    expect(screen.getByText("AN")).toBeInTheDocument();
  });

  it("aktywny konflikt z klientem to chip otwierający okno „Konflikty i weta”", async () => {
    conflicts.rows = [
      { id: 1, active: true, type_label: "NDA / cooling-off", client_name: "Bank Północny" },
    ];
    const onConflicts = vi.fn();
    renderBar({}, false, { onConflicts });
    const chip = await screen.findByRole("button", { name: /Konflikt: Bank Północny/ });
    fireEvent.click(chip);
    expect(onConflicts).toHaveBeenCalled();
  });
});

describe("ProfilePersonBar — kontakt", () => {
  it("klik w adres otwiera okno maila M365, obok kopiowanie adresu i numeru", async () => {
    const writeText = vi.fn(() => Promise.resolve());
    Object.assign(navigator, { clipboard: { writeText } });
    const onEmail = vi.fn();
    renderBar({ email: "anna@example.com", phone: "600 100 200" }, true, { onEmail });
    fireEvent.click(screen.getByRole("button", { name: "anna@example.com" }));
    expect(onEmail).toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Kopiuj numer telefonu" }));
    expect(writeText).toHaveBeenCalledWith("600 100 200");
    await waitFor(() => expect(toast.showSuccess).toHaveBeenCalledWith("Skopiowano numer telefonu"));
    // Dawny `mailto:` (prywatny program pocztowy) zniknął — jedna droga maila.
    expect(document.querySelector('a[href^="mailto:"]')).toBeNull();
  });

  it("rola bez zapisu widzi adres jako tekst do zaznaczenia", () => {
    renderBar({ email: "anna@example.com" }, false);
    expect(screen.queryByRole("button", { name: "anna@example.com" })).toBeNull();
    expect(screen.getByText("anna@example.com")).toBeInTheDocument();
  });
});

// Przegląd kodu 04.10.2026: tagi, pule, konflikty i weta zeszły z widoku do
// menu „⋯” — rola bez zapisu nie może ich stracić z oczu.
describe("ProfilePersonBar — menu „⋯”", () => {
  it("bez prawa zapisu: okna do odczytu, bez akcji zapisu", () => {
    renderBar({}, false);
    expect(screen.queryByRole("button", { name: /Przypisz do rekrutacji/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Dodaj notatkę/ })).toBeNull();
    fireEvent.keyDown(screen.getByRole("button", { name: "Więcej akcji" }), { key: "Enter" });
    expect(screen.getByRole("menuitem", { name: /Tagi i pule/ })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: /Konflikty i weta/ })).toBeTruthy();
    expect(screen.queryByRole("menuitem", { name: /Edytuj dane/ })).toBeNull();
    expect(screen.queryByRole("menuitem", { name: /Napisz maila/ })).toBeNull();
  });

  it("z prawem zapisu: akcje w jednym rzędzie i menu bez martwych pozycji (D1–D3)", () => {
    renderBar({ email: "anna@example.com" }, true, { onNoAnswer: noop });
    for (const name of [/Przypisz do rekrutacji/, /Dodaj notatkę/, /Nie odebrał/]) {
      expect(screen.getByRole("button", { name })).toBeTruthy();
    }
    fireEvent.keyDown(screen.getByRole("button", { name: "Więcej akcji" }), { key: "Enter" });
    for (const name of [/Napisz maila/, /Zaplanuj rozmowę/, /Zaproś na prep/, /Edytuj dane/, /Tagi i pule/]) {
      expect(screen.getByRole("menuitem", { name })).toBeTruthy();
    }
    for (const gone of [/Obserwuj/, /Wrzuć na targ/, /Korekta imienia/, /Generuj CV/]) {
      expect(screen.queryByRole("menuitem", { name: gone })).toBeNull();
    }
  });

  it("„Status osoby → Czarna lista…” z prawem zapisu otwiera okno (17.10.2026)", async () => {
    const onBlacklist = vi.fn();
    renderBar({}, true, { onBlacklist });
    fireEvent.keyDown(screen.getByRole("button", { name: "Więcej akcji" }), { key: "Enter" });
    expect(screen.getByText("Status osoby")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("menuitem", { name: /Czarna lista…/ }));
    await waitFor(() => expect(onBlacklist).toHaveBeenCalledTimes(1));
  });

  it("bez prawa zapisu nie ma „Czarnej listy…”", () => {
    renderBar({}, false, { onBlacklist: vi.fn() });
    fireEvent.keyDown(screen.getByRole("button", { name: "Więcej akcji" }), { key: "Enter" });
    expect(screen.queryByRole("menuitem", { name: /Czarna lista/ })).toBeNull();
    expect(screen.queryByText("Status osoby")).toBeNull();
  });
});

describe("ProfilePersonBar — „Najnowsze CV” (22.10.2026, jak w Traffit)", () => {
  const cv = {
    id: 9,
    filename: "Anna-Nowak-CV.pdf",
    content_type: "application/pdf",
    size_bytes: 1000,
    document_kind: "cv" as const,
    is_primary: true,
    uploaded_at: "2024-09-23T10:00:00Z",
    external_source: null,
    created_at: "2024-09-23T10:00:00Z",
    uploaded_by_name: "Jan Rekruter",
  };

  it("otwiera podgląd także bez prawa zapisu; w podpowiedzi plik, data i kto wgrał", () => {
    const onOpenLatestCv = vi.fn();
    renderBar({}, false, { latestCv: cv, onOpenLatestCv });
    const button = screen.getByRole("button", { name: "Najnowsze CV" });
    expect(button.getAttribute("title")).toBe("Anna-Nowak-CV.pdf · wgrane 23.09.2024 przez Jan Rekruter");
    fireEvent.click(button);
    expect(onOpenLatestCv).toHaveBeenCalledTimes(1);
  });

  it("bez pliku CV przycisku nie ma", () => {
    renderBar({}, true, { latestCv: null, onOpenLatestCv: noop });
    expect(screen.queryByRole("button", { name: "Najnowsze CV" })).toBeNull();
  });
});
