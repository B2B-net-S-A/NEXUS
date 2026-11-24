"use client";

// Karta „Umowa ramowa” kontraktu (F1, 15.11.2026): kategoria i poziom z umowy
// ramowej (z COA albo wybrane przez DL), limit = maksimum z cennika × dopłata,
// i przyznana dopłata za technologię z potwierdzeniem klienta. Dopłata nie
// zmienia zamówienia ani stawki przychodowej — tylko limit.
import { useState } from "react";
import { Scale } from "lucide-react";

import { PremiumSkillsSection } from "@/components/contracts/PremiumSkillsSection";
import { AppModal } from "@/components/ds/AppModal";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import {
  addonTechnology,
  useFrameworkCategory,
  useSaveFrameworkCategory,
  type FrameworkCategory,
} from "@/lib/api/framework-rates";
import { formatIsoDatePl } from "@/lib/date-pl";
import {
  STATUS_LABEL,
  categoryFormError,
  limitBreakdown,
  plnPerHour,
  showsFrameworkCard,
  sourceLabel,
  statusTone,
} from "@/lib/framework-category";
import { warsawToday } from "@/lib/warsaw-date";

function FrameworkCardTitle() {
  return (
    <h2 className="flex items-center gap-2 text-sm font-semibold text-foreground">
      <Scale className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
      Umowa ramowa
    </h2>
  );
}

interface Props {
  contractId: number;
  canView: boolean;
  canEdit: boolean;
}

export function FrameworkCategoryCard({ contractId, canView, canEdit }: Props) {
  const query = useFrameworkCategory(contractId, canView);
  const [open, setOpen] = useState(false);
  if (!canView) return null;
  // Awaria (poza odmową i brakiem kontraktu) nie może wyglądać jak klient bez
  // umowy ramowej — nie wiemy, czy ją ma, więc karta mówi, że nie sprawdziła.
  if (query.isError) {
    const status = (query.error as { response?: { status?: number } } | null)?.response?.status;
    if (status === 403 || status === 404) return null;
    return (
      <div className="rounded-xl border border-border bg-card p-4" data-testid="framework-category-card">
        <FrameworkCardTitle />
        <QueryStateNotice
          state="error"
          className="mt-3 py-4"
          description={apiErrorMessage(query.error, "Nie udało się sprawdzić umowy ramowej klienta.")}
          onRetry={() => void query.refetch()}
        />
      </div>
    );
  }
  if (!query.isSuccess || !showsFrameworkCard(query.data)) return null;
  const data = query.data;
  const breakdown = limitBreakdown(data);
  const gap = data.gap === null ? null : Number(data.gap);

  return (
    <div className="rounded-xl border border-border bg-card p-4" data-testid="framework-category-card">
      <div className="flex items-start justify-between gap-2">
        <FrameworkCardTitle />
        {canEdit && (
          <Button size="sm" variant="outline" data-tour="contracts.framework-category" onClick={() => setOpen(true)}>
            Kategoria i dopłata
          </Button>
        )}
      </div>
      <dl className="mt-3 space-y-1.5 text-sm">
        <div className="flex justify-between gap-3">
          <dt className="text-muted-foreground">Status</dt>
          <dd>
            <StatusDot
              tone={statusTone(data.status)}
              note={gap !== null && data.status === "over" ? `o ${plnPerHour(gap)} ponad limit` : undefined}
            >
              {STATUS_LABEL[data.status]}
            </StatusDot>
          </dd>
        </div>
        <div className="flex justify-between gap-3">
          <dt className="text-muted-foreground">Kategoria</dt>
          <dd className="text-right">
            {data.card ? (
              <>
                {data.card.label}
                {sourceLabel(data.source) && (
                  <span className="ml-1 text-xs text-muted-foreground">({sourceLabel(data.source)})</span>
                )}
              </>
            ) : (
              <span className="text-muted-foreground">nie ustalono</span>
            )}
          </dd>
        </div>
        {data.coa_label && (!data.card || data.card.label !== data.coa_label) && (
          <div className="flex justify-between gap-3 text-xs">
            <dt className="text-muted-foreground">W ostatnim COA</dt>
            <dd className="text-right text-warning">
              {data.coa_label}
              {!data.card ? " — brak tej pozycji w cenniku" : ""}
            </dd>
          </div>
        )}
        <div className="flex justify-between gap-3">
          <dt className="text-muted-foreground">Limit</dt>
          <dd className="text-right tabular-nums">{breakdown ?? plnPerHour(data.framework_limit)}</dd>
        </div>
        {data.addon && (
          <div className="flex justify-between gap-3 text-xs">
            <dt className="text-muted-foreground">Potwierdzenie dopłaty</dt>
            <dd className="text-right">
              {data.addon.confirmed_by}
              {data.addon.confirmed_on ? `, ${formatIsoDatePl(data.addon.confirmed_on)}` : ""}
            </dd>
          </div>
        )}
      </dl>
      <PremiumSkillsSection contractId={contractId} canEdit={canEdit} category={data.card?.label ?? null} />
      {open && <CategoryDialog data={data} contractId={contractId} onClose={() => setOpen(false)} />}
    </div>
  );
}

