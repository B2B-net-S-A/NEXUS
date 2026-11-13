import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PortalApiError, portalApi, type PortalTraining } from "@/lib/api/consultant-portal";

import { isCurrent, panelNavItems } from "../PanelNav";
import { TrainerScreen } from "../PanelScreens";
import { TrainingDetailView } from "../TrainingDetail";
import { TrainingsScreen, TrainingsView, defaultTab } from "../TrainingScreens";
import { PREVIEW_APPLICATION, PREVIEW_TRAININGS, previewTraining } from "../training-fixtures";
import { agendaProblem, agendaTotal, currentStep, feeSum, missingFees, moneyLabel, stageOf } from "../training-model";

const TODAY = "2026-11-13";
const LONG_DASH = "—";

function wrap(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{children}</QueryClientProvider>);
}

/** Zamówienie bez prezentacji i audio: pozycje C i D nie dotyczą. */
function onlyMaterials(status: PortalTraining["status"] = "ordered"): PortalTraining {
  const base = previewTraining(5, status);
  return {
    ...base,
    order: { ...base.order, deliverables: base.order.deliverables.filter((item) => item.key === "materials") },
  };
}

const plain = (text: string | null | undefined) => (text ?? "").replace(/\s/g, "");

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("reguły szkoleń", () => {
  const fees = previewTraining(1, "ordered").fees.items;

  it("suma liczy tylko pozycje z zamówienia", () => {
    const amounts = { fee_prep: "1000", fee_delivery: "500,50", fee_presentation: "300", fee_audio: "200", fee_rights: "100" };
    expect(feeSum(fees, amounts, ["materials", "presentation", "audio"])).toBeCloseTo(2100.5);
    expect(feeSum(fees, amounts, ["materials"])).toBeCloseTo(1600.5);
    expect(feeSum(fees, amounts, ["materials", "audio"])).toBeCloseTo(1800.5);
  });

  it("A, B i E są zawsze wymagane, C i D tylko z zamówionym plikiem", () => {
    expect(missingFees(fees, {}, ["materials"])).toEqual(["fee_prep", "fee_delivery", "fee_rights"]);
    expect(missingFees(fees, {}, ["presentation", "audio"])).toEqual([
      "fee_prep",
      "fee_delivery",
      "fee_presentation",
      "fee_audio",
      "fee_rights",
    ]);
    expect(missingFees(fees, { fee_prep: "abc" }, [])).toContain("fee_prep");
  });

  it("agenda: suma minut, 1–12 modułów, 5–600 minut", () => {
    expect(agendaTotal([{ title: "A", minutes: 35 }, { title: "B", minutes: 25 }, { title: "", minutes: 90 }])).toBe(60);
    expect(agendaProblem([{ title: "", minutes: null }])).toMatch(/przynajmniej jeden moduł/);
    expect(agendaProblem([{ title: "A", minutes: 4 }])).toMatch(/5–600/);
    expect(agendaProblem([{ title: "A", minutes: 601 }])).toMatch(/5–600/);
    expect(agendaProblem(Array.from({ length: 13 }, () => ({ title: "A", minutes: 10 })))).toMatch(/najwyżej 12/);
    expect(agendaProblem([{ title: "A", minutes: 5 }])).toBeNull();
  });

  it("pasek etapów idzie za stanem szkolenia", () => {
    expect(currentStep(previewTraining(1, "ordered"), TODAY)).toBe(1);
    expect(currentStep(previewTraining(1, "accepted"), TODAY)).toBe(2);
    const future = previewTraining(1, "signed");
    expect(currentStep({ ...future, order: { ...future.order, session_date: "2026-12-01" } }, TODAY)).toBe(3);
    expect(currentStep(future, TODAY)).toBe(4);
    expect(currentStep({ ...future, payment: { invoice_ready_at: "2026-11-12", paid_at: null } }, TODAY)).toBe(5);
  });

  it("pigułka etapu mówi, czy ruch jest po stronie trenera", () => {
    const row = PREVIEW_TRAININGS.mine[0];
    expect(stageOf({ ...row, status: "ordered" }, TODAY)).toMatchObject({ label: "Do wyceny", yours: true });
    expect(stageOf({ ...row, status: "quoted" }, TODAY).yours).toBe(false);
    expect(stageOf({ ...row, status: "signed", session_date: "2026-10-07" }, TODAY).label).toBe("Przekaż pliki");
    expect(stageOf({ ...row, status: "signed", invoice_ready_at: "2026-11-12" }, TODAY).label).toBe("Wystaw fakturę");
    expect(stageOf({ ...row, paid_at: "2026-11-20" }, TODAY).label).toBe("Zapłacone");
    expect(defaultTab(PREVIEW_TRAININGS, TODAY)).toBe("mine");
  });

  it("menu: Szkolenia zamiast Zostań trenerem, podświetlone też na szkoleniu", () => {
    const labels = panelNavItems({ menu: { start: false, equipment: false } }).map((item) => item.label);
    expect(labels).toContain("Szkolenia");
    expect(labels).not.toContain("Zostań trenerem");
    expect(isCurrent("/konsultant/szkolenia/7", "/konsultant/szkolenia")).toBe(true);
    expect(isCurrent("/konsultant/trener", "/konsultant/szkolenia")).toBe(true);
    expect(isCurrent("/konsultant/szkolenia", "/konsultant")).toBe(false);
  });
});

