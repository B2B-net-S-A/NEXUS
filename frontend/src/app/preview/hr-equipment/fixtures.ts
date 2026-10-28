/**
 * Dane fikcyjne harnessów „Sprzęt” (makiety 12 i 13 raportu „Ludzie w NEXUSIE”):
 * `/preview/hr-equipment` (ewidencja) i `/preview/hr-equipment-issue` (wydanie
 * i protokół). Jeden rejestr recepcji w dwóch chwilach:
 * - `after` (makieta 12) — trzy dni po wydaniu zestawu kontraktorce: pięć
 *   pozycji „Wydany”, protokół czeka na podpis, link wysłany;
 * - `before` (makieta 13) — te same pozycje jeszcze leżą na stanie, a zestaw
 *   kontraktora czeka w „Do zrobienia”.
 *
 * Numery seryjne, IMEI, ICCID, numery kart dostępu i protokołów są wyraźnie
 * zmyślone (`SN-TEST-…`, `TEST-…`, `PZO/TEST/…`), telefony z puli
 * `+48 500 000 …`. Daty liczone od „dziś” przeglądarki (Europe/Warsaw), jak
 * w ekranie — harness otwarty w innym miesiącu wygląda tak samo.
 */

import type { QueryClient } from "@tanstack/react-query";

import { CATEGORY_LABELS } from "@/components/equipment/equipment-format";
import { FREE_ITEMS_FILTERS } from "@/components/equipment/IssueWizard";
import { itemFilters, type StockChip } from "@/components/equipment/ItemsTab";
import { editionKeys } from "@/lib/api/academy-edition";
import {
  equipmentKeys,
  type AssignmentRow,
  type EquipmentCategory,
  type EquipmentHolder,
  type EquipmentHolderKind,
  type EquipmentItem,
  type EquipmentItemDetail,
  type EquipmentItemStatus,
  type EquipmentModel,
  type EquipmentOwnership,
  type EquipmentProtocol,
  type EquipmentSummary,
  type EquipmentTask,
  type HolderEquipment,
  type ImportBatch,
  type ImportDecision,
  type ImportRow,
  type ImportRowData,
  type ItemFilters,
  type ProtocolLine,
  type ProtocolStatus,
  type ReturnCondition,
  type SignatureMethod,
} from "@/lib/api/equipment";
import {
  intuneKeys,
  type IntuneDiscrepancies,
  type IntuneStatus,
} from "@/lib/api/equipment-intune";
import { warsawToday } from "@/lib/warsaw-date";
import { formatIsoDatePl } from "@/lib/date-pl";

import { HR_CAST, HR_CLIENTS, HR_CONSULTANTS, shiftDay } from "../hr-fixtures";

export type EquipmentPhase = "before" | "after";

// ── Cennik ──────────────────────────────────────────────────────────────────

type ModelKey =
  | "vostro16"
  | "vostro32"
  | "latitude"
  | "thinkpad"
  | "clientT14"
  | "redmi"
  | "galaxy"
  | "monitor"
  | "sim"
  | "card"
  | "headset"
  | "vostroOld"
  | "monitorImport";

function model(
  id: number,
  category: EquipmentCategory,
  name: string,
  manufacturer: string | null,
  price: string | null,
  isActive = true,
): EquipmentModel {
  return { id, category, name, manufacturer, price_pln: price, is_active: isActive };
}

const MODELS: Record<ModelKey, EquipmentModel> = {
  vostro16: model(1, "laptop", "Dell Vostro 3530, 16 GB", "Dell", "2589.00"),
  vostro32: model(2, "laptop", "Dell Vostro 3530, 32 GB", "Dell", "2949.00"),
  latitude: model(3, "laptop", "Dell Latitude 5520, 32 GB", "Dell", "2997.76"),
  thinkpad: model(4, "laptop", "Lenovo ThinkPad E14", "Lenovo", "3120.00"),
  clientT14: model(5, "laptop", "Lenovo ThinkPad T14", "Lenovo", null),
  redmi: model(6, "telefon", "Xiaomi Redmi A5", "Xiaomi", "489.00"),
  galaxy: model(7, "telefon", "Samsung Galaxy A16", "Samsung", "897.76"),
  monitor: model(8, "monitor", "Dell P2422H, 24 cale", "Dell", "749.00"),
  sim: model(9, "karta_sim", "abonament firmowy", null, null),
  card: model(10, "karta_dostepu", "ogólny + biuro, pon–pt 7–19", null, null),
  headset: model(11, "akcesorium", "Słuchawki Jabra Evolve2 40 SE", "Jabra", "416.97"),
  vostroOld: model(12, "laptop", "Dell Vostro 3520, 8 GB", "Dell", "2199.00", false),
  // Ten sam monitor założony z importu Exceli innym zapisem — „Modele” liczą go razem.
  monitorImport: model(13, "monitor", "DELL P2422H, 24 cale", "DELL", "749.00"),
};

// ── Posiadacze ──────────────────────────────────────────────────────────────

export type HolderKey =
  | "anna"
  | "michal"
  | "karolina"
  | "bartosz"
  | "pawel"
  | "ola"
  | "tomasz"
  | "julia"
  | "ewa"
  | "kacper";

interface Holder extends EquipmentHolder {
  client_name: string | null;
}

interface Person {
  id: number;
  name: string;
  email: string;
}

function userHolder(person: Person): Holder {
  return {
    kind: "user",
    id: person.id,
    name: person.name,
    email: person.email,
    detail: "Konto NEXUSA",
    client_name: null,
  };
}

