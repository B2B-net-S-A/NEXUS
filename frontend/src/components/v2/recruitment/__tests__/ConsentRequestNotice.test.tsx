import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  job: vi.fn(),
  policy: vi.fn(),
  rule: vi.fn(),
  branded: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: {
    get: (url: string) => {
      if (url === "/api/cv-generator/policy") return mocks.policy();
      if (url.endsWith("/rule-for-generation")) return mocks.rule();
      throw new Error(`nieznany adres ${url}`);
    },
  },
  jobsApi: { get: mocks.job },
  candidateStageCvApi: { branded: { get: mocks.branded } },
  candidatesApi: { get: vi.fn() },
  microsoft365Api: { listCandidateThreads: vi.fn() },
}));
vi.mock("@/components/v2/recruitment/ConsentRequestButton", async (original) => ({
  ...(await original<typeof import("../ConsentRequestButton")>()),
  ConsentRequestButton: () => <button type="button">Poproś kandydata o zgodę</button>,
}));

import { ConsentRequestNotice } from "../ConsentRequestNotice";

const PKO = { data: { client_id: 26, client_name: "Powszechna Kasa Oszczędności Bank Polski S.A" } };

function mount(moment: "screening" | "cv" = "screening") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ConsentRequestNotice stageId={5} candidateId={7} candidateName="Anna Fikcyjna" jobId={3} moment={moment} />
    </QueryClientProvider>,
  );
}

async function settled() {
  await waitFor(() => expect(mocks.policy).toHaveBeenCalled());
  await waitFor(() => expect(mocks.branded).toHaveBeenCalled());
  await new Promise((resolve) => setTimeout(resolve, 20));
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.job.mockResolvedValue(PKO);
  mocks.policy.mockResolvedValue({ data: { managed: false } });
  mocks.rule.mockResolvedValue({ data: { is_active: false } });
  mocks.branded.mockResolvedValue({ data: { consent_attached: false } });
});

describe("ConsentRequestNotice", () => {
  it("centralna reguła z wymogiem zgody: pasek na screeningu mówi o rozmowie", async () => {
    mocks.policy.mockResolvedValue({ data: { managed: true, effective_policy: { requires_rodo_consent_block: true } } });
    mount();
    const notice = await screen.findByTestId("consent-request-notice");
    expect(notice).toHaveTextContent("PKO BP przyjmuje CV tylko ze zgodą kandydata");
    expect(notice).toHaveTextContent("Powiedz o tym na rozmowie");
    expect(screen.getByRole("button", { name: /Poproś kandydata o zgodę/ })).toBeInTheDocument();
  });

  it("aktywna reguła klienta też włącza pasek, a na karcie nie ma mowy o rozmowie", async () => {
    mocks.rule.mockResolvedValue({ data: { is_active: true, requires_rodo_consent_block: true } });
    mount("cv");
    const notice = await screen.findByTestId("consent-request-notice");
    expect(notice).not.toHaveTextContent("na rozmowie");
  });

  it("propozycja reguły (nieaktywna) nie włącza paska", async () => {
    mocks.rule.mockResolvedValue({ data: { is_active: false, requires_rodo_consent_block: true } });
    mount();
    await settled();
    expect(screen.queryByTestId("consent-request-notice")).not.toBeInTheDocument();
  });

  it("klient bez wymogu: bez paska, nawet gdy nazwa zawiera PKO", async () => {
    mount();
    await settled();
    expect(screen.queryByTestId("consent-request-notice")).not.toBeInTheDocument();
  });

  it("zrzut już jest: bez paska", async () => {
    mocks.policy.mockResolvedValue({ data: { managed: true, effective_policy: { requires_rodo_consent_block: true } } });
    mocks.branded.mockResolvedValue({ data: { consent_attached: true } });
    mount();
    await settled();
    expect(screen.queryByTestId("consent-request-notice")).not.toBeInTheDocument();
  });

  it("awaria odczytu reguły: bez paska i bez błędu, pobranie blokuje serwer", async () => {
    mocks.policy.mockRejectedValue(new Error("500"));
    mocks.rule.mockRejectedValue(new Error("500"));
    mount();
    await settled();
    expect(screen.queryByTestId("consent-request-notice")).not.toBeInTheDocument();
  });
});
