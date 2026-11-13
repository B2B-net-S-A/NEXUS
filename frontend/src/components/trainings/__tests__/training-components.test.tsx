import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { FINANCE_ME, HANDOVER, PREVIOUS_FEES, PREVIOUS_ROW, QUOTED, TCM_ME } from "@/app/preview/trainings/fixtures";

import { HandoverReview } from "../HandoverReview";
import { DeliverablesFields } from "../OrderFields";
import { PublishPanel } from "../PublishPanel";
import { QuoteTable } from "../QuoteTable";
import { defaultDeliverables } from "../training-model";

afterEach(cleanup);

describe("PublishPanel", () => {
  it("przed zapłatą „Opublikuj” jest wyłączone z powodem", () => {
    render(<PublishPanel view={HANDOVER} me={TCM_ME} onPaid={vi.fn()} onPublish={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Opublikuj w bibliotece" })).toBeDisabled();
    expect(screen.getByTestId("publish-block")).toHaveTextContent("§ 8 ust. 3");
  });

  it("po zapłacie można opublikować", () => {
    const paid = {
      ...HANDOVER,
      payment: { invoice_ready_at: "2026-12-08T10:00:00Z", paid_at: "2026-12-20T10:00:00Z" },
      can_publish: true,
    };
    render(<PublishPanel view={paid} me={TCM_ME} onPaid={vi.fn()} onPublish={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Opublikuj w bibliotece" })).toBeEnabled();
    expect(screen.queryByTestId("publish-block")).toBeNull();
  });

  it("Finanse: „Zapłacone” czeka na przyjęcie plików, publikacji nie ma", () => {
    render(<PublishPanel view={HANDOVER} me={FINANCE_ME} onPaid={vi.fn()} onPublish={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Zapłacone" })).toBeDisabled();
    expect(screen.getByText(/po przyjęciu wszystkich plików/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Opublikuj w bibliotece" })).toBeNull();
  });

  it("Finanse oznaczają zapłatę, gdy pliki przyjęte", async () => {
    const onPaid = vi.fn().mockResolvedValue(true);
    const ready = { ...HANDOVER, payment: { invoice_ready_at: "2026-12-08T10:00:00Z", paid_at: null } };
    render(<PublishPanel view={ready} me={FINANCE_ME} onPaid={onPaid} onPublish={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Zapłacone" }));
    expect(onPaid).toHaveBeenCalledWith(true);
  });
});

describe("QuoteTable", () => {
  it("suma netto i kolumna poprzedniego szkolenia z różnicą", () => {
    render(<QuoteTable fees={QUOTED.fees!} previousFees={PREVIOUS_FEES} previous={PREVIOUS_ROW} />);
    expect(screen.getByText("Poprzednie szkolenie tego trenera")).toBeInTheDocument();
    const total = screen.getByTestId("quote-total");
    expect(total.textContent?.replace(/\s/g, " ")).toContain("4 100");
    expect(total.textContent?.replace(/\s/g, " ")).toContain("(−2 100)");
    const row = screen.getByText("D. Pliki audio").closest("tr")!;
    expect(within(row).getAllByRole("cell")[1]).toHaveTextContent("—");
    expect(within(row).getAllByRole("cell")[2]).toHaveTextContent("900");
  });

  it("bez poprzedniego szkolenia nie ma kolumny porównania", () => {
    render(<QuoteTable fees={QUOTED.fees!} />);
    expect(screen.queryByText("Poprzednie szkolenie tego trenera")).toBeNull();
  });
});

describe("HandoverReview", () => {
  it("stany pozycji i akcje: zwrócony z uwagą i terminem, nowy do przyjęcia", () => {
    render(
      <HandoverReview items={HANDOVER.handover} canManage onDownload={vi.fn()} onReview={vi.fn()} />,
    );
    const materials = screen.getByTestId("handover-materials");
    expect(within(materials).getByText("Zwrócone do poprawy")).toBeInTheDocument();
    expect(within(materials).getByText(/poprawa do 10\.12\.2026/)).toBeInTheDocument();
    expect(within(materials).queryByRole("button", { name: "Zwróć do poprawy" })).toBeNull();
    const presentation = screen.getByTestId("handover-presentation");
    expect(within(presentation).getByText("Do sprawdzenia")).toBeInTheDocument();
    expect(within(presentation).getByRole("button", { name: "Przyjmij" })).toBeInTheDocument();
    expect(within(presentation).getByRole("button", { name: "Zwróć do poprawy" })).toBeInTheDocument();
  });

  it("przyjęcie wysyła decyzję bez uwagi", async () => {
    const onReview = vi.fn().mockResolvedValue(true);
    render(<HandoverReview items={HANDOVER.handover} canManage onDownload={vi.fn()} onReview={onReview} />);
    await userEvent.click(
      within(screen.getByTestId("handover-presentation")).getByRole("button", { name: "Przyjmij" }),
    );
    expect(onReview).toHaveBeenCalledWith({ fileId: 7002, accept: true, note: "" });
  });

  it("zwrot pyta o uwagę w oknie potwierdzenia", async () => {
    const onReview = vi.fn().mockResolvedValue(true);
    render(<HandoverReview items={HANDOVER.handover} canManage onDownload={vi.fn()} onReview={onReview} />);
    await userEvent.click(
      within(screen.getByTestId("handover-presentation")).getByRole("button", { name: "Zwróć do poprawy" }),
    );
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByRole("textbox"), "Brakuje slajdu z agendą");
    await userEvent.click(within(dialog).getByRole("button", { name: "Zwróć do poprawy" }));
    expect(onReview).toHaveBeenCalledWith({ fileId: 7002, accept: false, note: "Brakuje slajdu z agendą" });
  });

  it("bez prowadzenia szkoleń nie ma przycisków decyzji", () => {
    render(
      <HandoverReview items={HANDOVER.handover} canManage={false} onDownload={vi.fn()} onReview={vi.fn()} />,
    );
    expect(screen.queryByRole("button", { name: "Przyjmij" })).toBeNull();
  });
});

describe("DeliverablesFields", () => {
  it("domyślne formaty i terminy, odznaczone pola wyłączone", () => {
    render(<DeliverablesFields value={defaultDeliverables()} onChange={vi.fn()} />);
    expect(screen.getByLabelText("Format: Prezentacja")).toHaveValue("PPTX do edycji i PDF dla uczestników");
    expect(screen.getByLabelText("Termin w dniach po szkoleniu: Materiały dla uczestników")).toHaveValue(2);
    expect(screen.getByLabelText("Format: Pliki audio")).toBeDisabled();
  });

  it("zaznaczenie audio przekazuje zmianę", async () => {
    const onChange = vi.fn();
    render(<DeliverablesFields value={defaultDeliverables()} onChange={onChange} />);
    await userEvent.click(screen.getByRole("checkbox", { name: "Pliki audio" }));
    const next = onChange.mock.calls[0][0] as ReturnType<typeof defaultDeliverables>;
    expect(next.find((d) => d.key === "audio")?.checked).toBe(true);
  });
});

describe("TrainingCard i TrainingLibrary", () => {
  it("wycena do decyzji: kroki, porównanie i trzy decyzje TCM", async () => {
    const { TrainingCard } = await import("../TrainingCard");
    const actions = new Proxy({}, { get: () => vi.fn().mockResolvedValue(true) });
    render(
      <TrainingCard
        view={QUOTED}
        me={TCM_ME}
        today="2026-11-13"
        previous={{ row: PREVIOUS_ROW, fees: PREVIOUS_FEES }}
        actions={actions as never}
      />,
    );
    expect(screen.getByText("Wycena", { selector: "[aria-current='step']" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Akceptuję, przygotuj umowę" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Odeślij z uwagą" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Anuluj szkolenie" })).toBeInTheDocument();
    expect(screen.queryByText("Przekazanie plików", { selector: "h2" })).toBeNull();
  });

  it("biblioteka: zapis na żywo i lista nagrań", async () => {
    const { TrainingLibrary } = await import("../TrainingLibrary");
    const { LIBRARY } = await import("@/app/preview/trainings/fixtures");
    const onRegister = vi.fn().mockResolvedValue(true);
    render(
      <TrainingLibrary
        library={LIBRARY}
        onRegister={onRegister}
        getMediaUrl={() => new Promise(() => undefined)}
        onDownload={vi.fn()}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Zapisz się" }));
    expect(onRegister).toHaveBeenCalledWith(902, true);
    expect(screen.getByRole("link", { name: "Dołącz" })).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.getByRole("heading", { name: "Cyberbezpieczeństwo w pracy z AI" })).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Szukaj w nagraniach i materiałach"), "dora");
    expect(screen.getByRole("heading", { name: "DORA w praktyce projektu" })).toBeInTheDocument();
  });
});
