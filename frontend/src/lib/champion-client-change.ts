/**
 * „Klient coś zmienił” (23.11.2026) — zmiana od klienta w Profilu Championa.
 *
 * Backend: `services/champion_client_change.py`, trasy
 * `POST /api/jobs/{id}/champion-profile/client-change[/apply]`. Propozycja nic
 * nie zapisuje; „Zastosuj” to jeden zwykły zapis profilu (wersja w „Zmiany”,
 * karta dla rekruterów) ze zdaniem DL od razu w wersji.
 *
 * Jarvis otwiera to samo okno: zapisuje treść `stashClientChangeText` i prowadzi
 * na `clientChangeHref(jobId)`; strona rekrutacji odczytuje ją jednorazowo
 * (`takeClientChangeText`) i od razu prosi o propozycję.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api, type ChampionProfileResponse } from "@/lib/api";
import { invalidateChampionDependents } from "@/lib/champion-cache";

export type ClientChangeLevel = "must" | "nice";
export type ClientChangeTextField =
  "project.about" | "project.responsibilities" | "client.selling_points";

interface ChangeBase {
  id: string;
  quote: string;
}

export type ClientChange =
  | (ChangeBase & { op: "row_add"; word: string; level: ClientChangeLevel })
  | (ChangeBase & { op: "row_remove"; word: string; before: ClientChangeLevel })
  | (ChangeBase & {
      op: "row_level";
      word: string;
      level: ClientChangeLevel;
      before: ClientChangeLevel;
    })
  | (ChangeBase & { op: "notes_append"; text: string })
  | (ChangeBase & { op: "talk_add"; name: string; level: ClientChangeLevel })
  | (ChangeBase & {
      op: "question_add";
      question: string;
      ideal_answer: string;
      deal_breaker: string;
    })
  | (ChangeBase & {
      op: "question_remove";
      question_id: string;
      before: string;
    })
  | (ChangeBase & {
      op: "question_edit";
      question_id: string;
      after: Partial<
        Record<"question" | "ideal_answer" | "deal_breaker", string>
      >;
      before: Partial<
        Record<"question" | "ideal_answer" | "deal_breaker", string>
      >;
    })
  | (ChangeBase & {
      op: "text_edit";
      field: ClientChangeTextField;
      label: string;
      before: string;
      after: string;
    });

export interface ClientChangeGap {
  word: string;
  open_total: number;
  missing: {
    before_screening: number;
    after_screening: number;
    at_client: number;
  };
  people: {
    process_id: number;
    candidate_id: number;
    name: string;
    stage: "after_screening" | "at_client";
    owner_user_id: number | null;
  }[];
}

export interface ClientChangeProposal {
  status: "ready" | "failed";
  changes: ClientChange[];
  note: string;
  message: string | null;
  gaps: ClientChangeGap[];
  profile_hash: string | null;
}

export interface ClientChangeApplyResult extends ChampionProfileResponse {
  applied: number;
  notified: number;
}

const STASH_PREFIX = "nexus.clientChange.";
export const CLIENT_CHANGE_PARAM = "client_change";

export function clientChangeHref(jobId: number): string {
  return `/jobs/${jobId}?tab=champion&ptab=brief&${CLIENT_CHANGE_PARAM}=1`;
}

/** Treść od klienta dla okna na stronie rekrutacji (Jarvis → „Pokaż i popraw”). */
export function stashClientChangeText(jobId: number, text: string): void {
  try {
    sessionStorage.setItem(`${STASH_PREFIX}${jobId}`, text);
  } catch {
    // Bez sessionStorage okno otworzy się puste — DL wklei treść sam.
  }
}

export function takeClientChangeText(jobId: number): string | null {
  try {
    const key = `${STASH_PREFIX}${jobId}`;
    const text = sessionStorage.getItem(key);
    sessionStorage.removeItem(key);
    return text;
  } catch {
    return null;
  }
}

export function useProposeClientChange(jobId: number) {
  return useMutation({
    mutationFn: async (text: string): Promise<ClientChangeProposal> => {
      const res = await api.post(
        `/jobs/${jobId}/champion-profile/client-change`,
        { text },
      );
      return res.data as ClientChangeProposal;
    },
  });
}

