/**
 * Kafelek „Szczegóły administracyjne” (0524): odbiorcy premii z rekrutacji
 * tylko do odczytu, komunikat o osobie prowadzącej, podpowiedzi po wybraniu
 * rekrutacji i „Replacement za kogo”.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  prefill: vi.fn(),
  replacementOptions: vi.fn(),
  me: { id: 90 } as { id: number } | null,
}));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: {},
  b2bGeneratorApi: {
    prefill: (...a: unknown[]) => mocks.prefill(...a),
    replacementOptions: (...a: unknown[]) => mocks.replacementOptions(...a),
  },
}));

vi.mock("@/store/auth", () => ({
  useAuthStore: (select: (s: { user: { id: number } | null }) => unknown) =>
    select({ user: mocks.me }),
}));

import { AgreementAdminDetailsCard } from "@/components/v2/b2b-generator/AgreementAdminDetailsCard";
import {
  EMPTY_ADMIN_VALUE,
  type AgreementAdminValue,
} from "@/lib/agreement-admin-details";

const REPLACED = {
  contract_id: 497,
  candidate_id: 3003,
  client_id: 39,
  name: "Zofia Przykładowa",
  client_name: "Klient Testowy S.A.",
  job_title: null,
  status: "ended",
  start_date: "2026-04-01",
  end_date: "2026-08-31",
};

function prefillWith(admin: Record<string, unknown>) {
  return {
    candidate_id: 1001,
    job_id: 2002,
    rate: null,
    start_date: null,
    availability_text: null,
    client_rate: null,
    client_rate_redacted: false,
    existing: null,
    admin: {
      client_id: 39,
      client_name: "Klient Testowy S.A.",
      recruiter: {
        user_id: 85,
        name: "Anna Przykładowa",
        source: "verifier",
        source_label: "pierwsza weryfikacja na Tablicy",
      },
      delivery_lead: {
        user_id: 30,
        name: "Ewa Testowa",
        source: "client_head",
        source_label: "główny DL klienta",
      },
      replacement_from_title: false,
      replaced: null,
      ...admin,
    },
  };
}

function Harness({
  candidateId = 1001,
  jobId = 2002,
  initial = EMPTY_ADMIN_VALUE,
  onValue,
}: {
  candidateId?: number | null;
  jobId?: number | null;
  initial?: AgreementAdminValue;
  onValue?: (v: AgreementAdminValue) => void;
}) {
  const [value, setValue] = React.useState(initial);
  return (
    <AgreementAdminDetailsCard
      candidateId={candidateId}
      jobId={jobId}
      value={value}
      onChange={(v) => {
        setValue(v);
        onValue?.(v);
      }}
    />
  );
}

function renderCard(props: React.ComponentProps<typeof Harness> = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <Harness {...props} />
    </QueryClientProvider>,
  );
}

describe("AgreementAdminDetailsCard", () => {
  beforeEach(() => {
    mocks.prefill.mockReset();
    mocks.replacementOptions.mockReset();
    mocks.me = { id: 90 };
  });

  it("przed wybraniem rekrutacji nic nie pobiera, a pola czekają", () => {
    renderCard({ candidateId: null, jobId: null });
    expect(mocks.prefill).not.toHaveBeenCalled();
    expect(
      screen.getAllByText("Uzupełni się po wybraniu rekrutacji"),
    ).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Tak" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "1" })).toBeDisabled();
  });

  it("pokazuje odbiorców premii i mówi, że umowę robisz za prowadzącą", async () => {
    mocks.prefill.mockResolvedValue(prefillWith({}));
    const onValue = vi.fn();
    renderCard({ onValue });

    expect(await screen.findByText("Anna Przykładowa")).toBeInTheDocument();
    expect(screen.getByText("Ewa Testowa")).toBeInTheDocument();
    expect(screen.getByText("główny DL klienta")).toBeInTheDocument();
    expect(
      screen.getByText(/Tworzysz umowę za osobę prowadzącą: Anna Przykładowa/),
    ).toBeInTheDocument();
    // Podpowiedzi po wybraniu rekrutacji: Nie i pełny etat.
    await waitFor(() =>
      expect(onValue).toHaveBeenLastCalledWith({
        isReplacement: false,
        replaced: null,
        fte: "1",
      }),
    );
    expect(screen.getByRole("button", { name: "Nie" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("prowadząca widzi, że placement i premia są jej", async () => {
    mocks.me = { id: 85 };
    mocks.prefill.mockResolvedValue(prefillWith({}));
    renderCard();
    expect(
      await screen.findByText(/Prowadzisz tę osobę: placement w Lidze/),
    ).toBeInTheDocument();
  });

  it("bez prowadzącego ostrzega, że nie będzie premii rekrutera", async () => {
    mocks.prefill.mockResolvedValue(prefillWith({ recruiter: null }));
    renderCard();
    expect(
      await screen.findByText(/Nikt nie prowadzi tej osoby w rekrutacji/),
    ).toBeInTheDocument();
    expect(screen.getByText("Brak osoby prowadzącej")).toBeInTheDocument();
  });

  it("zastępstwo z tytułu: Tak, osoba i gwarancja", async () => {
    mocks.prefill.mockResolvedValue(
      prefillWith({ replacement_from_title: true, replaced: REPLACED }),
    );
    renderCard();
    expect(await screen.findByText("Zofia Przykładowa")).toBeInTheDocument();
    expect(screen.getByText("z tytułu rekrutacji")).toBeInTheDocument();
    expect(
      screen.getByText(/Gwarancja: kontrakt Zofia Przykładowa trwał 5 mies./),
    ).toBeInTheDocument();
  });

  it("Nie chowa „za kogo” i czyści wybór; FTE 0,5 mówi o terminie premii", async () => {
    mocks.prefill.mockResolvedValue(
      prefillWith({ replacement_from_title: true, replaced: REPLACED }),
    );
    const onValue = vi.fn();
    const user = userEvent.setup();
    renderCard({ onValue });
    await screen.findByText("Zofia Przykładowa");

    await user.click(screen.getByRole("button", { name: "Nie" }));
    expect(screen.queryByText("Replacement za kogo")).not.toBeInTheDocument();
    expect(onValue).toHaveBeenLastCalledWith({
      isReplacement: false,
      replaced: null,
      fte: "1",
    });

    await user.click(screen.getByRole("button", { name: "0,5" }));
    expect(
      screen.getByText(/ok\. 42 dni roboczych od startu/),
    ).toBeInTheDocument();
  });

  it("lista „za kogo”: kontraktorzy klienta, potem cały NEXUS", async () => {
    mocks.prefill.mockResolvedValue(prefillWith({}));
    mocks.replacementOptions.mockImplementation(
      async (params: { clientId?: number | null; q?: string }) =>
        params.clientId
          ? [REPLACED]
          : [
              {
                ...REPLACED,
                contract_id: 624,
                name: "Piotr Fikcyjny",
                client_name: "Bosch",
              },
            ],
    );
    const user = userEvent.setup();
    renderCard();
    await screen.findByText("Anna Przykładowa");

    await user.click(screen.getByRole("button", { name: "Tak" }));
    await user.click(screen.getByRole("combobox"));
    expect(
      await screen.findByText("zakończony 31.08.2026"),
    ).toBeInTheDocument();
    expect(mocks.replacementOptions).toHaveBeenCalledWith({
      clientId: 39,
      excludeCandidateId: 1001,
    });

    await user.click(
      screen.getByText("Szukaj we wszystkich kontraktorach NEXUSA"),
    );
    await user.type(screen.getByPlaceholderText(/Nazwisko/), "Kowal");
    await user.click(await screen.findByText("Piotr Fikcyjny"));
    expect(
      screen.getByRole("button", { name: "Usuń Piotr Fikcyjny" }),
    ).toBeInTheDocument();
  });
});
