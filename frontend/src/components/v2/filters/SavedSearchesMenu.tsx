"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, BellRing, Bookmark, ChevronDown, Plus, Trash2 } from "lucide-react";
import { savedSearchesApi, type SavedSearchRow } from "@/lib/api";
import { decodeFilters, filtersToApiParams } from "@/lib/url-filters";
import { useAuthStore } from "@/store/auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
 Popover,
 PopoverContent,
 PopoverTrigger,
} from "@/components/ui/popover";

interface SavedSearchesMenuProps {
 currentQs: string;
 /**
  * `previousViewedAt` — last_viewed_at sprzed tego otwarcia (tylko własne
  * searche; null = brak wyróżniania). Lista podświetla kandydatów z
  * created_at > previousViewedAt jako „Nowy".
  */
 onApply: (
 qs: string,
 savedSearchId: number,
 previousViewedAt: string | null,
 ) => void;
}

/** filters payload zapisywany na saved search: klasyczny querystring (replay
 * do stanu UI) + parametry GET /api/candidates (replay przez skaner alertów
 * w tle — patrz backend app/tasks/saved_search_alerts.py). */
function buildFiltersPayload(qs: string): Record<string, unknown> {
 const decoded = decodeFilters(new URLSearchParams(qs));
 return { qs, api: filtersToApiParams(decoded, 1) };
}

