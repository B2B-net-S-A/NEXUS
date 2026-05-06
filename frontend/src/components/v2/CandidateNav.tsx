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
 onClick={onPrev}
 disabled={!hasPrev || isLoading}
 aria-label="Poprzedni kandydat"
 aria-keyshortcuts="["
 >
 <ChevronLeft className="h-4 w-4" /> Poprzedni
 </Button>
 </span>
 </TooltipTrigger>
 <TooltipContent>
 {prevDisabledMsg ??"Skrót: ["}
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
 onClick={onNext}
 disabled={!hasNext || isLoading}
 aria-label="Następny kandydat"
 aria-keyshortcuts="]"
 >
 Następny <ChevronRight className="h-4 w-4" />
 </Button>
 </span>
 </TooltipTrigger>
 <TooltipContent>
 {nextDisabledMsg ??"Skrót: ]"}
 </TooltipContent>
 </Tooltip>

 {onExpand ? (
 <Tooltip>
 <TooltipTrigger asChild>
 <Button
 size="sm"
 variant="ghost"
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
 onClick={onClose}
 aria-label="Zamknij profil"
 >
 Zamknij
 </Button>
 ) : null}
 </div>
 </div>
 </TooltipProvider>
 );
}
