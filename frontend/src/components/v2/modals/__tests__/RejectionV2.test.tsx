/**
 * Mail odrzucenia jest OPT-IN od 17.09.2026: checkbox domyślnie odznaczony,
 * a okno zawsze wysyła jawny boolean — serwer planuje wysyłkę wyłącznie
 * przy `true`.
 */

import type * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { mockPost } = vi.hoisted(() => ({ mockPost: vi.fn() }));
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  default: { post: mockPost },
}));

import { RejectionV2 } from "@/components/v2/modals/RejectionV2";
import type { RejectionReasonDef } from "@/lib/api";
import { mapRejectionReasons, rejectionReasonLabel } from "@/lib/rejection-reasons";

const reasons = [
  { id: "7", label: "Za wysoka stawka", applies_to: ["rejected" as const] },
];

/** Okno ma podgląd maila na react-query (13.10.2026) — klient w każdym teście. */
function renderUi(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(ui, {
    wrapper: ({ children }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  });
}

function renderRejection(onConfirm = vi.fn()) {
  renderUi(
    <RejectionV2
      open
      onOpenChange={() => {}}
      terminalType="rejected"
      reasons={reasons}
      previousStageCategory="external"
      previousStage="cv_sent"
      onConfirm={onConfirm}
    />,
  );
  return onConfirm;
}

describe("RejectionV2 — mail odrzucenia opt-in", () => {
  it("checkbox maila jest domyślnie odznaczony i wysyłamy jawne false", () => {
    const onConfirm = renderRejection();
    const checkbox = screen.getByRole("checkbox");
    expect(checkbox).not.toBeChecked();

    fireEvent.click(screen.getByText("Za wysoka stawka"));
    fireEvent.click(screen.getByRole("button", { name: "Potwierdź" }));

    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onConfirm.mock.calls[0][2]).toBe(false);
  });

  it("zaznaczony checkbox wysyła true", () => {
    const onConfirm = renderRejection();
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByText("Za wysoka stawka"));
    fireEvent.click(screen.getByRole("button", { name: "Potwierdź" }));

    expect(onConfirm.mock.calls[0][2]).toBe(true);
  });
});

describe("RejectionV2 — dostępność maila z reguły serwera (runda 9)", () => {
  it("`emailAvailable` wygrywa z kategorią kolumny", () => {
    renderUi(
      <RejectionV2
        open
        onOpenChange={() => {}}
        terminalType="rejected"
        reasons={reasons}
        previousStageCategory="internal"
        previousStage="cv_sent"
        emailAvailable
        onConfirm={vi.fn()}
      />,
    );
    expect(screen.getByRole("checkbox")).toBeInTheDocument();
  });

  it("bez możliwości maila checkboxa nie ma, nawet przy kategorii external", () => {
    renderUi(
      <RejectionV2
        open
        onOpenChange={() => {}}
        terminalType="rejected"
        reasons={reasons}
        previousStageCategory="external"
        previousStage="screening"
        emailAvailable={false}
        onConfirm={vi.fn()}
      />,
    );
    expect(screen.queryByRole("checkbox")).toBeNull();
  });
});

describe("RejectionV2 — kto zakończył proces (Pipeline v4)", () => {
  it("domyślnie „Odrzucamy my”, wybór klienta idzie w ostatnim argumencie", () => {
    const onConfirm = renderRejection();
    // Bez uprawnień DL opcji „Odrzuca Delivery Lead" nie ma.
    expect(screen.queryByText("Odrzuca Delivery Lead")).toBeNull();
    fireEvent.click(screen.getByText("Odrzuca klient"));
    fireEvent.click(screen.getByText("Za wysoka stawka"));
    fireEvent.click(screen.getByRole("button", { name: "Potwierdź" }));
    expect(onConfirm.mock.calls[0][5]).toBe("client");
  });

  it("upuszczenie na „Odrzucony przez DL” wstępnie wybiera DL; rezygnacja to zawsze kandydat", () => {
    const onConfirm = vi.fn();
    const { rerender } = renderUi(
      <RejectionV2
        open
        onOpenChange={() => {}}
        terminalType="rejected"
        reasons={reasons}
        onConfirm={onConfirm}
        initialEndedBy="delivery_lead"
        canEndAsDeliveryLead
      />,
    );
    fireEvent.click(screen.getByText("Za wysoka stawka"));
    fireEvent.click(screen.getByRole("button", { name: "Potwierdź" }));
    expect(onConfirm.mock.calls[0][5]).toBe("delivery_lead");

    rerender(
      <RejectionV2
        open
        onOpenChange={() => {}}
        terminalType="withdrawn"
        reasons={[{ id: "9", label: "Lepsza oferta", applies_to: ["withdrawn"] }]}
        onConfirm={onConfirm}
      />,
    );
    expect(screen.queryByText("Kto kończy?")).toBeNull();
    fireEvent.click(screen.getByText("Lepsza oferta"));
    fireEvent.click(screen.getByRole("button", { name: "Potwierdź" }));
    expect(onConfirm.mock.calls[1][5]).toBe("candidate");
  });
});

