"use client";

// Zakładka „📝 Draft (do uzupełnienia)" widoku wielo-konsultantowego (BIK/BNP).
//
// Wiersz = samodzielny szkic zamówienia z hooka zatrudnienia („Oznacz jako
// podpisane" / pipeline „hired"). Delivery Lead uzupełnia tu te same 4 pola
// co w widoku jednoosobowym (numer, okres, obie stawki) — tym samym widgetem
// inline (`InlineOrderFields`). Po komplecie backend aktywuje zamówienie
// i MATERIALIZUJE grupę o wpisanym numerze; wiersz przechodzi wtedy do
// „Aktywne" jako linia grupy. Piąte pole — „liczba MD" — jest opcjonalne
// (nie blokuje aktywacji) i zasila alert `ALERT_MD_BUDGET_LOW`.

import { EmptyState } from "@/components/ds";
import {
  InlinePeriod,
  InlineText,
  fmtDate,
} from "@/components/orders/InlineOrderFields";
import { dlPortalApi, type ClientOrderUpdate } from "@/lib/api/dlPortal";
import type { OrderDraftRead } from "@/lib/api/orderGroups";
import { parseDecimalInput, sanitizeDecimalInput } from "@/lib/utils";

function fmtMoney(v: number | null): string {
  if (v === null || v === undefined) return "—";
  return v.toLocaleString("pl-PL");
}

/** Szkice z hooka zatrudnienia u klientów MD rodzą się z tytułem
 *  „(bez numeru)" — dla UI to BRAK numeru (pole do uzupełnienia),
 *  nie wartość do pokazania czy prefill edytora. */
function editableTitle(title: string): string {
  return title === "(bez numeru)" ? "" : title;
}

/** Czytelny komunikat z 4xx — `detail` bywa stringiem albo obiektem. */
function saveError(err: unknown): Error {
  const detail = (err as { response?: { data?: { detail?: unknown } } })
    ?.response?.data?.detail;
  if (typeof detail === "string") return new Error(detail);
  return err instanceof Error ? err : new Error("Nie udało się zapisać");
}

interface Props {
  clientId: number;
  drafts: OrderDraftRead[];
  /** admin / Delivery Lead — te same role, które prowadzą obsadę zamówień. */
  canManage: boolean;
  onError: (msg: string) => void;
  /** Po każdym zapisie; `activated` gdy szkic przeszedł do „Aktywne". */
  onSaved: (result: { activated: boolean; orderNumber: string }) => void;
}

