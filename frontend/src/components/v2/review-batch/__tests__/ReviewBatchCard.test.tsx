/**
 * Porcja dnia (07.11.2026), makieta M7: decyzja jednym klawiszem, bez
 * pomijania. „Do screeningu” i „Odrzuć” idą przez `usePipelineMoveCore`
 * (ta sama droga co Tablica); odrzucenie bez maila do kandydata, z powodem
 * dla systemu, przy braku umiejętności — z nazwą umiejętności.
 */

import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  gapRows,
  orderLine,
  rememberLine,
  ReviewBatchCard,
  rejectMissing,
  sentBeforeText,
} from "@/components/v2/review-batch/ReviewBatchCard";
import type { ReviewBatchItem } from "@/lib/api/reviewBatch";
import { notLookingUntil } from "@/lib/autofill-feedback";

const move = vi.hoisted(() => ({
  send: vi.fn(async () => ({ ok: true as const, data: {} })),
}));

vi.mock("@/hooks/usePipelineMoveCore", () => ({
  usePipelineMoveCore: () => ({ send: move.send, dialogs: null }),
}));
const template = vi.hoisted(() => {
  const defaultReasons = [
    { id: "41", label: "Nie spełnia wymagań technicznych", name: "Nie spełnia wymagań technicznych", applies_to: ["rejected"] },
    { id: "43", label: "Nie akceptuje trybu pracy (biuro / hybryda)", name: "work_mode_mismatch", applies_to: ["rejected"] },
    // Od 19.11.2026 (0745) „Inna rola” ma własny powód w szablonie.
    { id: "44", label: "Inny poziom lub inna rola", name: "other_level_or_role", applies_to: ["rejected"] },
    { id: "49", label: "Inne", name: "Inne (rejected)", applies_to: ["rejected"] },
  ];
  return { defaultReasons, reasons: defaultReasons };
});
vi.mock("@/hooks/useJobPipelineTemplate", () => ({
  useJobPipelineTemplate: () => ({ rejectionReasons: template.reasons }),
}));

const item: ReviewBatchItem = {
  process_id: 7,
  stage_id: 70,
  job_id: 789176,
  job_title: "Senior Fullstack developer",
  candidate_id: 67003,
  name: "Aliaksei",
  city: "Gdańsk",
  years: 8,
  position: null,
  score: 78.16,
  matched_must: ["java", "angular"],
  missing_must: ["spring boot"],
  rate_from_hourly: 115,
  rate_currency: "PLN",
  availability_status: "actively_looking",
  cautions: [],
  budget_hourly: 130,
};

beforeEach(() => {
  move.send.mockClear();
  template.reasons = template.defaultReasons;
});

/** Lustro 422 z `POST /api/pipeline/move` dla powodu z szablonu (api/pipeline.py). */
function serverRefusal(payload: Record<string, unknown>): string | null {
  const reason = template.reasons.find((r) => r.id === payload.rejection_reason_id);
  const days = payload.work_mode_max_onsite_days;
  if (reason?.name === "work_mode_mismatch" && days == null) return "Podaj, ile dni w biurze";
  if (reason?.name !== "work_mode_mismatch" && days != null) return "Dni tylko przy trybie pracy";
  if (reason?.label === "Inne" && !String(payload.notes ?? "").trim()) return "Opisz powód";
  return null;
}

async function rejectWithKey(key: string): Promise<Record<string, unknown>> {
  render(<ReviewBatchCard item={item} onDecided={() => {}} />);
  fireEvent.keyDown(window, { key: "o" });
  fireEvent.keyDown(window, { key });
  fireEvent.keyDown(window, { key: "Enter" });
  await vi.waitFor(() => expect(move.send).toHaveBeenCalled());
  return (move.send.mock.calls[0] as unknown as [Record<string, unknown>])[0];
}

