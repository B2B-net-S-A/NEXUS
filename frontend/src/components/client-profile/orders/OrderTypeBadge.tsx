import { Badge } from "@/components/ui/badge";
import type { EffectiveOrderType } from "@/lib/client-order-list";

const ORDER_TYPE_BADGES: Record<
  EffectiveOrderType,
  { label: string; variant: "info" | "warning" | "success" }
> = {
  md: { label: "MD", variant: "info" },
  cost: { label: "Kosztowe", variant: "warning" },
  periodic: { label: "Okresowe", variant: "success" },
};

export function OrderTypeBadge({ type }: { type: EffectiveOrderType }) {
  const badge = ORDER_TYPE_BADGES[type];
  return (
    <Badge variant={badge.variant} size="sm">
      {badge.label}
    </Badge>
  );
}

export function orderTypeLabel(type: EffectiveOrderType): string {
  return ORDER_TYPE_BADGES[type].label;
}