/** Kontrakt konsultanta — podpis jak w wyszukiwarce posiadaczy („Kontraktor · klient · start”). */
function contractHolder(person: Person, client: { name: string }, start: string): Holder {
  return {
    kind: "contract",
    id: person.id,
    name: person.name,
    email: person.email,
    detail: `Kontraktor · ${client.name} · start ${formatIsoDatePl(start)}`,
    client_name: client.name,
  };
}

// ── Egzemplarze ─────────────────────────────────────────────────────────────

interface ItemSpec {
  id: number;
  model: ModelKey;
  nr?: string;
  sn?: string;
  imei?: string;
  /** Dziewięć cyfr bez +48 (jak w bazie). */
  phone?: string;
  card?: string;
  status?: EquipmentItemStatus;
  ownership?: EquipmentOwnership;
  location?: string;
  notes?: string;
  /** Data zakupu: tyle dni temu. */
  bought?: number;
  holder?: HolderKey;
  protocol?: ProtocolKey;
}

type ProtocolKey = "P03" | "P04" | "P06" | "P07" | "P09" | "P11" | "P12" | "P13" | "P14";

/** Zestaw kontraktorki z makiety 13 — w chwili `before` leży jeszcze na stanie. */
const ANNA_KIT: Record<number, { location: string; accessories: string | null }> = {
  221: { location: "szafka B", accessories: "zasilacz, podkładka, mysz" },
  1102: { location: "szafka A", accessories: "kabel USB-C, kostka" },
  3145: { location: "sejf recepcji", accessories: null },
  4044: { location: "szafka A", accessories: "kabel USB-C" },
  5611: { location: "sejf recepcji", accessories: null },
};

/** Pozycje z tabeli makiety 12 najpierw, potem reszta wydanych i serwis. */
function registeredSpecs(today: string): ItemSpec[] {
  return [
    { id: 221, model: "vostro16", nr: "221", sn: "SN-TEST-0221", holder: "anna", protocol: "P14", bought: 30 },
    { id: 153, model: "latitude", nr: "153", sn: "SN-TEST-0153", holder: "ola", protocol: "P09", bought: 400 },
    { id: 1061, model: "redmi", nr: "T-061", imei: "TEST-0061", holder: "tomasz", protocol: "P04", bought: 380 },
    { id: 3077, model: "sim", phone: "500000077", holder: "tomasz", protocol: "P04", notes: "W telefonie T-061." },
    { id: 5588, model: "card", nr: "K-1588", card: "TEST-1588", holder: "tomasz", protocol: "P04" },
    { id: 159, model: "vostro32", nr: "159", sn: "SN-TEST-0159", location: "szafka B", bought: 60 },
    {
      id: 157,
      model: "vostro16",
      nr: "157",
      sn: "SN-TEST-0157",
      status: "serwis",
      location: "IT",
      notes: `Do przygotowania przez IT od ${formatIsoDatePl(shiftDay(today, -7))}: reinstalacja systemu.`,
      bought: 30,
    },
    { id: 1102, model: "galaxy", nr: "T-102", imei: "TEST-0102", holder: "anna", protocol: "P14", bought: 30 },
    { id: 3145, model: "sim", phone: "500000145", holder: "anna", protocol: "P14", notes: "W telefonie T-102." },
    { id: 4044, model: "headset", nr: "J-044", sn: "SN-TEST-J044", holder: "anna", protocol: "P14", bought: 90 },
    { id: 5611, model: "card", nr: "K-1611", card: "TEST-1611", holder: "anna", protocol: "P14" },
    { id: 147, model: "latitude", nr: "147", sn: "SN-TEST-0147", holder: "tomasz", protocol: "P04", bought: 420 },
    { id: 6031, model: "monitor", nr: "M-031", sn: "SN-TEST-M031", holder: "julia", protocol: "P12", bought: 200 },
    { id: 4039, model: "headset", nr: "J-039", sn: "SN-TEST-J039", holder: "ewa", protocol: "P13", bought: 200 },
    {
      id: 7007,
      model: "clientT14",
      sn: "SN-TEST-KL07",
      ownership: "klienta",
      holder: "karolina",
      notes: "Laptop klienta — wraca do klienta, nie do recepcji.",
    },
    { id: 3133, model: "sim", phone: "500000133", holder: "pawel", protocol: "P06" },
    {
      id: 1088,
      model: "galaxy",
      nr: "T-088",
      imei: "TEST-0088",
      status: "serwis",
      location: "serwis zewnętrzny",
      notes: "Pęknięty ekran, naprawa gwarancyjna.",
      bought: 150,
    },
  ];
}

function range(from: number, to: number): number[] {
  return Array.from({ length: to - from + 1 }, (_, index) => from + index);
}

const pad3 = (value: number) => String(value).padStart(3, "0");

