/**
 * Baner Powtórki (wariant 2, 24.11.2026): najlepiej pasująca rekrutacja na
 * górze, reszta pod „Inne podobne”, kolumny „Weźmiemy z” / „Z nowego maila”,
 * „Użyj <nr>…” oddaje szablon i łączenie, „Czytaj od zera” — nic nie zmienia.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { IntakeOfferChip } from "@/components/v2/jobs/new/IntakeOfferChip";
import { RepeatRequestBanner } from "@/components/v2/jobs/new/RepeatRequestBanner";
import type { RequestHistoryEntry } from "@/lib/api";
import { repeatTemplate } from "@/lib/job-intake-repeat";
import { EMPTY_INTAKE_FORM, type IntakeForm } from "@/lib/job-request-intake";

const entry = (patch: Partial<RequestHistoryEntry>): RequestHistoryEntry => ({
  job_id: 1,
  title: "Backend Java developer",
  train_name: null,
  same_train: false,
  seniority: null,
  status: "published",
  is_in_progress: true,
  outcome: null,
  close_reason: null,
  similarity: 0.7,
  similarity_source: "sql_same_client",
  closed_at: null,
  created_at: "2026-11-13T09:00:00Z",
  tth_days: null,
  client_id: 7,
  client_name: "Nordea",
  champion_name: null,
  champion_candidate_id: null,
  champions_count: 0,
  candidates_count: 69,
  fee_rate: null,
  fee_currency: null,
  rate_unit: null,
  tac_name: null,
  delivery_lead_name: "Igor T.",
  ...patch,
});

const TEMPLATE = repeatTemplate(
  {
    id: 43260,
    rate_budget_hourly: 130,
    rate_budget_hourly_min: 100,
    remote_policy: "hybrid",
    onsite_days_per_week: 3,
    hiring_manager_contact_id: 501,
    hiring_manager_name: "Anna Nowak",
    champion_profile: {
      stack: { rows: [{ words: ["Java"], level: "must" }], critical: ["Java"] },
    },
  },
  null,
);

const READ: IntakeForm = {
  ...EMPTY_INTAKE_FORM,
  title: "Backend Java Developer",
  clientTitle: "Backend Java developer - TOR (51234)",
  referenceHint: "51234",
  about: "Nowy projekt.",
  rateBudget: "150",
  rateBudgetMin: "120",
  provenance: { role: "request" },
};

function renderBanner(entries: RequestHistoryEntry[]) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const loadTemplate = vi.fn(async () => TEMPLATE);
  const onUse = vi.fn();
  const onFromScratch = vi.fn();
  render(
    <QueryClientProvider client={queryClient}>
      <RepeatRequestBanner
        clientName="Nordea"
        entries={entries}
        read={READ}
        loadTemplate={loadTemplate}
        onUse={onUse}
        onFromScratch={onFromScratch}
      />
    </QueryClientProvider>,
  );
  return { loadTemplate, onUse, onFromScratch };
}

describe("RepeatRequestBanner", () => {
  it("na górze najlepiej pasująca, z kolumnami i różnicami z maila", async () => {
    const { loadTemplate } = renderBanner([
      entry({ job_id: 40001, similarity: 0.65, is_in_progress: false, outcome: "filled" }),
      entry({ job_id: 43260, similarity: 0.91 }),
    ]);
    expect(screen.getByText("To wygląda na powtórkę requestu u Nordea")).toBeInTheDocument();
    expect(screen.getByText("Backend Java developer (43260)")).toBeInTheDocument();
    expect(screen.getByText(/W toku od 13\.11 · 69 kandydatów · DL: Igor T\./)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Inne podobne (1)" })).toBeInTheDocument();
    expect(loadTemplate).toHaveBeenCalledWith(43260);
    await waitFor(() =>
      expect(screen.getByTestId("repeat-request-take")).toHaveTextContent(
        "1 wymaganie (krytyczne: Java) · budżet 100–130 · hybrydowo 3 dni",
      ),
    );
    expect(screen.getByTestId("repeat-request-mail")).toHaveTextContent(
      "nazwa i numer · opis projektu · rola · inne niż w 43260: budżet PLN/h",
    );
  });

  it("„Użyj” oddaje wpis, szablon i łączenie; z „Inne podobne” można wybrać inną", async () => {
    const user = userEvent.setup();
    const { onUse, loadTemplate } = renderBanner([
      entry({ job_id: 43260, similarity: 0.91 }),
      entry({ job_id: 40001, similarity: 0.65, title: "Java dev — stary" }),
    ]);
    await user.click(screen.getByRole("button", { name: "Inne podobne (1)" }));
    await user.click(screen.getByRole("button", { name: "Porównaj z tą" }));
    expect(loadTemplate).toHaveBeenLastCalledWith(40001);
    const use = await screen.findByRole("button", {
      name: "Użyj 40001 i przeczytaj z maila tylko różnice",
    });
    await waitFor(() => expect(use).toBeEnabled());
    await user.click(use);
    expect(onUse).toHaveBeenCalledTimes(1);
    const arg = onUse.mock.calls[0][0];
    expect(arg.entry.job_id).toBe(40001);
    expect(arg.merge.form.rows[0].level).toBe("critical");
    expect(arg.merge.offers.find((o: { unit: string }) => o.unit === "hiringManager")).toMatchObject({
      sourceLabel: "40001",
    });
  });

  it("„Czytaj od zera” nie wypełnia niczego", async () => {
    const user = userEvent.setup();
    const { onUse, onFromScratch } = renderBanner([entry({ job_id: 43260 })]);
    expect(screen.queryByRole("button", { name: /Inne podobne/ })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Czytaj od zera" }));
    expect(onFromScratch).toHaveBeenCalled();
    expect(onUse).not.toHaveBeenCalled();
  });

  it("awaria wczytania szablonu jest widoczna i nie blokuje „Czytaj od zera”", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <RepeatRequestBanner
          clientName="Nordea"
          entries={[entry({ job_id: 43260 })]}
          read={READ}
          loadTemplate={() => Promise.reject(new Error("500"))}
          onUse={vi.fn()}
          onFromScratch={vi.fn()}
        />
      </QueryClientProvider>,
    );
    expect(
      await screen.findByText("Nie udało się wczytać 43260 — spróbuj ponownie albo czytaj od zera."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Spróbuj ponownie" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Czytaj od zera" })).toBeEnabled();
  });
});

describe("IntakeOfferChip — hiring manager z poprzedniej rekrutacji", () => {
  it("„Ta sama osoba co w 43260” z „Potwierdź” / „Inna osoba”", async () => {
    const user = userEvent.setup();
    const onUse = vi.fn();
    const onDismiss = vi.fn();
    render(
      <IntakeOfferChip
        offer={{
          id: "hiringManager",
          unit: "hiringManager",
          source: "template",
          label: "Hiring manager",
          text: "Anna Nowak",
          basis: "client_history",
          patch: {},
          sourceLabel: "43260",
        }}
        onUse={onUse}
        onDismiss={onDismiss}
      />,
    );
    expect(screen.getByText(/Ta sama osoba co w 43260:/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Potwierdź — Hiring manager" }));
    await user.click(screen.getByRole("button", { name: "Inna osoba — Hiring manager" }));
    expect(onUse).toHaveBeenCalled();
    expect(onDismiss).toHaveBeenCalled();
  });
});
