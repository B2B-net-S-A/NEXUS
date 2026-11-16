import { describe, expect, it } from "vitest";

import {
  basisText,
  breakdown,
  errorDetail,
  fileProblem,
  groupLines,
  groupProblems,
  grosze,
  inputBody,
  inputFor,
  inputsAfterCompute,
  kindsTitle,
  kpiStats,
  lineMarker,
  listActions,
  monthRange,
  parseGross,
  peoplePayrollHref,
  peopleText,
  plural,
  rangeProblem,
  statusNote,
  zl,
} from "../payroll-model";
import { LINES, line, list, month } from "./payroll-fixtures";

describe("kwoty z API", () => {
  it("zamienia złote z tekstu na grosze i z powrotem", () => {
    expect(grosze("5646.86")).toBe(564686);
    expect(grosze("7")).toBe(700);
    expect(grosze("0.5")).toBe(50);
    expect(grosze("-12.30")).toBe(-1230);
    expect(grosze("0.005")).toBe(1);
    expect(grosze("1E+2")).toBe(10000);
    expect(grosze(null)).toBeNull();
    expect(grosze("abc")).toBeNull();
    expect(zl("149798.00")).toBe("149 798,00");
    expect(zl(null)).toBe("—");
  });

  it("czyta kwotę brutto z formularza: zero wolno, minus i trzy cyfry po przecinku nie", () => {
    expect(parseGross("1 234,5")).toBe("1234.50");
    expect(parseGross("0")).toBe("0.00");
    expect(parseGross("-5")).toBeNull();
    expect(parseGross("1,234")).toBeNull();
    expect(parseGross("10000000,01")).toBeNull();
    expect(parseGross("")).toBeNull();
  });

  it("odmienia po liczbie", () => {
    expect(plural(1, "pozycja", "pozycje", "pozycji")).toBe("1 pozycja");
    expect(plural(3, "pozycja", "pozycje", "pozycji")).toBe("3 pozycje");
    expect(plural(12, "pozycja", "pozycje", "pozycji")).toBe("12 pozycji");
    expect(plural(22, "pozycja", "pozycje", "pozycji")).toBe("22 pozycje");
  });
});

describe("grupy umów", () => {
  it("grupuje pozycje po formie z sumami kolumn — pozycja bez kwoty liczy się jak zero", () => {
    const groups = groupLines(LINES);
    expect(groups.map((group) => [group.label, group.lines.length])).toEqual([
      ["Umowy o pracę", 2],
      ["Umowy zlecenia — zespół i kontraktorzy u klientów", 2],
    ]);
    expect(groups[0].sums.gross).toBe(1_730_000);
    expect(groups[0].sums.net).toBe(564_686 + 680_577);
    expect(groups[1].sums.gross).toBe(705_600);
    expect(groups[1].sums.employer_social).toBe(144_508);
  });

  it("nazywa formy na liście", () => {
    expect(kindsTitle(LINES)).toBe("UoP i zlecenia");
    expect(kindsTitle([...LINES, line({ id: 9, kind: "dzielo", kind_label: "Dzieło" })])).toBe("UoP, zlecenia i dzieła");
    expect(kindsTitle([LINES[0]])).toBe("UoP");
    expect(kindsTitle([])).toBe("");
  });
});

describe("podstawa pozycji", () => {
  it("pokazuje godziny × stawkę z „Mojego miesiąca”", () => {
    expect(basisText(LINES[2])).toEqual({ main: "168 h × 42,00", sub: "„Mój miesiąc”" });
    expect(
      basisText(line({ basis: { hours: "7.50", hourly_rate: "40.00", bonus_total: "500.00" } })),
    ).toEqual({ main: "7,5 h × 40,00", sub: "„Mój miesiąc” + premie 500,00" });
  });

  it("bez stawki mówi, skąd kwota", () => {
    expect(basisText(LINES[0]).main).toBe("„Mój miesiąc”");
    expect(basisText(LINES[3])).toEqual({ main: "brak kwoty", sub: "rozliczenie nieprzyjęte" });
    expect(basisText(line({ source: "manual", basis: { note: "stawka z aneksu" } }))).toEqual({
      main: "kwota Rozliczeń",
      sub: "stawka z aneksu",
    });
    expect(basisText(line({ source: "manual", basis: { note: "dopłata", outside_month: true } }))).toEqual({
      main: "kwota Rozliczeń",
      sub: "umowa poza miesiącem · dopłata",
    });
    expect(basisText(line({ source: "client_settlement", basis: { md_charged: "20.00" } }))).toEqual({
      main: "rozliczenie klienta",
      sub: "20 MD",
    });
  });
});