describe("ReviewBatchCard", () => {
  it("pokazuje powód dopasowania bez otwierania profilu", () => {
    render(<ReviewBatchCard item={item} onDecided={() => {}} />);
    expect(screen.getByText("78%")).toBeInTheDocument();
    expect(screen.getByText("✓ java")).toBeInTheDocument();
    expect(screen.getByText("? spring boot")).toBeInTheDocument();
    expect(screen.getByText("Aktywnie szuka")).toBeInTheDocument();
    expect(screen.getByText("od 115 zł/h · budżet 130")).toBeInTheDocument();
    expect(screen.queryByText(/Pomiń/)).not.toBeInTheDocument();
  });

  it("klawisz S przenosi na screening przez wspólny ruch", async () => {
    const onDecided = vi.fn();
    render(<ReviewBatchCard item={item} onDecided={onDecided} />);
    fireEvent.keyDown(window, { key: "s" });
    await vi.waitFor(() => expect(onDecided).toHaveBeenCalled());
    expect(move.send).toHaveBeenCalledWith(
      { candidate_id: 67003, job_id: 789176, stage: "screening" },
      { candidateName: "Aliaksei" },
    );
  });

  it("odrzucenie: brak klikany przy pozycji, bez maila, z brakami dla systemu", async () => {
    const user = userEvent.setup();
    render(<ReviewBatchCard item={item} onDecided={() => {}} />);
    fireEvent.keyDown(window, { key: "o" });
    fireEvent.keyDown(window, { key: "1" });
    expect(screen.getByTestId("review-reject-confirm")).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "spring boot: brak" }));
    await user.click(screen.getByRole("button", { name: "angular: tylko wzmianka" }));
    await user.click(screen.getByTestId("review-reject-confirm"));
    await vi.waitFor(() => expect(move.send).toHaveBeenCalled());
    const [payload] = move.send.mock.calls[0] as unknown as [Record<string, unknown>];
    expect(payload).toMatchObject({
      stage: "rejected",
      send_rejection_email: false,
      notes: "Brak: spring boot, angular (tylko wzmianka)",
      autofill_reason: "missing_skill",
      autofill_learned_from: "profile",
      autofill_gaps: [
        { label: "spring boot", kind: "missing" },
        { label: "angular", kind: "mention" },
      ],
      rejection_reason_id: "41",
    });
  });

  it("brak spoza listy: sam opis wystarcza, bez braków przy pozycjach", async () => {
    const user = userEvent.setup();
    render(<ReviewBatchCard item={item} onDecided={() => {}} />);
    fireEvent.keyDown(window, { key: "o" });
    fireEvent.keyDown(window, { key: "1" });
    await user.type(screen.getByRole("textbox"), "produkty inwestycyjne");
    await user.click(screen.getByTestId("review-reject-confirm"));
    await vi.waitFor(() => expect(move.send).toHaveBeenCalled());
    const [payload] = move.send.mock.calls[0] as unknown as [Record<string, unknown>];
    expect(payload.notes).toBe("Brak: produkty inwestycyjne");
    expect(payload.autofill_gaps).toBeUndefined();
  });

  it("„Nie szuka pracy” zapisuje datę, do kiedy", async () => {
    render(<ReviewBatchCard item={item} onDecided={() => {}} />);
    fireEvent.keyDown(window, { key: "o" });
    fireEvent.keyDown(window, { key: "8" });
    fireEvent.keyDown(window, { key: "Enter" });
    await vi.waitFor(() => expect(move.send).toHaveBeenCalled());
    const [payload] = move.send.mock.calls[0] as unknown as [Record<string, unknown>];
    expect(payload.autofill_reason).toBe("not_looking");
    expect(String(payload.autofill_not_looking_until)).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });
});