function CategoryDialog({
  data,
  contractId,
  onClose,
}: {
  data: FrameworkCategory;
  contractId: number;
  onClose: () => void;
}) {
  const { showSuccess } = useToast();
  const save = useSaveFrameworkCategory(contractId);
  const [rateCardId, setRateCardId] = useState<number | null>(data.card?.id ?? null);
  const [addon, setAddon] = useState(data.addon?.technology ?? "");
  const [confirmedBy, setConfirmedBy] = useState(data.addon?.confirmed_by ?? "");
  const [confirmedOn, setConfirmedOn] = useState(data.addon?.confirmed_on ?? "");
  const [evidence, setEvidence] = useState(data.addon?.evidence ?? "");
  const [effectiveFrom, setEffectiveFrom] = useState(warsawToday());
  const [error, setError] = useState<string | null>(null);
  const card = data.cards.find((c) => c.id === rateCardId) ?? null;
  const addonOptions = card?.addons ?? [];

  const submit = async () => {
    const formError = categoryFormError({ rateCardId, addon, confirmedBy, confirmedOn });
    if (formError) {
      setError(formError);
      return;
    }
    try {
      await save.mutateAsync({
        rate_card_id: rateCardId as number,
        addon_technology: addon || null,
        confirmed_by: addon ? confirmedBy.trim() : null,
        confirmed_on: addon ? confirmedOn : null,
        evidence: addon ? evidence.trim() || null : null,
        effective_from: effectiveFrom || null,
      });
      showSuccess("Zapisano kategorię i limit z umowy ramowej");
      onClose();
    } catch (err) {
      setError(apiErrorMessage(err, "Nie udało się zapisać kategorii."));
    }
  };

  return (
    <AppModal
      open
      onOpenChange={(next) => !next && onClose()}
      title="Kategoria i dopłata z umowy ramowej"
      description="Dopłata nie zmienia zamówienia ani stawki przychodowej. Podnosi tylko limit, do którego porównujemy stawkę."
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Anuluj
          </Button>
          <Button onClick={() => void submit()} disabled={save.isPending}>
            Zapisz
          </Button>
        </>
      }
    >
      <div className="space-y-3 text-sm">
        <div className="space-y-1">
          <Label htmlFor="fa-card">Kategoria i poziom</Label>
          <select
            id="fa-card"
            className="w-full rounded-md border border-border bg-background px-2 py-1.5"
            value={rateCardId ?? ""}
            onChange={(e) => {
              setRateCardId(e.target.value ? Number(e.target.value) : null);
              setAddon("");
            }}
          >
            <option value="">Wybierz…</option>
            {data.cards.map((c) => (
              <option key={c.id} value={c.id}>
                {c.label} — {plnPerHour(c.rate_max)}
              </option>
            ))}
          </select>
          {data.coa_label && <p className="text-xs text-muted-foreground">W ostatnim COA: {data.coa_label}</p>}
        </div>
        <div className="space-y-1">
          <Label htmlFor="fa-addon">Dopłata za technologię</Label>
          <select
            id="fa-addon"
            className="w-full rounded-md border border-border bg-background px-2 py-1.5"
            value={addon}
            onChange={(e) => setAddon(e.target.value)}
            disabled={!card || addonOptions.length === 0}
          >
            <option value="">Brak</option>
            {addonOptions.map((label) => (
              <option key={label} value={addonTechnology(label)}>
                {label}
              </option>
            ))}
          </select>
          {card && addonOptions.length === 0 && (
            <p className="text-xs text-muted-foreground">Umowa nie przewiduje dopłat w tej kategorii.</p>
          )}
        </div>
        {addon && (
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label htmlFor="fa-by">Potwierdził po stronie klienta</Label>
              <Input id="fa-by" value={confirmedBy} onChange={(e) => setConfirmedBy(e.target.value)} />
            </div>
            <div className="space-y-1">
              <Label htmlFor="fa-on">Data potwierdzenia</Label>
              <Input id="fa-on" type="date" value={confirmedOn} onChange={(e) => setConfirmedOn(e.target.value)} />
            </div>
            <div className="col-span-2 space-y-1">
              <Label htmlFor="fa-evidence">Dowód (mail, wpis w CPRO)</Label>
              <Textarea id="fa-evidence" rows={3} value={evidence} onChange={(e) => setEvidence(e.target.value)} />
            </div>
          </div>
        )}
        <div className="space-y-1">
          <Label htmlFor="fa-from">Limit obowiązuje od</Label>
          <Input id="fa-from" type="date" value={effectiveFrom} onChange={(e) => setEffectiveFrom(e.target.value)} />
        </div>
        {error && <p className="text-sm text-destructive">{error}</p>}
      </div>
    </AppModal>
  );
}
