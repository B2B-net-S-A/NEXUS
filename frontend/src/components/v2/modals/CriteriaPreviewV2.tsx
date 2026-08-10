"use client";

import * as React from"react";
import { useCallback, useEffect, useState } from"react";
import { ArrowDown, ArrowUp, Plus, Save, Sparkles, X } from"lucide-react";
import api, { recommendationsApi } from"@/lib/api";
import {
 Dialog,
 DialogBody,
 DialogContent,
 DialogDescription,
 DialogFooter,
 DialogHeader,
 DialogTitle,
} from"@/components/ui/dialog";
import { Button } from"@/components/ui/button";
import { Badge } from"@/components/ui/badge";
import { Input } from"@/components/ui/input";

type Skill = { name: string; level?: string | null };

interface Props {
 open: boolean;
 onOpenChange: (open: boolean) => void;
 jobId: number;
 onSaved?: () => void;
}

export function CriteriaPreviewV2({ open, onOpenChange, jobId, onSaved }: Props) {
 const [loading, setLoading] = useState(true);
 const [saving, setSaving] = useState(false);
 const [error, setError] = useState<string | null>(null);
 const [source, setSource] = useState<"ollama" |"heuristic" | null>(null);
 const [must, setMust] = useState<Skill[]>([]);
 const [nice, setNice] = useState<Skill[]>([]);
 const [newMust, setNewMust] = useState("");
 const [newNice, setNewNice] = useState("");
 // name -> true iff the chip will be bolded as a technology in the generated CV
 const [techMap, setTechMap] = useState<Record<string, boolean>>({});

 const classify = useCallback(async (names: string[]) => {
 const uniq = Array.from(new Set(names.map((n) => n.trim()).filter(Boolean)));
 if (uniq.length === 0) return;
 try {
 const r = await recommendationsApi.classifyTechnologies(uniq);
 setTechMap((prev) => ({ ...prev, ...r.data.technologies }));
 } catch {
 // best-effort preview — leave chips unmarked on failure
 }
 }, []);

 useEffect(() => {
 if (!open) return;
 let cancel = false;
 (async () => {
 setLoading(true);
 setError(null);
 setTechMap({});
 try {
 const r = await recommendationsApi.previewCriteria(jobId);
 if (cancel) return;
 const m = [...(r.data.must_skills ?? [])];
 const n = [...(r.data.nice_skills ?? [])];
 setMust(m);
 setNice(n);
 setSource(r.data.source);
 void classify([...m, ...n].map((s) => s.name));
 } catch (e: any) {
 if (!cancel) {
 setError(e?.response?.data?.detail ??"Błąd generowania kryteriów.");
 }
 } finally {
 if (!cancel) setLoading(false);
 }
 })();
 return () => {
 cancel = true;
 };
 }, [open, jobId, classify]);

 const addSkill = (list: "must" |"nice", input: string) => {
 const n = input.trim();
 if (!n) return;
 const setter = list === "must" ? setMust : setNice;
 const arr = list === "must" ? must : nice;
 if (arr.some((s) => s.name.toLowerCase() === n.toLowerCase())) return;
 setter([...arr, { name: n }]);
 void classify([n]);
 if (list === "must") setNewMust("");
 else setNewNice("");
 };

 const remove = (list: "must" |"nice", idx: number) => {
 if (list === "must") setMust(must.filter((_, i) => i !== idx));
 else setNice(nice.filter((_, i) => i !== idx));
 };

 const move = (from: "must" |"nice", idx: number) => {
 if (from === "must") {
 const s = must[idx];
 setMust(must.filter((_, i) => i !== idx));
 setNice([...nice, s]);
 } else {
 const s = nice[idx];
 setNice(nice.filter((_, i) => i !== idx));
 setMust([...must, s]);
 }
 };

 const handleSave = async () => {
 setSaving(true);
 setError(null);
 try {
 await api.patch(`/api/jobs/${jobId}`, { must_skills: must, nice_skills: nice });
 onSaved?.();
 onOpenChange(false);
 } catch (e: any) {
 setError(e?.response?.data?.detail ??"Błąd zapisu.");
 } finally {
 setSaving(false);
 }
 };

 return (
 <Dialog open={open} onOpenChange={onOpenChange}>
 <DialogContent size="lg">
 <DialogHeader>
 <div className="flex items-center gap-2">
 <Sparkles className="h-4 w-4 text-primary" />
 <DialogTitle>Kryteria AI — must-have / nice-to-have</DialogTitle>
 {source && (
 <Badge variant="soft" size="sm">
 {source === "ollama" ?"Ollama" :"heurystyka"}
 </Badge>
 )}
 </div>
 <DialogDescription>
 Popraw sugestie AI zanim zapiszesz do rekrutacji.
 </DialogDescription>
 </DialogHeader>

 <DialogBody>
 {loading ? (
 <div className="py-8 text-center text-sm text-muted-foreground">
 Generuję kryteria…
 </div>
 ) : error ? (
 <div className="text-sm text-primary bg-primary/10 px-3 py-2 rounded-md">
 {error}
 </div>
 ) : (
 <div className="space-y-3">
 <div className="grid md:grid-cols-2 gap-4">
 <SkillColumn
 title="Must-have"
 color="burgundy"
 skills={must}
 techMap={techMap}
 input={newMust}
 onInputChange={setNewMust}
 onAdd={() => addSkill("must", newMust)}
 onRemove={(i) => remove("must", i)}
 onMove={(i) => move("must", i)}
 moveLabel="↓ do nice-to-have"
 />
 <SkillColumn
 title="Nice-to-have"
 color="soft"
 skills={nice}
 techMap={techMap}
 input={newNice}
 onInputChange={setNewNice}
 onAdd={() => addSkill("nice", newNice)}
 onRemove={(i) => remove("nice", i)}
 onMove={(i) => move("nice", i)}
 moveLabel="↑ do must-have"
 />
 </div>
 <p className="text-xs text-muted-foreground">
 <span className="font-semibold text-foreground">Pogrubione</span> chipy zostaną
 wyróżnione (bold) w wygenerowanym CV jako technologie. Wyszarzone (np.
 metodyki, kompetencje, języki) — nie. Zmiana kryteriów wymaga{" "}
 <span className="font-semibold text-foreground">ponownego wygenerowania CV</span>.
 </p>
 </div>
 )}
 </DialogBody>

 <DialogFooter>
 <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={saving}>
 Anuluj
 </Button>
 <Button variant="primary" onClick={handleSave} loading={saving}>
 <Save className="h-4 w-4" />
 Zapisz
 </Button>
 </DialogFooter>
 </DialogContent>
 </Dialog>
 );
}

