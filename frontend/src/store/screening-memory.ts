import { useEffect, useMemo } from "react";
import { create } from "zustand";

import { memoryHasEntries, memoryPairSummary, type ScreeningMemory } from "@/lib/screening-memory";
import {
  SCREENING_MEMORY_TTL_MS,
  readStoredScreeningMemory,
  writeStoredScreeningMemory,
} from "@/lib/screening-memory-storage";

/**
 * Pamięć rozmowy screeningowej per osoba pisząca i kandydat (16.10.2026,
 * D1 A / D3 B). Formularze piszą do niej przy każdej zmianie i czytają z niej
 * przy starcie, panel osoby pokazuje z niej „N odpowiedzi w pamięci”.
 * Kopia w `sessionStorage` (lib/screening-memory-storage.ts) przeżywa
 * zamknięcie panelu i odświeżenie strony.
 */
interface ScreeningMemoryState {
  entries: Record<string, ScreeningMemory | null>;
}

export const useScreeningMemoryStore = create<ScreeningMemoryState>(() => ({ entries: {} }));

const entryKey = (userId: number | undefined, candidateId: number) => `${userId ?? "anon"}:${candidateId}`;

/** Wpis z karty przeglądarki to dane z zewnątrz — zepsuty kształt = brak pamięci. */
function isMemory(value: unknown): value is ScreeningMemory {
  if (!value || typeof value !== "object") return false;
  const m = value as Partial<ScreeningMemory>;
  return (
    m.v === 1 &&
    typeof m.updatedAt === "number" &&
    typeof m.anchorJobId === "number" &&
    Array.isArray(m.selected) &&
    m.selected.every((id) => typeof id === "number") &&
    typeof m.pairs === "object" &&
    m.pairs !== null &&
    typeof m.shared === "object" &&
    m.shared !== null &&
    typeof m.clients === "object" &&
    m.clients !== null &&
    typeof m.origins === "object" &&
    m.origins !== null &&
    (m.note === null || typeof m.note === "object")
  );
}

/** Pamięć tej rozmowy albo `null` — woła się w efektach i obsłudze zdarzeń, nie w renderze. */
export function readScreeningMemory(
  userId: number | undefined,
  candidateId: number,
  now: number = Date.now(),
): ScreeningMemory | null {
  if (candidateId <= 0) return null;
  const key = entryKey(userId, candidateId);
  const entries = useScreeningMemoryStore.getState().entries;
  const loaded = key in entries;
  let memory: ScreeningMemory | null = loaded ? entries[key] : null;
  if (!loaded) {
    const stored = readStoredScreeningMemory(userId, candidateId, now);
    memory = isMemory(stored) ? stored : null;
  }
  if (memory && now - memory.updatedAt > SCREENING_MEMORY_TTL_MS) {
    memory = null;
    writeStoredScreeningMemory(userId, candidateId, null);
  }
  if (!loaded || entries[key] !== memory) {
    useScreeningMemoryStore.setState((s) => ({ entries: { ...s.entries, [key]: memory } }));
  }
  return memory;
}

export function writeScreeningMemory(
  userId: number | undefined,
  candidateId: number,
  update: (prev: ScreeningMemory | null) => ScreeningMemory | null,
): ScreeningMemory | null {
  if (candidateId <= 0) return null;
  const prev = readScreeningMemory(userId, candidateId);
  const next = update(prev);
  const stored = memoryHasEntries(next) ? next : null;
  if (stored === prev) return stored;
  const key = entryKey(userId, candidateId);
  useScreeningMemoryStore.setState((s) => ({ entries: { ...s.entries, [key]: stored } }));
  writeStoredScreeningMemory(userId, candidateId, stored);
  return stored;
}

export interface ScreeningMemorySummary {
  hasEntries: boolean;
  /** `job_id` → ile odpowiedzi i czy cokolwiek czeka w pamięci. */
  byJob: ReadonlyMap<number, { answers: number; any: boolean }>;
}

/**
 * Podsumowanie pamięci do listy „Screening dla”. Panel przerysowuje się tylko,
 * gdy zmienia się samo podsumowanie — nie przy każdym wpisanym znaku.
 */
export function useScreeningMemorySummary(userId: number | undefined, candidateId: number): ScreeningMemorySummary {
  const key = entryKey(userId, candidateId);
  useEffect(() => {
    readScreeningMemory(userId, candidateId);
  }, [userId, candidateId]);
  const signature = useScreeningMemoryStore((s) => {
    const memory = s.entries[key] ?? null;
    if (!memory) return "";
    const jobs = Object.keys(memory.pairs)
      .map((id) => {
        const summary = memoryPairSummary(memory, Number(id));
        return `${id}:${summary.answers}:${summary.any ? 1 : 0}`;
      })
      .join(",");
    return `${memoryHasEntries(memory) ? 1 : 0}|${jobs}`;
  });
  return useMemo(() => {
    const [has, jobs] = signature.split("|");
    const byJob = new Map<number, { answers: number; any: boolean }>();
    for (const part of (jobs ?? "").split(",").filter(Boolean)) {
      const [id, answers, any] = part.split(":");
      byJob.set(Number(id), { answers: Number(answers), any: any === "1" });
    }
    return { hasEntries: has === "1", byJob };
  }, [signature]);
}
