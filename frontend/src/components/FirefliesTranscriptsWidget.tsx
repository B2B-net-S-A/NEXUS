"use client";

import { useEffect, useState } from "react";
import { Loader2, Mic, RefreshCw, ExternalLink } from "lucide-react";
import api from "@/lib/api";

interface Transcript {
  id: number;
  title: string;
  candidate_id: number | null;
  created_at: string | null;
  preview: string;
}

interface Props {
  candidateId: number;
}

export function FirefliesTranscriptsWidget({ candidateId }: Props) {
  const [rows, setRows] = useState<Transcript[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await api.get<Transcript[]>("/api/fireflies/transcripts", {
        params: { candidate_id: candidateId, limit: 50 },
      });
      setRows(r.data);
    } catch (e: unknown) {
      const msg =
        e && typeof e === "object" && "response" in e
          ? ((e as { response?: { data?: { detail?: string } } }).response?.data?.detail ??
            "Błąd")
          : "Błąd";
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [candidateId]);

  const handleSync = async () => {
    setSyncing(true);
    setError(null);
    try {
      await api.get("/api/fireflies/sync");
      await load();
    } catch (e: unknown) {
      const msg =
        e && typeof e === "object" && "response" in e
          ? ((e as { response?: { data?: { detail?: string } } }).response?.data?.detail ??
            "Błąd synchronizacji")
          : "Błąd synchronizacji";
      setError(msg);
    } finally {
      setSyncing(false);
    }
  };

  const toggle = (id: number) =>
    setExpanded(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const fmt = (iso: string | null) => {
    if (!iso) return "";
    try {
      return new Date(iso).toLocaleString("pl-PL", {
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch {
      return iso;
    }
  };

  return (
    <div className="bg-card dark:bg-muted rounded-lg border border-border dark:border-border p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-medium flex items-center gap-2 text-foreground dark:text-foreground">
          <Mic className="w-4 h-4 text-orange-500" />
          Fireflies transkrypty ({rows.length})
        </h3>
        <div className="flex gap-2">
          <button
            onClick={handleSync}
            disabled={syncing}
            className="flex items-center gap-1 text-xs px-2.5 py-1 rounded-md border border-border dark:border-border hover:bg-muted dark:hover:bg-muted disabled:opacity-50"
            title="Ręczna synchronizacja z Fireflies"
          >
            {syncing ? (
              <Loader2 className="w-3 h-3 animate-spin" />
            ) : (
              <RefreshCw className="w-3 h-3" />
            )}
            Sync
          </button>
          <a
            href="https://app.fireflies.ai/"
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-1 text-xs px-2.5 py-1 rounded-md border border-border dark:border-border hover:bg-muted dark:hover:bg-muted"
          >
            <ExternalLink className="w-3 h-3" />
            Otwórz
          </a>
        </div>
      </div>

      {error && (
        <div className="text-xs text-destructive bg-destructive/10 dark:bg-destructive/15 rounded p-2 mb-2">
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex justify-center py-4">
          <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
        </div>
      ) : rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          Brak transkryptów dla tego kandydata. Kliknij <strong>Sync</strong> aby
          pociągnąć najnowsze spotkania z Fireflies.
        </p>
      ) : (
        <ul className="space-y-2">
          {rows.map(t => {
            const isOpen = expanded.has(t.id);
            return (
              <li
                key={t.id}
                className="border border-border dark:border-border rounded-lg p-3"
              >
                <button
                  onClick={() => toggle(t.id)}
                  className="w-full text-left flex items-start justify-between gap-3"
                >
                  <div className="flex-1 min-w-0">
                    <h4 className="font-medium text-sm text-foreground dark:text-foreground">
                      {t.title}
                    </h4>
                    <p className="text-xs text-muted-foreground mt-0.5">{fmt(t.created_at)}</p>
                  </div>
                  <span className="text-xs text-primary">{isOpen ? "▲" : "▼"}</span>
                </button>
                {isOpen && (
                  <div className="mt-2 pt-2 border-t border-border dark:border-border text-xs whitespace-pre-wrap text-foreground dark:text-muted-foreground">
                    {t.preview}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