describe("liczby nad tabelą", () => {
  it("podaje terminy wypłaty, ZUS i PIT-4 z listy", () => {
    const stats = kpiStats(list());
    expect(stats.map((stat) => [stat.label, stat.value])).toEqual([
      ["Osób na liście", "4"],
      ["Brutto", "24 356,00 zł"],
      ["Do wypłaty (do 10.11)", "17 549,59 zł"],
      ["ZUS razem (do 15.12)", "10 061,53 zł"],
      ["PIT-4 (do 21.12)", "1 733,00 zł"],
      ["Składki pracodawcy", "4 988,12 zł"],
    ]);
  });

  it("dokłada PPK i ryczałt PIT-8AR, gdy są", () => {
    const base = list();
    const stats = kpiStats({
      ...base,
      totals: { ...base.totals, pit_flat: "24.00", pit_scale: "1709.00", ppk_employee: "100.00", ppk_employer: "75.00" },
    });
    expect(stats.find((stat) => stat.id === "pit")).toMatchObject({
      label: "PIT-4 i PIT-8AR (do 21.12)",
      title: "Zaliczki (PIT-4) 1 709,00 zł, podatek ryczałtowy (PIT-8AR) 24,00 zł",
    });
    expect(stats.find((stat) => stat.id === "ppk")).toMatchObject({ label: "PPK (do 15.12)", value: "175,00 zł" });
  });
});

describe("przyciski listy", () => {
  it("szkic: przelicz i paski tak, KEDU i przelewy po zatwierdzeniu, zatwierdzenie z odmową serwera", () => {
    const actions = listActions(month());
    expect(actions.compute.enabled).toBe(true);
    expect(actions.payslips.enabled).toBe(true);
    expect(actions.kedu).toEqual({ enabled: false, reason: "Deklaracje ZUS powstają z zatwierdzonej listy." });
    expect(actions.transfers.enabled).toBe(false);
    expect(actions.approve).toEqual({
      visible: true,
      enabled: false,
      reason: "Tę listę policzyłeś Ty — zatwierdza druga osoba z Rozliczeń.",
    });
    expect(actions.cancel.visible).toBe(true);
  });

  it("zatwierdzona: bez przeliczenia i zatwierdzania, z plikami; wypłacona bez anulowania", () => {
    const approved = month({ can_compute: false, list: list({ status: "approved", can_approve: false, approve_refusal: null }) });
    const actions = listActions(approved);
    expect(actions.compute).toEqual({ enabled: false, reason: "Zatwierdzonej listy się nie przelicza — najpierw ją anuluj." });
    expect(actions.kedu.enabled).toBe(true);
    expect(actions.transfers.enabled).toBe(true);
    expect(actions.approve.visible).toBe(false);
    expect(listActions({ ...approved, list: { ...approved.list!, paid_at: "2026-11-10T12:00:00Z" } }).cancel.visible).toBe(false);
  });

  it("otwarty miesiąc w Rozliczeniach blokuje przeliczenie z powodem", () => {
    const actions = listActions(month({ period_status: "open", can_compute: false, list: null }));
    expect(actions.compute.reason).toMatch(/Najpierw zamknij miesiąc w Rozliczeniach/);
    expect(actions.payslips).toEqual({ enabled: false, reason: "Najpierw przelicz listę." });
    expect(actions.cancel.visible).toBe(false);
  });

  it("szkic do zatwierdzenia mówi, kto i kiedy liczył", () => {
    expect(statusNote(list())).toBe(
      "policzona 03.11.2026 (Osoba Rozliczeń)",
    );
    expect(
      statusNote(list({ status: "approved", approved_at: "2026-11-04T08:00:00Z", approved_by: "Osoba B", transfers_created_at: "2026-11-05T08:00:00Z" })),
    ).toBe("zatwierdzona 04.11.2026 (Osoba B) · plik przelewów pobrany 05.11.2026");
  });
});

describe("problemy", () => {
  it("grupuje po rodzaju, blokujące najpierw, z osobami", () => {
    const groups = groupProblems([
      ...list().problems,
      { code: "person_data_missing", label: "Brak danych", blocking: true, person: "Ewa Przykładowa" },
      { code: "params_to_confirm", label: "Parametry płac czekają na potwierdzenie przez Rozliczenia.", blocking: true },
    ]);
    expect(groups.map((group) => [group.code, group.blocking, group.people])).toEqual([
      ["person_data_missing", true, ["Jan Testowy", "Ewa Przykładowa"]],
      ["settlement_not_accepted", true, ["Piotr Testowy"]],
      ["params_to_confirm", true, []],
      ["files_data", false, ["Ewa Przykładowa"]],
    ]);
    expect(peopleText(["A", "B", "C", "D", "E"])).toBe("A, B, C i jeszcze 2");
  });

  it("oznacza wiersz z problemem", () => {
    expect(lineMarker(LINES[1])).toBe("blocking");
    expect(lineMarker(LINES[2])).toBe("warning");
    expect(lineMarker(LINES[0])).toBeNull();
  });
});

