import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  Info,
  Loader2,
} from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * Banner-style alert for inline notifications inside cards/forms.
 *
 * Phase 4.1 of the M365 plan — extracted from the Microsoft365Card backfill /
 * error / reconnect banners so other integration cards (CloudTalk, Autenti,
 * future Gmail) can reuse the same shape and not drift on copy/paste.
 *
 * Intentionally NOT shadcn's `<Alert />` — we want a self-contained component
 * that owns the leading icon + title + description layout without leaking
 * implementation details to callers.
 */

const alertVariants = cva(
  "flex items-start gap-2 text-sm border rounded-xl px-4 py-3",
  {
    variants: {
      variant: {
        info: "text-primary bg-primary/10 border-primary/20",
        success: "text-emerald-800 dark:text-emerald-200 bg-emerald-50 dark:bg-emerald-950/30 border-emerald-200 dark:border-emerald-900/50",
        warning: "text-amber-800 dark:text-amber-200 bg-amber-50 dark:bg-amber-950/30 border-amber-200 dark:border-amber-900/50",
        error: "text-destructive bg-destructive/10 border-destructive/20",
      },
    },
    defaultVariants: {
      variant: "info",
    },
  }
);

type AlertVariant = NonNullable<VariantProps<typeof alertVariants>["variant"]>;

const ICONS: Record<AlertVariant, React.ComponentType<{ className?: string }>> = {
  info: Info,
  success: CheckCircle2,
  warning: AlertTriangle,
  error: AlertCircle,
};

// Omit `title` from the underlying HTMLAttributes — the DOM `title` attr is a
// string (tooltip), but we want ReactNode here for the bold heading slot.
export interface AlertProps
  extends Omit<React.HTMLAttributes<HTMLDivElement>, "title">,
    VariantProps<typeof alertVariants> {
  /** Bold leading line. */
  title?: React.ReactNode;
  /** Optional secondary text shown under the title. */
  description?: React.ReactNode;
  /**
   * Override the default icon for the variant (e.g. swap to a Loader2 spinner
   * while a backfill is in progress).
   */
  icon?: React.ComponentType<{ className?: string }>;
  /** When true, the icon spins (use with `icon={Loader2}` or default info). */
  spinning?: boolean;
}

export function Alert({
  variant,
  title,
  description,
  icon,
  spinning,
  className,
  children,
  ...props
}: AlertProps) {
  const resolvedVariant = (variant ?? "info") as AlertVariant;
  const Icon = icon ?? (spinning ? Loader2 : ICONS[resolvedVariant]);
  return (
    <div className={cn(alertVariants({ variant }), className)} {...props}>
      <Icon
        className={cn(
          "w-4 h-4 flex-shrink-0 mt-0.5",
          spinning && "animate-spin"
        )}
      />
      <div className="min-w-0 flex-1">
        {title ? <p className="font-medium">{title}</p> : null}
        {description ? (
          <p
            className={cn(
              "text-xs break-words",
              title && "mt-0.5",
              "opacity-90"
            )}
          >
            {description}
          </p>
        ) : null}
        {children}
      </div>
    </div>
  );
}

export { alertVariants };
