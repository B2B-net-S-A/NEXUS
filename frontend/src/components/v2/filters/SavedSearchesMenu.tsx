"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
 AlertTriangle,
 Bell,
 BellRing,
 Bookmark,
 ChevronDown,
 Plus,
 Trash2,
} from "lucide-react";
import { savedSearchesApi, type SavedSearchRow } from "@/lib/api";
import { detectSavedSearchFormat } from "@/lib/saved-search-format";
import {
 buildCandidateSavedSearchPayload,
 listQsFromSavedSearch,
} from "@/lib/candidate-saved-search";
import { semanticsReapproval } from "@/lib/saved-search-reapproval";
import { SemanticsReapprovalPanel } from "@/components/v2/filters/SemanticsReapprovalPanel";
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
 /** Kto wszedł do wyniku od ostatniego otwarcia (log alertów). */
 newCandidateIds: number[],
 ) => void;
}

/** filters payload zapisywany na saved search: klasyczny querystring (replay
 * do stanu UI) + parametry GET /api/candidates (replay przez skaner alertów
 * w tle — patrz backend app/tasks/saved_search_alerts.py). */
export function SavedSearchesMenu({ currentQs, onApply }: SavedSearchesMenuProps) {
 const [open, setOpen] = useState(false);
 const [newName, setNewName] = useState("");
 // Dzwonek domyślnie WŁĄCZONY (22.09.2026): na produkcji żaden z zapisów nie
 // miał dzwonka, więc nikt nie dostawał informacji o nowych pasujących osobach.
 const [notifyOnSave, setNotifyOnSave] = useState(true);
 // Zapis wstrzymany przez migrację semantyki filtrów — panel decyzji w menu.
 const [reviewId, setReviewId] = useState<number | null>(null);
 // Wyjaśnienie w menu zamiast natywnego `alert()`, który zamrażał kartę.
 const [notice, setNotice] = useState<string | null>(null);
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
 filters: buildCandidateSavedSearchPayload(currentQs),
 notify_new_matches: notifyOnSave,
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
 if (
 enable &&
 ss.requires_reapproval &&
 !confirm(
 `Zapis „${ss.name}" zawierał wycofane miesięczne kryteria stawki. Zostały usunięte bez konwersji. Czy zatwierdzasz pozostałe filtry i chcesz ponownie włączyć alert?`,
 )
 ) {
 return Promise.resolve(null);
 }
 const qs = listQsFromSavedSearch(ss.filters);
 return savedSearchesApi.update(
 ss.id,
 enable
 ? {
 notify_new_matches: true,
 filters: buildCandidateSavedSearchPayload(qs),
 confirm_reapproval: ss.requires_reapproval,
 }
 : { notify_new_matches: false },
 );
 },
 onSuccess: invalidate,
 });

 // „Zatwierdź nowe wyniki" / „Zostaw po staremu" — istniejący mechanizm
 // `confirm_reapproval`; backend wznawia alert, który był włączony.
 const reapprovalMutation = useMutation({
 mutationFn: ({ id, choice }: { id: number; choice: "accept" | "keep_legacy" }) =>
 savedSearchesApi.update(id, {
 confirm_reapproval: true,
 reapproval_choice: choice,
 }),
 onSuccess: () => {
 setReviewId(null);
 invalidate();
 },
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
 // Zapis z dawnej wyszukiwarki ręcznej (surowe żądanie, bez `qs`) otwiera
 // się jako wiersze wymagań — `listQsFromSavedSearch` przekłada go tym
 // samym adapterem co stare adresy. Do 25.09.2026 lista odsyłała go do
 // „Wyszukaj manualnie” rekrutacji, a tego ekranu już nie ma.
 if (detectSavedSearchFormat(ss.filters) === "unknown") {
 setNotice(`Zapis „${ss.name}” ma nieobsługiwany format — nie został otwarty.`);
 return;
 }
 setNotice(null);
 // `sv=1` (zapis przypięty do dawnych zasad) i `hu=1` (v3) nie żyją w `qs`.
 const qs = listQsFromSavedSearch(ss.filters);
 let previousViewedAt: string | null = null;
 let newCandidateIds: number[] = [];
 if (isMine) {
 try {
 const r = await savedSearchesApi.markViewed(ss.id);
 previousViewedAt = r.data.previous_viewed_at;
 newCandidateIds = r.data.new_candidate_ids ?? [];
 invalidate();
 } catch {
 // Badge reset jest best-effort — sam search ma się zaaplikować zawsze.
 }
 }
 onApply(qs, ss.id, previousViewedAt, newCandidateIds);
 setOpen(false);
 };

 const renderReview = (ss: SavedSearchRow, isMine: boolean) =>
 reviewId === ss.id ? (
 <SemanticsReapprovalPanel
 name={ss.name}
 filters={ss.filters}
 canDecide={isMine}
 pending={reapprovalMutation.isPending}
 error={
 reapprovalMutation.isError
 ? "Nie udało się zapisać decyzji. Spróbuj ponownie."
 : null
 }
 onChoose={(choice) => reapprovalMutation.mutate({ id: ss.id, choice })}
 className="mx-2 mb-2"
 />
 ) : null;

 const renderRow = (ss: SavedSearchRow, isMine: boolean) => (
 <div key={ss.id}>
 <div className="flex items-center gap-1 px-2 py-1.5 text-sm rounded-md hover:bg-accent">
 <button
 type="button"
 onClick={() => void applyRow(ss, isMine)}
 className="flex-1 min-w-0 text-left flex items-center gap-1.5"
 title={ss.description ?? ss.name}
 >
 <span className="truncate">{ss.name}</span>
 {ss.requires_reapproval && !semanticsReapproval(ss.filters) ? (
 <span
 className="inline-flex shrink-0 items-center gap-1 rounded bg-warning-muted px-1.5 py-0.5 text-[10px] font-medium text-warning-muted-foreground"
 title="Miesięczne kryteria stawki zostały usunięte bez konwersji. Sprawdź pozostałe filtry przed ponownym włączeniem alertu."
 >
 <AlertTriangle aria-hidden="true" className="h-3 w-3" />
 Ponownie zatwierdź
 </span>
 ) : null}
 {isMine && ss.unseen_count > 0 && (
 <span className="shrink-0 inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full bg-primary text-primary-foreground text-[10px] font-semibold">
 {ss.unseen_count > 99 ? "99+" : ss.unseen_count}
 </span>
 )}
 </button>
 {ss.requires_reapproval && semanticsReapproval(ss.filters) ? (
 <button
 type="button"
 onClick={(e) => {
 e.stopPropagation();
 setReviewId(reviewId === ss.id ? null : ss.id);
 }}
 aria-expanded={reviewId === ss.id}
 className="inline-flex shrink-0 items-center gap-1 rounded bg-warning-muted px-1.5 py-0.5 text-[10px] font-medium text-warning-muted-foreground hover:opacity-80"
 >
 <AlertTriangle aria-hidden="true" className="h-3 w-3" />
 Sprawdź zmianę
 </button>
 ) : null}
 {isMine && (
 <>
 <button
 type="button"
 onClick={(e) => {
 e.stopPropagation();
 // Włączenie dzwonka przebudowuje filters z `qs` — dla zapisu z
 // wyszukiwania manualnego NADPISAŁOBY jego filtry, a skaner alertów
 // i tak czyta tylko format listy. Wyłączenie niczego nie przebudowuje.
 const format = detectSavedSearchFormat(ss.filters);
 if (!ss.notify_new_matches && format !== "candidates_list") {
 setNotice(
 format === "search_request"
 ? `Powiadomienia działają dla zapisów z listy. Zapis „${ss.name}” pochodzi z dawnej wyszukiwarki — otwórz go i zapisz ponownie, a nowy zapis dostanie dzwonek.`
 : `Zapis „${ss.name}” ma nieobsługiwany format — powiadomień nie da się włączyć.`,
 );
 return;
 }
 if (ss.requires_reapproval && semanticsReapproval(ss.filters)) {
 // Najpierw decyzja o nowych zasadach — dzwonek przebudowałby filtry.
 setReviewId(ss.id);
 return;
 }
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
 {renderReview(ss, isMine)}
 </div>
 );

 const totalCount = mine.length + shared.length;
 const totalUnseen = mine.reduce((acc, s) => acc + (s.unseen_count || 0), 0);

 return (
 <Popover
 open={open}
 onOpenChange={(next) => {
 setOpen(next);
 if (!next) setNotice(null);
 }}
 >
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
 {notice && (
 <p
 role="status"
 className="mb-2 rounded-md bg-muted px-2 py-1.5 text-xs leading-snug text-foreground"
 >
 {notice}
 </p>
 )}
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
 <label className="mt-2 flex items-start gap-2 px-2 text-[11px] leading-snug text-foreground">
 <input
 type="checkbox"
 checked={notifyOnSave}
 onChange={(e) => setNotifyOnSave(e.target.checked)}
 className="mt-0.5"
 />
 <span>
 Powiadamiaj, gdy ktoś zacznie pasować — nowa osoba w bazie albo
 nowe CV czy notatka u kogoś, kto już jest.
 </span>
 </label>
 <p className="mt-1 px-2 text-[10px] leading-snug text-muted-foreground">
 <Bell className="inline h-3 w-3 mr-0.5 align-[-2px]" />
 Dzwonek przy zapisie włącza i wyłącza powiadomienia. Liczba przy
 nazwie = nowe osoby od ostatniego otwarcia.
 </p>
 </PopoverContent>
 </Popover>
 );
}
