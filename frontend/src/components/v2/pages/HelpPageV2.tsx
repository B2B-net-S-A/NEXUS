"use client";

import { useCallback, useEffect, useMemo, useState } from"react";
import { useMutation, useQuery, useQueryClient } from"@tanstack/react-query";
import {
 BookOpen,
 Eye,
 EyeOff,
 HelpCircle,
 Library,
 Pencil,
 Plus,
 Search,
 Trash2,
} from"lucide-react";
import ReactMarkdown from"react-markdown";
import remarkGfm from"remark-gfm";

import { Button } from"@/components/ui/button";
import { Input } from"@/components/ui/input";
import { cn } from"@/lib/utils";
import { hasRole, useAuthStore } from"@/store/auth";
import {
 Procedure,
 ProcedureSummary,
 proceduresApi,
} from"@/lib/api/procedures";
import { ProcedureEditorModal } from"@/components/v2/modals/ProcedureEditorModal";
import { TabsContent } from"@/components/ui/tabs";
import { TabbedNav, TabbedNavItem } from"@/components/ds/TabbedNav";
import { HelpMaterial } from"@/lib/api/help-materials";
import { HelpMaterialsSection } from"@/components/v2/pages/HelpMaterialsSection";
import { HelpMaterialEditorModal } from"@/components/v2/modals/HelpMaterialEditorModal";

type HelpTab ="procedures" |"materials";

const HELP_TABS: TabbedNavItem[] = [
 { value:"procedures", label:"Procedury", icon: BookOpen },
 { value:"materials", label:"Materiały", icon: Library },
];

/**
 * Pomoc — wewnętrzna baza wiedzy dla zespołu, dwie zakładki:
 *  · Procedury (SOP) — treść trzymana i renderowana w NEXUSie,
 *  · Materiały — biblioteka LINKÓW do dokumentów w SharePoincie (NEXUS ich
 *    nie hostuje; tam są natywnie edytowalne w Word Online).
 * Widoczna dla wszystkich zalogowanych; edycja tylko dla roli `admin`.
 */
