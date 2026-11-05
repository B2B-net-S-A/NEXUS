import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getJob = vi.hoisted(() => vi.fn());
const getCandidate = vi.hoisted(() => vi.fn());
const sendEmail = vi.hoisted(() => vi.fn());
const listThreads = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({
  jobsApi: { get: getJob },
  candidatesApi: { get: getCandidate },
  microsoft365Api: { listCandidateThreads: listThreads },
}));
vi.mock("@/components/v2/modals/SendEmailV2", () => ({
  SendEmailV2: (props: Record<string, unknown>) => {
    sendEmail(props);
    return <div role="dialog" aria-label="Nowy email" />;
  },
}));

import { ConsentRequestButton } from "../ConsentRequestButton";

function renderButton(candidateName: string | undefined = "Anna Fikcyjna") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ConsentRequestButton candidateId={7} candidateName={candidateName} jobId={3} />
    </QueryClientProvider>,
  );
}

const PKO_JOB = { title: "Programista (ZOB-3109)", client_name: "Powszechna Kasa Oszczędności Bank Polski S.A", client_reference: "ZOB 3109" };

beforeEach(() => {
  vi.clearAllMocks();
  listThreads.mockResolvedValue({ data: { items: [] } });
});

describe("ConsentRequestButton", () => {
  it("otwiera okno maila z adresem kandydata i uzupełnioną zgodą", async () => {
    getJob.mockResolvedValue({ data: PKO_JOB });
    getCandidate.mockResolvedValue({ data: { email: "anna@example.com" } });
    renderButton();
    await userEvent.click(await screen.findByRole("button", { name: /Poproś kandydata o zgodę/ }));
    await screen.findByRole("dialog", { name: "Nowy email" });
    const props = sendEmail.mock.calls.at(-1)?.[0];
    expect(props.candidateEmail).toBe("anna@example.com");
    expect(props.defaultSubject).toBe("ZOB-3109 - zgoda na przetwarzanie danych osobowych");
    expect(props.defaultBody).toContain("Ja, Anna Fikcyjna,");
    expect(props.defaultBody).toContain("przekazanym przez B2B.net S.A.");
  });

  it("nie pokazuje tekstu PKO przy innym kliencie", async () => {
    getJob.mockResolvedValue({ data: { ...PKO_JOB, client_name: "Inny Bank" } });
    renderButton();
    await waitFor(() => expect(getJob).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByRole("button")).toBeNull());
  });

  it("bez numeru ZOB prosi o jego uzupełnienie", async () => {
    getJob.mockResolvedValue({ data: { title: "Programista", client_name: "PKO BP", client_reference: null } });
    renderButton();
    expect(await screen.findByText(/uzupełnij „Numer u klienta”/)).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("awaria odczytu rekrutacji mówi, co się stało", async () => {
    getJob.mockRejectedValue(new Error("boom"));
    renderButton();
    expect(await screen.findByRole("alert")).toHaveTextContent(/Nie udało się przygotować prośby o zgodę/);
  });

  it("awaria odczytu adresu nie otwiera okna z pustym adresem", async () => {
    getJob.mockResolvedValue({ data: PKO_JOB });
    getCandidate.mockRejectedValue(new Error("boom"));
    renderButton();
    await userEvent.click(await screen.findByRole("button", { name: /Poproś kandydata o zgodę/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Nie udało się wczytać adresu kandydata/);
    expect(sendEmail).not.toHaveBeenCalled();
  });

  const consentThread = (direction: string, from: string) => ({
    subject: "ZOB-3109 - zgoda na przetwarzanie danych osobowych",
    latest: { direction, from_address: from, sent_at: "2026-10-29T11:00:00Z", received_at: "2026-10-29T11:00:02Z" },
  });

  it("po wysłanej prośbie mówi o tym i proponuje ponowienie", async () => {
    getJob.mockResolvedValue({ data: PKO_JOB });
    getCandidate.mockResolvedValue({ data: { email: "anna@example.com" } });
    listThreads.mockResolvedValue({ data: { items: [consentThread("sent", "rekruter@example.com")] } });
    renderButton();
    expect(await screen.findByTestId("consent-request-status")).toHaveTextContent("Prośba wysłana 29.10");
    expect(screen.getByRole("button", { name: /Poproś ponownie/ })).toBeInTheDocument();
  });

  it("odpowiedź kandydata prosi o wgranie zrzutu", async () => {
    getJob.mockResolvedValue({ data: PKO_JOB });
    getCandidate.mockResolvedValue({ data: { email: "anna@example.com" } });
    listThreads.mockResolvedValue({ data: { items: [consentThread("received", "anna@example.com")] } });
    renderButton();
    await waitFor(() =>
      expect(screen.getByTestId("consent-request-status")).toHaveTextContent("Kandydat odpisał 29.10"),
    );
  });

  it("awaria listy maili nie zabiera przycisku", async () => {
    getJob.mockResolvedValue({ data: PKO_JOB });
    listThreads.mockRejectedValue(new Error("404"));
    renderButton();
    expect(await screen.findByRole("button", { name: /Poproś kandydata o zgodę/ })).toBeInTheDocument();
    expect(screen.queryByTestId("consent-request-status")).not.toBeInTheDocument();
  });

  it("nie czyta maili przy kliencie bez tego tekstu", async () => {
    getJob.mockResolvedValue({ data: { ...PKO_JOB, client_name: "Inny Bank" } });
    renderButton();
    await waitFor(() => expect(getJob).toHaveBeenCalled());
    await act(() => new Promise((resolve) => setTimeout(resolve, 20)));
    expect(listThreads).not.toHaveBeenCalled();
  });

  it("bez imienia z rodzica bierze je z profilu kandydata", async () => {
    getJob.mockResolvedValue({ data: PKO_JOB });
    getCandidate.mockResolvedValue({ data: { email: "anna@example.com", name: "Anna", lastname: "Fikcyjna" } });
    renderButton(undefined);
    await userEvent.click(await screen.findByRole("button", { name: /Poproś kandydata o zgodę/ }));
    await screen.findByRole("dialog", { name: "Nowy email" });
    expect(sendEmail.mock.calls.at(-1)?.[0].defaultBody).toContain("Ja, Anna Fikcyjna,");
  });
});