describe("wycena", () => {
  it("bez prezentacji i audio nie ma pól C i D, a suma rośnie na żywo", async () => {
    wrap(<TrainingDetailView training={onlyMaterials()} today={TODAY} />);
    expect(screen.queryByLabelText("C. Prezentacja")).toBeNull();
    expect(screen.queryByLabelText("D. Pliki audio")).toBeNull();
    expect(screen.getAllByText("nie dotyczy")).toHaveLength(2);
    await userEvent.type(screen.getByLabelText("A. Program i materiały"), "2400");
    await userEvent.type(screen.getByLabelText("B. Przeprowadzenie"), "1800");
    await userEvent.type(screen.getByLabelText("E. Prawa autorskie"), "500");
    expect(plain(screen.getByTestId("fee-sum").textContent)).toBe("4700zł");
  });

  it("z prezentacją i audio pokazuje C i D", () => {
    wrap(<TrainingDetailView training={previewTraining(5, "ordered")} today={TODAY} />);
    expect(screen.getByLabelText("C. Prezentacja")).toBeTruthy();
    expect(screen.getByLabelText("D. Pliki audio")).toBeTruthy();
  });

  it("agenda liczy minuty razem", async () => {
    wrap(<TrainingDetailView training={onlyMaterials()} today={TODAY} />);
    await userEvent.type(screen.getByLabelText("Moduł 1: temat"), "Wstęp");
    await userEvent.type(screen.getByLabelText("Moduł 1: minuty"), "35");
    await userEvent.click(screen.getByRole("button", { name: /Moduł/ }));
    await userEvent.type(screen.getByLabelText("Moduł 2: temat"), "Ćwiczenia");
    await userEvent.type(screen.getByLabelText("Moduł 2: minuty"), "145");
    expect(screen.getByTestId("agenda-total").textContent).toBe("Razem 180 min (3 h)");
  });

  it("wysyła C i D puste, gdy nie ma ich w zamówieniu", async () => {
    const save = vi
      .spyOn(portalApi, "saveQuote")
      .mockResolvedValue({ training: { ...onlyMaterials("quoted") } });
    wrap(<TrainingDetailView training={onlyMaterials()} today={TODAY} />);
    await userEvent.type(screen.getByLabelText("Moduł 1: temat"), "Wstęp");
    await userEvent.type(screen.getByLabelText("Moduł 1: minuty"), "60");
    await userEvent.type(screen.getByLabelText("A. Program i materiały"), "1000");
    await userEvent.type(screen.getByLabelText("B. Przeprowadzenie"), "800,5");
    await userEvent.click(screen.getByRole("button", { name: "Wyślij wycenę" }));
    expect(await screen.findByRole("alert")).toHaveProperty("textContent", "Wpisz kwotę: E. Prawa autorskie.");
    expect(save).not.toHaveBeenCalled();
    await userEvent.type(screen.getByLabelText("E. Prawa autorskie"), "200");
    await userEvent.click(screen.getByRole("button", { name: "Wyślij wycenę" }));
    await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    expect(save.mock.calls[0][1]).toMatchObject({
      agenda: [{ title: "Wstęp", minutes: 60 }],
      fee_prep: "1000.00",
      fee_delivery: "800.50",
      fee_presentation: null,
      fee_audio: null,
      fee_rights: "200.00",
    });
  });

  it("odesłana wycena pokazuje uwagę Talent Community", () => {
    wrap(<TrainingDetailView training={previewTraining(5, "returned")} today={TODAY} />);
    expect(screen.getByText(/Rozpisz proszę ćwiczenia/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Wyślij wycenę" })).toBeTruthy();
  });
});

describe("umowa i przekazanie", () => {
  it("umowa do podpisu: pobranie, wgranie i podpis kwalifikowany", () => {
    wrap(<TrainingDetailView training={previewTraining(2, "accepted")} today={TODAY} />);
    expect(screen.getByRole("button", { name: /Pobierz umowę/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Wgraj podpisany PDF/ })).toBeTruthy();
    expect(screen.getByText(/PAdES/)).toBeTruthy();
    expect(screen.getByText(/§ 17/)).toBeTruthy();
  });

  it("lista plików pokazuje stan każdej pozycji", () => {
    wrap(<TrainingDetailView training={previewTraining(1, "signed")} today={TODAY} />);
    const returned = screen.getByTestId("handover-materials");
    expect(within(returned).getByText("Do poprawy do 18.11.2026")).toBeTruthy();
    expect(within(returned).getByText(/W kluczu ćwiczenia 2/)).toBeTruthy();
    expect(within(returned).getByText(/3 dni robocze, § 11 ust. 4/)).toBeTruthy();
    expect(within(returned).getByRole("button", { name: "Wgraj nowy" })).toBeTruthy();
    const accepted = screen.getByTestId("handover-presentation");
    expect(within(accepted).getByText("Przyjęte")).toBeTruthy();
    expect(within(accepted).queryByRole("button")).toBeNull();
    const missing = screen.getByTestId("handover-audio");
    expect(within(missing).getByText("Do wgrania")).toBeTruthy();
    expect(within(missing).getByText(/\.drp/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Wgraj fakturę/ })).toBeNull();
  });

  it("projekt montażowy nie idzie na serwer", async () => {
    const upload = vi.spyOn(portalApi, "uploadDeliverable");
    wrap(<TrainingDetailView training={previewTraining(1, "signed")} today={TODAY} />);
    const input = within(screen.getByTestId("handover-audio")).getByLabelText("Wgraj");
    await userEvent.upload(input, new File(["x"], "podcast.drp"));
    expect(await screen.findByText(/plik projektu montażowego/)).toBeTruthy();
    expect(upload).not.toHaveBeenCalled();
  });

  it("faktura dopiero po przyjęciu wszystkich plików", () => {
    const base = previewTraining(1, "signed");
    wrap(
      <TrainingDetailView
        training={{ ...base, can_invoice: true, payment: { invoice_ready_at: "2026-11-12", paid_at: null } }}
        today={TODAY}
      />,
    );
    expect(screen.getByText("Możesz wystawić fakturę.")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Wgraj fakturę/ })).toBeTruthy();
  });
});