export function SavedSearchesMenu({ currentQs, onApply }: SavedSearchesMenuProps) {
 const [open, setOpen] = useState(false);
 const [newName, setNewName] = useState("");
 const currentUser = useAuthStore((s) => s.user);
 const queryClient = useQueryClient();

 const { data: searches = [] } = useQuery<SavedSearchRow[]>({
 queryKey: ["saved-searches","candidates"],
 queryFn: () => savedSearchesApi.list("candidates").then((r) => r.data),
 staleTime: 30_000,
 });

 const invalidate = () =>
 queryClient.invalidateQueries({
 queryKey: ["saved-searches","candidates"],
 });

 const createMutation = useMutation({
 mutationFn: (name: string) =>
 savedSearchesApi.create({
 name,
 entity: "candidates",
 filters: buildFiltersPayload(currentQs),
 }),
 onSuccess: () => {
 invalidate();
 setNewName("");
 },
 });

 const deleteMutation = useMutation({
 mutationFn: (id: number) => savedSearchesApi.delete(id),
 onSuccess: invalidate,
 });

 // Toggle dzwonka. Przy włączaniu odświeżamy też filters.api z zapisanego
 // qs — starsze searche mają tylko {qs}, a skaner potrzebuje parametrów API.
 const alertMutation = useMutation({
 mutationFn: (ss: SavedSearchRow) => {
 const enable = !ss.notify_new_matches;
 const qs = typeof ss.filters.qs === "string" ? ss.filters.qs : "";
 return savedSearchesApi.update(
 ss.id,
 enable
 ? { notify_new_matches: true, filters: buildFiltersPayload(qs) }
 : { notify_new_matches: false },
 );
 },
 onSuccess: invalidate,
 });

 const mine = searches.filter((s) => s.user_id === currentUser?.id);
 const shared = searches.filter(
 (s) => s.shared && s.user_id !== currentUser?.id
 );

 const saveCurrent = (e: React.FormEvent) => {
 e.preventDefault();
 const name = newName.trim();
 if (!name) return;
 createMutation.mutate(name);
 };

 const applyRow = async (ss: SavedSearchRow, isMine: boolean) => {
 const qs = typeof ss.filters.qs === "string" ? ss.filters.qs : "";
 let previousViewedAt: string | null = null;
 if (isMine) {
 try {
 const r = await savedSearchesApi.markViewed(ss.id);
 previousViewedAt = r.data.previous_viewed_at;
 invalidate();
 } catch {
 // Badge reset jest best-effort — sam search ma się zaaplikować zawsze.
 }
 }
 onApply(qs, ss.id, previousViewedAt);
 setOpen(false);
 };

 const renderRow = (ss: SavedSearchRow, isMine: boolean) => (
 <div
 key={ss.id}
 className="flex items-center gap-1 px-2 py-1.5 text-sm rounded-md hover:bg-primary/10"
 >
 <button
 type="button"
 onClick={() => void applyRow(ss, isMine)}
 className="flex-1 min-w-0 text-left flex items-center gap-1.5"
 title={ss.description ?? ss.name}
 >
 <span className="truncate">{ss.name}</span>
 {isMine && ss.unseen_count > 0 && (
 <span className="shrink-0 inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full bg-primary text-primary-foreground text-[10px] font-semibold">
 {ss.unseen_count > 99 ? "99+" : ss.unseen_count}
 </span>
 )}
 </button>
 {isMine && (
 <>
 <button
 type="button"
 onClick={(e) => {
 e.stopPropagation();
 alertMutation.mutate(ss);
 }}
 className={
 ss.notify_new_matches
 ? "h-6 w-6 flex items-center justify-center rounded-md text-primary hover:text-primary/70"
 : "h-6 w-6 flex items-center justify-center rounded-md text-muted-foreground hover:text-primary"
 }
 title={
 ss.notify_new_matches
 ? "Powiadomienia o nowych kandydatach: WŁĄCZONE"
 : "Powiadamiaj o nowych kandydatach pasujących do tego wyszukiwania"
 }
 aria-label={`Przełącz alert dla ${ss.name}`}
 >
 {ss.notify_new_matches ? (
 <BellRing className="h-3.5 w-3.5" />
 ) : (
 <Bell className="h-3.5 w-3.5" />
 )}
 </button>
 <button
 type="button"
 onClick={(e) => {
 e.stopPropagation();
 if (confirm(`Usunąć zapisane wyszukiwanie „${ss.name}"?`)) {
 deleteMutation.mutate(ss.id);
 }
 }}
 className="h-6 w-6 flex items-center justify-center rounded-md text-muted-foreground hover:text-destructive"
 aria-label={`Usuń ${ss.name}`}
 >
 <Trash2 className="h-3 w-3" />
 </button>
 </>
 )}
 </div>
 );

 const totalCount = mine.length + shared.length;
 const totalUnseen = mine.reduce((acc, s) => acc + (s.unseen_count || 0), 0);

 return (
 <Popover open={open} onOpenChange={setOpen}>
 <PopoverTrigger asChild>
 <Button size="md" variant="outline" className="relative">
 <Bookmark className="h-4 w-4" /> Zapisane
 {totalCount > 0 && (
 <span className="ml-1 text-[10px] text-muted-foreground">
 ({totalCount})
 </span>
 )}
 {totalUnseen > 0 && (
 <span className="absolute -top-1.5 -right-1.5 inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full bg-primary text-primary-foreground text-[10px] font-semibold">
 {totalUnseen > 99 ? "99+" : totalUnseen}
 </span>
 )}
 <ChevronDown className="h-4 w-4 opacity-60" />
 </Button>
 </PopoverTrigger>
 <PopoverContent align="start" className="w-72 p-2">
 {mine.length === 0 && shared.length === 0 && (
 <p className="text-xs text-muted-foreground px-2 py-3 text-center">
 Brak zapisanych wyszukiwań. Ustaw filtry i zapisz poniżej.
 </p>
 )}
 {mine.length > 0 && (
 <div>
 <h3 className="text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-1 px-2">
 Moje
 </h3>
 {mine.map((s) => renderRow(s, true))}
 </div>
 )}
 {shared.length > 0 && (
 <div className="mt-2">
 <h3 className="text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-1 px-2">
 Udostępnione
 </h3>
 {shared.map((s) => renderRow(s, false))}
 </div>
 )}
 <form
 onSubmit={saveCurrent}
 className="mt-3 pt-2 border-t border-border flex items-center gap-1"
 >
 <Input
 placeholder="Nazwa nowego zapisu…"
 value={newName}
 onChange={(e) => setNewName(e.target.value)}
 className="h-8 text-sm"
 />
 <Button
 type="submit"
 size="sm"
 variant="outline"
 disabled={!newName.trim() || createMutation.isPending}
 title="Zapisz bieżące filtry"
 >
 <Plus className="h-3.5 w-3.5" />
 </Button>
 </form>
 <p className="mt-2 px-2 text-[10px] leading-snug text-muted-foreground">
 <Bell className="inline h-3 w-3 mr-0.5 align-[-2px]" />
 Włącz dzwonek przy zapisie, aby dostawać powiadomienia o nowych
 kandydatach pasujących do wyszukiwania.
 </p>
 </PopoverContent>
 </Popover>
 );
}