/** Wolny sprzęt na stanie: 11 laptopów, 14 telefonów, 8 monitorów, 6 SIM, 4 karty, 9 słuchawek. */
function freeSpecs(): ItemSpec[] {
  return [
    { id: 154, model: "vostro16", nr: "154", sn: "SN-TEST-0154", location: "szafka B", bought: 90 },
    { id: 152, model: "vostro16", nr: "152", sn: "SN-TEST-0152", location: "szafka B", bought: 330 },
    ...range(148, 151).map((n): ItemSpec => ({
      id: n,
      model: "latitude",
      nr: String(n),
      sn: `SN-TEST-0${n}`,
      location: "szafka B",
      bought: 420,
    })),
    ...[95, 96, 97, 99].map((n): ItemSpec => ({
      id: n,
      model: "thinkpad",
      nr: pad3(n),
      sn: `SN-TEST-0${pad3(n)}`,
      location: "szafka C",
      bought: 700,
    })),
    ...range(62, 69).map((n): ItemSpec => ({
      id: 1000 + n,
      model: "redmi",
      nr: `T-0${n}`,
      imei: `TEST-00${n}`,
      location: "szafka A",
      bought: 380,
    })),
    ...range(103, 108).map((n): ItemSpec => ({
      id: 1000 + n,
      model: "galaxy",
      nr: `T-${n}`,
      imei: `TEST-0${n}`,
      location: "szafka A",
      bought: 30,
    })),
    ...range(32, 39).map((n): ItemSpec => ({
      id: 6000 + n,
      model: n >= 37 ? "monitorImport" : "monitor",
      nr: `M-0${n}`,
      sn: `SN-TEST-M0${n}`,
      location: "magazyn",
      bought: 200,
    })),
    ...[140, 141, 142, 143, 144, 146].map((n): ItemSpec => ({
      id: 3000 + n,
      model: "sim",
      phone: `500000${n}`,
      location: "sejf recepcji",
    })),
    ...range(1612, 1615).map((n): ItemSpec => ({
      id: 4000 + n,
      model: "card",
      nr: `K-${n}`,
      card: `TEST-${n}`,
      location: "sejf recepcji",
    })),
    ...range(45, 53).map((n): ItemSpec => ({
      id: 4000 + n,
      model: "headset",
      nr: `J-0${n}`,
      sn: `SN-TEST-J0${n}`,
      location: "szafka A",
      bought: 90,
    })),
  ];
}

// ── Protokoły ───────────────────────────────────────────────────────────────

interface ProtocolSpec {
  id: number;
  seq: string;
  kind: "wydanie" | "zwrot";
  daysAgo: number;
  holder: HolderKey;
  status: ProtocolStatus;
  signature: SignatureMethod;
  items: number[];
  /** Link do podpisu: utworzony tyle dni temu, użyty albo nie. */
  link?: { createdAgo: number; used: boolean };
  signer?: string;
  signedFile?: boolean;
  condition?: ReturnCondition;
  accessories?: Record<number, string>;
}

const PROTOCOLS: Record<ProtocolKey, ProtocolSpec> = {
  P03: { id: 5003, seq: "003", kind: "wydanie", daysAgo: 300, holder: "bartosz", status: "potwierdzony", signature: "papier", items: [152] },
  P04: { id: 5004, seq: "004", kind: "wydanie", daysAgo: 210, holder: "tomasz", status: "potwierdzony", signature: "papier", items: [147, 1061, 3077, 5588] },
  P06: {
    id: 5006,
    seq: "006",
    kind: "wydanie",
    daysAgo: 120,
    holder: "pawel",
    status: "potwierdzony",
    signature: "link",
    items: [3133],
    link: { createdAgo: 120, used: true },
    signer: HR_CONSULTANTS.pawel.name,
  },
  P07: { id: 5007, seq: "007", kind: "zwrot", daysAgo: 60, holder: "bartosz", status: "potwierdzony", signature: "papier", items: [152], condition: "sprawny" },
  P09: {
    id: 5009,
    seq: "009",
    kind: "wydanie",
    daysAgo: 40,
    holder: "ola",
    status: "potwierdzony",
    signature: "profil_zaufany",
    items: [153],
    signer: HR_CAST.ola.name,
    signedFile: true,
  },
  P11: { id: 5011, seq: "011", kind: "wydanie", daysAgo: 20, holder: "michal", status: "anulowany", signature: "brak", items: [6032] },
  P12: { id: 5012, seq: "012", kind: "wydanie", daysAgo: 2, holder: "julia", status: "oczekuje", signature: "brak", items: [6031] },
  P13: {
    id: 5013,
    seq: "013",
    kind: "wydanie",
    daysAgo: 1,
    holder: "ewa",
    status: "podpisany",
    signature: "link",
    items: [4039],
    link: { createdAgo: 1, used: true },
    signer: HR_CAST.ewa.name,
  },
  P14: {
    id: 5014,
    seq: "014",
    kind: "wydanie",
    daysAgo: 3,
    holder: "anna",
    status: "oczekuje",
    signature: "link",
    items: [221, 1102, 3145, 4044, 5611],
    link: { createdAgo: 3, used: false },
    accessories: Object.fromEntries(
      Object.entries(ANNA_KIT)
        .filter(([, kit]) => kit.accessories)
        .map(([id, kit]) => [id, kit.accessories as string]),
    ),
  },
};

/** Numer jak z backendu (`PZO/<rok>/<miesiąc>/<kolejny>`), z „TEST” w miejscu roku. */
function protocolNumber(spec: ProtocolSpec, date: string): string {
  return `PZO/TEST/${date.slice(5, 7)}/${spec.seq}`;
}

/** Zakończone wydanie, które zostawiło ślad w historii egzemplarza. */
const PAST_ASSIGNMENTS = [
  { itemId: 152, holder: "bartosz" as HolderKey, issue: "P03" as ProtocolKey, ret: "P07" as ProtocolKey },
];

// ── Złożenie danych ─────────────────────────────────────────────────────────

const CATEGORY_KEYS: EquipmentCategory[] = [
  "laptop",
  "telefon",
  "monitor",
  "karta_sim",
  "karta_dostepu",
  "akcesorium",
  "inne",
];
const STATUS_KEYS: EquipmentItemStatus[] = ["na_stanie", "wydany", "serwis", "wycofany", "zgubiony"];

export interface EquipmentHarnessData {
  today: string;
  models: EquipmentModel[];
  items: EquipmentItem[];
  details: EquipmentItemDetail[];
  protocols: EquipmentProtocol[];
  tasks: EquipmentTask[];
  holders: Record<HolderKey, EquipmentHolder>;
  holderEquipment: { holder: EquipmentHolder; data: HolderEquipment & { holder: EquipmentHolder } }[];
  /** Wszyscy, których znajdzie wyszukiwarka posiadaczy. */
  searchable: EquipmentHolder[];
  summary: EquipmentSummary;
  batch: ImportBatch;
  batchRows: ImportRow[];
}