describe("zakładka Szkolenia", () => {
  it("nagranie: rozdziały z agendy i materiały do pobrania", () => {
    wrap(<TrainingsView data={PREVIEW_TRAININGS} today={TODAY} initialTab="recordings" initialRecording={21} />);
    expect(screen.getByText("01:40")).toBeTruthy();
    expect(screen.getByText("Ćwiczenia 2–3")).toBeTruthy();
    expect(screen.getAllByRole("button", { name: /Pobierz/ })).toHaveLength(3);
    expect(screen.getByRole("button", { name: /Słuchaj/ })).toBeTruthy();
  });

  it("na żywo: zapis i link dla zapisanych", async () => {
    const register = vi.spyOn(portalApi, "register").mockResolvedValue({ registered: true });
    vi.spyOn(portalApi, "trainings").mockResolvedValue(PREVIEW_TRAININGS);
    wrap(<TrainingsView data={PREVIEW_TRAININGS} today={TODAY} initialTab="live" />);
    expect(screen.getByRole("link", { name: /Dołącz/ }).getAttribute("href")).toBe("https://example.com/spotkanie");
    await userEvent.click(screen.getByRole("button", { name: "Zapisz się" }));
    await waitFor(() => expect(register).toHaveBeenCalledWith(2, true));
    expect(screen.getByRole("button", { name: "Wypisz się" })).toBeTruthy();
  });

  it("Prowadzę: lista z pigułkami etapów", () => {
    wrap(<TrainingsView data={PREVIEW_TRAININGS} today={TODAY} />);
    expect(screen.getByRole("tab", { name: /Prowadzę/ }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getByText("Umowa do podpisu")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Wyceń" }).getAttribute("href")).toBe("/konsultant/szkolenia/3");
  });

  it("bez zgłoszenia prowadzi do formularza trenera", () => {
    wrap(<TrainingsView data={{ ...PREVIEW_TRAININGS, mine: [], applied: false }} today={TODAY} initialTab="mine" />);
    expect(screen.getAllByRole("link", { name: "Zostań trenerem" })[0].getAttribute("href")).toBe("/konsultant/trener");
  });

  it("awaria nie wygląda jak pusta lista", async () => {
    vi.spyOn(portalApi, "trainings").mockRejectedValue(new PortalApiError(500, undefined));
    wrap(<TrainingsScreen />);
    expect(await screen.findByRole("alert", {}, { timeout: 8000 })).toBeTruthy();
    expect(screen.queryByText(/Gdy zamówimy u Ciebie szkolenie/)).toBeNull();
    expect(screen.queryByText(/Pierwsze nagrania/)).toBeNull();
  }, 12_000);
});

describe("zgłoszenie trenera", () => {
  it("bez formy i stawki za dzień, z propozycją szkolenia i próbką", async () => {
    vi.spyOn(portalApi, "trainer").mockResolvedValue({ application: null });
    wrap(<TrainerScreen />);
    expect(await screen.findByLabelText("Propozycja pierwszego szkolenia")).toBeTruthy();
    expect(screen.getByLabelText("Ile godzin na żywo")).toBeTruthy();
    expect(screen.getByLabelText("Dla kogo")).toBeTruthy();
    expect(screen.getByLabelText("Plik próbki")).toBeTruthy();
    expect(screen.queryByLabelText(/Stawka/)).toBeNull();
    expect(screen.queryByLabelText("Forma")).toBeNull();
    expect(screen.getByText("Dane do umowy szkoleniowej")).toBeTruthy();
  });

  it("wysyła zgłoszenie, a potem próbkę", async () => {
    vi.spyOn(portalApi, "trainer").mockResolvedValue({ application: null });
    const save = vi.spyOn(portalApi, "saveTrainer").mockResolvedValue({ application: PREVIEW_APPLICATION });
    const sample = vi.spyOn(portalApi, "trainerSample").mockResolvedValue({ application: PREVIEW_APPLICATION });
    wrap(<TrainerScreen />);
    await userEvent.click(await screen.findByRole("button", { name: "Python" }));
    await userEvent.type(screen.getByLabelText("Doświadczenie trenerskie"), "Pięć lat szkoleń");
    await userEvent.type(screen.getByLabelText("Ile godzin na żywo"), "3 h");
    await userEvent.upload(screen.getByLabelText("Plik próbki"), new File(["%PDF"], "program.pdf"));
    await userEvent.click(screen.getByRole("button", { name: /Wyślij zgłoszenie/ }));
    await waitFor(() => expect(sample).toHaveBeenCalledTimes(1));
    expect(save.mock.calls[0][0]).toEqual({
      topics: ["Python"],
      experience: "Pięć lat szkoleń",
      proposal_title: "",
      proposal_hours: "3 h",
      audience: "",
      availability: "",
      materials: "",
    });
    expect(save.mock.invocationCallOrder[0]).toBeLessThan(sample.mock.invocationCallOrder[0]);
  });

  it("po wysłaniu pokazuje, kto się zajmuje zgłoszeniem", async () => {
    vi.spyOn(portalApi, "trainer").mockResolvedValue({ application: PREVIEW_APPLICATION });
    wrap(<TrainerScreen />);
    expect(await screen.findByText("Po naszej stronie: Ewa Przykładowa")).toBeTruthy();
    expect(screen.getByText("program.pdf")).toBeTruthy();
  });
});

describe("teksty dla konsultanta", () => {
  it.each([
    ["wycena", () => <TrainingDetailView training={previewTraining(5, "ordered")} today={TODAY} />],
    ["umowa", () => <TrainingDetailView training={previewTraining(2, "accepted")} today={TODAY} />],
    ["umowa u nas", () => <TrainingDetailView training={previewTraining(2, "trainer_signed")} today={TODAY} />],
    ["przekazanie", () => <TrainingDetailView training={previewTraining(1, "signed")} today={TODAY} />],
    ["Prowadzę", () => <TrainingsView data={PREVIEW_TRAININGS} today={TODAY} initialTab="mine" />],
    ["Na żywo", () => <TrainingsView data={PREVIEW_TRAININGS} today={TODAY} initialTab="live" />],
    ["nagranie", () => <TrainingsView data={PREVIEW_TRAININGS} today={TODAY} initialTab="recordings" initialRecording={21} />],
    ["szkolenie bez dat", () => {
      const base = previewTraining(6, "ordered");
      return <TrainingDetailView training={{ ...base, order: { ...base.order, session_date: null, time_from: "", time_to: "", expected_participants: null } }} today={TODAY} />;
    }],
  ])("%s: bez długiej pauzy", (_name, view) => {
    const { container } = wrap(view());
    expect(container.textContent).not.toContain(LONG_DASH);
  });

  it("formularz i stan zgłoszenia bez długiej pauzy", async () => {
    vi.spyOn(portalApi, "trainer").mockResolvedValue({ application: null });
    const { container } = wrap(<TrainerScreen />);
    await screen.findByLabelText("Propozycja pierwszego szkolenia");
    expect(container.textContent).not.toContain(LONG_DASH);
    cleanup();
    vi.spyOn(portalApi, "trainer").mockResolvedValue({ application: PREVIEW_APPLICATION });
    const sent = wrap(<TrainerScreen />);
    await screen.findByText("Dziękujemy za zgłoszenie");
    expect(sent.container.textContent).not.toContain(LONG_DASH);
  });
});

describe("kwoty w panelu trenera", () => {
  it("grupują też cztery cyfry, jak ekran NEXUSA", () => {
    expect(moneyLabel("1600")).toBe("1 600 zł");
    expect(moneyLabel(500)).toBe("500 zł");
    expect(moneyLabel("12500.5")).toMatch(/^12\s500,5 zł$/);
    expect(moneyLabel(null)).toBe("");
  });
});
