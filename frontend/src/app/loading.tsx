import { TableSkeleton, CardSkeleton } from "@/components/SkeletonLoader";

export default function PageLoading() {
  return (
    <div className="space-y-6 animate-pulse">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <CardSkeleton key={i} />
        ))}
      </div>
      <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5">
        <TableSkeleton rows={6} />
      </div>
    </div>
  );
}
