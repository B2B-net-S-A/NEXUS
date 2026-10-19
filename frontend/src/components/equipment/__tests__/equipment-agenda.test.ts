/**
 * Logika ekranów „Sprzętu” po makiecie 19.10.2026: widok „Modele”, gotowe
 * zestawy, „Czy starczy na wydania?”, agenda „Do zrobienia” i plan tygodnia.
 */
import { describe, expect, it } from "vitest";

import type {
  EquipmentCategory,
  EquipmentItem,
  EquipmentTask,
} from "@/lib/api/equipment";

import {
  agendaDue,
  agendaGroups,
  daysSince,
  groupByModel,
  holderInitials,
  kitByKey,
  kitForTask,
  matchesAgendaFilter,
  pickKit,
  stockCoverage,
  taskContext,
  weekPlan,
} from "../equipment-format";

const MODELS: Record<string, { id: number; category: EquipmentCategory; name: string }> = {
  latitude: { id: 1, category: "laptop", name: "Dell Latitude 5520" },
  vostro: { id: 2, category: "laptop", name: "Dell Vostro 3530" },
  redmi: { id: 3, category: "telefon", name: "Xiaomi Redmi A5" },
  sim: { id: 4, category: "karta_sim", name: "abonament firmowy" },
  card: { id: 5, category: "karta_dostepu", name: "ogólny + biuro" },
  headset: { id: 6, category: "akcesorium", name: "Słuchawki Jabra Evolve2" },
  cable: { id: 7, category: "akcesorium", name: "Kabel USB-C" },
  monitor: { id: 8, category: "monitor", name: "Dell P2422H" },
};

let nextId = 100;
function item(model: keyof typeof MODELS, nr: string | null, extra: Partial<EquipmentItem> = {}): EquipmentItem {
  const m = MODELS[model];
  nextId += 1;
  return {
    id: nextId,
    model: { ...m, manufacturer: null, price_pln: null, is_active: true },
    category: m.category,
    inventory_number: nr,
    serial_number: null,
    imei: null,
    iccid: null,
    phone_number: model === "sim" ? `5000000${String(nextId).slice(-2)}` : null,
    access_card_number: null,
    status: "na_stanie",
    ownership: "nasz",
    purchase_date: null,
    location: null,
    notes: null,
    holder: null,
    issue_protocol: null,
    ...extra,
  };
}

function task(overrides: Partial<EquipmentTask>): EquipmentTask {
  nextId += 1;
  return {
    id: nextId,
    kind: "wydanie",
    status: "otwarte",
    title: "Zadanie",
    due_on: null,
    overdue_days: 0,
    holder: { kind: "user", id: 1, name: "Anna Przykładowa" },
    protocol: null,
    details: {},
    ...overrides,
  };
}

describe("widok „Modele” — wolne sztuki zwinięte po modelu", () => {
  it("grupuje po modelu, sortuje numery po ludzku i bierze najczęstsze miejsce", () => {
    const groups = groupByModel([
      item("vostro", "154", { location: "szafka B" }),
      item("latitude", "151", { location: "szafka B" }),
      item("redmi", "T-062", { location: "szafka A" }),
      item("latitude", "148", { location: "szafka C" }),
      item("latitude", "149", { location: "szafka B" }),
      item("vostro", "152", { location: "szafka B" }),
    ]);
    expect(groups.map((g) => [g.model.name, g.items.length])).toEqual([
      // laptopy przed telefonami; w kategorii więcej sztuk wyżej
      ["Dell Latitude 5520", 3],
      ["Dell Vostro 3530", 2],
      ["Xiaomi Redmi A5", 1],
    ]);
    expect(groups[0].items.map((i) => i.inventory_number)).toEqual(["148", "149", "151"]);
    expect(groups[0].locations).toEqual(["szafka B", "szafka C"]);
  });

  it("„095” jest przed „148” (porównanie liczbowe, nie znak po znaku)", () => {
    const [group] = groupByModel([item("vostro", "148"), item("vostro", "095"), item("vostro", "1000")]);
    expect(group.items.map((i) => i.inventory_number)).toEqual(["095", "148", "1000"]);
  });

  it("pusta lista = brak grup", () => {
    expect(groupByModel([])).toEqual([]);
  });
});

