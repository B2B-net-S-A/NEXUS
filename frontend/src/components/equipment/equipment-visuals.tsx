"use client";

// Drobne elementy ekranów „Sprzętu” po makiecie 19.10.2026: ikona rodzaju,
// awatar posiadacza i protokół jako pigułka.

import {
  Cable,
  Cpu,
  Headphones,
  IdCard,
  Laptop,
  Monitor,
  Package,
  Smartphone,
  type LucideIcon,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import type { EquipmentCategory, EquipmentHolderKind, ProtocolStatus } from "@/lib/api/equipment";
import { cn } from "@/lib/utils";

import { CATEGORY_LABELS, PROTOCOL_STATUS_LABELS, holderInitials } from "./equipment-format";

const CATEGORY_ICON: Record<EquipmentCategory, LucideIcon> = {
  laptop: Laptop,
  telefon: Smartphone,
  monitor: Monitor,
  karta_sim: Cpu,
  karta_dostepu: IdCard,
  akcesorium: Cable,
  inne: Package,
};

/** Ikona rodzaju; akcesorium o nazwie słuchawek dostaje słuchawki. */
export function categoryIcon(category: EquipmentCategory, modelName?: string | null): LucideIcon {
  if (category === "akcesorium" && modelName && /słuchawk|headset/i.test(modelName)) {
    return Headphones;
  }
  return CATEGORY_ICON[category];
}

export function CategoryIcon({
  category,
  modelName,
  size = "md",
  className,
}: {
  category: EquipmentCategory;
  modelName?: string | null;
  size?: "sm" | "md";
  className?: string;
}) {
  const Icon = categoryIcon(category, modelName);
  return (
    <span
      title={CATEGORY_LABELS[category]}
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground",
        size === "sm" ? "h-6 w-6" : "h-8 w-8",
        className,
      )}
    >
      <Icon className={size === "sm" ? "h-3.5 w-3.5" : "h-4 w-4"} aria-hidden />
    </span>
  );
}

/** Skład zestawu albo protokołu ikonami („laptop, telefon, SIM…” dla czytnika). */
export function KitIcons({
  categories,
  label,
}: {
  categories: { category: EquipmentCategory; modelName?: string | null }[];
  label: string;
}) {
  if (categories.length === 0) return null;
  return (
    <span className="hidden shrink-0 gap-1 sm:inline-flex" role="img" aria-label={label}>
      {categories.map((entry, index) => (
        <CategoryIcon key={index} size="sm" category={entry.category} modelName={entry.modelName} />
      ))}
    </span>
  );
}

/** Awatar z inicjałami — pracownik w kolorze marki, kontraktor i reszta w ostrzegawczym. */
export function HolderAvatar({
  name,
  kind,
  size = "md",
}: {
  name: string;
  kind: EquipmentHolderKind | null;
  size?: "sm" | "md";
}) {
  return (
    <span
      aria-hidden
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-full font-semibold",
        size === "sm" ? "h-7 w-7 text-[11px]" : "h-8 w-8 text-xs",
        kind === "user" ? "bg-primary/10 text-primary" : "bg-warning-muted text-warning-muted-foreground",
      )}
    >
      {holderInitials(name)}
    </span>
  );
}

const PROTOCOL_BADGE: Record<ProtocolStatus, "warning" | "info" | "success" | "neutral"> = {
  oczekuje: "warning",
  podpisany: "info",
  potwierdzony: "success",
  anulowany: "neutral",
};

export function ProtocolPill({ status }: { status: ProtocolStatus }) {
  return <Badge variant={PROTOCOL_BADGE[status]}>{PROTOCOL_STATUS_LABELS[status]}</Badge>;
}
