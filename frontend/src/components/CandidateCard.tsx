"use client";

import { memo } from "react";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { Star, User } from "lucide-react";
import Link from "next/link";

interface CandidateCardProps {
  candidateId: number;
  stage: string;
  rating?: number;
  daysInStage?: number;
}

export const CandidateCard = memo(function CandidateCard({ candidateId, stage, rating, daysInStage }: CandidateCardProps) {
  const { data: candidate } = useQuery({
    queryKey: ["candidate", candidateId],
    queryFn: () => api.get(`/api/candidates/${candidateId}`).then((r) => r.data),
    staleTime: 60_000,
  });

  return (
    <Link href={`/candidates/${candidateId}`}>
      <div className="bg-card dark:bg-muted border border-border dark:border-border rounded-lg p-3 hover:border-primary/30 dark:hover:border-primary hover:shadow-sm transition-all cursor-pointer">
        <div className="flex items-start gap-2">
          <div className="w-7 h-7 rounded-full bg-primary/15 dark:bg-primary/40 text-primary dark:text-primary flex items-center justify-center flex-shrink-0 text-xs font-medium">
            {candidate ? candidate.name.charAt(0) : <User className="w-3.5 h-3.5" />}
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-foreground dark:text-muted-foreground truncate">
              {candidate ? `${candidate.name} ${candidate.lastname}` : `Kandydat #${candidateId}`}
            </p>
            {candidate?.location && (
              <p className="text-xs text-muted-foreground dark:text-muted-foreground truncate">{candidate.location}</p>
            )}
          </div>
        </div>

        <div className="flex items-center justify-between mt-2">
          {rating ? (
            <div className="flex items-center gap-0.5">
              {Array.from({ length: 5 }).map((_, i) => (
                <Star
                  key={i}
                  className={`w-3 h-3 ${i < rating ? "text-yellow-400 fill-yellow-400" : "text-muted-foreground dark:text-muted-foreground"}`}
                />
              ))}
            </div>
          ) : <div />}
          {daysInStage !== undefined && daysInStage !== null && (
            <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${
              daysInStage > 7 ? "bg-destructive/15 text-destructive dark:bg-red-900/40 dark:text-destructive" :
              daysInStage > 3 ? "bg-amber-100 text-amber-600 dark:bg-amber-900/40 dark:text-amber-400" :
              "bg-muted text-muted-foreground dark:bg-gray-600 dark:text-muted-foreground"
            }`}>
              {daysInStage}d
            </span>
          )}
        </div>
      </div>
    </Link>
  );
});
