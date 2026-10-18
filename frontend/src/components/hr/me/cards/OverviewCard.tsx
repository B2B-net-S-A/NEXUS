import type { ReactNode } from "react";

import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { resolveViewState, type ViewState } from "@/lib/view-state";

const CARD_TITLE = "text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground";

export function OverviewCard({
  title,
  aside,
  children,
  className,
}: {
  title: string;
  aside?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <Card size="sm" className={cn("flex min-w-0 flex-col gap-2", className)} aria-label={title}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-2">
        <h2 className={CARD_TITLE}>{title}</h2>
        {aside ? <span className="text-xs text-muted-foreground">{aside}</span> : null}
      </div>
      {children}
    </Card>
  );
}

/** Awaria jednej części karty: zdanie z ponowieniem, nigdy „0”. */
export function PartError({ label, onRetry }: { label: string; onRetry: () => void }) {
  return (
    <p role="alert" className="text-sm text-destructive">
      {label}{" "}
      <button
        type="button"
        onClick={onRetry}
        className="font-medium text-primary underline-offset-2 hover:underline"
      >
        Spróbuj ponownie
      </button>
    </p>
  );
}

export function stateOf(query: {
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  isSuccess: boolean;
}): ViewState {
  return resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
  });
}

export function Loading() {
  return <p className="text-sm text-muted-foreground">Wczytywanie…</p>;
}
