import { HEALTH_DOT, HEALTH_TEXT, type CareHealth } from "@/lib/api/care-board";
import { cn } from "@/lib/utils";

function healthTitle(health: CareHealth): string {
  return health.reasons.length
    ? `Zdrowie relacji: ${health.label} — ${health.reasons.join("; ")}`
    : `Zdrowie relacji: ${health.label}`;
}

/** Kropka zdrowia relacji (Dobrze / Uwaga / Ryzyko); powód w dymku i dla czytnika. */
export function HealthDot({ health, className }: { health: CareHealth; className?: string }) {
  return (
    <span
      className={cn("inline-block size-2 shrink-0 rounded-full", HEALTH_DOT[health.level], className)}
      title={healthTitle(health)}
    >
      <span className="sr-only">{healthTitle(health)}</span>
    </span>
  );
}

/** Zdrowie słowem i kolorem — z kropką. */
export function HealthWord({ health, className }: { health: CareHealth; className?: string }) {
  return (
    <span
      className={cn("inline-flex items-center gap-1 text-[11.5px] font-medium", HEALTH_TEXT[health.level], className)}
      title={healthTitle(health)}
    >
      <span aria-hidden className={cn("size-1.5 rounded-full", HEALTH_DOT[health.level])} />
      {health.label}
    </span>
  );
}