export function DraftOrdersSection({
  clientId,
  drafts,
  canManage,
  onError,
  onSaved,
}: Props) {
  async function patch(draft: OrderDraftRead, payload: ClientOrderUpdate) {
    try {
      const res = await dlPortalApi.updateOrder(clientId, draft.id, payload);
      onSaved({
        activated: res.data.status === "active",
        orderNumber: res.data.title,
      });
    } catch (err) {
      throw saveError(err);
    }
  }

  if (drafts.length === 0) {
    return (
      <EmptyState
        title="Brak szkiców do uzupełnienia"
        description={
          "Szkic pojawia się tu automatycznie po „Oznacz jako podpisane” " +
          "w Generatorze umów B2B (dla umów podpisanych od dnia wdrożenia " +
          "zakładki). Po uzupełnieniu numeru, okresu i obu stawek zamówienie " +
          "przechodzi do „Aktywne”."
        }
      />
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="text-xs text-muted-foreground">
        Po uzupełnieniu numeru zamówienia, daty rozpoczęcia i obu stawek szkic
        automatycznie przechodzi do „Aktywne” (okres bezterminowy nie blokuje
        aktywacji). Liczba MD jest opcjonalna — można ją uzupełnić później.
      </p>
      {drafts.map((draft) => (
        <div
          key={draft.id}
          className="rounded-lg border border-border bg-card p-4"
          data-testid={`draft-order-${draft.id}`}
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <span className="font-medium">
                👤 {draft.consultant_name || "Konsultant"}
              </span>
              <span className="rounded bg-yellow-100 px-1.5 py-0.5 text-xs text-yellow-800">
                Draft
              </span>
            </div>
            <span className="text-xs text-muted-foreground">
              utworzono: {fmtDate(draft.created_at) ?? "—"}
            </span>
          </div>

          <div className="mt-2 flex flex-wrap items-center gap-x-6 gap-y-1.5 text-sm">
            <span className="inline-flex items-center gap-1">
              <span className="text-muted-foreground">Numer zamówienia:</span>
              {canManage ? (
                <InlineText
                  value={editableTitle(draft.title)}
                  display={
                    <span className="font-medium">
                      {editableTitle(draft.title) || "—"}
                    </span>
                  }
                  ariaLabel={`numer zamówienia (${draft.consultant_name})`}
                  placeholder="np. 4500030222"
                  onSave={(raw) => patch(draft, { title: raw })}
                  onError={onError}
                />
              ) : (
                <span className="font-medium">
                  {editableTitle(draft.title) || "—"}
                </span>
              )}
            </span>

            {canManage ? (
              <InlinePeriod
                startDate={draft.start_date}
                endDate={draft.end_date}
                onSave={(start, end) =>
                  patch(draft, { start_date: start, end_date: end })
                }
                onError={onError}
              />
            ) : (
              <span>
                okres zamówienia: {fmtDate(draft.start_date) ?? "—"} →{" "}
                {fmtDate(draft.end_date) ?? "bezterminowo"}
              </span>
            )}

            <span className="inline-flex items-center gap-1">
              <span className="text-muted-foreground">stawka kosztowa:</span>
              {canManage ? (
                <InlineText
                  value={draft.rate_cost != null ? String(draft.rate_cost) : ""}
                  display={<span>{fmtMoney(draft.rate_cost)}</span>}
                  ariaLabel={`stawka kosztowa (${draft.consultant_name})`}
                  inputMode="decimal"
                  sanitize={sanitizeDecimalInput}
                  onSave={(raw) =>
                    patch(draft, {
                      rate_candidate: raw ? parseDecimalInput(raw) : null,
                    })
                  }
                  onError={onError}
                />
              ) : (
                <span>{fmtMoney(draft.rate_cost)}</span>
              )}
            </span>

            <span className="inline-flex items-center gap-1">
              <span className="text-muted-foreground">stawka przychodowa:</span>
              {canManage ? (
                <InlineText
                  value={
                    draft.rate_revenue != null ? String(draft.rate_revenue) : ""
                  }
                  display={<span>{fmtMoney(draft.rate_revenue)}</span>}
                  ariaLabel={`stawka przychodowa (${draft.consultant_name})`}
                  inputMode="decimal"
                  sanitize={sanitizeDecimalInput}
                  onSave={(raw) =>
                    patch(draft, {
                      rate_client: raw ? parseDecimalInput(raw) : null,
                    })
                  }
                  onError={onError}
                />
              ) : (
                <span>{fmtMoney(draft.rate_revenue)}</span>
              )}
            </span>

            <span className="inline-flex items-center gap-1">
              <span className="text-muted-foreground">liczba MD (opcjonalnie):</span>
              {canManage ? (
                <InlineText
                  value={
                    draft.md_quantity != null ? String(draft.md_quantity) : ""
                  }
                  display={<span>{draft.md_quantity ?? "—"}</span>}
                  ariaLabel={`liczba MD zamówienia (${draft.consultant_name})`}
                  inputMode="decimal"
                  sanitize={sanitizeDecimalInput}
                  onSave={(raw) =>
                    patch(draft, {
                      md_quantity: raw ? parseDecimalInput(raw) : null,
                    })
                  }
                  onError={onError}
                />
              ) : (
                <span>{draft.md_quantity ?? "—"}</span>
              )}
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}