export function HelpPageV2() {
 const { user } = useAuthStore();
 const isAdmin = hasRole(user, "admin");
 const queryClient = useQueryClient();

 const [rawQuery, setRawQuery] = useState("");
 const [debouncedQuery, setDebouncedQuery] = useState("");
 const [selectedId, setSelectedId] = useState<number | null>(null);
 const [editorOpen, setEditorOpen] = useState(false);
 const [editorTarget, setEditorTarget] = useState<Procedure | null>(null);
 const [toast, setToast] = useState<{ message: string; type: "success" | "error" } | null>(
 null
 );
 const [activeTab, setActiveTab] = useState<HelpTab>("procedures");
 const [materialEditorOpen, setMaterialEditorOpen] = useState(false);
 const [materialEditorTarget, setMaterialEditorTarget] = useState<HelpMaterial | null>(null);
 const [materialCategories, setMaterialCategories] = useState<string[]>([]);

 useEffect(() => {
 const handle = setTimeout(() => setDebouncedQuery(rawQuery), 250);
 return () => clearTimeout(handle);
 }, [rawQuery]);

 const listQuery = useQuery({
 queryKey: ["procedures", { q: debouncedQuery, asAdmin: isAdmin }],
 queryFn: () =>
 proceduresApi.list({
 q: debouncedQuery || undefined,
 published_only: isAdmin ? false : true,
 }),
 });

 const items: ProcedureSummary[] = listQuery.data ?? [];

 // Auto-select first item when list loads (and when filter changes)
 useEffect(() => {
 if (items.length === 0) {
 setSelectedId(null);
 return;
 }
 if (selectedId === null || !items.some((i) => i.id === selectedId)) {
 setSelectedId(items[0].id);
 }
 }, [items, selectedId]);

 const detailQuery = useQuery({
 queryKey: ["procedure", selectedId],
 queryFn: () => proceduresApi.get(selectedId!),
 enabled: selectedId !== null,
 });

 const deleteMutation = useMutation({
 mutationFn: (id: number) => proceduresApi.remove(id),
 onSuccess: () => {
 queryClient.invalidateQueries({ queryKey: ["procedures"] });
 setSelectedId(null);
 showToast("Procedura usunięta");
 },
 });

 // `type` przychodzi z akcji szablonu zaproszenia (kopiowanie do schowka bywa
 // blokowane przez przeglądarkę). Bez niego nieudane kopiowanie pokazywało się
 // tym samym, neutralnym dymkiem co sukces — rekruter szedł dalej przekonany,
 // że treść ma w schowku.
 const showToast = (msg: string, type: "success" | "error" = "success") => {
 setToast({ message: msg, type });
 setTimeout(() => setToast(null), 3000);
 };

 const handleEdit = async (id: number) => {
 try {
 const full = await proceduresApi.get(id);
 setEditorTarget(full);
 setEditorOpen(true);
 } catch {
 showToast("Nie udało się wczytać procedury");
 }
 };

 const handleDelete = (proc: Procedure) => {
 if (typeof window !== "undefined") {
 const ok = window.confirm(`Usunąć procedurę"${proc.title}"? Operacja nieodwracalna.`);
 if (!ok) return;
 }
 deleteMutation.mutate(proc.id);
 };

 const openMaterialEditor = (target: HelpMaterial | null) => {
 setMaterialEditorTarget(target);
 setMaterialEditorOpen(true);
 };

 // Stabilna referencja — sekcja woła to z useEffect.
 const handleMaterialCategories = useCallback((categories: string[]) => {
 setMaterialCategories(categories);
 }, []);

 const statsText = useMemo(() => {
 if (listQuery.isLoading) return"Ładowanie…";
 if (items.length === 0) return"Brak procedur";
 return `${items.length} ${items.length === 1 ?"procedura" : items.length < 5 ?"procedury" :"procedur"}`;
 }, [listQuery.isLoading, items.length]);

 return (
 <div className="max-w-[1400px] mx-auto space-y-4">
 {/* Header */}
 <div className="flex items-end justify-between flex-wrap gap-3">
 <div>
 <p className="text-xs font-semibold uppercase tracking-eyebrow text-primary">
 System · Pomoc
 </p>
 <h1 className="font-semibold text-3xl font-extrabold tracking-heading-tight text-foreground mt-1">
 Pomoc
 </h1>
 <p className="text-sm text-muted-foreground mt-1">
 Wewnętrzna baza wiedzy: procedury (SOP), checklisty, FAQ zespołowe
 oraz materiały firmowe.
 </p>
 </div>
 {isAdmin &&
 (activeTab ==="procedures" ? (
 <Button
 size="sm"
 variant="primary"
 onClick={() => {
 setEditorTarget(null);
 setEditorOpen(true);
 }}
 >
 <Plus className="h-4 w-4" /> Dodaj procedurę
 </Button>
 ) : (
 <Button
 size="sm"
 variant="primary"
 onClick={() => openMaterialEditor(null)}
 >
 <Plus className="h-4 w-4" /> Dodaj materiał
 </Button>
 ))}
 </div>

 <TabbedNav
 tabs={HELP_TABS}
 value={activeTab}
 onValueChange={(v) => setActiveTab(v as HelpTab)}
 ariaLabel="Sekcje pomocy"
 >
 <TabsContent value="procedures">
 {/* Layout: list + content */}
 <div className="grid grid-cols-1 md:grid-cols-[320px_1fr] gap-4">
 {/* Left: search + list */}
 <aside className="space-y-3 md:sticky md:top-4 md:self-start">
 <Input
 leadingIcon={<Search className="h-4 w-4" />}
 placeholder="Szukaj po tytule lub treści…"
 value={rawQuery}
 onChange={(e) => setRawQuery(e.target.value)}
 />
 <nav
 aria-label="Lista procedur"
 className="rounded-lg border border-border bg-card overflow-hidden"
 >
 {listQuery.isLoading ? (
 <p className="p-4 text-sm text-muted-foreground">Ładowanie…</p>
 ) : items.length === 0 ? (
 <div className="p-6 text-center">
 <BookOpen className="h-8 w-8 mx-auto text-muted-foreground opacity-40 mb-2" />
 <p className="text-sm text-muted-foreground">
 {debouncedQuery
 ?"Brak wyników dla tego zapytania."
 : isAdmin
 ?"Brak procedur. Dodaj pierwszą, żeby zacząć."
 :"Brak procedur. Skontaktuj się z administratorem."}
 </p>
 </div>
 ) : (
 <ul className="divide-y divide-border">
 {items.map((item) => {
 const active = item.id === selectedId;
 return (
 <li key={item.id}>
 <button
 type="button"
 onClick={() => setSelectedId(item.id)}
 className={cn("w-full text-left px-4 py-3 transition-colors flex items-start gap-2","hover:bg-primary/10",
 active &&"bg-primary/10"
 )}
 aria-current={active ?"true" : undefined}
 >
 <span className="flex-1 min-w-0">
 <span className="block text-sm font-medium text-foreground truncate">
 {item.title}
 </span>
 <span className="block text-xs text-muted-foreground mt-0.5">
 {new Date(item.updated_at).toLocaleDateString("pl-PL")}
 </span>
 </span>
 {!item.is_published && isAdmin && (
 <span
 title="Szkic"
 className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wider text-muted-foreground mt-0.5 shrink-0"
 >
 <EyeOff className="h-3 w-3" /> szkic
 </span>
 )}
 </button>
 </li>
 );
 })}
 </ul>
 )}
 </nav>
 <p className="text-xs text-muted-foreground px-1">{statsText}</p>
 </aside>

 {/* Right: content */}
 <section className="rounded-lg border border-border bg-card min-h-[400px]">
 {selectedId === null ? (
 <EmptyContent />
 ) : detailQuery.isLoading ? (
 <div className="p-8 text-sm text-muted-foreground">Ładowanie procedury…</div>
 ) : detailQuery.error || !detailQuery.data ? (
 <div className="p-8 text-sm text-muted-foreground">
 Nie udało się wczytać procedury.
 </div>
 ) : (
 <ProcedureContent
 procedure={detailQuery.data}
 isAdmin={isAdmin}
 onEdit={() => handleEdit(detailQuery.data!.id)}
 onDelete={() => handleDelete(detailQuery.data!)}
 />
 )}
 </section>
 </div>
 </TabsContent>

 <TabsContent value="materials">
 <HelpMaterialsSection
 isAdmin={isAdmin}
 onEdit={(material) => openMaterialEditor(material)}
 onAdd={() => openMaterialEditor(null)}
 onToast={showToast}
 onCategoriesChange={handleMaterialCategories}
 />
 </TabsContent>
 </TabbedNav>

 {editorOpen && (
 <ProcedureEditorModal
 procedure={editorTarget}
 open={editorOpen}
 onOpenChange={(v) => {
 setEditorOpen(v);
 if (!v) setEditorTarget(null);
 }}
 onSaved={(saved) => {
 setEditorOpen(false);
 setEditorTarget(null);
 setSelectedId(saved.id);
 showToast(editorTarget ?"Procedura zaktualizowana" :"Procedura dodana");
 }}
 />
 )}

 {materialEditorOpen && (
 <HelpMaterialEditorModal
 material={materialEditorTarget}
 open={materialEditorOpen}
 categorySuggestions={materialCategories}
 onOpenChange={(v) => {
 setMaterialEditorOpen(v);
 if (!v) setMaterialEditorTarget(null);
 }}
 onSaved={() => {
 setMaterialEditorOpen(false);
 showToast(
 materialEditorTarget ?"Materiał zaktualizowany" :"Materiał dodany"
 );
 setMaterialEditorTarget(null);
 }}
 />
 )}

 {toast && (
 <div
 role="status"
 className={cn(
"fixed bottom-4 right-4 z-9999 px-4 py-3 rounded-lg shadow-md text-sm border",
 toast.type ==="error"
 ?"bg-destructive-muted text-destructive-muted-foreground border-destructive"
 :"bg-card text-foreground border-border"
 )}
 >
 {toast.message}
 </div>
 )}
 </div>
 );
}

