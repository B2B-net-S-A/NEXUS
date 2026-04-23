"use client";

import { Circle } from "lucide-react";
import { cn } from "@/lib/utils";

interface Props {
  status: string;
  compact?: boolean;
}

const STATUS_LABEL: Record<string, string> = {
  actively_looking: "Aktywnie szuka",
  open_to_offers: "Otwarty na oferty",
  not_looking: "Nie szuka",
  unknown: "Nieznany",
};

const STATUS_COLOR: Record<string, string> = {
  actively_looking: "text-green-700 bg-green-100 border-green-200",
  open_to_offers: "text-blue-700 bg-blue-100 border-blue-200",
  not_looking: "text-gray-600 bg-gray-100 border-gray-200",
  unknown: "text-gray-500 bg-gray-50 border-gray-200",
};

export function MarketplaceStatusBadge({ status, compact = false }: Props) {
  const label = STATUS_LABEL[status] ?? status;
  const color = STATUS_COLOR[status] ?? STATUS_COLOR.unknown;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 text-xs font-medium rounded-full border",
        compact ? "px-1.5 py-0.5" : "px-2 py-0.5",
        color
      )}
    >
      <Circle className="w-2 h-2 fill-current" />
      {label}
    </span>
  );
}