// Runda 5 (16.11.2026): feedback z 13.11 — „Inna rola” 49× bez słowa,
// „Za drogi” 27× bez kwoty, 22 z 45 „Inne” to porządki albo sama kropka.
describe("ReviewBatchCard: szczegół powodu (runda 5)", () => {
  async function openReason(key: string) {
    render(<ReviewBatchCard item={{ ...item, position: "Oracle Database Administrator" }} onDecided={() => {}} />);
    fireEvent.keyDown(window, { key: "o" });
    fireEvent.keyDown(window, { key });
  }
  async function sent(): Promise<Record<string, unknown>> {
    await vi.waitFor(() => expect(move.send).toHaveBeenCalled());
    return (move.send.mock.calls[0] as unknown as [Record<string, unknown>])[0];
  }

  it("„Inna rola” mówi, co nie pasuje, kim jest osoba i kogo szukamy zamiast", async () => {
    const user = userEvent.setup();
    await openReason("7");
    expect(screen.getByLabelText("Osoba to:")).toHaveValue("Oracle Database Administrator");
    await user.click(screen.getByRole("button", { name: "Inny zawód" }));
    await user.clear(screen.getByLabelText("Osoba to:"));
    await user.type(screen.getByLabelText("Osoba to:"), "Oracle DBA");
    await user.type(screen.getByLabelText("Szukamy:"), "analityk biznesowy");
    await user.click(screen.getByTestId("review-reject-confirm"));
    expect(await sent()).toMatchObject({
      autofill_reason: "other_level_or_role",
      autofill_detail: {
        role_kind: "profession",
        role_wanted: "analityk biznesowy",
        person_role: "Oracle DBA",
      },
      rejection_reason_id: "44",
      notes: "Inny zawód, osoba: Oracle DBA, szukamy: analityk biznesowy",
    });
  });

  it("po 7 klawisze 1–8 wybierają, co nie gra z rolą, a Enter dalej odrzuca", async () => {
    render(<ReviewBatchCard item={item} onDecided={() => {}} />);
    fireEvent.keyDown(window, { key: "o" });
    fireEvent.keyDown(window, { key: "7" });
    fireEvent.keyDown(window, { key: "6" });
    expect(screen.getByRole("button", { name: "Robił to dawno, teraz co innego" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    fireEvent.keyDown(window, { key: "4" });
    expect(screen.getByRole("button", { name: "Lider zamiast wykonawcy" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.keyDown(window, { key: "Enter" });
    expect(await sent()).toMatchObject({
      autofill_reason: "other_level_or_role",
      autofill_detail: { role_kind: "lead_not_ic" },
    });
  });

  it("Backspace po 7 wraca do wyboru powodu", () => {
    render(<ReviewBatchCard item={item} onDecided={() => {}} />);
    fireEvent.keyDown(window, { key: "o" });
    fireEvent.keyDown(window, { key: "7" });
    fireEvent.keyDown(window, { key: "Backspace" });
    expect(screen.queryByTestId("review-reject-role")).not.toBeInTheDocument();
    fireEvent.keyDown(window, { key: "4" });
    expect(screen.getByRole("radio", { name: /Za droga/ })).toHaveAttribute("aria-checked", "true");
  });

  it("„Szukamy:” podpowiada rolę z profilu, a linia mówi, kiedy silnik przestanie", async () => {
    const user = userEvent.setup();
    render(
      <ReviewBatchCard
        item={{ ...item, position: "Data Engineer" }}
        onDecided={() => {}}
        profile={{
          job_id: item.job_id,
          role: "analityk",
          specialty: null,
          technology: null,
          level: "dowolny",
          saved: true,
          excluded: [],
          learning: [{ label: "data engineer", count: 2, dismissed: false }],
          exclude_min: 3,
        }}
      />,
    );
    await user.keyboard("o7");
    expect(screen.getByLabelText("Szukamy:")).toHaveValue("analityk");
    expect(screen.getByTestId("review-reject-remember")).toHaveTextContent(
      "Silnik zapamięta: „Data Engineer” po raz 3. Od teraz nie proponuje takich osób w tej rekrutacji.",
    );
  });

  it("„Inna rola” bez kliknięcia dalej idzie jednym klawiszem, bez szczegółu", async () => {
    const payload = await rejectWithKey("7");
    expect(payload.autofill_reason).toBe("other_level_or_role");
    expect(payload.autofill_detail).toBeUndefined();
  });

  it("„Za drogi” z kwotą zapisuje „Ile chce?”, bez kwoty idzie jak dotąd", async () => {
    const user = userEvent.setup();
    await openReason("4");
    await user.type(screen.getByLabelText("Ile chce?"), "14a0");
    await user.click(screen.getByTestId("review-reject-confirm"));
    expect(await sent()).toMatchObject({ autofill_reason: "too_expensive", autofill_rate_hourly: 140 });
  });

  it("„Za drogi” bez kwoty nie wysyła stawki", async () => {
    expect((await rejectWithKey("4")).autofill_rate_hourly).toBeUndefined();
  });

  it("okres wypowiedzenia ustawia „Nie szuka do” za tyle miesięcy", async () => {
    const user = userEvent.setup();
    await openReason("8");
    await user.click(screen.getByRole("button", { name: "Okres wypowiedzenia" }));
    await user.selectOptions(screen.getByLabelText("Okres wypowiedzenia"), "2");
    await user.click(screen.getByTestId("review-reject-confirm"));
    expect(await sent()).toMatchObject({
      autofill_reason: "not_looking",
      autofill_not_looking_until: notLookingUntil(2),
      autofill_detail: { availability: "notice" },
    });
  });

  it("„Dostępny od” bez daty nie pozwala odrzucić", async () => {
    const user = userEvent.setup();
    await openReason("8");
    await user.click(screen.getByRole("button", { name: "Dostępny od…" }));
    expect(screen.getByTestId("review-reject-confirm")).toBeDisabled();
    expect(screen.getByText("Podaj, od kiedy jest dostępny.")).toBeInTheDocument();
  });

  it("„Inne” z samą kropką nie przechodzi, porządki idą jako `cleanup`", async () => {
    const user = userEvent.setup();
    await openReason("0");
    await user.type(screen.getByRole("textbox"), ".");
    expect(screen.getByTestId("review-reject-confirm")).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Duplikat" }));
    await user.click(screen.getByTestId("review-reject-confirm"));
    const payload = await sent();
    expect(payload).toMatchObject({
      autofill_reason: "cleanup",
      autofill_detail: { cleanup: "duplicate" },
      rejection_reason_id: "49",
    });
    expect(String(payload.notes)).toMatch(/^Porządki \(nie ocena osoby\)\. Duplikat/);
    expect(serverRefusal(payload)).toBeNull();
  });
});

describe("ReviewBatchCard: każdy powód zapisuje się jednym klawiszem", () => {
  it.each(["2", "3", "4", "5", "6", "7", "8", "9"])("klawisz %s przechodzi walidację serwera", async (key) => {
    expect(serverRefusal(await rejectWithKey(key))).toBeNull();
  });

  it.each([
    ["5", "no_polish", "Brak polskiego"],
    ["6", "weak_english", "Angielski za słaby"],
    ["9", "contract_form", "Forma umowy (UoP / B2B)"],
  ])("klawisz %s (bez odpowiednika w szablonie) idzie jako „Inne” z nazwą powodu w opisie", async (key, reason, label) => {
    expect(await rejectWithKey(key)).toMatchObject({
      rejection_reason_id: "49",
      notes: label,
      autofill_reason: reason,
    });
  });

  it("„Lokalizacja / tryb” bez znanych dni nie mówi nic o trybie pracy na profilu", async () => {
    const payload = await rejectWithKey("3");
    expect(payload).toMatchObject({
      rejection_reason_id: "49",
      notes: "Lokalizacja lub tryb pracy",
      autofill_reason: "location_mode",
    });
    expect(payload.work_mode_max_onsite_days).toBeUndefined();
  });

  it("znane dni w biurze idą z powodem „Nie akceptuje trybu pracy” i trafiają na profil", async () => {
    const user = userEvent.setup();
    render(<ReviewBatchCard item={item} onDecided={() => {}} />);
    fireEvent.keyDown(window, { key: "o" });
    fireEvent.keyDown(window, { key: "3" });
    await user.click(screen.getByRole("button", { name: /Znam liczbę dni w biurze/ }));
    await user.click(screen.getByRole("radio", { name: "Do 2 dni" }));
    await user.click(screen.getByTestId("review-reject-confirm"));
    await vi.waitFor(() => expect(move.send).toHaveBeenCalled());
    const [payload] = move.send.mock.calls[0] as unknown as [Record<string, unknown>];
    expect(payload).toMatchObject({
      rejection_reason_id: "43",
      work_mode_max_onsite_days: 2,
      work_mode_save_to_profile: true,
      autofill_reason: "location_mode",
    });
    expect(payload.notes).toBeUndefined();
    expect(serverRefusal(payload)).toBeNull();
  });

  it("szablon bez powodu „tryb pracy”: nie pyta o dni i idzie jako „Inne”", async () => {
    template.reasons = template.defaultReasons.filter((r) => r.name !== "work_mode_mismatch");
    const payload = await rejectWithKey("3");
    expect(screen.queryByRole("button", { name: /Znam liczbę dni w biurze/ })).not.toBeInTheDocument();
    expect(payload).toMatchObject({ rejection_reason_id: "49", notes: "Lokalizacja lub tryb pracy" });
    expect(serverRefusal(payload)).toBeNull();
  });

  it("szablon bez odpowiednika „Za junior”: spada na „Inne”, a opis i tak jest", async () => {
    expect(await rejectWithKey("2")).toMatchObject({
      rejection_reason_id: "49",
      notes: "Za mało doświadczenia",
    });
  });
});

describe("rejectMissing", () => {
  it("podaje powód kolejności, a przy samym wyniku milczy", () => {
    expect(orderLine(item)).toBeNull();
    expect(orderLine({ ...item, score: 78, order_active: true, order_in_budget: true })).toBe(
      "Kolejność: 78% + aktywnie szuka + stawka w budżecie",
    );
    const known = { points: 8, client_points: 0, note_points: 8, verified_at_client: 0, last_note_days: 12 };
    expect(orderLine({ ...item, score: 70, known })).toBe("Kolejność: 70% + notatka 12 dni temu");
    // 16.11.2026: polski nieojczysty i lider/wykonawca mówią, czemu karta jest dalej.
    expect(orderLine({ ...item, score: 72, order_polish_later: true })).toBe(
      "Kolejność: 72% · polski nie ojczysty → dalej",
    );
    expect(
      orderLine({ ...item, score: 72, order_active: true, order_polish_later: true, order_leader_gap: true }),
    ).toBe("Kolejność: 72% + aktywnie szuka · polski nie ojczysty, szukamy lidera → dalej");
  });

  it("mówi, czego brakuje", () => {
    expect(rejectMissing(null, "")).toMatch(/Wybierz powód/);
    expect(rejectMissing("missing_skill", " ")).toMatch(/Kliknij, czego brakuje/);
    expect(rejectMissing("missing_skill", " ", 1)).toBe("");
    expect(rejectMissing("other", "")).toMatch(/Opisz/);
    expect(rejectMissing("other", ".")).toMatch(/Opisz powód słowami/);
    expect(rejectMissing("other", ".", 0, { cleanup: "duplicate" })).toBe("");
    expect(rejectMissing("other", "brak bankowości")).toBe("");
    expect(rejectMissing("too_junior", "")).toBe("");
  });

  it("pozycje do braków: najpierw nieznalezione, bez powtórzeń, najwyżej 8", () => {
    expect(gapRows({ missing_must: ["Kafka", "kafka "], matched_must: ["java", "KAFKA"] })).toEqual(["Kafka", "java"]);
    const many = Array.from({ length: 12 }, (_, i) => `s${i}`);
    expect(gapRows({ missing_must: many, matched_must: [] })).toHaveLength(8);
  });
});

describe("rememberLine", () => {
  const base = {
    job_id: 1,
    role: null,
    specialty: null,
    technology: null,
    level: "dowolny" as const,
    saved: false,
    excluded: [],
    learning: [],
    exclude_min: 3,
  };
  it("pierwszy raz liczy od 1 i mówi o progu", () => {
    expect(rememberLine("Tester", base)).toBe(
      "Silnik zapamięta: „Tester” po raz 1. Od 3. razu przestaje proponować takie osoby w tej rekrutacji.",
    );
  });
  it("etykieta już na liście i zdjęta z listy", () => {
    expect(
      rememberLine("scrum  master", { ...base, excluded: [{ label: "Scrum Master", count: 0, source: "manual" }] }),
    ).toContain("już jest w „Nie proponujemy”");
    expect(
      rememberLine("DBA", { ...base, learning: [{ label: "dba", count: 4, dismissed: true }] }),
    ).toContain("po raz 5. Ktoś zdjął to");
  });
  it("puste pole milczy", () => {
    expect(rememberLine("  ", base)).toBeNull();
  });
});

describe("ReviewBatchCard: nazwy powodów z jednego słownika (19.11.2026)", () => {
  it("klawisze 1–9 mają nazwy z okna „Zamknij proces”", async () => {
    const { QUICK_REASONS } = await import("@/components/v2/review-batch/ReviewBatchCard");
    expect(Object.fromEntries(QUICK_REASONS.map((r) => [r.key, r.label]))).toMatchObject({
      "1": "Brak kluczowej umiejętności",
      "2": "Za mało doświadczenia",
      "3": "Lokalizacja lub tryb pracy",
      "4": "Za droga",
      "7": "Inny poziom lub inna rola",
      "8": "Nie szuka pracy",
      "0": "Inne — opisz",
    });
  });
});

describe("wysłany wcześniej (20.11.2026)", () => {
  it("karta mówi, ile razy i gdzie ostatnio osoba poszła do klienta", () => {
    render(
      <ReviewBatchCard
        item={{ ...item, sent_before: { count: 2, last_days: 7, last_job_title: "Backend Java developer – TOR" } }}
        onDecided={() => {}}
      />,
    );
    expect(screen.getByTestId("review-sent-before")).toHaveTextContent(
      "Wysłany do klienta 2× · ostatnio 7 dni temu: Backend Java developer – TOR",
    );
  });
  it("bez wysyłki linii nie ma", () => {
    render(<ReviewBatchCard item={{ ...item, sent_before: null }} onDecided={() => {}} />);
    expect(screen.queryByTestId("review-sent-before")).toBeNull();
  });
  it("dziś i wczoraj słowami", () => {
    expect(sentBeforeText({ count: 1, last_days: 0, last_job_title: "" })).toBe("Wysłany do klienta 1× · ostatnio dziś");
    expect(sentBeforeText({ count: 1, last_days: 1, last_job_title: " QA " })).toBe(
      "Wysłany do klienta 1× · ostatnio wczoraj: QA",
    );
  });
});
