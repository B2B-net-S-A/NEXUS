"use client";

import { useState } from "react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import { useDecideTopup, usePendingTopups, type ApprovalTopupRow } from "@/lib/api/hr-approvals";

import { moneyPl } from "./approvals-format";

function TopupItem({ item }: { item: ApprovalTopupRow }) {
  const decide = useDecideTopup();
  const { showToast } = useToast();
  const [rejecting, setRejecting] = useState(false);
  const [note, setNote] = useState("");
  const doc = item.document;
  const comparison = doc.comparison;

  const send = (action: "approve" | "reject") =>
    decide.mutate(
      { id: item.request_id, documentId: doc.id, action, note: action === "reject" ? note : null },
      {
        onSuccess: () =>
          showToast(action === "approve" ? "Dopłata zatwierdzona." : "Dopłata odrzucona.", "success"),
        onError: (err) => showToast(apiErrorMessage(err, "Nie udało się zapisać decyzji."), "error"),
      },
    );

  return (
    <li className="space-y-2 border-t border-border/60 px-3.5 py-3 first:border-t-0">
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-foreground">{item.title}</p>
          <p className="text-xs text-muted-foreground">
            {item.kind_label} · {item.requester_name ?? "—"} · zgoda {item.amount_text}
          </p>
          <p className="text-xs text-muted-foreground">
            {doc.seller_name ?? "Sprzedawca"} · faktura {moneyPl(doc.gross_amount, doc.currency)}
            {comparison?.percent ? ` (+${comparison.percent}%)` : ""}
          </p>
        </div>
        <p className="text-right text-sm">
          <span className="block text-xs text-muted-foreground">Dopłata</span>
          <span className="font-semibold tabular-nums">{moneyPl(doc.topup?.amount, doc.currency)}</span>
        </p>
      </div>
      {rejecting ? (
        <div className="space-y-2">
          <Textarea
            rows={2}
            maxLength={1000}
            value={note}
            onChange={(event) => setNote(event.target.value)}
            aria-label="Dlaczego odrzucasz dopłatę"
            placeholder="Krótko: dlaczego nie"
          />
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="destructive"
              onClick={() => send("reject")}
              disabled={note.trim().length < 3}
              loading={decide.isPending}
            >
              Odrzuć dopłatę
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setRejecting(false)}>
              Anuluj
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          <Button size="sm" onClick={() => send("approve")} loading={decide.isPending}>
            Zatwierdź dopłatę
          </Button>
          <Button size="sm" variant="outline" onClick={() => setRejecting(true)}>
            Odrzuć
          </Button>
        </div>
      )}
    </li>
  );
}

/** „Dopłaty do decyzji” nad skrzynką zgód — faktura wyższa o ponad 10% (0486). */
export function TopupsPanel() {
  const topups = usePendingTopups();
  const items = topups.data ?? [];
  // Licznik Akceptacji dolicza dopłaty — awaria nie może wyglądać jak „nic nie czeka”.
  if (topups.isError) {
    return (
      <QueryStateNotice
        state="error"
        description={apiErrorMessage(topups.error, "Nie udało się wczytać dopłat do decyzji.")}
        onRetry={() => topups.refetch()}
      />
    );
  }
  if (!topups.isSuccess || items.length === 0) return null;
  return (
    <section aria-label="Dopłaty do decyzji" className="overflow-hidden rounded-xl border border-border bg-card">
      <h3 className="px-3.5 py-2.5 text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">
        Dopłaty do decyzji · {items.length}
      </h3>
      <ul>
        {items.map((item) => (
          <TopupItem key={`${item.request_id}-${item.document.id}`} item={item} />
        ))}
      </ul>
    </section>
  );
}
