// Hurtowe wydanie zestawów edycji Akademii — czyste funkcje (testowane bez renderowania).
//
// Zestaw = lista modeli z cennika (np. laptop, telefon, słuchawki). Każdy
// uczestnik dostaje po jednym wolnym egzemplarzu każdego modelu; NEXUS
// proponuje przydział po numerze ewidencyjnym, recepcja może go zmienić.

import { CATEGORY_ORDER, itemNumber } from "@/components/equipment/equipment-format";
import type { EquipmentCategory, EquipmentItem } from "@/lib/api/equipment";

export interface FreeModel {
  modelId: number;
  name: string;
  category: EquipmentCategory;
  free: number;
}

/** Przydział: uczestnik → model → egzemplarz (`null` = zabrakło wolnego). */
export type KitPlan = Readonly<Record<number, Readonly<Record<number, number | null>>>>;

function byNumber(a: EquipmentItem, b: EquipmentItem): number {
  return itemNumber(a).localeCompare(itemNumber(b), "pl", { numeric: true }) || a.id - b.id;
}

/** Modele z wolnymi egzemplarzami, w kolejności kategorii rejestru. */
export function freeModels(items: readonly EquipmentItem[]): FreeModel[] {
  const models = new Map<number, FreeModel>();
  for (const item of items) {
    const known = models.get(item.model.id);
    if (known) {
      models.set(item.model.id, { ...known, free: known.free + 1 });
    } else {
      models.set(item.model.id, {
        modelId: item.model.id,
        name: item.model.name,
        category: item.category,
        free: 1,
      });
    }
  }
  return [...models.values()].sort(
    (a, b) =>
      CATEGORY_ORDER.indexOf(a.category) - CATEGORY_ORDER.indexOf(b.category) ||
      a.name.localeCompare(b.name, "pl"),
  );
}

/** Wolne egzemplarze modelu po numerze ewidencyjnym. */
export function itemsOfModel(items: readonly EquipmentItem[], modelId: number): EquipmentItem[] {
  return items.filter((item) => item.model.id === modelId).sort(byNumber);
}

/** Propozycja: kolejni uczestnicy dostają kolejne wolne egzemplarze każdego modelu. */
export function proposeKits(
  applicationIds: readonly number[],
  modelIds: readonly number[],
  items: readonly EquipmentItem[],
): KitPlan {
  const pools = new Map(modelIds.map((id) => [id, itemsOfModel(items, id)]));
  const plan: Record<number, Record<number, number | null>> = {};
  applicationIds.forEach((applicationId, index) => {
    plan[applicationId] = Object.fromEntries(
      modelIds.map((modelId) => [modelId, pools.get(modelId)?.[index]?.id ?? null]),
    );
  });
  return plan;
}

/**
 * Zmiana egzemplarza w komórce. Egzemplarz użyty już u innej osoby zamienia
 * się z nią miejscami — ta sama pozycja nigdy nie trafia do dwóch protokołów.
 */
export function assignItem(
  plan: KitPlan,
  applicationId: number,
  modelId: number,
  itemId: number | null,
): KitPlan {
  const previous = plan[applicationId]?.[modelId] ?? null;
  const next: Record<number, Record<number, number | null>> = {};
  for (const [key, row] of Object.entries(plan)) {
    const id = Number(key);
    const cell = row[modelId] ?? null;
    if (id === applicationId) {
      next[id] = { ...row, [modelId]: itemId };
    } else if (itemId != null && cell === itemId) {
      next[id] = { ...row, [modelId]: previous };
    } else {
      next[id] = row;
    }
  }
  return next;
}

/** Kto ma komplet (każdy model zestawu), a komu czegoś brakuje. */
export function splitComplete(
  plan: KitPlan,
  modelIds: readonly number[],
): { ready: number[]; incomplete: number[] } {
  const ready: number[] = [];
  const incomplete: number[] = [];
  for (const [key, row] of Object.entries(plan)) {
    const complete = modelIds.length > 0 && modelIds.every((modelId) => row[modelId] != null);
    (complete ? ready : incomplete).push(Number(key));
  }
  return { ready, incomplete };
}

/** Treść żądania hurtowego wydania — tylko uczestnicy z kompletem. */
export function kitPayload(
  plan: KitPlan,
  modelIds: readonly number[],
  ready: readonly number[],
): { application_id: number; lines: { item_id: number }[] }[] {
  return ready.map((applicationId) => ({
    application_id: applicationId,
    lines: modelIds.flatMap((modelId) => {
      const itemId = plan[applicationId]?.[modelId];
      return itemId == null ? [] : [{ item_id: itemId }];
    }),
  }));
}
