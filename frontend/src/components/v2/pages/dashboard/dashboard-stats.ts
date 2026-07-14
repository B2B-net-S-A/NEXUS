export interface FunnelStage {
  key: string
  label: string
  count: number
}

type UnknownRecord = Record<string, unknown>

function asRecord(value: unknown): UnknownRecord | null {
  return value !== null && typeof value === "object"
    ? (value as UnknownRecord)
    : null
}

function nonNegativeCount(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0
    ? value
    : 0
}

/** Maps the current `/api/reports/recruitment` contract without inventing data. */
export function recruitmentFunnelStages(payload: unknown): FunnelStage[] {
  const root = asRecord(payload)
  const funnel = asRecord(root?.funnel)
  const source = funnel ?? root

  return [
    {
      key: "verified",
      label: "Weryfikacje",
      count: nonNegativeCount(source?.verified ?? source?.weryfikacje_count),
    },
    {
      key: "recommended",
      label: "Rekomendacje",
      count: nonNegativeCount(source?.recommended ?? source?.rekomendacje_count),
    },
    {
      key: "internal_interview",
      label: "Interview wewn.",
      count: nonNegativeCount(source?.internal_interview ?? source?.interviews_count),
    },
    {
      key: "client_interview",
      label: "Interview klienta",
      count: nonNegativeCount(source?.client_interview),
    },
    {
      key: "hired",
      label: "Placementy",
      count: nonNegativeCount(source?.placed ?? source?.placements_count),
    },
  ]
}
