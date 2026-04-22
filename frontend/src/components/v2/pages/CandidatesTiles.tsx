"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { Briefcase, MapPin } from "lucide-react";
import { cn } from "@/lib/utils";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Checkbox } from "@/components/ui/checkbox";

interface TileCandidate {
  id: number;
  name?: string;
  lastname?: string;
  position?: string;
  current_role?: string;
  location?: string;
}

interface CandidatesTilesProps {
  items: TileCandidate[];
  selectedIds: Set<number>;
  onToggleSelect: (id: number) => void;
  onOpenDetail: (id: number) => void;
  onQuickAssign: (candidate: { id: number; name: string }) => void;
}

const TILE_MIN_WIDTH = 240;
const TILE_GAP = 12;
const ROW_HEIGHT = 200;

export function CandidatesTiles({
  items,
  selectedIds,
  onToggleSelect,
  onOpenDetail,
  onQuickAssign,
}: CandidatesTilesProps) {
  const parentRef = useRef<HTMLDivElement>(null);
  const [lanes, setLanes] = useState(3);

  useEffect(() => {
    const node = parentRef.current;
    if (!node) return;
    const update = () => {
      const width = node.clientWidth;
      const computed = Math.max(
        1,
        Math.floor((width + TILE_GAP) / (TILE_MIN_WIDTH + TILE_GAP))
      );
      setLanes(computed);
    };
    update();
    const ro = new ResizeObserver(update);
    ro.observe(node);
    return () => ro.disconnect();
  }, []);

  const rows = useMemo(() => {
    const out: TileCandidate[][] = [];
    for (let i = 0; i < items.length; i += lanes) {
      out.push(items.slice(i, i + lanes));
    }
    return out;
  }, [items, lanes]);

  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 4,
  });

  return (
    <div
      ref={parentRef}
      style={{ height: "calc(100vh - 340px)", minHeight: 360 }}
      className="overflow-auto p-3"
    >
      <div
        style={{
          height: `${virtualizer.getTotalSize()}px`,
          position: "relative",
          width: "100%",
        }}
      >
        {virtualizer.getVirtualItems().map((virtualRow) => {
          const row = rows[virtualRow.index];
          return (
            <div
              key={virtualRow.index}
              style={{
                position: "absolute",
                top: 0,
                left: 0,
                width: "100%",
                height: `${virtualRow.size}px`,
                transform: `translateY(${virtualRow.start}px)`,
                display: "grid",
                gridTemplateColumns: `repeat(${lanes}, minmax(0, 1fr))`,
                gap: `${TILE_GAP}px`,
                paddingBottom: `${TILE_GAP}px`,
              }}
            >
              {row.map((candidate) => {
                const fullName =
                  `${candidate.name ?? ""} ${candidate.lastname ?? ""}`.trim() ||
                  "Kandydat";
                const initials = fullName
                  .split(" ")
                  .map((w) => w[0])
                  .slice(0, 2)
                  .join("")
                  .toUpperCase();
                const position = candidate.position ?? candidate.current_role ?? "";
                const isSelected = selectedIds.has(candidate.id);
                return (
                  <div
                    key={candidate.id}
                    className={cn(
                      "group relative flex flex-col items-center text-center gap-2 rounded-v2-m border bg-[hsl(var(--bg-surface))] p-4 transition-colors",
                      isSelected
                        ? "border-[hsl(var(--accent))] bg-[hsl(var(--accent-soft))]/30"
                        : "border-[hsl(var(--border-subtle))] hover:border-[hsl(var(--accent))]/60"
                    )}
                  >
                    <div className="absolute left-2 top-2">
                      <Checkbox
                        checked={isSelected}
                        onCheckedChange={() => onToggleSelect(candidate.id)}
                        aria-label={`Zaznacz ${fullName}`}
                      />
                    </div>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        onQuickAssign({ id: candidate.id, name: fullName });
                      }}
                      title="Przypisz do oferty"
                      className="absolute right-2 top-2 h-7 w-7 flex items-center justify-center rounded-v2-s text-[hsl(var(--text-muted))] hover:bg-[hsl(var(--accent-soft))] hover:text-[hsl(var(--accent))] opacity-0 group-hover:opacity-100 transition-opacity"
                    >
                      <Briefcase className="h-3.5 w-3.5" />
                    </button>
                    <button
                      type="button"
                      onClick={() => onOpenDetail(candidate.id)}
                      className="flex flex-col items-center gap-2 min-w-0 w-full pt-2"
                    >
                      <Avatar size="lg">
                        <AvatarFallback>{initials}</AvatarFallback>
                      </Avatar>
                      <div className="min-w-0 w-full">
                        <div className="font-medium text-sm text-[hsl(var(--text-title))] truncate hover:text-[hsl(var(--accent))]">
                          {fullName}
                        </div>
                        {position && (
                          <div className="text-xs text-[hsl(var(--text-body))] truncate mt-0.5">
                            {position}
                          </div>
                        )}
                        {candidate.location && (
                          <div className="text-[11px] text-[hsl(var(--text-muted))] truncate mt-1 flex items-center justify-center gap-1">
                            <MapPin className="h-3 w-3" />
                            {candidate.location}
                          </div>
                        )}
                      </div>
                    </button>
                  </div>
                );
              })}
            </div>
          );
        })}
      </div>
    </div>
  );
}
