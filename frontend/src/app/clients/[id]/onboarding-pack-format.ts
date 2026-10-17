// Pakiet klienta „Wejście u klienta” (etap 3, O2) — czysta logika zakładki:
// termin względem startu, szkic edycji i to, co idzie do zapisu.
// Lustro reguł `backend/app/services/hr/client_pack.py`.

import type {
  ClientPack,
  ClientPackSave,
  PackAssignee,
  PackItem,
  PackItemInput,
} from "@/lib/api/client-onboarding";
import type { EquipmentProvider } from "@/lib/api/equipment";

export type Timing = "before" | "day" | "after";

/** Najdalsze przesunięcie (dni robocze) — jak `MAX_OFFSET_BEFORE/AFTER` ścieżek. */
export const MAX_DAYS_BEFORE = 60;
export const MAX_DAYS_AFTER = 120;
const TIME = /^([01]?\d|2[0-3]):([0-5]\d)$/;

export const TIMING_LABELS: Record<Timing, string> = {
  before: "przed startem",
  day: "w dniu startu",
  after: "po starcie",
};

export const ASSIGNEE_LABELS: Record<PackAssignee, string> = {
  care_owner: "Opiekun",
  delivery_lead: "Delivery Lead",
  administration: "Administracja",
  it: "IT",
  reception: "Recepcja",
};

export function splitOffset(offset: number | null | undefined): { timing: Timing; days: number } {
  if (!offset) return { timing: "day", days: 0 };
  return offset < 0 ? { timing: "before", days: -offset } : { timing: "after", days: offset };
}

export function joinOffset(timing: Timing, days: number): number {
  if (timing === "day") return 0;
  const safe = Math.max(1, Math.round(Math.abs(days) || 1));
  return timing === "before" ? -Math.min(safe, MAX_DAYS_BEFORE) : Math.min(safe, MAX_DAYS_AFTER);
}

function workdays(count: number): string {
  return count === 1 ? "1 dzień rob." : `${count} dni rob.`;
}

/** „5 dni rob. przed startem”, „w dniu startu”, „do 7 dni rob. po starcie”. */
export function offsetLabel(offset: number | null | undefined): string {
  const { timing, days } = splitOffset(offset);
  if (timing === "day") return TIMING_LABELS.day;
  if (timing === "before") return `${workdays(days)} przed startem`;
  return `do ${workdays(days)} po starcie`;
}

export interface ItemDraft {
  key: string;
  name: string;
  note: string;
  assignee: PackAssignee;
  timing: Timing;
  days: number;
  required: boolean;
  requiresFile: boolean;
}

export interface PackDraft {
  provider: EquipmentProvider;
  issueTemplateId: number | null;
  returnTemplateId: number | null;
  ours: ItemDraft[];
  client: ItemDraft[];
  firstDay: { contactId: number | null; place: string; time: string; bring: string };
  documents: ItemDraft[];
  accesses: ItemDraft[];
}

let keySeq = 0;
export function newKey(): string {
  keySeq += 1;
  return `item-${keySeq}`;
}

export function emptyItem(defaults: Partial<ItemDraft> = {}): ItemDraft {
  return {
    key: newKey(),
    name: "",
    note: "",
    assignee: "care_owner",
    timing: "before",
    days: 5,
    required: true,
    requiresFile: false,
    ...defaults,
  };
}

function itemDraft(item: PackItem): ItemDraft {
  const { timing, days } = splitOffset(item.offset_days);
  return {
    key: newKey(),
    name: item.name,
    note: item.note ?? "",
    assignee: item.assignee ?? "care_owner",
    timing,
    days: days || 1,
    required: item.required,
    requiresFile: item.requires_file,
  };
}

export function draftFromPack(pack: ClientPack): PackDraft {
  return {
    provider: pack.equipment.provider,
    issueTemplateId: pack.equipment.issue_template_id,
    returnTemplateId: pack.equipment.return_template_id,
    ours: pack.equipment.ours.map(itemDraft),
    client: pack.equipment.client.map(itemDraft),
    firstDay: {
      contactId: pack.first_day.contact_id,
      place: pack.first_day.place ?? "",
      time: pack.first_day.time ?? "",
      bring: pack.first_day.bring ?? "",
    },
    documents: pack.documents.map(itemDraft),
    accesses: pack.accesses.map(itemDraft),
  };
}

const text = (value: string): string | null => value.trim().replace(/\s+/g, " ") || null;

function thingInput(item: ItemDraft): PackItemInput {
  return { name: item.name.trim(), note: text(item.note) };
}

function documentInput(item: ItemDraft): PackItemInput {
  return {
    ...thingInput(item),
    offset_days: joinOffset(item.timing, item.days),
    required: item.required,
    requires_file: item.requiresFile,
  };
}

function accessInput(item: ItemDraft): PackItemInput {
  return {
    ...thingInput(item),
    assignee: item.assignee,
    offset_days: joinOffset(item.timing, item.days),
    required: item.required,
  };
}

/** Części, które ta osoba może zapisać (recepcja — tylko sprzęt). */
export function saveFromDraft(
  draft: PackDraft,
  canEdit: ClientPack["can_edit"],
  version: number,
): ClientPackSave {
  const payload: ClientPackSave = { expected_version: version || undefined };
  if (canEdit.equipment) {
    payload.equipment = {
      provider: draft.provider,
      issue_template_id: draft.issueTemplateId,
      return_template_id: draft.returnTemplateId,
      ours: draft.ours.map(thingInput),
      client: draft.client.map(thingInput),
    };
  }
  if (canEdit.rest) {
    payload.first_day = {
      contact_id: draft.firstDay.contactId,
      place: text(draft.firstDay.place),
      time: text(draft.firstDay.time),
      bring: text(draft.firstDay.bring),
    };
    payload.documents = draft.documents.map(documentInput);
    payload.accesses = draft.accesses.map(accessInput);
  }
  return payload;
}

/** Zmiana względem zapisanego pakietu (bez numeru wersji i kluczy wierszy). */
export function isDirty(
  saved: PackDraft,
  current: PackDraft,
  canEdit: ClientPack["can_edit"],
): boolean {
  const strip = (draft: PackDraft) => {
    const { expected_version: _version, ...rest } = saveFromDraft(draft, canEdit, 0);
    return JSON.stringify(rest);
  };
  return strip(saved) !== strip(current);
}

/** Pierwszy brak, który zatrzymałby zapis na serwerze (albo `null`). */
export function draftProblem(draft: PackDraft): string | null {
  const rows = [...draft.ours, ...draft.client, ...draft.documents, ...draft.accesses];
  if (rows.some((row) => !row.name.trim())) {
    return "Uzupełnij nazwę każdej pozycji albo ją usuń.";
  }
  const time = draft.firstDay.time.trim();
  if (time && !TIME.test(time)) return "Godzinę wpisz jak 9:00 albo 13:30.";
  return null;
}