describe("RejectionV2 — powody po polsku (test na produkcji 23.09.2026)", () => {
  // Kształt odpowiedzi `GET /api/pipeline-templates/{id}`: `name` jest kluczem
  // danych (kody z migracji 0068, „Inne (…)" z 0006), `label` liczy backend.
  const SEEDED: [string, string, "rejected" | "withdrawn"][] = [
    ["counter_offer", "Kontroferta od obecnego pracodawcy", "withdrawn"],
    ["personal_reasons", "Powody osobiste", "withdrawn"],
    ["lost_interest", "Stracił zainteresowanie", "withdrawn"],
    ["accepted_other_offer", "Przyjął inną ofertę", "withdrawn"],
    ["salary_mismatch", "Rozbieżność oczekiwań finansowych", "withdrawn"],
    ["process_too_long", "Za długi proces", "withdrawn"],
    ["Inne (withdrawn)", "Inne", "withdrawn"],
    ["Inne (rejected)", "Inne", "rejected"],
  ];
  const rows: RejectionReasonDef[] = SEEDED.map(([name, label, category], i) => ({
    id: i + 1,
    template_id: 1,
    stage_def_id: null,
    name,
    label,
    order: 0,
    category,
    active: true,
    disqualifies_person: false,
    created_at: "2026-09-23T00:00:00Z",
    updated_at: "2026-09-23T00:00:00Z",
  }));

  it("okno „Kandydat zrezygnował” pokazuje etykiety, nigdy surowe kody", () => {
    renderUi(
      <RejectionV2
        open
        onOpenChange={() => {}}
        terminalType="withdrawn"
        reasons={mapRejectionReasons(rows)}
        onConfirm={vi.fn()}
      />,
    );
    expect(screen.getByText("Kandydat zrezygnował")).toBeInTheDocument();
    for (const [name, label, category] of SEEDED) {
      if (category !== "withdrawn") continue;
      expect(screen.getByText(label)).toBeInTheDocument();
      expect(screen.queryByText(name)).toBeNull();
    }
  });

  it("odpowiedź bez `label` (stary mock) spada na `name`", () => {
    expect(rejectionReasonLabel({ name: "Brak doświadczenia" })).toBe("Brak doświadczenia");
    expect(rejectionReasonLabel({ name: "counter_offer", label: "  " })).toBe("counter_offer");
  });
});

describe("RejectionV2 — notatka startowa", () => {
  function renderWithNotes(initialNotes: string | null, open = true) {
    const onConfirm = vi.fn();
    const view = renderUi(
      <RejectionV2
        open={open}
        onOpenChange={() => {}}
        terminalType="rejected"
        reasons={reasons}
        onConfirm={onConfirm}
        initialNotes={initialNotes}
      />,
    );
    return { onConfirm, ...view };
  }

  it("wstawia notatkę przy otwarciu i wysyła ją z odrzuceniem", () => {
    const { onConfirm } = renderWithNotes("Odpada, gdy: brak Javy");
    const notes = screen.getByRole("textbox");
    expect(notes).toHaveValue("Odpada, gdy: brak Javy");

    fireEvent.click(screen.getByText("Za wysoka stawka"));
    fireEvent.click(screen.getByRole("button", { name: "Potwierdź" }));
    expect(onConfirm.mock.calls[0][1]).toBe("Odpada, gdy: brak Javy");
  });

  it("zmiana propa przy otwartym oknie nie nadpisuje tego, co ktoś wpisał", () => {
    const onConfirm = vi.fn();
    const props = {
      open: true,
      onOpenChange: () => {},
      terminalType: "rejected" as const,
      reasons,
      onConfirm,
    };
    const { rerender } = renderUi(<RejectionV2 {...props} initialNotes="Pierwsza" />);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "Moja notatka" } });
    rerender(<RejectionV2 {...props} initialNotes="Druga" />);
    expect(screen.getByRole("textbox")).toHaveValue("Moja notatka");
  });

  it("bez notatki startowej pole jest puste", () => {
    renderWithNotes(null);
    expect(screen.getByRole("textbox")).toHaveValue("");
  });
});

