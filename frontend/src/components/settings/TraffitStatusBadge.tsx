import {
  AlertCircle,
  CheckCircle2,
  FlaskConical,
  PauseCircle,
  PowerOff,
  TriangleAlert,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { TraffitHealthKind } from "@/lib/traffit-integration";

const STATUS_STYLE: Record<
  TraffitHealthKind,
  { icon: typeof CheckCircle2; className: string }
> = {
  healthy: {
    icon: CheckCircle2,
    className: "border-primary/20 bg-primary/10 text-primary",
  },
  degraded: {
    icon: TriangleAlert,
    className: "border-border bg-muted text-foreground",
  },
  error: {
    icon: AlertCircle,
    className: "border-destructive/20 bg-destructive/10 text-destructive",
  },
  paused: {
    icon: PauseCircle,
    className: "border-border bg-muted text-muted-foreground",
  },
  dry_run: {
    icon: FlaskConical,
    className: "border-primary/20 bg-primary/10 text-primary",
  },
  disabled: {
    icon: PowerOff,
    className: "border-border bg-muted text-muted-foreground",
  },
};

export function TraffitStatusBadge({
  kind,
  label,
  className,
}: {
  kind: TraffitHealthKind;
  label: string;
  className?: string;
}) {
  const config = STATUS_STYLE[kind];
  const Icon = config.icon;
  return (
    <Badge
      variant="outline"
      className={cn(config.className, className)}
      aria-label={`Stan integracji: ${label}`}
    >
      <Icon className="h-3 w-3" aria-hidden="true" />
      {label}
    </Badge>
  );
}
