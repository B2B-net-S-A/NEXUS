import { TableSkeleton, CardSkeleton } from "@/components/SkeletonLoader";

export default function PageLoading() {
  return (
    <>
      {/* Kids mode: a cheerful bouncing mascot instead of skeletons (CSS-gated) */}
      <div className="kids-only flex-col items-center justify-center gap-3 py-24 text-center">
        <span className="kids-anim-float inline-block text-6xl">🤖</span>
        <p className="text-lg font-semibold text-foreground">Ładuję zabawę…</p>
      </div>

      {/* Default: skeletons */}
      <div className="kids-hidden space-y-6 animate-pulse">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <CardSkeleton key={i} />
          ))}
        </div>
        <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border p-5">
          <TableSkeleton rows={6} />
        </div>
      </div>
    </>
  );
}