/** Chwila ISO z dnia `YYYY-MM-DD` (ekran pokazuje tylko datę). */
const at = (day: string) => `${day}T08:00:00Z`;

/** Nazwa pozycji jak w protokole recepcji (`issuing.line_name` w backendzie). */
function lineName(item: EquipmentItem, accessories: string | null): string {
  let base: string;
  if (item.category === "karta_sim") {
    base = `Karta SIM +48 ${item.phone_number?.replace(/(\d{3})(\d{3})(\d{3})/, "$1 $2 $3") ?? ""}`.trim();
  } else if (item.category === "karta_dostepu") {
    base = `Karta dostępu nr ${item.access_card_number ?? item.inventory_number ?? ""}`.trim();
  } else {
    const prefix = ["laptop", "telefon", "monitor"].includes(item.category)
      ? `${CATEGORY_LABELS[item.category]} `
      : "";
    base = `${prefix}${item.model.name}${item.inventory_number ? ` (${item.inventory_number})` : ""}`;
  }
  return accessories ? `${base} ${accessories}` : base;
}

/** Numer w protokole (`issuing.line_identifier` w backendzie). */
function lineIdentifier(item: EquipmentItem): string | null {
  switch (item.category) {
    case "telefon":
      return item.imei ? `IMEI: ${item.imei}` : null;
    case "karta_sim":
      return item.iccid ? `ICCID: ${item.iccid}` : null;
    case "karta_dostepu":
      return item.access_card_number ?? item.inventory_number;
    case "laptop":
      return item.serial_number;
    default:
      return item.serial_number ? `S/N:${item.serial_number}` : null;
  }
}

function centsToPln(cents: number): string {
  return (cents / 100).toFixed(2);
}

