"use client";

import * as React from"react";
import { useRef, useState } from"react";
import { useMutation, useQueryClient } from"@tanstack/react-query";
import {
 AlertCircle,
 CheckCircle2,
 FileUp,
 Upload,
 XCircle,
} from"lucide-react";
import api from"@/lib/api";
import { cn } from"@/lib/utils";
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

interface ImportResult {
 imported?: number;
 skipped?: number;
 errors?: { row: number; reason: string }[];
 total_rows?: number;
}

interface Props {
 open: boolean;
 onOpenChange: (open: boolean) => void;
 onImported?: () => void;
}

export function ImportCandidatesV2({ open, onOpenChange, onImported }: Props) {
 const queryClient = useQueryClient();
 const fileInputRef = useRef<HTMLInputElement>(null);
 const [file, setFile] = useState<File | null>(null);
 const [dragOver, setDragOver] = useState(false);
 const [result, setResult] = useState<ImportResult | null>(null);
 const [error, setError] = useState<string | null>(null);

 const reset = () => {
 setFile(null);
 setResult(null);
 setError(null);
 };

 // Reset on close
 React.useEffect(() => {
 if (!open) reset();
 }, [open]);

 const importMut = useMutation({
 mutationFn: async (f: File) => {
 const fd = new FormData();
 fd.append("file", f);
 const r = await api.post("/api/import/candidates", fd, {
 headers: {"Content-Type":"multipart/form-data" },
 });
 return r.data as ImportResult;
 },
 onSuccess: (data) => {
 setResult(data);
 queryClient.invalidateQueries({ queryKey: ["candidates"] });
 queryClient.invalidateQueries({ queryKey: ["candidates-v2"] });
 onImported?.();
 },
 onError: (err: any) => {
 setError(err?.response?.data?.detail ||"Błąd podczas importu. Sprawdź format pliku.");
 },
 });

 const handleFile = (f: File) => {
 if (!f.name.toLowerCase().endsWith(".csv")) {
 setError("Dozwolone są tylko pliki CSV.");
 return;
 }
 setError(null);
 setFile(f);
 };

 return (
 <Dialog open={open} onOpenChange={onOpenChange}>
 <DialogContent size="md">
 {result ? (
 <>
 <DialogHeader>
 <div className="flex items-center gap-2">
 <CheckCircle2 className="h-5 w-5 text-[#1d5e31]" />
 <DialogTitle>Import zakończony</DialogTitle>
 </div>
 </DialogHeader>
 <DialogBody>
 <dl className="grid grid-cols-3 gap-3 text-sm">
 <div className="rounded-lg bg-primary/10 p-3">
 <dt className="text-xs text-muted-foreground uppercase tracking-wider">
 Zaimportowano
 </dt>
 <dd className="text-2xl font-bold text-primary font-mono">
 {result.imported ?? 0}
 </dd>
 </div>
 <div className="rounded-lg bg-amber-50 border border-amber-200 p-3">
 <dt className="text-xs text-amber-700 uppercase tracking-wider">Pominięto</dt>
 <dd className="text-2xl font-bold text-amber-800 font-mono">
 {result.skipped ?? 0}
 </dd>
 </div>
 <div className="rounded-lg bg-[hsl(var(--border-subtle))]/40 p-3">
 <dt className="text-xs text-muted-foreground uppercase tracking-wider">
 Wierszy łącznie
 </dt>
 <dd className="text-2xl font-bold text-foreground font-mono">
 {result.total_rows ?? 0}
 </dd>
 </div>
 </dl>
 {!!result.errors?.length && (
 <div className="mt-4">
 <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-2">
 Błędy ({result.errors.length})
 </h3>
 <div className="space-y-1 max-h-40 overflow-y-auto text-xs">
 {result.errors.slice(0, 20).map((e, i) => (
 <div
 key={i}
 className="flex items-start gap-1.5 text-primary"
 >
 <XCircle className="h-3 w-3 mt-0.5 shrink-0" />
 <span>
 Wiersz {e.row}: {e.reason}
 </span>
 </div>
 ))}
 </div>
 </div>
 )}
 </DialogBody>
 <DialogFooter>
 <Button variant="ghost" onClick={() => reset()}>
 Importuj kolejny
 </Button>
 <Button variant="primary" onClick={() => onOpenChange(false)}>
 Zamknij
 </Button>
 </DialogFooter>
 </>
 ) : (
 <>
 <DialogHeader>
 <div className="flex items-center gap-2">
 <FileUp className="h-4 w-4 text-primary" />
 <DialogTitle>Import kandydatów z CSV</DialogTitle>
 </div>
 <DialogDescription>
 Plik CSV z kolumnami: name, lastname, email, phone, location, source.
 </DialogDescription>
 </DialogHeader>

 <DialogBody>
 <div
 onDragOver={(e) => {
 e.preventDefault();
 setDragOver(true);
 }}
 onDragLeave={() => setDragOver(false)}
 onDrop={(e) => {
 e.preventDefault();
 setDragOver(false);
 const f = e.dataTransfer.files?.[0];
 if (f) handleFile(f);
 }}
 onClick={() => fileInputRef.current?.click()}
 className={cn("cursor-pointer rounded-lg border-2 border-dashed p-8 text-center transition-colors",
 dragOver
 ?"border-primary bg-primary/10"
 :"border-border hover:border-primary/60 hover:bg-background/40"
 )}
 >
 <Upload className="h-10 w-10 mx-auto mb-3 text-muted-foreground" />
 {file ? (
 <div>
 <div className="text-sm font-medium text-foreground">
 {file.name}
 </div>
 <div className="text-xs text-muted-foreground">
 {(file.size / 1024).toFixed(1)} KB
 </div>
 </div>
 ) : (
 <div>
 <div className="text-sm font-medium text-foreground">
 Przeciągnij plik CSV lub kliknij
 </div>
 <div className="text-xs text-muted-foreground mt-1">
 Max 10 MB · UTF-8
 </div>
 </div>
 )}
 <input
 ref={fileInputRef}
 type="file"
 accept=".csv,text/csv"
 hidden
 onChange={(e) => {
 const f = e.target.files?.[0];
 if (f) handleFile(f);
 }}
 />
 </div>
 {error && (
 <div
 role="alert"
 className="mt-3 inline-flex items-center gap-2 text-sm text-primary bg-primary/10 px-3 py-2 rounded-md w-full"
 >
 <AlertCircle className="h-4 w-4 shrink-0" />
 <span>{error}</span>
 </div>
 )}
 </DialogBody>

 <DialogFooter>
 <Button variant="ghost" onClick={() => onOpenChange(false)}>
 Anuluj
 </Button>
 <Button
 variant="primary"
 disabled={!file}
 loading={importMut.isPending}
 onClick={() => file && importMut.mutate(file)}
 >
 <Upload className="h-4 w-4" /> Importuj
 </Button>
 </DialogFooter>
 </>
 )}
 </DialogContent>
 </Dialog>
 );
}
