import { cn } from "@/lib/utils";

import { personInitials } from "./hr-format";

const SIZES = {
  xs: "h-5 w-5 text-[9px]",
  sm: "h-7 w-7 text-[11px]",
  md: "h-8 w-8 text-[11px]",
  lg: "h-14 w-14 text-lg",
} as const;

export interface PersonAvatarProps {
  name: string;
  size?: keyof typeof SIZES;
  className?: string;
}

/** Kółko z inicjałami osoby (katalog, kartoteka, Struktura). Ozdoba — `aria-hidden`. */
export function PersonAvatar({ name, size = "md", className }: PersonAvatarProps) {
  return (
    <span
      aria-hidden
      className={cn(
        "grid shrink-0 place-items-center rounded-full bg-primary/10 font-semibold text-primary",
        SIZES[size],
        className,
      )}
    >
      {personInitials(name)}
    </span>
  );
}