export function buildEquipmentData(phase: EquipmentPhase): EquipmentHarnessData {
  const today = warsawToday();
  const ago = (days: number) => shiftDay(today, -days);
  const inDays = (days: number) => shiftDay(today, days);
  const { anna, michal, karolina, bartosz, pawel } = HR_CONSULTANTS;
  const { ola, tomasz, julia, ewa, kacper } = HR_CAST;

  const holders: Record<HolderKey, Holder> = {
    anna: contractHolder(anna, HR_CLIENTS.insurance, inDays(5)),
    michal: contractHolder(michal, HR_CLIENTS.bank, inDays(16)),
    karolina: contractHolder(karolina, HR_CLIENTS.telecom, ago(400)),
    bartosz: contractHolder(bartosz, HR_CLIENTS.bank, ago(330)),
    pawel: contractHolder(pawel, HR_CLIENTS.clinic, ago(200)),
    ola: userHolder(ola),
    tomasz: userHolder(tomasz),
    julia: userHolder(julia),
    ewa: userHolder(ewa),
    kacper: userHolder(kacper),
  };
  const plain = (holder: Holder): EquipmentHolder => ({
    kind: holder.kind,
    id: holder.id,
    name: holder.name,
    email: holder.email,
    detail: holder.detail,
  });

  // `before`: zestaw kontraktorki leży jeszcze na stanie, protokołu 014 nie ma.
  const specs = [...registeredSpecs(today), ...freeSpecs()].map((spec): ItemSpec => {
    const kit = ANNA_KIT[spec.id];
    if (phase === "before" && kit) {
      return { ...spec, holder: undefined, protocol: undefined, location: kit.location };
    }
    return spec;
  });
  const protocolSpecs = (Object.keys(PROTOCOLS) as ProtocolKey[])
    .filter((key) => !(phase === "before" && key === "P14"))
    .map((key) => ({ key, spec: PROTOCOLS[key] }));
  const protocolDate = (key: ProtocolKey) => ago(PROTOCOLS[key].daysAgo);
  const numberOf = (key: ProtocolKey) => protocolNumber(PROTOCOLS[key], protocolDate(key));

  const items: EquipmentItem[] = specs.map((spec) => {
    const m = MODELS[spec.model];
    const holder = spec.holder ? holders[spec.holder] : null;
    const protocol = spec.protocol ? PROTOCOLS[spec.protocol] : null;
    return {
      id: spec.id,
      model: m,
      category: m.category,
      inventory_number: spec.nr ?? null,
      serial_number: spec.sn ?? null,
      imei: spec.imei ?? null,
      iccid: spec.phone ? `TEST-ICCID-${spec.phone.slice(-4)}` : null,
      phone_number: spec.phone ?? null,
      access_card_number: spec.card ?? null,
      status: spec.status ?? (holder ? "wydany" : "na_stanie"),
      ownership: spec.ownership ?? "nasz",
      purchase_date: spec.bought != null ? ago(spec.bought) : null,
      location: spec.location ?? null,
      notes: spec.notes ?? null,
      holder: holder
        ? {
            kind: holder.kind,
            id: holder.id,
            name: holder.name,
            client_name: holder.client_name,
            assignment_id: 20000 + spec.id,
            issued_at: at(protocol ? ago(protocol.daysAgo) : ago(400)),
          }
        : null,
      issue_protocol:
        spec.protocol && protocol
          ? { id: protocol.id, number: numberOf(spec.protocol), status: protocol.status }
          : null,
    };
  });
  const byId = new Map(items.map((item) => [item.id, item]));
  const specById = new Map(specs.map((spec) => [spec.id, spec]));

  const assignmentRow = (
    item: EquipmentItem,
    holderKey: HolderKey,
    issue: ProtocolKey | null,
    ret: ProtocolKey | null,
    assignmentId: number,
  ): AssignmentRow => {
    const holder = holders[holderKey];
    const issued = issue ? protocolDate(issue) : ago(400);
    return {
      assignment_id: assignmentId,
      item_id: item.id,
      category: item.category,
      model_name: item.model.name,
      inventory_number: item.inventory_number,
      serial_number: item.serial_number,
      imei: item.imei,
      phone_number: item.phone_number,
      access_card_number: item.access_card_number,
      ownership: item.ownership,
      item_status: item.status,
      holder: { kind: holder.kind, id: holder.id, name: holder.name, client_name: holder.client_name },
      issued_at: at(issued),
      returned_at: ret ? at(protocolDate(ret)) : null,
      return_condition: ret ? (PROTOCOLS[ret].condition ?? "sprawny") : null,
      return_notes: null,
      issue_protocol: issue ? numberOf(issue) : null,
      issue_protocol_id: issue ? PROTOCOLS[issue].id : null,
      return_protocol: ret ? numberOf(ret) : null,
      return_protocol_id: ret ? PROTOCOLS[ret].id : null,
      unit_value: item.model.price_pln,
    };
  };

  const activeRow = (item: EquipmentItem): AssignmentRow | null => {
    const spec = specById.get(item.id);
    if (!spec?.holder) return null;
    return assignmentRow(item, spec.holder, spec.protocol ?? null, null, 20000 + item.id);
  };
  const pastRows = (item: EquipmentItem): AssignmentRow[] =>
    PAST_ASSIGNMENTS.filter((past) => past.itemId === item.id).map((past, index) =>
      assignmentRow(item, past.holder, past.issue, past.ret, 30000 + item.id * 10 + index),
    );

  const details: EquipmentItemDetail[] = items.map((item) => {
    const active = activeRow(item);
    return { ...item, history: [...(active ? [active] : []), ...pastRows(item)] };
  });

  const protocols: EquipmentProtocol[] = protocolSpecs.map(({ key, spec }) => {
    const date = protocolDate(key);
    const holder = holders[spec.holder];
    const lines: ProtocolLine[] = spec.items.map((itemId, index) => {
      const item = byId.get(itemId) as EquipmentItem;
      const noValue = item.category === "karta_sim" || item.category === "karta_dostepu";
      return {
        position: index + 1,
        item_id: item.id,
        category: item.category,
        name: lineName(item, spec.accessories?.[item.id] ?? null),
        identifier: lineIdentifier(item),
        quantity: 1,
        unit_value: spec.kind === "wydanie" && !noValue ? item.model.price_pln : null,
        condition: spec.kind === "zwrot" ? (spec.condition ?? "sprawny") : null,
        notes: null,
        // Okno „Popraw protokół” rozdziela nazwę z rejestru i dodatki recepcji.
        ...(spec.kind === "wydanie"
          ? { base_name: lineName(item, null), accessories: spec.accessories?.[item.id] ?? "" }
          : {}),
      };
    });
    const totalCents = lines.reduce(
      (sum, line) => sum + (line.unit_value ? Math.round(Number(line.unit_value) * 100) : 0),
      0,
    );
    const signed = spec.status === "podpisany" || spec.status === "potwierdzony";
    return {
      id: spec.id,
      kind: spec.kind,
      number: numberOf(key),
      protocol_date: date,
      holder: { kind: holder.kind, id: holder.id, name: holder.name, email: holder.email },
      issuer_name: HR_CAST.zofia.name,
      total_value: centsToPln(totalCents),
      status: spec.status,
      signature_method: spec.signature,
      signed_at: signed ? at(shiftDay(date, spec.status === "podpisany" ? 1 : 2)) : null,
      signer_name: spec.signer ?? (signed ? holder.name : null),
      has_signed_file: spec.signedFile ?? spec.signature === "papier",
      confirmed_at: spec.status === "potwierdzony" ? at(shiftDay(date, 2)) : null,
      template_version: "recepcja-1",
      created_at: at(date),
      link: spec.link
        ? {
            created_at: at(ago(spec.link.createdAgo)),
            expires_at: at(ago(spec.link.createdAgo - 14)),
            used_at: spec.link.used ? at(shiftDay(date, 1)) : null,
          }
        : null,
      lines,
    };
  });

  const task = (
    id: number,
    kind: EquipmentTask["kind"],
    title: string,
    dueOn: string,
    holder: Holder,
    details: Record<string, unknown>,
    extra: Partial<EquipmentTask> = {},
  ): EquipmentTask => ({
    id,
    kind,
    status: "otwarte",
    title,
    due_on: dueOn,
    overdue_days: 0,
    holder: { kind: holder.kind, id: holder.id, name: holder.name },
    protocol: null,
    details,
    ...extra,
  });
  const tasks: EquipmentTask[] = [
    task(801, "wydanie", `Przygotuj zestaw biura: ${kacper.name}`, inDays(16), holders.kacper, {
      start_date: inDays(16),
      reason: "wejscie",
    }),
    phase === "before"
      ? task(802, "wydanie", `Przygotuj zestaw kontraktora: ${anna.name}`, today, holders.anna, {
          start_date: inDays(5),
          client_name: HR_CLIENTS.insurance.name,
          reason: "start_kontraktu",
        })
      : task(803, "wydanie", `Przygotuj zestaw kontraktora: ${michal.name}`, inDays(7), holders.michal, {
          start_date: inDays(16),
          client_name: HR_CLIENTS.bank.name,
          reason: "start_kontraktu",
        }),
    ...(phase === "after"
      ? [
          task(
            804,
            "podpis",
            `Podpis protokołu: ${anna.name}`,
            shiftDay(protocolDate("P14"), 3),
            holders.anna,
            {},
            {
              protocol: {
                id: PROTOCOLS.P14.id,
                number: numberOf("P14"),
                status: PROTOCOLS.P14.status,
                categories: PROTOCOLS.P14.items.map((id) => (byId.get(id) as EquipmentItem).category),
                client_name: holders.anna.client_name,
                link_sent_on: ago(PROTOCOLS.P14.link?.createdAgo ?? 0),
              },
            },
          ),
        ]
      : []),
    task(805, "zwrot", `Odbierz sprzęt: ${tomasz.name}`, inDays(44), holders.tomasz, {
      last_day: inDays(44),
      items: 4,
      reason: "odejscie",
    }),
    task(806, "zwrot", `Odbierz sprzęt: ${karolina.name}`, inDays(14), holders.karolina, {
      end_date: inDays(14),
      client_name: HR_CLIENTS.telecom.name,
      items: 1,
      client_items: 1,
      reason: "koniec_wspolpracy",
    }),
    task(
      807,
      "zwrot",
      `Odbierz sprzęt: ${pawel.name}`,
      ago(6),
      holders.pawel,
      { end_date: ago(6), client_name: HR_CLIENTS.clinic.name, items: 1, client_items: 0, reason: "koniec_wspolpracy" },
      { overdue_days: 6 },
    ),
  ];

  const holderEquipment = (Object.keys(holders) as HolderKey[]).map((key) => {
    const holder = plain(holders[key]);
    const active = items
      .filter((item) => specById.get(item.id)?.holder === key)
      .map((item) => activeRow(item) as AssignmentRow);
    const history = PAST_ASSIGNMENTS.filter((past) => past.holder === key).map((past, index) =>
      assignmentRow(byId.get(past.itemId) as EquipmentItem, key, past.issue, past.ret, 30000 + past.itemId * 10 + index),
    );
    const refs = protocols
      .filter((protocol) => protocol.holder.kind === holder.kind && protocol.holder.id === holder.id)
      .map((protocol) => ({
        id: protocol.id,
        number: protocol.number,
        kind: protocol.kind,
        status: protocol.status,
        protocol_date: protocol.protocol_date,
      }));
    return { holder, data: { holder, active, history, protocols: refs } };
  });

  const searchable: EquipmentHolder[] = [
    ...Object.values(HR_CAST).map((person) => plain(userHolder(person))),
    ...(["anna", "michal", "karolina", "bartosz", "pawel"] as const).map((key) => plain(holders[key])),
    {
      kind: "external",
      id: 61,
      name: "Anna Zewnętrzna",
      email: "anna.zewnetrzna@example.com",
      detail: "Audytorka IT, umowa zlecenie",
    },
  ];

  const { batch, rows: batchRows } = importBatch(ago(5));
  const free = items.filter((item) => item.status === "na_stanie" && item.holder == null);
  const freeBy = (category: EquipmentCategory) =>
    free.filter((item) => item.category === category).length;
  const statusCount = (status: EquipmentItemStatus) =>
    items.filter((item) => item.status === status).length;
  const waitingProtocols = protocols.filter(
    (p) => p.status === "oczekuje" || p.status === "podpisany",
  );
  const byCategory = Object.fromEntries(
    CATEGORY_KEYS.map((category) => [
      category,
      Object.fromEntries(
        STATUS_KEYS.map((status) => [
          status,
          items.filter((item) => item.category === category && item.status === status).length,
        ]),
      ),
    ]),
  ) as EquipmentSummary["by_category"];
  const summary: EquipmentSummary = {
    free_by_category: {
      laptop: freeBy("laptop"),
      telefon: freeBy("telefon"),
      monitor: freeBy("monitor"),
      karta_sim: freeBy("karta_sim"),
      karta_dostepu: freeBy("karta_dostepu"),
      akcesorium: freeBy("akcesorium"),
      inne: freeBy("inne"),
    },
    by_status: {
      na_stanie: statusCount("na_stanie"),
      wydany: statusCount("wydany"),
      serwis: statusCount("serwis"),
      wycofany: statusCount("wycofany"),
      zgubiony: statusCount("zgubiony"),
    },
    by_category: byCategory,
    protocols_waiting: waitingProtocols.length,
    oldest_waiting_on:
      waitingProtocols.map((p) => p.protocol_date).sort()[0] ?? null,
    unsigned_items: items.filter(
      (item) =>
        item.holder != null &&
        (item.issue_protocol?.status === "oczekuje" || item.issue_protocol?.status === "podpisany"),
    ).length,
    import_unresolved: batch.summary.counts?.do_wyjasnienia ?? 0,
  };

  const models = Object.values(MODELS).map((m) => ({
    ...m,
    items: items.filter((item) => item.model.id === m.id).length,
  }));

  return {
    today,
    models,
    items,
    details,
    protocols,
    tasks,
    holders: Object.fromEntries(
      (Object.keys(holders) as HolderKey[]).map((key) => [key, plain(holders[key])]),
    ) as Record<HolderKey, EquipmentHolder>,
    holderEquipment,
    searchable,
    summary,
    batch,
    batchRows,
  };
}

