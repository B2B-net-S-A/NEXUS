import { type LucideIcon } from "lucide-react"

import { StatCard } from "@/components/ds"

export type PastelKpiColor = "slate" | "amber" | "purple" | "emerald"

interface PastelKpiProps {
  title: string
  value: React.ReactNode
  subtitle?: string
  icon: LucideIcon
  /** @deprecated Styling is now token-based (uniform indigo chip) via the DS
   *  StatCard. Kept so existing call sites compile without edits. */
  color?: PastelKpiColor
}

/**
 * Thin compat wrapper over the DS `StatCard`. Previously rendered hardcoded
 * pastel tiles (bg-slate-50 / bg-amber-50 / …) which broke dark mode + palettes;
 * now token-based and consistent with the recruiter dashboard.
 */
export function PastelKpi({ title, value, subtitle, icon }: PastelKpiProps) {
  return <StatCard label={title} value={value} sub={subtitle} icon={icon} />
}
