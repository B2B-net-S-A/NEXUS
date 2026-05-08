"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import {
  ArrowLeft,
  BookOpen,
  Plus,
  Archive,
  ArchiveRestore,
  Loader2,
  AlertCircle,
  Edit,
  ChevronRight,
} from "lucide-react";
import {
  dictionariesApi,
  type DictionaryDto,
  type DictionaryItemDto,
  type DictionarySummaryDto,
} from "@/lib/api";
import { cn } from "@/lib/utils";

// ── Items panel (right side, when a slug is selected) ─────────────────────────

interface ItemsPanelProps {
  slug: string;
  dictionary: DictionaryDto;
}

function AddItemRow({ slug }: { slug: string }) {
  const [keyDraft, setKeyDraft] = useState("");
  const [labelDraft, setLabelDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const create = useMutation({
    mutationFn: () =>
      dictionariesApi
        .createItem(slug, { key: keyDraft.trim(), label_pl: labelDraft.trim() })
        .then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dictionary", slug] });
      queryClient.invalidateQueries({ queryKey: ["dictionaries"] });
      setKeyDraft("");
      setLabelDraft("");
      setError(null);
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : "Nie udało się dodać";
      setError(msg);
    },
  });

  const submit = () => {
    if (!keyDraft.trim() || !labelDraft.trim()) {
      setError("Klucz i etykieta są wymagane");
      return;
    }
    create.mutate();
  };

  return (
    <div className="bg-card border border-dashed border-border rounded-lg p-3">
      <div className="flex flex-wrap items-center gap-2">
        <input
          value={keyDraft}
          onChange={(e) => setKeyDraft(e.target.value)}
          placeholder="key (np. consulting)"
          className="flex-1 min-w-[10rem] px-3 py-1.5 bg-background border border-input rounded-md text-sm font-mono focus:outline-none focus:ring-2 focus:ring-ring"
        />
        <input
          value={labelDraft}
          onChange={(e) => setLabelDraft(e.target.value)}
          placeholder="Etykieta PL"
          className="flex-1 min-w-[10rem] px-3 py-1.5 bg-background border border-input rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          onKeyDown={(e) => {
            if (e.key === "Enter") submit();
          }}
        />
        <button
          type="button"
          onClick={submit}
          disabled={create.isPending}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-primary text-primary-foreground rounded-md text-sm disabled:opacity-50"
        >
          {create.isPending ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Plus className="w-4 h-4" />
          )}
          Dodaj
        </button>
      </div>
      {error && (
        <div className="mt-2 text-xs text-rose-500 flex items-center gap-1">
          <AlertCircle className="w-3 h-3" />
          {error}
        </div>
      )}
    </div>
  );
}

function ItemRow({
  slug,
  item,
}: {
  slug: string;
  item: DictionaryItemDto;
}) {
  const [editing, setEditing] = useState(false);
  const [labelDraft, setLabelDraft] = useState(item.label_pl);
  const queryClient = useQueryClient();

  const update = useMutation({
    mutationFn: (payload: Parameters<typeof dictionariesApi.updateItem>[2]) =>
      dictionariesApi.updateItem(slug, item.id, payload).then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dictionary", slug] });
      queryClient.invalidateQueries({ queryKey: ["dictionaries"] });
      setEditing(false);
    },
  });

  const saveLabel = () => {
    const trimmed = labelDraft.trim();
    if (!trimmed) return;
    update.mutate({ label_pl: trimmed });
  };

  const toggleArchive = () => {
    update.mutate({ archived: !item.archived });
  };

  return (
    <div
      className={cn(
        "flex items-center gap-3 px-3 py-2 rounded-lg bg-card border border-border",
        item.archived && "opacity-50",
      )}
    >
      <span className="text-xs font-mono text-muted-foreground w-32 truncate" title={item.key}>
        {item.key}
      </span>

      {editing ? (
        <input
          value={labelDraft}
          onChange={(e) => setLabelDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") saveLabel();
            if (e.key === "Escape") {
              setLabelDraft(item.label_pl);
              setEditing(false);
            }
          }}
          autoFocus
          className="flex-1 px-2 py-1 bg-background border border-input rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-ring"
        />
      ) : (
        <span className="flex-1 text-sm text-foreground">
          {item.label_pl}
          {item.archived && (
            <span className="ml-2 text-xs text-muted-foreground">
              (zarchiwizowane)
            </span>
          )}
        </span>
      )}

      <div className="flex items-center gap-1">
        {editing ? (
          <button
            type="button"
            onClick={saveLabel}
            className="text-xs px-2 py-1 bg-primary text-primary-foreground rounded-md"
          >
            {update.isPending ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              "Zapisz"
            )}
          </button>
        ) : (
          <button
            type="button"
            onClick={() => setEditing(true)}
            className="p-1.5 text-muted-foreground hover:text-foreground rounded-md"
            title="Edytuj"
          >
            <Edit className="w-3.5 h-3.5" />
          </button>
        )}
        <button
          type="button"
          onClick={toggleArchive}
          className="p-1.5 text-muted-foreground hover:text-foreground rounded-md"
          title={item.archived ? "Przywróć" : "Archiwizuj"}
        >
          {item.archived ? (
            <ArchiveRestore className="w-3.5 h-3.5" />
          ) : (
            <Archive className="w-3.5 h-3.5" />
          )}
        </button>
      </div>
    </div>
  );
}

