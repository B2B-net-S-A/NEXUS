"use client";

import * as React from"react";
import { ChevronLeft, ChevronRight, Maximize2 } from"lucide-react";

import { Button } from"@/components/ui/button";
import {
 Tooltip,
 TooltipContent,
 TooltipProvider,
 TooltipTrigger,
} from"@/components/ui/tooltip";
import { cn } from"@/lib/utils";

interface CandidateNavProps {
 /** 1-based current position within the filtered list. */
 position: number;
 /** Total filtered count. */
 total: number;
 hasPrev: boolean;
 hasNext: boolean;
 onPrev: () => void;
 onNext: () => void;
 /** Optional spinner state when fetching adjacent pages. */
 isLoading?: boolean;
 /** Non-blocking adjacent-page fetch error. */
 error?: string | null;
 onRetry?: () => void;
 /** Optional close button (embedded mode). */
 onClose?: () => void;
 /** Optional"open in full page" button (embedded mode only). */
 onExpand?: () => void;
 className?: string;
}

/**
 * `← Poprzedni | 7 / 124 | Następny →` strip rendered above the candidate
 * profile hero. Driven by `useCandidateNavigation`.
 */
export function CandidateNav({
 position,
 total,
 hasPrev,
 hasNext,
 onPrev,
 onNext,
 isLoading,
 error,
 onRetry,
 onClose,
 onExpand,
 className,
}: CandidateNavProps) {
 const prevDisabledMsg = !hasPrev ?"Pierwszy kandydat" : null;
 const nextDisabledMsg = !hasNext ?"Ostatni kandydat" : null;

 return (
 <TooltipProvider delayDuration={200}>
 <div
 data-testid="candidate-nav"
 className={cn("flex items-center justify-between gap-3 rounded-lg border border-border bg-card px-3 py-2 text-sm",
 className,
 )}
 >
 <Tooltip>
 <TooltipTrigger asChild>
 <span className="inline-flex">
 <Button
 size="sm"
 variant="outline"
 className="min-h-11 min-w-11"
 onClick={onPrev}
 disabled={!hasPrev || isLoading}
 aria-label="Poprzedni kandydat"
 aria-keyshortcuts="K"
 >
 <ChevronLeft className="h-4 w-4" /> Poprzedni
 </Button>
 </span>
 </TooltipTrigger>
 <TooltipContent>
 {prevDisabledMsg ??"Skrót: K"}
 </TooltipContent>
 </Tooltip>

 <div
 className="text-xs tabular-nums text-muted-foreground"
 aria-live="polite"
 >
 {total > 0 ? (
 <>
 <span className="font-medium text-foreground">
 {position}
 </span>{""}
 / {total}
 </>
 ) : ("—"
 )}
 </div>

 <div className="flex items-center gap-2">
 <Tooltip>
 <TooltipTrigger asChild>
 <span className="inline-flex">
 <Button
 size="sm"
 variant="outline"
 className="min-h-11 min-w-11"
 onClick={onNext}
 disabled={!hasNext || isLoading}
 aria-label="Następny kandydat"
 aria-keyshortcuts="J"
 >
 Następny <ChevronRight className="h-4 w-4" />
 </Button>
 </span>
 </TooltipTrigger>
 <TooltipContent>
 {nextDisabledMsg ??"Skrót: J"}
 </TooltipContent>
 </Tooltip>

 {onExpand ? (
 <Tooltip>
 <TooltipTrigger asChild>
 <Button
 size="sm"
 variant="ghost"
 className="min-h-11 min-w-11"
 onClick={onExpand}
 aria-label="Otwórz w pełnym widoku"
 >
 <Maximize2 className="h-4 w-4" />
 </Button>
 </TooltipTrigger>
 <TooltipContent>Otwórz w pełnym widoku</TooltipContent>
 </Tooltip>
 ) : null}
 {onClose ? (
 <Button
 size="sm"
 variant="ghost"
 className="min-h-11 min-w-11"
 onClick={onClose}
 aria-label="Zamknij profil"
 >
 Zamknij
 </Button>
 ) : null}
 </div>
 {error ? (
 <div
 role="alert"
 className="col-span-full flex items-center justify-between gap-2 border-t border-destructive/20 pt-2 text-xs text-destructive"
 >
 <span>{error}</span>
 {onRetry ? (
 <button
 type="button"
 onClick={onRetry}
 className="inline-flex min-h-11 min-w-11 items-center justify-center font-medium underline"
 >
 Ponów
 </button>
 ) : null}
 </div>
 ) : null}
 </div>
 </TooltipProvider>
 );
}