// ── Import pliku recepcji ───────────────────────────────────────────────────

const UNRESOLVED_TEMPLATES: { sheet: string; data: (n: number) => ImportRowData; reason: string }[] = [
  {
    sheet: "Telefony",
    data: (n) => ({
      category: "telefon",
      model: "Xiaomi Redmi A5",
      inventory_number: `T-0${n}`,
      imei: `TEST-00${n}`,
      holder_text: "dawny pracownik",
      item_status: "na_stanie",
    }),
    reason: "Osoba z pliku nie ma konta w NEXUSIE",
  },
  {
    sheet: "Karty SIM",
    data: (n) => ({
      category: "karta_sim",
      model: "abonament firmowy",
      phone_number: `5000002${String(n).padStart(2, "0")}`,
      holder_text: "projekt?",
      item_status: "na_stanie",
    }),
    reason: "Numer SIM bez osoby i bez telefonu",
  },
  {
    sheet: "Monitory",
    data: (n) => ({
      category: "monitor",
      model: "Dell P2422H, 24 cale",
      inventory_number: `M-0${n}`,
      serial_number: `SN-TEST-M0${n}`,
      holder_text: "sala 2",
      item_status: "na_stanie",
    }),
    reason: "Miejsce zamiast osoby — sprawdź, czy sprzęt jest na stanie",
  },
  {
    sheet: "Laptopy",
    data: (n) => ({
      category: "laptop",
      model: "Lenovo ThinkPad E14",
      inventory_number: pad3(n),
      serial_number: `SN-TEST-0${pad3(n)}`,
      holder_text: "A. P.",
      item_status: "wydany",
    }),
    reason: "Dwie osoby pasują do inicjałów",
  },
];

