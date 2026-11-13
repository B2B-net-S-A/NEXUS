"use client";

// Karta osoby za miesiąc (roadmapa E1.6, E2, E4): dokumenty, wyliczenie z RCP,
// wynik kontroli, zejście MD z zamówienia i faktura kontraktora z KSeF.
import { useEffect, useState, type ReactNode } from "react";
import { AlertTriangle, ArrowLeft, Check, FileText, Minus, X } from "lucide-react";

import { QueryStateNotice, StatusDot } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import { downloadBlob } from "@/lib/authenticated-files";
import {
  useAcceptSettlement,
  useNeedsFixSettlement,
  fetchSettlementDocument,
  useNipDecision,
  useSetSettlementMd,
  useSettlementDetail,
  type CheckState,
  type ContractorInvoiceBlock,
  type SettlementCheck,
  type SettlementDetail,
  type SettlementKind,
} from "@/lib/api/client-settlements";
import { cn } from "@/lib/utils";

import { ExtrasSection } from "./ExtrasSection";
import { CONTRACTOR_INVOICE, STATUS, mdText, monthLabel, pln } from "./format";
import { IntegrationCostsSection } from "./IntegrationCostsSection";

const ICON: Record<CheckState, ReactNode> = {
  ok: <Check aria-hidden className="size-3" />,
  warn: <AlertTriangle aria-hidden className="size-3" />,
  fail: <X aria-hidden className="size-3" />,
  none: <Minus aria-hidden className="size-3" />,
};

const ICON_TONE: Record<CheckState, string> = {
  ok: "bg-success-muted text-success-muted-foreground",
  warn: "bg-warning-muted text-warning-muted-foreground",
  fail: "bg-destructive-muted text-destructive-muted-foreground",
  none: "bg-muted text-muted-foreground",
};

const MAIL_MIMES = new Set(["application/vnd.ms-outlook", "message/rfc822"]);

const CHECK_LABEL: Record<CheckState, string> = { ok: "Zgodne", warn: "Uwaga", fail: "Błąd", none: "Nie sprawdzono" };

interface SettlementCardProps {
  contractId: number;
  month: string;
  canWrite: boolean;
  onBack: () => void;
  /** `estimate` — plan miesiąca (E5.3), z ekranu planu. */
  kind?: SettlementKind;
}

