"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ChevronDown,
  ChevronRight,
  X as XIcon,
  Loader2,
  CircleUser,
  Clock,
  Store,
  Search,
} from "lucide-react";
import { marketplaceApi, MarketplaceCandidate } from "@/lib/api";
import { cn } from "@/lib/utils";
import { MarketplaceStatusBadge } from "./MarketplaceStatusBadge";
import { CandidateMatchesExpansion } from "./CandidateMatchesExpansion";

function formatDate(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleDateString("pl-PL", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

function daysAgo(iso: string): string {
  const diff = Math.floor(
    (Date.now() - new Date(iso).getTime()) / (1000 * 60 * 60 * 24)
  );
  if (diff <= 0) return "dziś";
  if (diff === 1) return "wczoraj";
  return `${diff} dni`;
}

export function MarketplaceTable() {
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [pageSize] = useState(25);
  const [q, setQ] = useState("");
  const [expanded, setExpanded] = useState<number | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["marketplace-candidates", { page, pageSize, q }],
    queryFn: () =>
      marketplaceApi
        .list({ page, page_size: pageSize, q: q || undefined })
        .then((r) => r.data),
  });

  const removeMutation = useMutation({
    mutationFn: (candidateId: number) => marketplaceApi.remove(candidateId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["marketplace-candidates"] });
    },
  });

  const items: MarketplaceCandidate[] = data?.items ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            type="text"
            placeholder="Szukaj po imieniu / nazwisku / email…"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setPage(1);
            }}
            className="h-10 w-full pl-10 pr-3 border border-gray-200 dark:border-gray-700 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 bg-white dark:bg-gray-800"
          />
        </div>
        <div className="text-xs text-gray-500">
          Razem na targu: <strong>{total}</strong>
        </div>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-20 text-gray-400 gap-2">
          <Loader2 className="w-5 h-5 animate-spin" />
          Ładuję kandydatów…
        </div>
      ) : items.length === 0 ? (
        <div className="text-center py-16 bg-gray-50 dark:bg-gray-900/40 rounded-2xl">
          <Store className="w-12 h-12 mx-auto mb-4 text-gray-300" />
          <h3 className="text-lg font-semibold text-gray-500 mb-1">
            Brak kandydatów na targu
          </h3>
          <p className="text-sm text-gray-400 max-w-md mx-auto">
            Dodaj przez profil kandydata („Wrzuć na targ"), albo ustaw
            availability na „Aktywnie szuka" — auto-sync wciągnie ich tu
            sam w ciągu 30 minut.
          </p>
        </div>
      ) : (
        <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-2xl overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 dark:bg-gray-900/40 text-xs uppercase text-gray-500">
              <tr>
                <th className="w-6"></th>
                <th className="text-left px-4 py-3">Kandydat</th>
                <th className="text-left px-4 py-3">Status</th>
                <th className="text-left px-4 py-3">Kategoria</th>
                <th className="text-left px-4 py-3">Owner</th>
                <th className="text-left px-4 py-3">Na targu</th>
                <th className="text-left px-4 py-3">Ważne do</th>
                <th className="w-10"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
              {items.map((c) => {
                const isOpen = expanded === c.id;
                return (
                  <>
                    <tr
                      key={c.id}
                      className={cn(
                        "hover:bg-gray-50 dark:hover:bg-gray-700/40 transition-colors",
                        isOpen && "bg-teal-50/40 dark:bg-teal-900/10"
                      )}
                    >
                      <td className="px-2 py-3">
                        <button
                          type="button"
                          onClick={() => setExpanded(isOpen ? null : c.id)}
                          className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-400 hover:text-gray-700"
                          aria-label={isOpen ? "Zwiń" : "Rozwiń matche"}
                        >
                          {isOpen ? (
                            <ChevronDown className="w-4 h-4" />
                          ) : (
                            <ChevronRight className="w-4 h-4" />
                          )}
                        </button>
                      </td>
                      <td className="px-4 py-3">
                        <Link
                          href={`/candidates/${c.id}`}
                          className="flex items-center gap-2 font-medium text-gray-900 dark:text-gray-100 hover:text-teal-600"
                        >
                          {c.avatar_url ? (
                            <img
                              src={c.avatar_url}
                              alt=""
                              className="w-7 h-7 rounded-full object-cover"
                            />
                          ) : (
                            <CircleUser className="w-7 h-7 text-gray-300" />
                          )}
                          <span>
                            {c.name} {c.lastname}
                          </span>
                        </Link>
                      </td>
                      <td className="px-4 py-3">
                        <MarketplaceStatusBadge status={c.availability_status} />
                      </td>
                      <td className="px-4 py-3 text-gray-600 dark:text-gray-300">
                        {c.competence_category ?? "—"}
                      </td>
                      <td className="px-4 py-3 text-gray-600 dark:text-gray-300">
                        {c.owner?.name ?? (
                          <span className="text-gray-400">(brak)</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-gray-500">
                        <span className="inline-flex items-center gap-1">
                          <Clock className="w-3 h-3" />
                          {daysAgo(c.added_at)}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-gray-500">
                        {c.marketplace_until ? (
                          formatDate(c.marketplace_until)
                        ) : (
                          <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-600 border border-gray-200">
                            auto
                          </span>
                        )}
                      </td>
                      <td className="px-2 py-3">
                        <button
                          type="button"
                          onClick={() => removeMutation.mutate(c.id)}
                          disabled={removeMutation.isPending}
                          className="p-1 rounded text-gray-400 hover:text-red-600 hover:bg-red-50"
                          title="Usuń z targu"
                        >
                          <XIcon className="w-4 h-4" />
                        </button>
                      </td>
                    </tr>
                    {isOpen && (
                      <tr className="bg-gray-50/60 dark:bg-gray-900/20">
                        <td colSpan={8} className="px-8">
                          <CandidateMatchesExpansion candidateId={c.id} />
                        </td>
                      </tr>
                    )}
                  </>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {totalPages > 1 && (
        <div className="flex items-center justify-between text-sm text-gray-500">
          <span>
            Strona {page} z {totalPages}
          </span>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
              className="px-3 py-1.5 rounded-lg border border-gray-200 disabled:opacity-50 hover:bg-gray-50"
            >
              Poprzednia
            </button>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page === totalPages}
              className="px-3 py-1.5 rounded-lg border border-gray-200 disabled:opacity-50 hover:bg-gray-50"
            >
              Następna
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