function EmptyContent() {
 return (
 <div className="p-10 text-center">
 <HelpCircle className="h-10 w-10 mx-auto text-muted-foreground opacity-40 mb-3" />
 <p className="text-sm text-muted-foreground">
 Wybierz procedurę z listy, aby zobaczyć jej treść.
 </p>
 </div>
 );
}

function ProcedureContent({
 procedure,
 isAdmin,
 onEdit,
 onDelete,
}: {
 procedure: Procedure;
 isAdmin: boolean;
 onEdit: () => void;
 onDelete: () => void;
}) {
 return (
 <article className="p-6 md:p-8">
 <header className="flex items-start justify-between gap-4 flex-wrap mb-5">
 <div className="min-w-0">
 <h2 className="font-semibold text-2xl font-bold tracking-heading text-foreground">
 {procedure.title}
 </h2>
 <p className="text-xs text-muted-foreground mt-1">
 Aktualizacja: {new Date(procedure.updated_at).toLocaleString("pl-PL")}
 {!procedure.is_published && (
 <span className="ml-2 inline-flex items-center gap-1 text-primary">
 <EyeOff className="h-3 w-3" /> szkic
 </span>
 )}
 {procedure.is_published && (
 <span className="ml-2 inline-flex items-center gap-1 text-muted-foreground">
 <Eye className="h-3 w-3" /> opublikowane
 </span>
 )}
 </p>
 </div>
 {isAdmin && (
 <div className="flex gap-2 shrink-0">
 <Button size="sm" variant="outline" onClick={onEdit}>
 <Pencil className="h-4 w-4" /> Edytuj
 </Button>
 <Button size="sm" variant="ghost" onClick={onDelete}>
 <Trash2 className="h-4 w-4 text-primary" /> Usuń
 </Button>
 </div>
 )}
 </header>

 <div className="prose prose-sm md:prose-base max-w-none prose-headings:font-semibold prose-headings:text-foreground prose-a:text-primary">
 <ReactMarkdown remarkPlugins={[remarkGfm]}>{procedure.content}</ReactMarkdown>
 </div>
 </article>
 );
}