function ItemsPanel({ slug, dictionary }: ItemsPanelProps) {
  const [showArchived, setShowArchived] = useState(false);
  const visibleItems = showArchived
    ? dictionary.items
    : dictionary.items.filter((i) => !i.archived);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-foreground">
            {dictionary.label_pl}
          </h2>
          {dictionary.description && (
            <p className="text-sm text-muted-foreground">
              {dictionary.description}
            </p>
          )}
        </div>
        <label className="inline-flex items-center gap-2 text-sm cursor-pointer">
          <input
            type="checkbox"
            checked={showArchived}
            onChange={(e) => setShowArchived(e.target.checked)}
            className="rounded"
          />
          Pokaż zarchiwizowane
        </label>
      </div>

      <AddItemRow slug={slug} />

      <div className="space-y-1.5">
        {visibleItems.length === 0 ? (
          <div className="p-6 text-center text-sm text-muted-foreground bg-muted/30 rounded-lg border border-dashed">
            {showArchived
              ? "Brak elementów."
              : "Brak aktywnych elementów. Dodaj pierwszy powyżej."}
          </div>
        ) : (
          visibleItems.map((item) => (
            <ItemRow key={item.id} slug={slug} item={item} />
          ))
        )}
      </div>
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function DictionariesPage() {
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);

  const indexQuery = useQuery({
    queryKey: ["dictionaries"],
    queryFn: () => dictionariesApi.list().then((r) => r.data),
  });

  const detailQuery = useQuery({
    queryKey: ["dictionary", selectedSlug],
    queryFn: () =>
      selectedSlug
        ? dictionariesApi.get(selectedSlug).then((r) => r.data)
        : Promise.resolve(null),
    enabled: Boolean(selectedSlug),
  });

  if (indexQuery.isLoading) {
    return (
      <div className="container max-w-5xl mx-auto py-8 px-4 flex items-center justify-center min-h-[400px]">
        <Loader2 className="w-8 h-8 text-muted-foreground animate-spin" />
      </div>
    );
  }

  if (indexQuery.error) {
    return (
      <div className="container max-w-5xl mx-auto py-8 px-4">
        <div className="p-6 bg-rose-500/10 border border-rose-500/20 rounded-xl text-rose-500 flex items-center gap-2">
          <AlertCircle className="w-5 h-5" />
          Nie udało się załadować słowników. Sprawdź uprawnienia administratora.
        </div>
      </div>
    );
  }

  const dictionaries: DictionarySummaryDto[] = indexQuery.data ?? [];

  return (
    <div className="container max-w-5xl mx-auto py-8 px-4">
      <div className="mb-6">
        <Link
          href="/settings"
          className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="w-4 h-4" />
          Ustawienia
        </Link>
        <h1 className="text-2xl font-bold text-foreground mt-2">Słowniki</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Edytuj wartości używane w listach rozwijanych — branże, powody
          odrzucenia, etc. Zarchiwizowane wartości pozostają w historycznych
          rekordach, ale znikają z list rozwijanych.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-[16rem_1fr] gap-6">
        <div className="space-y-1">
          <h2 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">
            Słowniki
          </h2>
          {dictionaries.map((dict) => (
            <button
              key={dict.slug}
              type="button"
              onClick={() => setSelectedSlug(dict.slug)}
              className={cn(
                "w-full flex items-center justify-between gap-2 px-3 py-2 rounded-lg text-sm transition-colors",
                selectedSlug === dict.slug
                  ? "bg-primary/10 text-primary"
                  : "text-foreground hover:bg-muted",
              )}
            >
              <span className="flex items-center gap-2 min-w-0">
                <BookOpen className="w-4 h-4 shrink-0" />
                <span className="truncate">{dict.label_pl}</span>
              </span>
              <span className="text-xs text-muted-foreground shrink-0">
                {dict.item_count}
              </span>
              <ChevronRight className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
            </button>
          ))}
        </div>

        <div>
          {selectedSlug ? (
            detailQuery.isLoading ? (
              <div className="flex items-center justify-center py-12">
                <Loader2 className="w-6 h-6 text-muted-foreground animate-spin" />
              </div>
            ) : detailQuery.data ? (
              <ItemsPanel slug={selectedSlug} dictionary={detailQuery.data} />
            ) : null
          ) : (
            <div className="p-8 text-center bg-muted/30 rounded-xl border border-dashed">
              <BookOpen className="w-8 h-8 text-muted-foreground mx-auto mb-2" />
              <p className="text-sm text-muted-foreground">
                Wybierz słownik z listy po lewej, aby edytować jego wartości.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