describe("kwota Rozliczeń", () => {
  it("znajduje wpis osoby z formą umowy albo kontraktu", () => {
    const inputs = [
      { id: 1, user_id: 11, contract_id: null, kind: "dzielo" as const, gross: "100.00", fund_basis: null, note: "x", entered_at: null },
      { id: 2, user_id: 11, contract_id: null, kind: "uop" as const, gross: "200.00", fund_basis: null, note: "y", entered_at: null },
      { id: 3, user_id: null, contract_id: 31, kind: "zlecenie" as const, gross: "300.00", fund_basis: null, note: "z", entered_at: null },
    ];
    expect(inputFor(LINES[0], inputs)?.id).toBe(2);
    expect(inputFor(LINES[3], inputs)?.id).toBe(3);
    expect(inputFor(LINES[1], inputs)).toBeNull();
  });

  it("buduje ciało: kontrakt u klienta albo osoba z formą; usunięcie bez opisu", () => {
    expect(inputBody(LINES[3], "4950.00", "rozliczenie w EUR")).toEqual({
      contract_id: 31,
      kind: "zlecenie",
      gross: "4950.00",
      note: "rozliczenie w EUR",
      fund_basis: null,
    });
    expect(inputBody(LINES[0], "3900.00", "pół miesiąca L4", "7800.00")).toEqual({
      user_id: 11,
      kind: "uop",
      gross: "3900.00",
      note: "pół miesiąca L4",
      fund_basis: "7800.00",
    });
    expect(inputBody(LINES[0], null)).toEqual({ user_id: 11, kind: "uop", gross: null });
  });

  it("widzi kwoty wpisane po przeliczeniu szkicu", () => {
    const later = { id: 1, user_id: 12, contract_id: null, kind: "uop" as const, gross: "1.00", fund_basis: null, note: "abc", entered_at: "2026-11-03T10:00:00+01:00" };
    expect(inputsAfterCompute(month({ inputs: [later] }))).toBe(true);
    expect(inputsAfterCompute(month({ inputs: [{ ...later, entered_at: "2026-11-03T08:00:00+01:00" }] }))).toBe(false);
  });
});

describe("rozpisanie pozycji", () => {
  it("dzieli wynik silnika na sekcje i chowa puste wiersze opcjonalne", () => {
    const sections = breakdown(LINES[0].result);
    expect(sections.map((section) => section.title)).toEqual(["Składki osoby", "Podatek", "Pracodawca"]);
    const tax = sections[1].rows.map((row) => row.label);
    expect(tax).not.toContain("W tym zwolniony (ulga)");
    expect(tax).toContain("Zaliczka PIT (skala)");
    expect(sections[2].rows.find((row) => row.label === "Koszt pracodawcy")?.value).toBe("9 397,44");
    expect(breakdown({})).toEqual([]);
  });
});

describe("błędy plików", () => {
  it("czyta kod i listę osób z odmowy KEDU", () => {
    const error = {
      response: {
        status: 409,
        data: {
          detail: {
            code: "kedu_data_missing",
            message: "Brakuje danych osób do deklaracji.",
            people: [{ person: "Jan Testowy", missing: ["adres zamieszkania", "kod tytułu ubezpieczenia"] }],
          },
        },
      },
    };
    expect(errorDetail(error)).toMatchObject({ status: 409, code: "kedu_data_missing" });
    expect(fileProblem(error)).toEqual({
      title: "Deklaracja ZUS — brakuje danych osób",
      message: "Brakuje danych osób do deklaracji.",
      items: ["Jan Testowy: adres zamieszkania, kod tytułu ubezpieczenia"],
    });
  });

  it("czyta pominięte osoby ze zgłoszeń; inne błędy idą do dymku", () => {
    const error = {
      response: {
        status: 409,
        data: { detail: { code: "nothing_to_register", message: "Nie ma kogo zgłosić.", skipped: [{ name: "Ewa Przykładowa", kind: "ZUA", reason: "brak PESEL-u" }] } },
      },
    };
    expect(fileProblem(error)?.items).toEqual(["Ewa Przykładowa (ZUA): brak PESEL-u"]);
    expect(fileProblem({ response: { status: 409, data: { detail: "Lista jest anulowana." } } })).toBeNull();
    expect(errorDetail(new Error("sieć"))).toEqual({ status: null, code: null, detail: null });
  });
});

describe("zakres zgłoszeń", () => {
  it("bierze miesiąc i pilnuje kwartału", () => {
    expect(monthRange(2026, 2)).toEqual({ from: "2026-02-01", to: "2026-02-28" });
    expect(monthRange(2026, 12)).toEqual({ from: "2026-12-01", to: "2026-12-31" });
    expect(rangeProblem("2026-10-01", "2026-12-31")).toBeNull();
    expect(rangeProblem("2026-10-01", "2027-01-05")).toBe("Zakres najwyżej kwartał (92 dni).");
    expect(rangeProblem("2026-10-05", "2026-10-01")).toBe("Data „od” jest po dacie „do”.");
    expect(rangeProblem("", "2026-10-01")).toBe("Podaj obie daty.");
  });

  it("linkuje miesiąc w Ludzie → Rozliczenia", () => {
    expect(peoplePayrollHref(2026, 3)).toBe("/people/payroll/2026-03");
  });
});
