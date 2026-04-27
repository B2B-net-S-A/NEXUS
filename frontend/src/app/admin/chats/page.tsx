"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  Briefcase,
  ChevronRight,
  MessageCircle,
  Search,
  User as UserIcon,
} from "lucide-react";

import { adminChatsApi } from "@/lib/api";
import { cn, formatRelativeTime } from "@/lib/utils";
import { useAuthStore } from "@/store/auth";

type ChatTypeFilter = "all" | "job" | "candidate";

export default function AdminGlobalChatsPage() {
  const user = useAuthStore((s) => s.user);
  const [search, setSearch] = useState("");
  const [activeSearch, setActiveSearch] = useState("");
  const [filter, setFilter] = useState<ChatTypeFilter>("all");

  const { data, isLoading, refetch } = useQuery({
    queryKey: ["admin-global-chats", filter, activeSearch],
    queryFn: async () => {
      const params: { limit: number; chat_type?: "job" | "candidate"; search?: string } = {
        limit: 100,
      };
      if (filter !== "all") params.chat_type = filter;
      if (activeSearch.trim()) params.search = activeSearch.trim();
      return (await adminChatsApi.listGlobal(params)).data;
    },
    refetchInterval: 30_000,
  });

  if (user?.role !== "admin") {
    return (
      <div className="p-8 text-center text-gray-500">
        Tylko administrator może oglądać globalny widok czatów.
      </div>
    );
  }

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    setActiveSearch(search);
  };

  return (
    <div className="max-w-5xl mx-auto p-6 space-y-4">
      <header className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <MessageCircle className="w-6 h-6 text-blue-500" />
          <h1 className="text-xl font-semibold">
            Globalny audyt czatów
          </h1>
        </div>
        <button
          onClick={() => refetch()}
          className="text-xs text-blue-600 hover:text-blue-800"
        >
          Odśwież
        </button>
      </header>

      {/* Filters */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex gap-1">
          {(["all", "job", "candidate"] as ChatTypeFilter[]).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={cn(
                "px-3 py-1 rounded text-sm border",
                filter === f
                  ? "bg-blue-600 text-white border-blue-600"
                  : "bg-white dark:bg-gray-900 border-gray-300 dark:border-gray-600 text-gray-700",
              )}
            >
              {f === "all" ? "Wszystkie" : f === "job" ? "Projekty" : "Kandydaci"}
            </button>
          ))}
        </div>
        <form onSubmit={handleSubmit} className="flex gap-1">
          <div className="relative">
            <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
            <input
              type="text"
              placeholder="Szukaj w treści…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-7 pr-2 py-1 text-sm rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900"
            />
          </div>
        </form>
      </div>

      {/* Items */}
      {isLoading && (
        <div className="text-center text-sm text-gray-400 py-8">
          Ładowanie…
        </div>
      )}
      {data && data.items.length === 0 && (
        <div className="text-center text-sm text-gray-400 py-8">
          Brak wiadomości pasujących do filtra.
        </div>
      )}
      <ul className="space-y-2">
        {data?.items.map((item) => {
          const link =
            item.chat_type === "job"
              ? `/jobs/${item.parent_id}?tab=chat&msg=${item.message_id}`
              : `/candidates/${item.parent_id}?tab=chat&msg=${item.message_id}`;
          const Icon = item.chat_type === "job" ? Briefcase : UserIcon;
          return (
            <li
              key={`${item.chat_type}-${item.message_id}`}
              className={cn(
                "p-3 rounded-lg border bg-white dark:bg-gray-800",
                "border-gray-200 dark:border-gray-700",
              )}
            >
              <div className="flex items-center justify-between gap-2 text-xs text-gray-500 mb-1">
                <div className="flex items-center gap-1.5">
                  <Icon className="w-3.5 h-3.5" />
                  <Link
                    href={link}
                    className="font-medium text-blue-600 hover:underline"
                  >
                    {item.parent_label}
                  </Link>
                  <ChevronRight className="w-3 h-3 text-gray-400" />
                  <span>{item.author_name ?? "(usunięty użytkownik)"}</span>
                </div>
                <span>{formatRelativeTime(item.created_at)}</span>
              </div>
              <div
                className={cn(
                  "text-sm whitespace-pre-wrap break-words",
                  item.is_deleted && "italic text-gray-400",
                )}
              >
                {item.content}
              </div>
            </li>
          );
        })}
      </ul>

      {data?.has_more && (
        <div className="text-center text-xs text-gray-500 pt-2">
          Pokazano 100 najnowszych. Użyj filtrów żeby zawęzić wyniki.
        </div>
      )}
    </div>
  );
}
