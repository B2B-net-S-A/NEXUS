"use client";

import * as React from"react";
import { useState } from"react";
import { Calendar, CheckSquare, Square, X, XCircle } from"lucide-react";
import api from"@/lib/api";
import { Button } from"@/components/ui/button";
import { RequireRole } from"@/components/RequireRole";
import { ConfirmV2 } from"./ConfirmV2";

interface Props {
 selectedIds: Set<number>;
 onClear: () => void;
 onDone: (msg: string) => void;
 onSelectAllVisible: () => void;
 visibleCount: number;
}

/**
 * ContractsBulkActionsBarV2 — floating plum chrome bar (sticky bottom) with
 * extend +3m/+6m/+12m + mark ended bulk operations. Replaces v1 inline
 * BulkActionsBar inside ContractsPage.
 */
export function ContractsBulkActionsBarV2({
 selectedIds,
 onClear,
 onDone,
 onSelectAllVisible,
 visibleCount,
}: Props) {
 const [busy, setBusy] = useState(false);
 const [confirmEnd, setConfirmEnd] = useState(false);

 const bulkExtend = async (months: number) => {
 if (selectedIds.size === 0) return;
 setBusy(true);
 try {
 const params = new URLSearchParams();
 selectedIds.forEach((id) => params.append("ids", String(id)));
 params.append("months", String(months));
 const { data: res } = await api.post(
 `/api/contracts/bulk-extend?${params.toString()}`
 );
 const skipped = res.skipped_no_end_date?.length ?? 0;
 onDone(
 `Przedłużono ${res.extended} kontraktów o ${months} mies.${
 skipped > 0 ? ` (pominięto ${skipped} bez daty końca)` :""
 }.`
 );
 } finally {
 setBusy(false);
 }
 };

 const bulkMarkEnded = async () => {
 if (selectedIds.size === 0) return;
 setBusy(true);
 try {
 const params = new URLSearchParams();
 selectedIds.forEach((id) => params.append("ids", String(id)));
 const { data: res } = await api.post(
 `/api/contracts/bulk-mark-ended?${params.toString()}`
 );
 onDone(`Zakończono ${res.changed} kontraktów.`);
 } finally {
 setBusy(false);
 setConfirmEnd(false);
 }
 };

 if (selectedIds.size === 0) {
 return (
 <div className="flex items-center gap-2 text-xs text-muted-foreground">
 <button
 onClick={onSelectAllVisible}
 className="inline-flex items-center gap-1 text-primary hover:underline"
 >
 <Square className="h-3 w-3" />
 Zaznacz widoczne ({visibleCount})
 </button>
 </div>
 );
 }

 return (
 <RequireRole roles={["admin","delivery_lead"]}>
 <div className="fixed bottom-5 left-1/2 -translate-x-1/2 z-40 bg-card text-foreground rounded-xl shadow-md border border-white/10 px-4 py-2.5 flex items-center gap-3 flex-wrap animate-slide-in-bottom max-w-[min(96vw,900px)]">
 <span className="text-xs inline-flex items-center gap-1.5">
 <CheckSquare className="h-3.5 w-3.5" />
 Wybrano: <span className="font-bold">{selectedIds.size}</span>
 </span>
 <div className="h-4 w-px bg-card/15" />
 <Button
 size="sm"
 variant="primary"
 onClick={() => bulkExtend(3)}
 disabled={busy}
 >
 <Calendar className="h-3.5 w-3.5" /> +3m
 </Button>
 <Button
 size="sm"
 variant="primary"
 onClick={() => bulkExtend(6)}
 disabled={busy}
 >
 <Calendar className="h-3.5 w-3.5" /> +6m
 </Button>
 <Button
 size="sm"
 variant="primary"
 onClick={() => bulkExtend(12)}
 disabled={busy}
 >
 <Calendar className="h-3.5 w-3.5" /> +12m
 </Button>
 <Button
 size="sm"
 variant="destructive"
 onClick={() => setConfirmEnd(true)}
 disabled={busy}
 >
 <XCircle className="h-3.5 w-3.5" /> Oznacz zakończone
 </Button>
 <button
 onClick={onClear}
 className="ml-auto text-xs text-foreground/70 hover:text-foreground inline-flex items-center gap-1"
 >
 <X className="h-3 w-3" />
 Wyczyść
 </button>
 </div>

 <ConfirmV2
 open={confirmEnd}
 onOpenChange={setConfirmEnd}
 title="Oznaczyć jako zakończone ? "
 description={`Zmieni status ${selectedIds.size} kontraktów na"ended". Operację można cofnąć ręcznie.`}
 confirmLabel="Zakończ"
 variant="destructive"
 loading={busy}
 onConfirm={bulkMarkEnded}
 />
 </RequireRole>
 );
}