describe("RejectionV2 — umowa z Generatora (04.10.2026)", () => {
  const unsigned = {
    id: 55,
    number: "1601/2026",
    contract_status: "in_progress",
    signature_status: "unsigned",
    created_at: "2026-10-01T10:00:00Z",
    signed_at: null,
    signature_requested_at: null,
    contract_id: null,
  };

  function renderWith(agreement: typeof unsigned | Record<string, unknown>) {
    const onConfirm = vi.fn();
    renderUi(
      <RejectionV2
        open
        onOpenChange={() => {}}
        terminalType="withdrawn"
        reasons={[{ id: "8", label: "Inna oferta", applies_to: ["withdrawn"] }]}
        onConfirm={onConfirm}
        agreement={agreement as never}
      />,
    );
    return onConfirm;
  }

  it("niepodpisaną umowę domyślnie anulujemy", () => {
    const onConfirm = renderWith(unsigned);
    expect(screen.getByRole("checkbox", { name: /Anuluj umowę 1601\/2026/ })).toBeChecked();
    fireEvent.click(screen.getByText("Inna oferta"));
    fireEvent.click(screen.getByRole("button", { name: "Potwierdź" }));
    expect(onConfirm.mock.calls[0][6]).toBe(55);
  });

  it("odznaczone — umowa zostaje", () => {
    const onConfirm = renderWith(unsigned);
    fireEvent.click(screen.getByRole("checkbox", { name: /Anuluj umowę 1601\/2026/ }));
    fireEvent.click(screen.getByText("Inna oferta"));
    fireEvent.click(screen.getByRole("button", { name: "Potwierdź" }));
    expect(onConfirm.mock.calls[0][6]).toBeNull();
  });

  it("podpisana z kontraktem → zdanie i link do zakończenia współpracy, bez checkboxa", () => {
    renderWith({ ...unsigned, signature_status: "signed_both", contract_status: "active", contract_id: 812 });
    expect(screen.queryByRole("checkbox", { name: /Anuluj umowę/ })).toBeNull();
    expect(screen.getByRole("link", { name: "zakończ ją w kontrakcie" }).getAttribute("href")).toBe(
      "/contracts/812",
    );
  });
});