export function SettlementCard({ contractId, month, canWrite, onBack, kind = "actual" }: SettlementCardProps) {
  const query = useSettlementDetail(contractId, month, kind);
  const accept = useAcceptSettlement(month, kind);
  const needsFix = useNeedsFixSettlement(month, kind);
  const { askReason, confirmDialog } = useConfirmV2();
  const { showSuccess, showError } = useToast();

  if (query.isError) {
    return <QueryStateNotice state="error" description={apiErrorMessage(query.error, "Nie udało się pobrać rozliczenia osoby.")} onRetry={() => query.refetch()} />;
  }
  if (!query.isSuccess) {
    return <div className="py-10 text-center text-sm text-muted-foreground">Ładowanie…</div>;
  }
  const d = query.data;
  const warnings = d.checks.flatMap((g) => g.checks).filter((c) => c.state === "warn").length;
  const canDecide = canWrite && ["checking", "ok", "warnings", "no_md", "accepted"].includes(d.status);

  async function onAccept() {
    try {
      await accept.mutateAsync(contractId);
      showSuccess(d.status === "accepted" ? "RCP przyjęte ponownie, zejście MD nadpisane." : "RCP przyjęte.");
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się przyjąć RCP."));
    }
  }

  async function onNeedsFix() {
    const reason = await askReason({
      title: "Odesłać RCP do poprawy?",
      description: "Konsultant zobaczy powód w panelu i w mailu.",
      confirmLabel: "Odeślij",
      field: { label: "Co trzeba poprawić", minLength: 5, maxLength: 1000 },
    });
    if (!reason) return;
    try {
      await needsFix.mutateAsync({ contractId, reason });
      showSuccess("Odesłano do poprawy.");
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się odesłać RCP."));
    }
  }

  return (
    <div className="space-y-3">
      {confirmDialog}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <button type="button" onClick={onBack} aria-label="Wróć do listy miesiąca" className="text-muted-foreground hover:text-foreground">
            <ArrowLeft aria-hidden className="size-4" />
          </button>
          <h2 className="truncate text-base font-semibold">{d.person}</h2>
          {kind === "estimate" ? <StatusDot tone="info">Plan miesiąca</StatusDot> : null}
          <StatusDot tone={STATUS[d.status].tone}>{STATUS[d.status].label}</StatusDot>
          <span className="min-w-0 truncate text-xs text-muted-foreground">
            {[d.client_name, monthLabel(d.month), d.order_number, d.contract_number ? `umowa ${d.contract_number}` : null]
              .filter(Boolean)
              .join(" · ")}
          </span>
        </div>
        {canDecide ? (
          <div className="flex gap-1.5">
            {d.status !== "accepted" ? (
              <Button size="sm" variant="outline" disabled={needsFix.isPending} onClick={onNeedsFix}>
                Do poprawy
              </Button>
            ) : null}
            <Button size="sm" disabled={accept.isPending || d.status === "no_md"} onClick={onAccept}>
              {d.status === "accepted" ? "Przyjmij ponownie" : warnings > 0 ? `Przyjmij z uwagami (${warnings})` : "Przyjmij"}
            </Button>
          </div>
        ) : null}
      </div>
      {d.estimate && d.estimate.status === "accepted" ? (
        <p className="rounded-lg bg-info-muted px-3 py-2 text-[13px] text-info-muted-foreground">
          Za ten miesiąc przyjęto plan: {mdText(d.estimate.md_charged)} MD. Faktura do klienta poszła z planu; RCP ponad plan nie
          przejdzie, a mniej MD zejdzie na kolejnej fakturze.
        </p>
      ) : null}
      {d.status === "needs_fix" && d.fix_reason ? (
        <p className="rounded-lg bg-destructive-muted px-3 py-2 text-[13px] text-destructive-muted-foreground">
          Odesłane do poprawy: {d.fix_reason}
        </p>
      ) : null}
      <div className="grid min-w-0 grid-cols-1 items-start gap-3 lg:grid-cols-2">
        <div className="min-w-0 space-y-3">
          <Documents detail={d} />
          {canWrite ? <MdForm detail={d} month={month} kind={kind} /> : null}
          <Computation detail={d} />
          {d.extras && kind === "actual" ? (
            <ExtrasSection contractId={contractId} month={month} block={d.extras} canWrite={canWrite} />
          ) : null}
          {d.contractor_invoice && kind === "actual" ? <ContractorInvoiceSection block={d.contractor_invoice} canWrite={canWrite} /> : null}
          {kind === "actual" ? <IntegrationCostsSection contractId={contractId} month={month} canWrite={canWrite} /> : null}
        </div>
        <section className="min-w-0 rounded-xl border bg-card p-3">
          <h3 className="text-sm font-semibold">Co sprawdziliśmy</h3>
          {d.checks.length === 0 ? (
            <p className="mt-1 text-xs text-muted-foreground">Kontrole ruszą, gdy wpłynie RCP.</p>
          ) : (
            d.checks.map((g) => (
              <div key={g.title}>
                <p className="mt-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{g.title}</p>
                <CheckList checks={g.checks} />
              </div>
            ))
          )}
        </section>
      </div>
    </div>
  );
}

function CheckList({ checks }: { checks: SettlementCheck[] }) {
  return (
    <ul>
      {checks.map((c) => (
        <li key={c.title} className="flex items-start gap-2 py-1.5">
          <span
            role="img"
            aria-label={CHECK_LABEL[c.state]}
            className={cn("mt-px flex size-[18px] shrink-0 items-center justify-center rounded-full", ICON_TONE[c.state])}
          >
            {ICON[c.state]}
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-[13px] font-medium leading-[18px]">{c.title}</p>
            {c.detail ? <p className="text-xs leading-[17px] text-muted-foreground">{c.detail}</p> : null}
          </div>
        </li>
      ))}
    </ul>
  );
}