function SkillColumn({
 title,
 color,
 skills,
 techMap,
 input,
 onInputChange,
 onAdd,
 onRemove,
 onMove,
 moveLabel,
}: {
 title: string;
 color: "burgundy" |"soft";
 skills: Skill[];
 techMap: Record<string, boolean>;
 input: string;
 onInputChange: (v: string) => void;
 onAdd: () => void;
 onRemove: (i: number) => void;
 onMove: (i: number) => void;
 moveLabel: string;
}) {
 return (
 <div className="rounded-lg border border-border p-3">
 <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-2 flex items-center gap-2">
 {title}
 <Badge size="sm" variant={color}>
 {skills.length}
 </Badge>
 </h3>
 <div className="flex flex-wrap gap-1.5 mb-3 min-h-[40px]">
 {skills.length === 0 ? (
 <span className="text-xs text-muted-foreground italic">Brak</span>
 ) : (
 skills.map((s, i) => {
 const willBold = techMap[s.name.trim()];
 return (
 <span
 key={s.name}
 title={
 willBold === false
 ? "Nie zostanie pogrubione w CV (nie rozpoznano jako technologia)"
 : willBold
 ? "Zostanie pogrubione w CV jako technologia"
 : undefined
 }
 className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary ${
 willBold === false ? "opacity-50" : willBold ? "font-semibold" : ""
 }`}
 >
 {s.name}
 <button
 onClick={() => onMove(i)}
 title={moveLabel}
 className="hover:opacity-70"
 >
 {moveLabel.startsWith("↓") ? (
 <ArrowDown className="h-3 w-3" />
 ) : (
 <ArrowUp className="h-3 w-3" />
 )}
 </button>
 <button onClick={() => onRemove(i)} className="hover:opacity-70">
 <X className="h-3 w-3" />
 </button>
 </span>
 );
 })
 )}
 </div>
 <div className="flex gap-2">
 <Input
 value={input}
 onChange={(e) => onInputChange(e.target.value)}
 onKeyDown={(e) => {
 if (e.key === "Enter") {
 e.preventDefault();
 onAdd();
 }
 }}
 placeholder="np. Python"
 className="flex-1"
 />
 <Button size="sm" variant="outline" onClick={onAdd}>
 <Plus className="h-4 w-4" />
 </Button>
 </div>
 </div>
 );
}