describe("gotowe zestawy", () => {
  const free = [
    item("vostro", "152"),
    item("latitude", "148"),
    item("redmi", "T-063"),
    item("redmi", "T-062"),
    item("sim", null),
    item("cable", "C-001"),
    item("headset", "J-045"),
    item("headset", "J-044"),
    item("card", "K-1612"),
  ];

  it("zestaw kontraktora bierze pierwsze wolne sztuki, słuchawki po nazwie modelu", () => {
    const { added, missing } = pickKit(kitByKey("kontraktor"), free, []);
    expect(missing).toEqual([]);
    expect(added.map((i) => i.inventory_number ?? i.category)).toEqual([
      "148",
      "T-062",
      "karta_sim",
      "J-044",
      "K-1612",
    ]);
  });

  it("miejsce zajęte już pozycją z protokołu nie dostaje drugiej sztuki", () => {
    const laptop = free[0];
    const { added } = pickKit(kitByKey("kontraktor"), free.slice(1), [laptop]);
    expect(added.some((i) => i.category === "laptop")).toBe(false);
    expect(added).toHaveLength(4);
  });

  it("brak wolnej sztuki wraca w `missing`, reszta zestawu się dodaje", () => {
    const withoutMonitor = free.filter((i) => i.category !== "karta_dostepu");
    const { added, missing } = pickKit(kitByKey("biuro"), withoutMonitor, []);
    expect(missing).toEqual(["monitor", "karta dostępu"]);
    expect(added.map((i) => i.category)).toEqual(["laptop", "akcesorium"]);
  });

  it("zestaw zadania: start kontraktu = kontraktor, wejście = biuro, reszta bez zestawu", () => {
    expect(kitForTask(task({ details: { reason: "start_kontraktu" } }))?.key).toBe("kontraktor");
    expect(kitForTask(task({ details: { reason: "wejscie" } }))?.key).toBe("biuro");
    expect(kitForTask(task({ details: {} }))).toBeNull();
    expect(kitForTask(task({ kind: "zwrot", details: { reason: "wejscie" } }))).toBeNull();
  });
});

describe("„Czy starczy na wydania?”", () => {
  const freeBy = {
    laptop: 11,
    telefon: 14,
    monitor: 8,
    karta_sim: 6,
    karta_dostepu: 1,
    akcesorium: 9,
    inne: 0,
  };

  it("sumuje zestawy otwartych zadań „Przygotuj” i pokazuje braki", () => {
    const rows = stockCoverage(
      [
        task({ details: { reason: "start_kontraktu" } }),
        task({ details: { reason: "wejscie" } }),
        task({ kind: "zwrot", details: { reason: "odejscie" } }),
        task({ status: "zrobione", details: { reason: "wejscie" } }),
      ],
      freeBy,
    );
    expect(rows).toEqual([
      { category: "laptop", needed: 2, free: 11, short: 0 },
      { category: "telefon", needed: 1, free: 14, short: 0 },
      { category: "monitor", needed: 1, free: 8, short: 0 },
      { category: "karta_sim", needed: 1, free: 6, short: 0 },
      { category: "karta_dostepu", needed: 2, free: 1, short: 1 },
      { category: "akcesorium", needed: 2, free: 9, short: 0 },
    ]);
  });

  it("bez zadań z zestawem — pusta lista (zakup i zwrot nie liczą się)", () => {
    expect(stockCoverage([task({ kind: "zakup" }), task({ kind: "zwrot" })], freeBy)).toEqual([]);
  });
});