/** Faktura kontraktora z KSeF (E4) i podpowiedź NIP-u do zatwierdzenia (E4.0). */
export function ContractorInvoiceSection({ block, canWrite }: { block: ContractorInvoiceBlock; canWrite: boolean }) {
  const decide = useNipDecision();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const { showSuccess, showError } = useToast();
  const state = CONTRACTOR_INVOICE[block.state];

  async function onDecide(invoiceId: number, nip: string, approve: boolean) {
    const ok = await askConfirm(
      approve
        ? {
            title: `Zapisać NIP ${nip} tej osobie?`,
            description: "Kolejne faktury z tego NIP-u przypiszą się do niej same.",
            confirmLabel: "Zatwierdź NIP",
          }
        : {
            title: "To nie ta osoba?",
            description: "Faktura zostanie bez osoby, a ten NIP nie wróci jako podpowiedź dla tego kontraktu.",
            confirmLabel: "Odrzuć podpowiedź",
            variant: "destructive",
          },
    );
    if (!ok) return;
    try {
      await decide.mutateAsync({ invoiceId, approve });
      showSuccess(approve ? "NIP zapisany." : "Podpowiedź odrzucona.");
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się zapisać decyzji."));
    }
  }

  return (
    <section className="rounded-xl border bg-card p-3">
      {confirmDialog}
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">Faktura kontraktora</h3>
        <StatusDot tone={state.tone}>{state.label}</StatusDot>
      </div>
      {block.invoices.length === 0 ? (
        <p className="mt-1 text-xs text-muted-foreground">W KSeF nie ma jeszcze faktury za ten miesiąc.</p>
      ) : (
        <ul className="mt-1 divide-y text-[13px]">
          {block.invoices.map((inv) => (
            <li key={inv.id} className="py-1.5">
              <div className="flex flex-wrap items-baseline justify-between gap-x-2">
                <span className="min-w-0 truncate font-medium">{inv.invoice_number ?? inv.ksef_number}</span>
                <span className="tabular-nums">{pln(inv.net_amount)} netto</span>
              </div>
              <p className="text-xs text-muted-foreground">
                {[
                  inv.issue_date ? `wystawiona ${new Date(inv.issue_date).toLocaleDateString("pl-PL")}` : null,
                  inv.due_date ? `płatność do ${new Date(inv.due_date).toLocaleDateString("pl-PL")}` : null,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
              {inv.nip_state === "suggested" ? (
                <div className="mt-1.5 rounded-lg bg-warning-muted px-2 py-1.5 text-xs text-warning-muted-foreground">
                  <p>
                    NIP {inv.seller_nip} nie jest zapisany przy tej osobie. Sprzedawca: {inv.seller_name ?? "bez nazwy"}.
                  </p>
                  {canWrite ? (
                    <div className="mt-1.5 flex flex-wrap gap-1.5">
                      <Button size="sm" disabled={decide.isPending} onClick={() => onDecide(inv.id, inv.seller_nip, true)}>
                        Zatwierdź NIP
                      </Button>
                      <Button size="sm" variant="outline" disabled={decide.isPending} onClick={() => onDecide(inv.id, inv.seller_nip, false)}>
                        To nie ta osoba
                      </Button>
                    </div>
                  ) : null}
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      {block.checks.filter((c) => c.title !== "NIP z KSeF do zatwierdzenia").length > 0 ? (
        <div className="mt-1 border-t pt-1">
          <CheckList checks={block.checks.filter((c) => c.title !== "NIP z KSeF do zatwierdzenia")} />
        </div>
      ) : null}
    </section>
  );
}

/** MD z RCP wpisane ręcznie (E1). Od E2 wypełnia je odczyt pliku, a Finanse poprawiają. */
function MdForm({ detail, month, kind }: { detail: SettlementDetail; month: string; kind: SettlementKind }) {
  const save = useSetSettlementMd(month, kind);
  const { showSuccess, showError } = useToast();
  const [regular, setRegular] = useState(detail.md_regular ?? "");
  const [extra, setExtra] = useState(detail.md_extra ?? "");
  useEffect(() => {
    setRegular(detail.md_regular ? String(Number(detail.md_regular)) : "");
    setExtra(detail.md_extra && Number(detail.md_extra) > 0 ? String(Number(detail.md_extra)) : "");
  }, [detail.md_regular, detail.md_extra]);
  const toNumber = (v: string) => v.trim().replace(",", ".");
  const valid = toNumber(regular) !== "" && !Number.isNaN(Number(toNumber(regular)));

  async function onSave() {
    try {
      await save.mutateAsync({
        contractId: detail.contract_id,
        mdRegular: toNumber(regular),
        mdExtra: toNumber(extra) === "" ? null : toNumber(extra),
      });
      showSuccess("MD zapisane, rozliczenie przeliczone.");
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się zapisać MD."));
    }
  }

  return (
    <section className="rounded-xl border bg-card p-3">
      <h3 className="text-sm font-semibold">
        MD z RCP
        <span className="ml-2 text-xs font-normal text-muted-foreground">
          {detail.md_source === "rcp"
            ? "odczytane z pliku"
            : detail.md_source === "manual"
              ? "wpisane ręcznie, odczyt pliku ich nie zmienia"
              : null}
        </span>
      </h3>
      <div className="mt-1.5 flex flex-wrap items-end gap-2 text-xs">
        <label className="grid gap-0.5">
          <span className="text-muted-foreground">Dni zwykłe</span>
          <Input inputMode="decimal" value={regular} onChange={(e) => setRegular(e.target.value)} className="h-8 w-24 text-sm tabular-nums" />
        </label>
        <label className="grid gap-0.5">
          <span className="text-muted-foreground">Praca dodatkowa (MD)</span>
          <Input inputMode="decimal" value={extra} onChange={(e) => setExtra(e.target.value)} className="h-8 w-24 text-sm tabular-nums" />
        </label>
        <Button size="sm" variant="outline" disabled={!valid || save.isPending} onClick={onSave}>
          Przelicz
        </Button>
      </div>
      {detail.status === "accepted" ? (
        <p className="mt-1.5 text-xs text-muted-foreground">Zmiana po przyjęciu wymaga ponownego przyjęcia; zejście MD nadpisze miesiąc.</p>
      ) : null}
    </section>
  );
}

function Documents({ detail }: { detail: SettlementDetail }) {
  const { showError } = useToast();
  async function open(docId: number, name: string | null) {
    try {
      downloadBlob(await fetchSettlementDocument(detail.contract_id, docId), name ?? `dokument-${docId}`);
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się pobrać pliku."));
    }
  }
  return (
    <section className="rounded-xl border bg-card p-3">
      <h3 className="text-sm font-semibold">Dokumenty</h3>
      {detail.documents.length === 0 ? (
        <p className="mt-1 text-xs text-muted-foreground">Nic jeszcze nie wpłynęło ani panelem, ani mailem.</p>
      ) : (
        <ul className="mt-1 divide-y text-[13px]">
          {detail.documents.map((doc) => (
            <li key={doc.id} className="flex items-center gap-2 py-1.5">
              <FileText aria-hidden className="size-3.5 shrink-0 text-muted-foreground" />
              <button
                type="button"
                onClick={() => open(doc.id, doc.file_name)}
                className="min-w-0 flex-1 truncate text-left text-primary hover:underline"
                title="Pobierz i sprawdź plik"
              >
                {doc.file_name ?? "Plik bez nazwy"}
              </button>
              <span className="shrink-0 text-xs text-muted-foreground">
                {doc.kind === "invoice" ? "Faktura" : MAIL_MIMES.has(doc.mime) ? "Mail" : "RCP"} · {doc.channel === "portal" ? "panel" : "mail"} ·{" "}
                {new Date(doc.received_at).toLocaleDateString("pl-PL")}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Computation({ detail }: { detail: SettlementDetail }) {
  return (
    <section className="rounded-xl border bg-card p-3">
      <h3 className="text-sm font-semibold">Ile wychodzi z RCP</h3>
      {detail.lines.length === 0 ? (
        <p className="mt-1 text-xs text-muted-foreground">Wyliczenie pojawi się po odczycie RCP.</p>
      ) : (
        <table className="mt-1.5 w-full text-[13px]">
          <thead className="text-left text-[11px] text-muted-foreground">
            <tr>
              <th className="py-0.5 font-medium">Pozycja</th>
              <th className="py-0.5 text-right font-medium">MD</th>
              <th className="py-0.5 text-right font-medium">Mnożnik</th>
              <th className="py-0.5 text-right font-medium">Netto</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {detail.lines.map((l) => (
              <tr key={l.label}>
                <td className="py-1">{l.label}</td>
                <td className="py-1 text-right tabular-nums">{mdText(l.md)}</td>
                <td className="py-1 text-right tabular-nums">{Math.round(Number(l.multiplier) * 100)}%</td>
                <td className="py-1 text-right tabular-nums">{pln(l.net)}</td>
              </tr>
            ))}
            <tr className="font-semibold">
              <td className="py-1">Razem</td>
              <td className="py-1 text-right tabular-nums">{mdText(detail.total_md)}</td>
              <td />
              <td className="py-1 text-right tabular-nums">{pln(detail.total_net)}</td>
            </tr>
          </tbody>
        </table>
      )}
      {detail.order ? (
        <p className="mt-2 text-xs text-muted-foreground">
          Zamówienie: {mdText(detail.order.md_total)} MD, zejdzie {mdText(detail.order.md_charged)} MD, zostanie{" "}
          {mdText(detail.order.md_remaining_after)} MD.
        </p>
      ) : (
        <p className="mt-2 text-xs text-warning-muted-foreground">Brak aktywnej linii zamówienia w tym miesiącu.</p>
      )}
    </section>
  );
}