function importBatch(createdOn: string): { batch: ImportBatch; rows: ImportRow[] } {
  const rows: ImportRow[] = [];
  const push = (
    sheet: string,
    data: ImportRowData,
    decision: ImportDecision,
    reason: string | null,
    holderName: string | null = null,
  ) => {
    rows.push({
      id: 70000 + rows.length,
      sheet,
      row_number: 3 + rows.filter((row) => row.sheet === sheet).length,
      data,
      decision,
      reason,
      holder_user_id: null,
      holder_contract_id: null,
      holder_name: holderName,
      item_id: null,
      applied: false,
    });
  };

  // 31 do wyjaśnienia — pierwszy wiersz z makiety 12 (laptop 098, osoba „nieznany”).
  push(
    "Laptopy",
    {
      category: "laptop",
      model: "Lenovo ThinkPad E14",
      inventory_number: "098",
      serial_number: "SN-TEST-0098",
      holder_text: "nieznany",
      item_status: "na_stanie",
    },
    "do_wyjasnienia",
    "Nie wiadomo, u kogo jest sprzęt",
  );
  for (let index = 0; index < 30; index += 1) {
    const template = UNRESOLVED_TEMPLATES[index % UNRESOLVED_TEMPLATES.length];
    push(template.sheet, template.data(70 + index), "do_wyjasnienia", template.reason);
  }
  // 3 konflikty z rejestrem.
  for (const n of [154, 159, 148]) {
    push(
      "Laptopy",
      { category: "laptop", model: "Dell Vostro 3530, 16 GB", inventory_number: String(n), serial_number: `SN-TEST-0${n}` },
      "konflikt",
      `Numer ${n} jest już w rejestrze z innym numerem seryjnym`,
    );
  }
  // 7 pominiętych.
  for (let index = 0; index < 7; index += 1) {
    push(
      "Archiwum",
      { category: "inne", model: "Drukarka biurowa", status_text: "zutylizowany" },
      "pomin",
      "Sprzęt zutylizowany w pliku",
    );
  }
  // 64 do przyjęcia — wolny sprzęt i sprzęt u osób z kontem.
  const owners = [HR_CAST.ola, HR_CAST.ewa, HR_CAST.julia, HR_CAST.adam, HR_CAST.marta, HR_CAST.kamil];
  for (let index = 0; index < 64; index += 1) {
    const owner = index % 3 === 0 ? owners[index % owners.length] : null;
    push(
      index % 2 === 0 ? "Laptopy" : "Telefony",
      index % 2 === 0
        ? {
            category: "laptop",
            model: "Dell Latitude 5520, 32 GB",
            inventory_number: String(300 + index),
            serial_number: `SN-TEST-0${300 + index}`,
            holder_text: owner ? owner.name : "szafka B",
            item_status: owner ? "wydany" : "na_stanie",
          }
        : {
            category: "telefon",
            model: "Samsung Galaxy A16",
            inventory_number: `T-${300 + index}`,
            imei: `TEST-0${300 + index}`,
            holder_text: owner ? owner.name : "szafka A",
            item_status: owner ? "wydany" : "na_stanie",
          },
      "przyjmij",
      null,
      owner?.name ?? null,
    );
  }

  const counts: Partial<Record<ImportDecision, number>> = {};
  for (const row of rows) counts[row.decision] = (counts[row.decision] ?? 0) + 1;
  const sheets = [...new Set(rows.map((row) => row.sheet))].map((name) => ({
    name,
    header_row: 2,
    rows: rows.filter((row) => row.sheet === name).length,
    skipped: null,
  }));
  return {
    rows,
    batch: {
      id: 41,
      file_name: "Ewidencja_sprzetu_recepcja.xlsx",
      status: "nowa",
      summary: {
        sheets,
        removed_columns: [
          { sheet: "Laptopy", column: "Klucz BitLocker", reason: "klucz odzyskiwania dysku" },
          { sheet: "Karty SIM", column: "PUK", reason: "kod odblokowania karty" },
          { sheet: "Telefony", column: "PESEL", reason: "dane osobowe" },
        ],
        ignored_columns: [],
        removed_values: { bitlocker: 48, puk: 23, pesel: 11 },
        counts,
      },
      created_at: at(createdOn),
      applied_at: null,
      pending: counts.do_wyjasnienia ?? 0,
    },
  };
}

// ── Zasiew cache ────────────────────────────────────────────────────────────

const HOLDER_FILTERS: ("none" | EquipmentHolderKind)[] = ["none", "user", "contract", "external", "academy"];
const STOCK_CHIPS: StockChip[] = [
  "all",
  "wydany",
  "na_stanie",
  "serwis",
  "unsigned",
  "wycofany",
  "zgubiony",
];
const DECISIONS: ImportDecision[] = ["przyjmij", "do_wyjasnienia", "konflikt", "pomin"];

