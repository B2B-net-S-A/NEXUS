"use client";

import { useState } from"react";
import { useMutation, useQuery, useQueryClient } from"@tanstack/react-query";
import { Bookmark, ChevronDown, Plus, Trash2 } from"lucide-react";
import { savedSearchesApi, type SavedSearch } from"@/lib/api";
import { useAuthStore } from"@/store/auth";
import { Button } from"@/components/ui/button";
import { Input } from"@/components/ui/input";
import {
 Popover,
 PopoverContent,
 PopoverTrigger,
} from"@/components/ui/popover";

interface SavedSearchesMenuProps {
 currentQs: string;
 onApply: (qs: string, savedSearchId: number) => void;
}

export function SavedSearchesMenu({ currentQs, onApply }: SavedSearchesMenuProps) {
 const [open, setOpen] = useState(false);
 const [newName, setNewName] = useState("");
 const currentUser = useAuthStore((s) => s.user);
 const queryClient = useQueryClient();

 const { data: searches = [] } = useQuery<SavedSearch[]>({
 queryKey: ["saved-searches","candidates"],
 queryFn: () => savedSearchesApi.list("candidates").then((r) => r.data),
 staleTime: 30_000,
 });

 const createMutation = useMutation({
 mutationFn: (name: string) =>
 savedSearchesApi.create({
 name,
 entity:"candidates",
 filters: { qs: currentQs },
 }),
 onSuccess: () => {
 queryClient.invalidateQueries({
 queryKey: ["saved-searches","candidates"],
 });
 setNewName("");
 },
 });

 const deleteMutation = useMutation({
 mutationFn: (id: number) => savedSearchesApi.delete(id),
 onSuccess: () => {
 queryClient.invalidateQueries({
 queryKey: ["saved-searches","candidates"],
 });
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

 const renderRow = (ss: SavedSearch, isMine: boolean) => (
 <div
 key={ss.id}
 className="flex items-center gap-1 px-2 py-1.5 text-sm rounded-md hover:bg-primary/10"
 >
 <button
 type="button"
 onClick={() => {
 const qs =
 typeof ss.filters.qs ==="string" ? ss.filters.qs :"";
 onApply(qs, ss.id);
 setOpen(false);
 }}
 className="flex-1 text-left truncate"
 title={ss.description ?? ss.name}
 >
 {ss.name}
 </button>
 {isMine && (
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
 )}
 </div>
 );

 const totalCount = mine.length + shared.length;

 return (
 <Popover open={open} onOpenChange={setOpen}>
 <PopoverTrigger asChild>
 <Button size="md" variant="outline">
 <Bookmark className="h-4 w-4" /> Zapisane
 {totalCount > 0 && (
 <span className="ml-1 text-[10px] text-muted-foreground">
 ({totalCount})
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
 </PopoverContent>
 </Popover>
 );
}
