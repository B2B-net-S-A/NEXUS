import { cn } from "@/lib/utils";

interface SkeletonProps {
  className?: string;
}

export function Skeleton({ className }: SkeletonProps) {
  return (
    <div
      className={cn(
        "animate-pulse bg-muted dark:bg-muted rounded",
        className
      )}
    />
  );
}

export function CardSkeleton() {
  return (
    <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border p-5 space-y-3 animate-pulse">
      <div className="flex justify-between">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-8 w-8 rounded-lg" />
      </div>
      <Skeleton className="h-8 w-16" />
      <Skeleton className="h-3 w-20" />
    </div>
  );
}

export function ListItemSkeleton() {
  return (
    <div className="flex items-center gap-3 p-3 border-b border-border dark:border-border animate-pulse">
      <Skeleton className="w-10 h-10 rounded-full shrink-0" />
      <div className="flex-1 space-y-2">
        <Skeleton className="h-4 w-32" />
        <Skeleton className="h-3 w-24" />
      </div>
      <Skeleton className="h-5 w-16 rounded-full" />
    </div>
  );
}

export function TableSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-0">
      {Array.from({ length: rows }).map((_, i) => (
        <ListItemSkeleton key={i} />
      ))}
    </div>
  );
}

export function DashboardSkeleton() {
  return (
    <div className="space-y-8 animate-pulse">
      {/* Title */}
      <div className="space-y-2">
        <Skeleton className="h-8 w-40" />
        <Skeleton className="h-4 w-64" />
      </div>
      {/* Stats row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {Array.from({ length: 4 }).map((_, i) => <CardSkeleton key={i} />)}
      </div>
      {/* Two column */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border p-5 space-y-4">
          <Skeleton className="h-5 w-32" />
          <Skeleton className="h-10 w-24" />
          <div className="space-y-2">
            {Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-3 w-full" />)}
          </div>
        </div>
        <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border p-5 space-y-4">
          <Skeleton className="h-5 w-32" />
          <Skeleton className="h-10 w-24" />
          <div className="space-y-2">
            {Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-3 w-full" />)}
          </div>
        </div>
      </div>
      {/* Activity + Recruiters */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border p-5 space-y-3">
          <Skeleton className="h-5 w-40" />
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="flex items-center gap-3">
              <Skeleton className="w-7 h-7 rounded-full shrink-0" />
              <div className="flex-1 space-y-1.5">
                <Skeleton className="h-3 w-full" />
                <Skeleton className="h-2.5 w-24" />
              </div>
            </div>
          ))}
        </div>
        <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border p-5 space-y-3">
          <Skeleton className="h-5 w-40" />
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="flex items-center gap-3 py-2">
              <Skeleton className="w-5 h-5 rounded" />
              <Skeleton className="w-7 h-7 rounded-full" />
              <Skeleton className="h-4 flex-1" />
              <Skeleton className="h-4 w-16" />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export function CandidatesListSkeleton() {
  return (
    <div className="space-y-4 animate-pulse">
      <div className="flex items-center justify-between">
        <Skeleton className="h-7 w-36" />
        <Skeleton className="h-9 w-32 rounded-lg" />
      </div>
      <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border overflow-hidden">
        <div className="p-4 border-b border-border dark:border-border">
          <Skeleton className="h-9 w-full rounded-lg" />
        </div>
        <TableSkeleton rows={8} />
      </div>
    </div>
  );
}

export function JobsListSkeleton() {
  return (
    <div className="space-y-4 animate-pulse">
      <div className="flex items-center justify-between">
        <Skeleton className="h-7 w-36" />
        <Skeleton className="h-9 w-32 rounded-lg" />
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border p-4 space-y-3">
            <div className="flex items-start justify-between gap-2">
              <Skeleton className="h-5 w-36" />
              <Skeleton className="h-5 w-16 rounded-full" />
            </div>
            <Skeleton className="h-4 w-24" />
            <Skeleton className="h-3 w-20" />
            <div className="flex gap-2 pt-1">
              <Skeleton className="h-6 w-16 rounded-full" />
              <Skeleton className="h-6 w-20 rounded-full" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// Error state component
interface ErrorBannerProps {
  message?: string;
  onRetry?: () => void;
}

export function ErrorBanner({ message = "Wystąpił błąd podczas ładowania danych.", onRetry }: ErrorBannerProps) {
  return (
    <div className="flex items-center justify-between gap-4 px-4 py-3 bg-destructive/10 dark:bg-destructive/15 border border-destructive/20 dark:border-red-800 rounded-xl text-sm">
      <div className="flex items-center gap-2 text-destructive dark:text-destructive">
        <svg className="w-4 h-4 shrink-0" fill="currentColor" viewBox="0 0 20 20">
          <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
        </svg>
        {message}
      </div>
      {onRetry && (
        <button
          onClick={onRetry}
          className="shrink-0 px-3 py-1.5 bg-red-600 hover:bg-red-700 text-white rounded-lg text-xs font-medium transition-colors"
        >
          Spróbuj ponownie
        </button>
      )}
    </div>
  );
}