/** Odpowiedź `GET /api/equipment/items` dla filtrów listy (bez szukania tekstem). */
function itemsFor(items: EquipmentItem[], filters: ItemFilters) {
  const rows = items.filter(
    (item) =>
      (!filters.category || item.category === filters.category) &&
      (!filters.status || item.status === filters.status) &&
      (!filters.holder ||
        (filters.holder === "none" ? item.holder == null : item.holder?.kind === filters.holder)) &&
      (!filters.free || (item.status === "na_stanie" && item.holder == null)) &&
      (!filters.unsigned ||
        (item.holder != null &&
          (item.issue_protocol?.status === "oczekuje" ||
            item.issue_protocol?.status === "podpisany"))),
  );
  return { items: rows, total: rows.length };
}

/** Szukane frazy okna „Wydaj sprzęt” / „Przyjmij zwrot” (każdy prefiks od dwóch liter). */
const HOLDER_SEARCHES = [
  HR_CONSULTANTS.anna.name,
  HR_CONSULTANTS.anna.name.toLowerCase(),
  HR_CONSULTANTS.michal.name,
  HR_CAST.kacper.name,
  HR_CAST.tomasz.name,
];

/**
 * Zasiewa każdy klucz, o który ekran „Sprzęt” pyta przy wejściu i po klikach
 * głównej ścieżki: liczniki, rejestr (bez filtra i z jednym filtrem), szczegół
 * każdej pozycji, wolny sprzęt kreatora, sprzęt każdego posiadacza, protokoły
 * (każdy stan × rodzaj i szczegół), zadania, cennik, partia importu (każda
 * decyzja), Intune bez podłączenia i pusta Akademia.
 */
export function seedEquipment(client: QueryClient, data: EquipmentHarnessData): void {
  client.setQueryData(equipmentKeys.summary, data.summary);
  client.setQueryData(equipmentKeys.models, data.models);

  // „Ewidencja”: kafel kategorii × chip stanu (filtry jak `itemFilters` w ItemsTab)
  // i lista „Posiadacz” bez kategorii.
  for (const category of ["", ...CATEGORY_KEYS] as (EquipmentCategory | "")[]) {
    for (const chip of STOCK_CHIPS) {
      const filters = itemFilters(chip, category, "", "");
      client.setQueryData(equipmentKeys.items(filters), itemsFor(data.items, filters));
    }
  }
  for (const holder of HOLDER_FILTERS) {
    const filters = itemFilters("all", "", holder, "");
    client.setQueryData(equipmentKeys.items(filters), itemsFor(data.items, filters));
  }
  // Kreator wydania: cały wolny sprzęt jednym zapytaniem.
  client.setQueryData(equipmentKeys.items(FREE_ITEMS_FILTERS), itemsFor(data.items, { free: true }));
  for (const detail of data.details) client.setQueryData(equipmentKeys.item(detail.id), detail);

  for (const { holder, data: equipment } of data.holderEquipment) {
    client.setQueryData(equipmentKeys.holder(holder.kind, holder.id), equipment);
  }
  for (const phrase of HOLDER_SEARCHES) {
    for (let length = 2; length <= phrase.length; length += 1) {
      const term = phrase.slice(0, length).trim();
      if (term.length < 2) continue;
      const needle = term.toLowerCase();
      client.setQueryData(
        equipmentKeys.holders(term),
        data.searchable.filter((holder) => holder.name.toLowerCase().includes(needle)),
      );
    }
  }

  const waiting = (status: ProtocolStatus) => status === "oczekuje" || status === "podpisany";
  for (const status of ["", "waiting", "potwierdzony", "anulowany"]) {
    for (const kind of ["", "wydanie", "zwrot"]) {
      const rows = data.protocols
        .filter((p) => !status || (status === "waiting" ? waiting(p.status) : p.status === status))
        .filter((p) => !kind || p.kind === kind)
        .sort((a, b) => b.protocol_date.localeCompare(a.protocol_date))
        .map((protocol) => ({ ...protocol, lines: undefined }));
      client.setQueryData(equipmentKeys.protocols(status, kind, ""), rows);
    }
  }
  for (const protocol of data.protocols) {
    client.setQueryData(equipmentKeys.protocol(protocol.id), protocol);
  }

  client.setQueryData(equipmentKeys.tasks("otwarte"), data.tasks);

  client.setQueryData(equipmentKeys.imports, [data.batch]);
  client.setQueryData(equipmentKeys.importBatch(data.batch.id, ""), {
    ...data.batch,
    rows: data.batchRows,
  });
  for (const decision of DECISIONS) {
    client.setQueryData(equipmentKeys.importBatch(data.batch.id, decision), {
      ...data.batch,
      rows: data.batchRows.filter((row) => row.decision === decision),
    });
  }

  const intuneStatus: IntuneStatus = {
    mode: "off",
    health: "disabled",
    last_run_at: null,
    last_success_at: null,
    device_count: 0,
    error: null,
    error_code: null,
  };
  const intuneReport: IntuneDiscrepancies = {
    rows: [],
    resolved: [],
    counts: {
      zniknal_z_intune: 0,
      brak_w_ewidencji: 0,
      inny_posiadacz: 0,
      brak_w_intune: 0,
      zgodne: 0,
      wyjasnione: 0,
    },
    checked: false,
    devices: 0,
  };
  client.setQueryData(intuneKeys.status, intuneStatus);
  client.setQueryData(intuneKeys.discrepancies, intuneReport);

  // Zakładka „Akademia” (`EditionLogistics`): brak uczestników po zadaniu.
  client.setQueryData(editionKeys.list(null), []);
}
