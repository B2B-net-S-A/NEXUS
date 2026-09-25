"use client";

/**
 * `/jobs/new` → „Ogłoszenie na portalach” (RocketJobs, JustJoin.IT).
 *
 * Renderuje się wyłącznie przy gotowym portalu (`any_ready`). DL zaznacza
 * portale, „Przygotuj ogłoszenie” prosi AI o opis publiczny z tego, co strona
 * już ma, a DL poprawia tytuł, podtytuł i opis oraz ustawia parametry. Nic
 * się tu nie zapisuje — publikacja idzie po „Utwórz i przekaż do searchu”
 * (`lib/new-job-portal-publish.ts`).
 */

import { useId } from "react";
import { AlertTriangle, Megaphone } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { PortalListingForm } from "@/components/v2/recruitment/PortalListingForm";
import {
  validateListingOptions,
  type JobPortal,
  type PortalConfigItem,
  type PublicDraftRead,
} from "@/lib/api/jobPortals";
import type { NewJobPortalPlan, PortalAdDraft } from "@/lib/new-job-portal-publish";

interface Props {
  portals: PortalConfigItem[];
  plan: NewJobPortalPlan;
  onPlanChange: (next: NewJobPortalPlan) => void;
  findings: PublicDraftRead["findings"];
  preparing: boolean;
  prepareError: string | null;
  onPrepare: () => void;
  disabled?: boolean;
}

export function NewJobPortalsStep({
  portals,
  plan,
  onPlanChange,
  findings,
  preparing,
  prepareError,
  onPrepare,
  disabled = false,
}: Props) {
  const id = useId();
  const setDraft = (patch: Partial<PortalAdDraft>) =>
    plan.draft && onPlanChange({ ...plan, draft: { ...plan.draft, ...patch } });
  const toggle = (portal: JobPortal, on: boolean) =>
    onPlanChange({
      ...plan,
      portals: on ? [...plan.portals, portal] : plan.portals.filter((p) => p !== portal),
    });
  const problems = [
    ...new Set(plan.portals.flatMap((portal) => validateListingOptions(plan.options, { board: portal }))),
  ];

  return (
    <section
      aria-labelledby={`${id}-title`}
      className="flex flex-col gap-4 rounded-xl border border-border bg-card p-4 sm:p-5"
    >
      <div className="flex items-start gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <Megaphone className="h-4 w-4" aria-hidden />
        </span>
        <div>
          <h2 id={`${id}-title`} className="text-sm font-semibold text-foreground">
            Ogłoszenie na portalach
          </h2>
          <p className="text-xs text-muted-foreground">
            Opcjonalnie. Ogłoszenie wyjdzie razem z rekrutacją, a kandydaci zaaplikują przez jej link na stronie kariery.
          </p>
        </div>
      </div>

      <div className="flex flex-wrap gap-4">
        {portals.map((item) => (
          <label key={item.portal} className="flex items-center gap-2 text-sm text-foreground">
            <Checkbox
              checked={plan.portals.includes(item.portal)}
              onCheckedChange={(checked) => toggle(item.portal, checked === true)}
              aria-label={item.label}
              disabled={disabled}
            />
            {item.label}
          </label>
        ))}
      </div>

      {plan.portals.length > 0 ? (
        <div className="flex flex-wrap items-center gap-3">
          <Button type="button" variant="outline" onClick={onPrepare} loading={preparing} disabled={disabled}>
            {plan.draft ? "Przygotuj ponownie" : "Przygotuj ogłoszenie"}
          </Button>
          {plan.draft ? (
            <span className="text-xs text-muted-foreground">
              Ponowne przygotowanie nadpisze tytuł, podtytuł i opis — parametry zostaną.
            </span>
          ) : null}
          {prepareError ? (
            <span role="alert" className="text-xs text-destructive">
              {prepareError}
            </span>
          ) : null}
        </div>
      ) : null}

      {plan.portals.length > 0 && plan.draft ? (
        <div className="flex flex-col gap-4">
          {findings.length > 0 ? (
            <div className="rounded-lg border border-warning bg-warning-muted p-3 text-sm text-warning-muted-foreground">
              <p className="flex items-center gap-2 font-medium">
                <AlertTriangle className="h-4 w-4" aria-hidden /> Kontrola opisu — popraw przed utworzeniem
              </p>
              <ul className="mt-1 list-disc space-y-0.5 pl-6 text-xs">
                {findings.map((finding, i) => (
                  <li key={`${finding.code}-${i}`}>
                    {finding.message}
                    {finding.excerpt ? <span className="text-muted-foreground"> („{finding.excerpt}”)</span> : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          <div className="flex flex-col gap-1">
            <label htmlFor={`${id}-public-title`} className="text-sm font-medium text-foreground">
              Tytuł ogłoszenia
            </label>
            <Input
              id={`${id}-public-title`}
              value={plan.draft.publicTitle}
              maxLength={200}
              disabled={disabled}
              onChange={(e) => setDraft({ publicTitle: e.target.value })}
            />
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor={`${id}-subtitle`} className="text-sm font-medium text-foreground">
              Podtytuł
            </label>
            <Input
              id={`${id}-subtitle`}
              value={plan.draft.subtitle}
              maxLength={300}
              disabled={disabled}
              onChange={(e) => setDraft({ subtitle: e.target.value })}
            />
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor={`${id}-about`} className="text-sm font-medium text-foreground">
              O projekcie
            </label>
            <Textarea
              id={`${id}-about`}
              rows={6}
              value={plan.draft.about}
              maxLength={4000}
              disabled={disabled}
              onChange={(e) => setDraft({ about: e.target.value })}
            />
            <span className="text-xs text-muted-foreground">
              Bez nazwy klienta, stawek i danych kontaktowych — kontrola sprawdzi to jeszcze raz przy zapisie.
            </span>
          </div>
          <PortalListingForm
            value={plan.options}
            onChange={(options) => onPlanChange({ ...plan, options })}
            selected={plan.portals}
            problems={problems}
            disabled={disabled}
          />
        </div>
      ) : null}
    </section>
  );
}
