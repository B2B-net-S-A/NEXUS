import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const put = vi.fn();
vi.mock("@/lib/api", () => ({
  default: { get: (...a: unknown[]) => get(...a), put: (...a: unknown[]) => put(...a) },
}));
const toastSuccess = vi.fn();
const toastError = vi.fn();
vi.mock("@/components/Toast", () => ({
  useToast: () => ({
    showSuccess: (...a: unknown[]) => toastSuccess(...a),
    showError: (...a: unknown[]) => toastError(...a),
  }),
}));

import {
  PairOwnerLine,
  canLead,
  currentOwner,
  mayAssignOwner,
} from "@/components/v2/jobs/PairOwnerLine";
import { useAuthStore } from "@/store/auth";

const PEOPLE = [
  { id: 131, name: "Zofia Przykładowa", role: "recruiter", roles: ["recruiter"], is_active: false },
  { id: 101, name: "Maria Przykładowa", role: "delivery_lead", roles: ["delivery_lead", "recruiter"], is_active: true },
  { id: 182, name: "Maria Przykładowa (DL)", role: "delivery_lead", roles: ["delivery_lead"], is_active: true },
  { id: 88, name: "Dawid Przykładowy", role: "recruiter", roles: ["recruiter"], is_active: true },
];

const verifiedItem = {
  candidate_id: 13251,
  verified_by_id: 131,
  verified_by_name: "Zofia Przykładowa",
  verified_at: "2026-07-30T10:18:00Z",
  added_to_job_by_id: 131,
  added_to_job_by_name: "Zofia Przykładowa",
  added_to_job_at: "2026-07-29T09:52:15Z",
};

function renderLine(item = verifiedItem, seed?: (client: QueryClient) => void) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  seed?.(client);
  return render(
    <QueryClientProvider client={client}>
      <PairOwnerLine item={item} jobId={324353} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  get.mockImplementation((url: string) =>
    url === "/api/users/mentionable"
      ? Promise.resolve({ data: PEOPLE })
      : Promise.resolve({ data: { delivery_lead_user: { id: 101, name: "Maria Przykładowa" } } }),
  );
  put.mockResolvedValue({ data: {} });
});

afterEach(() => {
  useAuthStore.setState({ user: null } as never);
  vi.clearAllMocks();
});

describe("currentOwner — kto prowadzi", () => {
  it("przypisany wygrywa z weryfikującym i mówi, kto przypisał i kto był", () => {
    const owner = currentOwner({
      ...verifiedItem,
      owner_user_id: 101,
      owner_name: "Maria Przykładowa",
      owner_assigned_by_name: "Olaf Przykładowy",
      owner_assigned_at: "2026-10-25T10:00:00Z",
      owner_previous_name: "Zofia Przykładowa",
    });
    expect(owner.id).toBe(101);
    expect(owner.name).toBe("Maria Przykładowa");
    expect(owner.detail).toContain("przypisał(a) Olaf Przykładowy");
    expect(owner.detail).toContain("było: Zofia Przykładowa");
  });

  it("bez przypisania: weryfikujący, potem dodający, potem brak danych", () => {
    expect(currentOwner(verifiedItem).detail).toMatch(/^zweryfikował\(a\)/);
    expect(
      currentOwner({ ...verifiedItem, verified_by_name: null, verified_by_id: null }).detail,
    ).toMatch(/^dodał\(a\)/);
    expect(currentOwner({ candidate_id: 1 })).toEqual({ id: null, name: null, detail: "brak danych" });
  });
});

describe("kto przypisuje i kogo można przypisać (Artur 25.10.2026)", () => {
  it("przypisuje tylko admin i Head of Recruitment", () => {
    expect(mayAssignOwner(["admin"])).toBe(true);
    expect(mayAssignOwner(["delivery_lead", "head_of_recruitment"])).toBe(true);
    expect(mayAssignOwner(["delivery_lead", "recruiter"])).toBe(false);
    expect(mayAssignOwner(["recruiter"])).toBe(false);
  });

  it("prowadzić może aktywna osoba z rolą rekrutera, także DL, który rekrutuje", () => {
    expect(PEOPLE.filter(canLead).map((p) => p.id)).toEqual([101, 88]);
  });
});

describe("PairOwnerLine w panelu osoby", () => {
  it("rekruter widzi, kto prowadzi, bez przycisku „Przypisz”", async () => {
    useAuthStore.setState({ user: { id: 88, role: "recruiter", roles: ["recruiter"] } } as never);
    renderLine();
    expect(screen.getByTestId("dock-pair-owner")).toHaveTextContent("ProwadziZofia Przykładowa");
    expect(await screen.findByText(/konto nieaktywne/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Przypisz" })).toBeNull();
  });

  it("Head of Recruitment przypisuje DL-a z rolą rekrutera; podgląd mówi o obu premiach", async () => {
    useAuthStore.setState({
      user: { id: 2, role: "head_of_recruitment", roles: ["head_of_recruitment"] },
    } as never);
    renderLine();
    await userEvent.click(screen.getByRole("button", { name: "Przypisz" }));
    const select = await screen.findByLabelText("Osoba prowadząca");
    await waitFor(() => expect(select).not.toBeDisabled());
    expect(screen.queryByRole("option", { name: /Maria Przykładowa \(DL\)/ })).toBeNull();
    await userEvent.selectOptions(select, "101");
    expect(await screen.findByTestId("pair-owner-bonus-preview")).toHaveTextContent(
      "dostanie obie premie",
    );
    const save = screen.getAllByRole("button", { name: "Przypisz" }).at(-1)!;
    expect(save).toBeDisabled(); // bez powodu
    await userEvent.type(screen.getByLabelText("Dlaczego (zostaje w historii)"), "Prowadzi od początku");
    await userEvent.click(save);
    await waitFor(() =>
      expect(put).toHaveBeenCalledWith("/api/pipeline/jobs/324353/candidates/13251/owner", {
        owner_user_id: 101,
        reason: "Prowadzi od początku",
      }),
    );
    expect(toastSuccess).toHaveBeenCalledWith("Prowadzi teraz Maria Przykładowa.");
  });

  it("Delivery Leada rekrutacji czyta z zapytania strony — bez drugiego GET /api/jobs/{id}", async () => {
    useAuthStore.setState({
      user: { id: 2, role: "head_of_recruitment", roles: ["head_of_recruitment"] },
    } as never);
    // Strona `/jobs/[id]` trzyma rekrutację pod `["job", <id z adresu>]`.
    renderLine(verifiedItem, (client) =>
      client.setQueryData(["job", "324353"], {
        delivery_lead_user: { id: 101, name: "Maria Przykładowa" },
      }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Przypisz" }));
    const select = await screen.findByLabelText("Osoba prowadząca");
    await waitFor(() => expect(select).not.toBeDisabled());
    await userEvent.selectOptions(select, "101");
    expect(await screen.findByTestId("pair-owner-bonus-preview")).toHaveTextContent(
      "dostanie obie premie",
    );
    expect(get).not.toHaveBeenCalledWith("/api/jobs/324353");
  });
});