describe("agenda „Do zrobienia”", () => {
  const today = "2026-10-19";

  it("dzieli na Po terminie → Dziś → Później, zadania bez terminu na końcu", () => {
    const groups = agendaGroups(
      [
        task({ id: 1, due_on: "2026-10-26" }),
        task({ id: 2, due_on: null }),
        task({ id: 3, due_on: "2026-10-13" }),
        task({ id: 4, due_on: today }),
        task({ id: 5, due_on: "2026-10-20" }),
      ],
      today,
    );
    expect(groups.map((g) => [g.bucket, g.tasks.map((t) => t.id)])).toEqual([
      ["overdue", [3]],
      ["today", [4]],
      ["later", [5, 1, 2]],
    ]);
  });

  it("pomija puste grupy", () => {
    expect(agendaGroups([task({ due_on: "2026-11-02" })], today).map((g) => g.bucket)).toEqual([
      "later",
    ]);
  });

  it("filtr: „Przygotuj” to wydanie i zakup, reszta jeden rodzaj", () => {
    expect(matchesAgendaFilter({ kind: "zakup" }, "przygotuj")).toBe(true);
    expect(matchesAgendaFilter({ kind: "wydanie" }, "przygotuj")).toBe(true);
    expect(matchesAgendaFilter({ kind: "podpis" }, "przygotuj")).toBe(false);
    expect(matchesAgendaFilter({ kind: "zwrot" }, "zwrot")).toBe(true);
    expect(matchesAgendaFilter({ kind: "podpis" }, "all")).toBe(true);
  });

  it("termin słowami", () => {
    expect(agendaDue("2026-10-13", today)).toBe("6 dni po");
    expect(agendaDue("2026-10-18", today)).toBe("1 dzień po");
    expect(agendaDue(today, today)).toBe("dziś");
    expect(agendaDue("2026-10-26", today)).toBe("do 26.10");
    expect(agendaDue(null, today)).toBe("bez terminu");
  });

  it("kontekst zadania: klient, powód z datą i liczba pozycji zwrotu", () => {
    expect(
      taskContext(
        task({ kind: "zwrot", details: { client_name: "Telekom Wzorcowy", reason: "koniec_wspolpracy", end_date: "2026-11-02", items: 1 } }),
      ),
    ).toBe("Telekom Wzorcowy · koniec współpracy 02.11 · 1 pozycja z ewidencji");
    expect(taskContext(task({ details: { reason: "wejscie", start_date: "2026-11-04" } }))).toBe(
      "start w biurze 04.11",
    );
    expect(taskContext(task({ details: {} }))).toBe("");
  });
});

describe("plan tygodnia recepcji", () => {
  const tasks = [
    task({ due_on: "2026-10-13" }), // zaległe — liczą się do dziś
    task({ due_on: "2026-10-19" }),
    task({ due_on: "2026-10-22" }),
    task({ due_on: "2026-10-22", status: "zrobione" }),
    task({ due_on: "2026-10-27" }),
    task({ due_on: "2026-10-26" }),
    task({ due_on: null }),
  ];

  it("poniedziałek–piątek tygodnia, dziś z zaległymi, następny tydzień osobno", () => {
    const plan = weekPlan(tasks, "2026-10-19");
    expect(plan.days.map((d) => [d.label, d.date, d.count, d.isToday])).toEqual([
      ["pon", "2026-10-19", 2, true],
      ["wt", "2026-10-20", 0, false],
      ["śr", "2026-10-21", 0, false],
      ["czw", "2026-10-22", 1, false],
      ["pt", "2026-10-23", 0, false],
    ]);
    expect(plan.next).toEqual({ count: 2, first: "2026-10-26" });
  });

  it("w środę tydzień zaczyna się w poniedziałek", () => {
    expect(weekPlan(tasks, "2026-10-21").days[0].date).toBe("2026-10-19");
  });

  it("w sobotę pokazuje nadchodzący tydzień", () => {
    const plan = weekPlan(tasks, "2026-10-24");
    expect(plan.days[0].date).toBe("2026-10-26");
    expect(plan.days.every((d) => !d.isToday)).toBe(true);
  });
});

describe("drobne", () => {
  it("dni od daty i inicjały", () => {
    expect(daysSince("2026-10-16", "2026-10-19")).toBe(3);
    expect(daysSince(null, "2026-10-19")).toBeNull();
    expect(holderInitials("Anna Kontraktorska")).toBe("AK");
    expect(holderInitials("Osoba usunięta")).toBe("OU");
    expect(holderInitials("—")).toBe("?");
  });
});