export function useApplyClientChange(jobId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (input: {
      changes: ClientChange[];
      note: string;
      notifyGaps: boolean;
      profileHash: string | null;
    }): Promise<ClientChangeApplyResult> => {
      const res = await api.post(
        `/jobs/${jobId}/champion-profile/client-change/apply`,
        {
          changes: input.changes,
          note: input.note.trim() || null,
          notify_gaps: input.notifyGaps,
          expected_profile_hash: input.profileHash,
        },
      );
      return res.data as ClientChangeApplyResult;
    },
    onSuccess: () => invalidateChampionDependents(qc, jobId),
  });
}

// ── Czyste pomocnicze (okno i testy) ─────────────────────────────────────────

export const LEVEL_LABEL_PL: Record<ClientChangeLevel, string> = {
  must: "Musi mieć",
  nice: "Mile widziane",
};

export interface ClientChangeGroup {
  key: string;
  label: string;
  changes: ClientChange[];
}

/** Zmiany ułożone według bloków Briefu, w kolejności bloków na ekranie. */
export function groupChanges(
  changes: readonly ClientChange[],
): ClientChangeGroup[] {
  const groups = new Map<string, ClientChangeGroup>();
  const order = [
    "search",
    "notes",
    "talk",
    "questions",
    "project.about",
    "project.responsibilities",
    "client.selling_points",
  ];
  const put = (key: string, label: string, change: ClientChange) => {
    const group = groups.get(key) ?? { key, label, changes: [] };
    group.changes.push(change);
    groups.set(key, group);
  };
  for (const change of changes) {
    switch (change.op) {
      case "row_add":
      case "row_remove":
      case "row_level":
        put("search", "Czego szukamy", change);
        break;
      case "notes_append":
        put("notes", "Niuanse", change);
        break;
      case "talk_add":
        put("talk", "Rekruter sprawdza w rozmowie", change);
        break;
      case "question_add":
      case "question_remove":
      case "question_edit":
        put("questions", "Pytania na rozmowę", change);
        break;
      case "text_edit":
        put(change.field, change.label, change);
        break;
    }
  }
  return order.flatMap((key) => (groups.has(key) ? [groups.get(key)!] : []));
}

export type DiffPart = { kind: "same" | "add" | "del"; text: string };

/**
 * Różnica po słowach (LCS) — pokazuje w polu tekstowym tylko to, co się zmienia.
 * Przy bardzo długich tekstach (> 600 słów) oddaje całość jako usunięte + dodane.
 */
export function wordDiff(before: string, after: string): DiffPart[] {
  const a = before.split(/(\s+)/).filter((t) => t !== "");
  const b = after.split(/(\s+)/).filter((t) => t !== "");
  if (a.length > 1200 || b.length > 1200) {
    return [
      ...(before ? [{ kind: "del" as const, text: before }] : []),
      ...(after ? [{ kind: "add" as const, text: after }] : []),
    ];
  }
  const dp: number[][] = Array.from({ length: a.length + 1 }, () =>
    new Array<number>(b.length + 1).fill(0),
  );
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      dp[i][j] =
        a[i] === b[j]
          ? dp[i + 1][j + 1] + 1
          : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const out: DiffPart[] = [];
  const push = (kind: DiffPart["kind"], text: string) => {
    const last = out[out.length - 1];
    if (last && last.kind === kind) last.text += text;
    else out.push({ kind, text });
  };
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      push("same", a[i]);
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      push("del", a[i++]);
    } else {
      push("add", b[j++]);
    }
  }
  while (i < a.length) push("del", a[i++]);
  while (j < b.length) push("add", b[j++]);
  return out;
}

/** Ile osób po screeningu i u klienta nie ma nowego wymaganego słowa w CV. */
export function lateGapCount(gaps: readonly ClientChangeGap[]): number {
  const ids = new Set<number>();
  for (const gap of gaps) for (const p of gap.people) ids.add(p.process_id);
  return ids.size;
}
