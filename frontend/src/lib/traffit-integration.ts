import type { TraffitIntegrationStatus } from "@/lib/api";

export type TraffitHealthKind =
  | "healthy"
  | "degraded"
  | "error"
  | "paused"
  | "dry_run"
  | "disabled";

export interface TraffitHealthPresentation {
  kind: TraffitHealthKind;
  label: string;
  description: string;
}

const PRESENTATIONS: Record<TraffitHealthKind, TraffitHealthPresentation> = {
  healthy: {
    kind: "healthy",
    label: "Zdrowa",
    description: "Zmiany przepływają w obu kierunkach.",
  },
  degraded: {
    kind: "degraded",
    label: "Wymaga uwagi",
    description: "Co najmniej jeden strumień nie spełnia celu 15 minut.",
  },
  error: {
    kind: "error",
    label: "Błąd",
    description: "W kolejce są zdarzenia wymagające interwencji.",
  },
  paused: {
    kind: "paused",
    label: "Wstrzymana",
    description: "Co najmniej jeden kierunek synchronizacji jest wstrzymany.",
  },
  dry_run: {
    kind: "dry_run",
    label: "Tryb testowy",
    description: "Zmiany wychodzące są tylko porównywane, bez zapisu w Traffit.",
  },
  disabled: {
    kind: "disabled",
    label: "Wyłączona",
    description: "Integracja Traffit nie jest aktywna.",
  },
};

/** Operational health used consistently by the settings card and full page. */
export function getTraffitHealthPresentation(
  status: TraffitIntegrationStatus,
): TraffitHealthPresentation {
  if (!status.enabled) return PRESENTATIONS.disabled;
  if (status.queues.dead_letter > 0) return PRESENTATIONS.error;
  if (
    status.paused.inbound ||
    status.paused.outbound ||
    status.paused.poll
  ) {
    return PRESENTATIONS.paused;
  }
  if (status.dry_run) return PRESENTATIONS.dry_run;

  const hasFailedStream = status.streams.some(
    (stream) =>
      stream.consecutive_failures > 0 ||
      ["failed", "error", "degraded"].includes(
        (stream.last_status ?? "").toLowerCase(),
      ),
  );
  const lag = getMaximumLagSeconds(status);
  if (
    !status.leader ||
    status.streams.length === 0 ||
    hasFailedStream ||
    (lag != null && lag > 15 * 60)
  ) {
    return PRESENTATIONS.degraded;
  }
  return PRESENTATIONS.healthy;
}

export function getMaximumLagSeconds(
  status: TraffitIntegrationStatus,
): number | null {
  const values = status.streams
    .map((stream) => stream.lag_seconds)
    .filter((value): value is number => value != null && value >= 0);
  return values.length > 0 ? Math.max(...values) : null;
}

export function formatLagSeconds(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return "—";
  if (seconds < 60) return `${Math.round(seconds)} s`;
  if (seconds < 3600) return `${Math.ceil(seconds / 60)} min`;
  if (seconds < 86_400) {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    return minutes > 0 ? `${hours} h ${minutes} min` : `${hours} h`;
  }
  const days = Math.floor(seconds / 86_400);
  const hours = Math.floor((seconds % 86_400) / 3600);
  return hours > 0 ? `${days} d ${hours} h` : `${days} d`;
}

export function formatIntegrationDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("pl-PL", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(date);
}

export function formatIntegrationValue(value: unknown): string {
  if (value == null || value === "") return "—";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  try {
    return JSON.stringify(value);
  } catch {
    return "[wartość złożona]";
  }
}