// 13.10.2026: okno mówi, kogo zamykasz, a z panelu osoby — kto będzie następny.
describe("RejectionV2 — kogo zamykasz i kto dalej", () => {
  function renderWith(extra: Partial<React.ComponentProps<typeof RejectionV2>>) {
    renderUi(
      <RejectionV2
        open
        onOpenChange={() => {}}
        terminalType="rejected"
        reasons={reasons}
        previousStageCategory="internal"
        previousStage="new"
        onConfirm={vi.fn()}
        {...extra}
      />,
    );
  }

  it("pokazuje osobę z kolumną i następną osobę z panelu", () => {
    renderWith({
      subject: { name: "Michał Zieliński", stageLabel: "Nowi" },
      nextPerson: { name: "Anna Wiśniewska", stageLabel: "Nowi" },
    });
    expect(screen.getByText("Michał Zieliński · Nowi")).toBeInTheDocument();
    expect(screen.getByText("Dalej: Anna Wiśniewska · Nowi")).toBeInTheDocument();
  });

  it("`nextPerson: null` zapowiada zamknięcie panelu po ostatniej osobie", () => {
    renderWith({ subject: { name: "Tomasz Wójcik" }, nextPerson: null });
    expect(screen.getByText("Tomasz Wójcik")).toBeInTheDocument();
    expect(
      screen.getByText("To ostatnia osoba w kolejce — panel się zamknie."),
    ).toBeInTheDocument();
  });

  it("bez propów (np. kilka osób, przeciągnięcie karty) nie ma żadnej z tych linii", () => {
    renderWith({});
    expect(screen.queryByText(/^Dalej:/)).toBeNull();
    expect(screen.queryByText(/To ostatnia osoba/)).toBeNull();
    expect(screen.queryByTestId("rejection-champion-notice")).toBeNull();
  });

  it("odrzucany champion: złota linia zaraz pod osobą mówi, co stanie się z rekrutacją (D7)", () => {
    const notice =
      "Karol jest ostatnim championem. Po odrzuceniu rekrutacja wróci do „Szukamy”, a P1 zacznie działać.";
    renderWith({
      subject: { name: "Karol Wzorcowy", stageLabel: "Rozmowa u klienta" },
      championNotice: notice,
    });
    const line = screen.getByTestId("rejection-champion-notice");
    expect(line).toHaveTextContent(notice);
    expect(line.className).toContain("bg-medal-gold");
    // Kolejność: osoba, potem linia championa.
    const subject = screen.getByText("Karol Wzorcowy · Rozmowa u klienta");
    expect(subject.compareDocumentPosition(line) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});

describe("RejectionV2 — podgląd maila odrzucenia (13.10.2026)", () => {
  const DEFAULT_BODY =
    "Cześć Anna,\n\ndziękujemy za udział w rekrutacji na stanowisko Senior Dev. " +
    "Niestety został wybrany inny kandydat.\n\n" +
    "Życzymy powodzenia i zachęcamy do udziału w przyszłych procesach rekrutacyjnych!";
  const ONE = { jobId: 3, people: [{ candidateId: 5, name: "Anna Przykładowa" }] };

  beforeEach(() => {
    mockPost.mockReset();
  });

  function previewResponse(
    people: { candidate_id: number; to_email: string | null; skip_reason: string | null }[],
    withText = true,
  ) {
    return {
      data: {
        subject: withText ? "Informacja zwrotna — Senior Dev" : null,
        body: withText ? DEFAULT_BODY : null,
        people,
      },
    };
  }

  function renderWithPreview(
    emailPreview: { jobId: number; people: { candidateId: number; name: string }[] },
  ) {
    const onConfirm = vi.fn();
    renderUi(
      <RejectionV2
        open
        onOpenChange={() => {}}
        terminalType="rejected"
        reasons={reasons}
        emailAvailable
        emailPreview={emailPreview}
        onConfirm={onConfirm}
      />,
    );
    return onConfirm;
  }

  it("pokazuje adresata i treść domyślną; poprawka idzie w 8. argumencie", async () => {
    mockPost.mockResolvedValue(
      previewResponse([{ candidate_id: 5, to_email: "anna@example.com", skip_reason: null }]),
    );
    const onConfirm = renderWithPreview(ONE);
    fireEvent.click(screen.getByRole("checkbox"));
    const body = (await screen.findByLabelText("Treść")) as HTMLTextAreaElement;
    expect(mockPost).toHaveBeenCalledWith("/api/rejection-emails/preview", {
      job_id: 3,
      candidate_ids: [5],
    });
    expect(body.value).toBe(DEFAULT_BODY);
    expect(screen.getByText("anna@example.com")).toBeInTheDocument();
    expect(screen.getByLabelText("Temat")).toHaveValue("Informacja zwrotna — Senior Dev");
    expect(screen.getByText(/podpis z Outlooka/)).toBeInTheDocument();

    fireEvent.change(body, { target: { value: "Cześć Anna,\n\nKlient wstrzymał projekt." } });
    expect(screen.getByText("Zmieniona ręcznie")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Za wysoka stawka"));
    fireEvent.click(screen.getByRole("button", { name: "Potwierdź" }));

    expect(onConfirm.mock.calls[0][2]).toBe(true);
    expect(onConfirm.mock.calls[0][7]).toEqual({
      subject: "Informacja zwrotna — Senior Dev",
      body: "Cześć Anna,\n\nKlient wstrzymał projekt.",
    });
  });

  it("bez poprawek wysyłamy treść domyślną (null), „Przywróć” cofa zmianę", async () => {
    mockPost.mockResolvedValue(
      previewResponse([{ candidate_id: 5, to_email: "anna@example.com", skip_reason: null }]),
    );
    const onConfirm = renderWithPreview(ONE);
    fireEvent.click(screen.getByRole("checkbox"));
    const subject = await screen.findByLabelText("Temat");
    fireEvent.change(subject, { target: { value: "Inny temat" } });
    fireEvent.click(screen.getByRole("button", { name: "Przywróć treść domyślną" }));
    expect(subject).toHaveValue("Informacja zwrotna — Senior Dev");
    expect(screen.queryByText("Zmieniona ręcznie")).toBeNull();

    fireEvent.click(screen.getByText("Za wysoka stawka"));
    fireEvent.click(screen.getByRole("button", { name: "Potwierdź" }));
    expect(onConfirm.mock.calls[0][2]).toBe(true);
    expect(onConfirm.mock.calls[0][7]).toBeNull();
  });

  it("pusta treść blokuje „Potwierdź” i mówi dlaczego", async () => {
    mockPost.mockResolvedValue(
      previewResponse([{ candidate_id: 5, to_email: "anna@example.com", skip_reason: null }]),
    );
    renderWithPreview(ONE);
    fireEvent.click(screen.getByText("Za wysoka stawka"));
    fireEvent.click(screen.getByRole("checkbox"));
    const body = await screen.findByLabelText("Treść");
    fireEvent.change(body, { target: { value: "   " } });
    expect(screen.getByText(/Treść maila nie może być pusta/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Potwierdź" })).toBeDisabled();
  });

  it("brak skrzynki: powód widać od razu, checkbox wyłączony, mail nie wychodzi", async () => {
    mockPost.mockResolvedValue(
      previewResponse(
        [{ candidate_id: 5, to_email: "anna@example.com", skip_reason: "no_mailbox" }],
        false,
      ),
    );
    const onConfirm = renderWithPreview(ONE);
    expect(
      await screen.findByText(/nie masz podłączonej skrzynki Microsoft 365/),
    ).toBeInTheDocument();
    expect(screen.getByRole("checkbox")).toBeDisabled();
    fireEvent.click(screen.getByText("Za wysoka stawka"));
    fireEvent.click(screen.getByRole("button", { name: "Potwierdź" }));
    expect(onConfirm.mock.calls[0][2]).toBe(false);
  });

  it("kilka osób: podgląd tylko do odczytu i lista, kto dostanie mail", async () => {
    mockPost.mockResolvedValue(
      previewResponse([
        { candidate_id: 5, to_email: "anna@example.com", skip_reason: null },
        { candidate_id: 6, to_email: "jan@example.com", skip_reason: "not_client_visible" },
      ]),
    );
    const onConfirm = renderWithPreview({
      jobId: 3,
      people: [
        { candidateId: 5, name: "Anna Przykładowa" },
        { candidateId: 6, name: "Jan Testowy" },
      ],
    });
    fireEvent.click(screen.getByRole("checkbox"));
    expect(await screen.findByText("tylko do odczytu")).toBeInTheDocument();
    expect(screen.getByText("Podgląd maila · Anna Przykładowa")).toBeInTheDocument();
    expect(screen.getByText("Mail wyjdzie do 1 z 2 osób")).toBeInTheDocument();
    expect(screen.getByText("bez maila: przed weryfikacją")).toBeInTheDocument();
    expect(screen.queryByLabelText("Treść")).toBeNull();

    fireEvent.click(screen.getByText("Za wysoka stawka"));
    fireEvent.click(screen.getByRole("button", { name: "Potwierdź" }));
    expect(onConfirm.mock.calls[0][2]).toBe(true);
    expect(onConfirm.mock.calls[0][7]).toBeNull();
  });

  // 17.10.2026 (D2): osoba w innych rekrutacjach — dopisek zamiast zakończenia.
  const MAIN =
    "Cześć Anna,\n\ndziękujemy za rozmowę i czas poświęcony na rekrutację na stanowisko " +
    "Senior Dev. Po przeanalizowaniu wymagań projektu zdecydowaliśmy, że w tym procesie " +
    "nie przedstawimy Twojej kandydatury.";
  const CLOSING =
    "Życzymy powodzenia i zachęcamy do udziału w przyszłych procesach rekrutacyjnych!";
  const OTHERS_TEXT =
    "To dotyczy tylko tej rekrutacji — nadal bierzesz udział w naszym pozostałym procesie:\n" +
    "• Java Tech Lead\n\nOdezwiemy się, gdy będziemy mieć w nim nowe informacje.";

  function withOthersResponse() {
    return {
      data: {
        subject: "Informacja zwrotna — Senior Dev",
        body: MAIN,
        closing: CLOSING,
        other_processes_text: OTHERS_TEXT,
        text_kind: "before_client",
        title_warning: false,
        people: [
          {
            candidate_id: 5,
            to_email: "anna@example.com",
            skip_reason: null,
            text_kind: "before_client",
            other_processes: [
              { job_id: 8, title: "Java TL", mail_title: "Java Tech Lead", column: "client_interview" },
            ],
          },
        ],
      },
    };
  }

  it("osoba w innej rekrutacji: dopisek obok pola, odznaczenie wraca do zakończenia", async () => {
    mockPost.mockResolvedValue(withOthersResponse());
    const onConfirm = renderWithPreview(ONE);
    fireEvent.click(screen.getByRole("checkbox"));
    const body = (await screen.findByLabelText("Treść")) as HTMLTextAreaElement;
    expect(body.value).toBe(MAIN);
    expect(screen.getByText("Treść: przed klientem")).toBeInTheDocument();
    expect(screen.getByTestId("rejection-email-other-processes")).toHaveTextContent(
      "nadal bierzesz udział w naszym pozostałym procesie",
    );
    expect(screen.getByText("Java TL · Rozmowa u klienta")).toBeInTheDocument();

    // Bez zmian: domyślnie dopisek, nic nie idzie w 8. argumencie.
    fireEvent.click(screen.getByText("Za wysoka stawka"));
    fireEvent.click(screen.getByRole("button", { name: "Potwierdź" }));
    expect(onConfirm.mock.calls[0][2]).toBe(true);
    expect(onConfirm.mock.calls[0][7]).toBeNull();

    // Odznaczony dopisek: nietknięte pole dostaje zakończenie, serwer — `false`.
    fireEvent.click(screen.getByRole("checkbox", { name: /Dopisz pozostałe rekrutacje tej osoby/ }));
    expect(body.value).toBe(`${MAIN}\n\n${CLOSING}`);
    expect(screen.queryByTestId("rejection-email-other-processes")).toBeNull();
    expect(screen.queryByText("Zmieniona ręcznie")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Potwierdź" }));
    expect(onConfirm.mock.calls[1][7]).toEqual({ otherProcesses: false });
  });

  it("brak skrzynki: „Podłącz skrzynkę” otwiera Ustawienia w nowej karcie", async () => {
    mockPost.mockResolvedValue(
      previewResponse(
        [{ candidate_id: 5, to_email: "anna@example.com", skip_reason: "no_mailbox" }],
        false,
      ),
    );
    renderWithPreview(ONE);
    const link = await screen.findByRole("link", { name: /Podłącz skrzynkę/ });
    expect(link).toHaveAttribute("href", "/settings?tab=integracje");
    expect(link).toHaveAttribute("target", "_blank");
  });

  it("kilka osób z różnych etapów: dwie treści do przełączenia i „+N w toku”", async () => {
    mockPost.mockResolvedValue({
      data: {
        subject: "Informacja zwrotna — Senior Dev",
        body: MAIN,
        closing: CLOSING,
        text_kind: "before_client",
        people: [
          {
            candidate_id: 5,
            to_email: "anna@example.com",
            skip_reason: null,
            text_kind: "before_client",
            other_processes: [
              { job_id: 8, title: "Java TL", mail_title: "Java Tech Lead", column: "client_interview" },
              { job_id: 9, title: "Kotlin", mail_title: null, column: "verified" },
            ],
          },
          {
            candidate_id: 6,
            to_email: "jan@example.com",
            skip_reason: null,
            text_kind: "after_client",
            other_processes: [],
          },
          { candidate_id: 7, to_email: null, skip_reason: "not_client_visible", text_kind: null },
        ],
        samples: [
          {
            text_kind: "before_client",
            candidate_id: 5,
            subject: "Informacja zwrotna — Senior Dev",
            body: MAIN,
            closing: CLOSING,
            other_processes_text: OTHERS_TEXT,
          },
          {
            text_kind: "after_client",
            candidate_id: 6,
            subject: "Informacja zwrotna — Senior Dev",
            body: "Cześć Jan,\n\nNiestety został wybrany inny kandydat.",
            closing: CLOSING,
            other_processes_text: null,
          },
        ],
      },
    });
    renderWithPreview({
      jobId: 3,
      people: [
        { candidateId: 5, name: "Anna Przykładowa" },
        { candidateId: 6, name: "Jan Testowy" },
        { candidateId: 7, name: "Piotr Próbny" },
      ],
    });
    fireEvent.click(screen.getByRole("checkbox"));
    const before = await screen.findByRole("tab", { name: "Przed klientem (1)" });
    expect(before).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText(/w tym procesie nie przedstawimy/)).toBeInTheDocument();
    expect(screen.getByText("· +2 w toku")).toBeInTheDocument();
    expect(screen.getByText(/1 osoba dostanie zamiast ostatniego zdania dopisek/)).toBeInTheDocument();
    expect(screen.getByText("bez maila: przed weryfikacją")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Po kliencie (1)" }));
    expect(screen.getByText(/Niestety został wybrany inny kandydat/)).toBeInTheDocument();
  });

  it("awaria podglądu nie blokuje wysyłki z treścią domyślną", async () => {
    mockPost.mockRejectedValue(new Error("Network Error"));
    const onConfirm = renderWithPreview(ONE);
    fireEvent.click(screen.getByRole("checkbox"));
    expect(await screen.findByText(/Mail wyjdzie z treścią domyślną/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("Za wysoka stawka"));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Potwierdź" })).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Potwierdź" }));
    expect(onConfirm.mock.calls[0][2]).toBe(true);
    expect(onConfirm.mock.calls[0][7]).toBeNull();
  });
});

// Audyt 13.10.2026: w formularzu screeningu „Potwierdź” dawało się kliknąć
// drugi raz w trakcie zapisu — drugi ruch szedł już przy następnej osobie.
describe("RejectionV2 — zapis w toku", () => {
  it("„Potwierdź” jest zablokowany, dopóki trwa zapis, i drugi klik nic nie wysyła", () => {
    const onConfirm = vi.fn();
    renderUi(
      <RejectionV2
        open
        onOpenChange={() => {}}
        terminalType="rejected"
        reasons={reasons}
        previousStageCategory="internal"
        onConfirm={onConfirm}
        pending
      />,
    );
    fireEvent.click(screen.getByText("Za wysoka stawka"));
    const confirm = screen.getByRole("button", { name: "Potwierdź" });
    expect(confirm).toBeDisabled();
    fireEvent.click(confirm);
    expect(onConfirm).not.toHaveBeenCalled();
  });
});

describe("RejectionV2 — „Nie akceptuje trybu pracy” (14.10.2026)", () => {
  const workModeReasons = [
    { id: "7", label: "Za wysoka stawka", applies_to: ["rejected" as const] },
    {
      id: "9",
      name: "work_mode_mismatch",
      label: "Nie akceptuje trybu pracy (biuro / hybryda)",
      applies_to: ["rejected" as const],
    },
  ];

  function renderWorkMode(
    props: Partial<React.ComponentProps<typeof RejectionV2>> = {},
  ) {
    const onConfirm = vi.fn();
    renderUi(
      <RejectionV2
        open
        onOpenChange={() => {}}
        terminalType="rejected"
        reasons={workModeReasons}
        previousStageCategory="internal"
        onConfirm={onConfirm}
        {...props}
      />,
    );
    return onConfirm;
  }

  it("pyta o dni w biurze dopiero po wybraniu powodu", () => {
    renderWorkMode();
    expect(screen.queryByTestId("rejection-work-mode")).toBeNull();
    fireEvent.click(screen.getByText("Nie akceptuje trybu pracy (biuro / hybryda)"));
    expect(screen.getByTestId("rejection-work-mode")).toBeInTheDocument();
  });

  it("pokazuje tylko mniej dni, niż wymaga rekrutacja, i jej tryb pracy", () => {
    renderWorkMode({ workModeJob: { remotePolicy: "hybrid", onsiteDaysPerWeek: 2 } });
    fireEvent.click(screen.getByText("Nie akceptuje trybu pracy (biuro / hybryda)"));
    const choices = screen.getByRole("radiogroup", {
      name: "Ile dni w biurze kandydat akceptuje",
    });
    expect(choices).toHaveTextContent("Tylko zdalnie");
    expect(choices).toHaveTextContent("Do 1 dnia");
    expect(choices).not.toHaveTextContent("Do 2 dni");
    expect(
      screen.getByText("Ta rekrutacja: hybrydowo · 2 dni w biurze w tygodniu."),
    ).toBeInTheDocument();
  });

  it("domyślnie „Tylko zdalnie” z zapisem na profilu — idzie w 9. argumencie", () => {
    const onConfirm = renderWorkMode();
    fireEvent.click(screen.getByText("Nie akceptuje trybu pracy (biuro / hybryda)"));
    expect(screen.getByText(/Tryb pracy → Tylko zdalnie/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Potwierdź" }));
    expect(onConfirm.mock.calls[0][0]).toBe("9");
    expect(onConfirm.mock.calls[0][8]).toEqual({ maxOnsiteDays: 0, saveToProfile: true });
  });

  it("wybrany dzień i odznaczony zapis trafiają do ruchu", () => {
    const onConfirm = renderWorkMode();
    fireEvent.click(screen.getByText("Nie akceptuje trybu pracy (biuro / hybryda)"));
    fireEvent.click(screen.getByText("Do 1 dnia"));
    expect(
      screen.getByText(/Tryb pracy → Hybrydowo lub zdalnie · do 1 dnia w biurze/),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "Potwierdź" }));
    expect(onConfirm.mock.calls[0][8]).toEqual({ maxOnsiteDays: 1, saveToProfile: false });
  });

  it("przy jednej osobie pokazuje, co jest teraz na profilu", () => {
    renderWorkMode({ profileWorkMode: { modes: ["remote", "hybrid"], days: 3 } });
    fireEvent.click(screen.getByText("Nie akceptuje trybu pracy (biuro / hybryda)"));
    expect(screen.getByTestId("rejection-work-mode-current")).toHaveTextContent(
      "Teraz na profilu: Hybrydowo lub zdalnie · do 3 dni w biurze w tygodniu",
    );
  });

  it("pusty profil to „Nie uzupełniono”", () => {
    renderWorkMode({ profileWorkMode: { modes: [], days: null } });
    fireEvent.click(screen.getByText("Nie akceptuje trybu pracy (biuro / hybryda)"));
    expect(screen.getByTestId("rejection-work-mode-current")).toHaveTextContent(
      "Teraz na profilu: Nie uzupełniono",
    );
  });

  it("kilka osób: zapis na profilach każdej, bez podglądu jednego profilu", () => {
    mockPost.mockResolvedValue({ data: { people: [] } });
    renderWorkMode({
      profileWorkMode: { modes: ["remote"], days: 0 },
      emailPreview: {
        jobId: 1,
        people: [
          { candidateId: 1, name: "Anna Przykładowa" },
          { candidateId: 2, name: "Jan Testowy" },
        ],
      },
    });
    fireEvent.click(screen.getByText("Nie akceptuje trybu pracy (biuro / hybryda)"));
    expect(screen.getByText(/Zapisz na profilach kandydatów/)).toBeInTheDocument();
    expect(screen.queryByTestId("rejection-work-mode-current")).toBeNull();
  });

  it("inny powód nie wysyła trybu pracy", () => {
    const onConfirm = renderWorkMode();
    fireEvent.click(screen.getByText("Za wysoka stawka"));
    fireEvent.click(screen.getByRole("button", { name: "Potwierdź" }));
    expect(onConfirm.mock.calls[0][8]).toBeNull();
  });

  it("klucz powodu przechodzi przez mapowanie słownika z API", () => {
    const [mapped] = mapRejectionReasons([
      {
        id: 9,
        template_id: 1,
        stage_def_id: null,
        name: "work_mode_mismatch",
        label: "Nie akceptuje trybu pracy (biuro / hybryda)",
        order: 4,
        category: "rejected",
        active: true,
      } as RejectionReasonDef,
    ]);
    expect(mapped.name).toBe("work_mode_mismatch");
  });
});
