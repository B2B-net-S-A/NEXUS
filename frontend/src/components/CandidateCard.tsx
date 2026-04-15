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
      <div className="bg-white dark:bg-gray-700 border border-gray-200 dark:border-gray-600 rounded-lg p-3 hover:border-blue-300 dark:hover:border-blue-500 hover:shadow-sm transition-all cursor-pointer">
        <div className="flex items-start gap-2">
          <div className="w-7 h-7 rounded-full bg-blue-100 dark:bg-blue-900/40 text-blue-600 dark:text-blue-400 flex items-center justify-center flex-shrink-0 text-xs font-medium">
            {candidate ? candidate.name.charAt(0) : <User className="w-3.5 h-3.5" />}
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-gray-800 dark:text-gray-200 truncate">
              {candidate ? `${candidate.name} ${candidate.lastname}` : `Kandydat #${candidateId}`}
            </p>
            {candidate?.location && (
              <p className="text-xs text-gray-400 dark:text-gray-500 truncate">{candidate.location}</p>
            )}
          </div>
        </div>

        <div className="flex items-center justify-between mt-2">
          {rating ? (
            <div className="flex items-center gap-0.5">
              {Array.from({ length: 5 }).map((_, i) => (
                <Star
                  key={i}
                  className={`w-3 h-3 ${i < rating ? "text-yellow-400 fill-yellow-400" : "text-gray-200 dark:text-gray-600"}`}
                />
              ))}
            </div>
          ) : <div />}
          {daysInStage !== undefined && daysInStage !== null && (
            <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${
              daysInStage > 7 ? "bg-red-100 text-red-600 dark:bg-red-900/40 dark:text-red-400" :
              daysInStage > 3 ? "bg-amber-100 text-amber-600 dark:bg-amber-900/40 dark:text-amber-400" :
              "bg-gray-100 text-gray-500 dark:bg-gray-600 dark:text-gray-400"
            }`}>
              {daysInStage}d
            </span>
          )}
        </div>
      </div>
    </Link>
  );
});
