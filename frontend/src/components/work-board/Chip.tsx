import { cn } from "@/lib/utils";

/** Chip filtra tablicy (obszar, „Na ten tydzień”, „Bez osoby”, „Moi podopieczni”). */
export function Chip({
  active,
  onClick,
  children,
  tone,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
  tone?: "danger";
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "inline-flex h-8 items-center gap-1.5 whitespace-nowrap rounded-full border px-3 text-[13px] font-medium transition-colors",
        active
          ? "border-primary/30 bg-primary/10 text-primary"
          : "border-border bg-card text-foreground hover:bg-muted",
        !active && tone === "danger" && "text-destructive",
      )}
    >
      {children}
    </button>
  );
}
