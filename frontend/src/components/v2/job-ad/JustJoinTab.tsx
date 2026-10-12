"use client";

/**
 * Zakładka JustJoin.IT: pola formularza do wyklikania w panelu, tech stack
 * z poziomem i jeden opis kopiowany z nagłówkami i listami albo jako zwykły
 * tekst.
 */

import { Check, Copy, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { AdTechItem, AdTechLevel, RenderedSection } from "@/lib/api/jobAd";
import { cn } from "@/lib/utils";

import { AdBlock } from "./AdBlock";
import { editHint, toneOf, type AdTabProps } from "./PracujTab";
import { editorText, findingsByField, isEditKey, withTechLevel, withoutTech } from "./job-ad-edit";

interface JustJoinTabProps extends AdTabProps {
  tech: AdTechItem[];
  onSaveTech: (tech: AdTechItem[]) => Promise<boolean>;
}

const LEVEL_OPTIONS: ReadonlyArray<{ value: AdTechLevel; label: string }> = [
  { value: "critical", label: "Advanced" },
  { value: "must", label: "Regular" },
  { value: "nice", label: "Nice to have" },
];

function LevelDots({ level }: { level: number }) {
  return (
    <span role="img" aria-label={`Poziom ${level} z 5`} className="flex gap-[3px]">
      {[1, 2, 3, 4, 5].map((dot) => (
        <span
          key={dot}
          className={cn("h-2.5 w-2.5 rounded-full", dot <= level ? "bg-primary" : "bg-border")}
        />
      ))}
    </span>
  );
}

function CopyButton({
  label,
  copied,
  blockedReason,
  primary,
  onClick,
}: {
  label: string;
  copied: boolean;
  blockedReason: string | null;
  primary?: boolean;
  onClick: () => void;
}) {
  return (
    <Button
      type="button"
      size="sm"
      variant={primary && !copied ? "primary" : "outline"}
      className={cn(copied && "border-success/30 bg-success-muted text-success-muted-foreground")}
      title={blockedReason ?? undefined}
      disabled={!!blockedReason}
      onClick={onClick}
    >
      {copied ? (
        <Check className="h-3.5 w-3.5" aria-hidden="true" />
      ) : (
        <Copy className="h-3.5 w-3.5" aria-hidden="true" />
      )}
      {copied ? `Skopiowane: ${label}` : `Kopiuj ${label}`}
    </Button>
  );
}

export function JustJoinTab({
  content,
  rendered,
  findings,
  saving,
  locked,
  drafts,
  copied,
  copyBlockedReason,
  onCopy,
  onDraftChange,
  onSaveField,
  tech,
  onSaveTech,
}: JustJoinTabProps) {
  const byField = findingsByField(findings);
  const { form_fields, tech_stack, tech_overflow, sections, body_html, body_text } = rendered.jjit;
  // Opis kopiuje się w całości — z otwartą poprawką poszedłby tekst sprzed niej.
  const bodyBlockedReason =
    copyBlockedReason ??
    (sections.some((item) => isEditKey(item.key) && drafts[item.key] !== undefined)
      ? "Najpierw zapisz albo anuluj otwartą poprawkę."
      : null);

  const section = (item: RenderedSection) => {
    const editKey = isEditKey(item.key) ? item.key : null;
    return (
      <AdBlock
        key={item.key}
        variant="section"
        fieldKey={item.key}
        label={item.heading}
        kind={item.kind}
        text={item.text}
        items={item.items}
        fixedCount={item.fixed_count}
        tone={toneOf(byField.get(item.key))}
        editValue={editKey ? editorText(content, editKey) : undefined}
        editHint={editKey ? editHint(editKey) : undefined}
        draft={editKey ? (drafts[editKey] ?? null) : null}
        onDraftChange={editKey ? (text) => onDraftChange(editKey, text) : undefined}
        onSave={editKey ? (text) => onSaveField(editKey, text) : undefined}
        saving={saving}
        locked={locked}
      />
    );
  };

  return (
    <div className="grid grid-cols-1 items-start gap-4 min-[1100px]:grid-cols-[320px_minmax(0,1fr)]">
      <div className="flex flex-col gap-4">
        <section aria-label="Pola formularza" className="flex flex-col gap-1.5">
          <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            Pola formularza — wybierasz w panelu JustJoin.IT
          </h3>
          <dl className="divide-y divide-border text-[13px]">
            {form_fields.map((field) => (
              <div key={field.key} className="flex items-center justify-between gap-2 py-1.5">
                <dt className="w-[104px] shrink-0 text-muted-foreground">{field.label}</dt>
                <dd className="min-w-0 flex-1 text-foreground">{field.value}</dd>
                {field.key === "title" ? (
                  <Button
                    type="button"
                    size="icon-sm"
                    variant="outline"
                    className="h-7 w-7"
                    aria-label={copied.has("jjit.title") ? "Skopiowane: tytuł" : "Kopiuj tytuł"}
                    title={copyBlockedReason ?? undefined}
                    disabled={!!copyBlockedReason}
                    onClick={() => onCopy("jjit.title", "", field.value)}
                  >
                    {copied.has("jjit.title") ? (
                      <Check className="h-3.5 w-3.5 text-success" aria-hidden="true" />
                    ) : (
                      <Copy className="h-3.5 w-3.5" aria-hidden="true" />
                    )}
                  </Button>
                ) : null}
              </div>
            ))}
            <div className="flex items-start justify-between gap-2 py-1.5">
              <dt className="w-[104px] shrink-0 text-muted-foreground">Widełki</dt>
              <dd className="min-w-0 flex-1 text-warning-muted-foreground">
                wpisujesz ręcznie w panelu (netto za godzinę, B2B)
              </dd>
            </div>
          </dl>
        </section>

        <section aria-label="Tech stack" data-ad-field="tech" className="flex flex-col gap-2">
          <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            Tech stack z poziomem
          </h3>
          {tech_stack.length === 0 ? (
            <p className="text-[13px] text-muted-foreground">
              Rekrutacja nie ma krótkich nazw technologii — dodaj je w wymaganiach Profilu
              Championa.
            </p>
          ) : (
            <ul className="flex flex-col gap-1.5 text-[13px]">
              {tech_stack.map((item) => (
                <li key={item.name} className="flex items-center gap-2">
                  <span className="min-w-0 flex-1 truncate font-medium text-foreground">
                    {item.name}
                  </span>
                  <LevelDots level={item.level} />
                  <select
                    aria-label={`Poziom: ${item.name}`}
                    className="h-7 rounded-md border border-border bg-card px-1.5 text-xs text-foreground"
                    value={item.source}
                    disabled={saving || locked}
                    onChange={(event) =>
                      void onSaveTech(
                        withTechLevel(tech, item.name, event.target.value as AdTechLevel),
                      )
                    }
                  >
                    {LEVEL_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                  <Button
                    type="button"
                    size="icon-sm"
                    variant="ghost"
                    className="h-7 w-7"
                    aria-label={`Usuń technologię: ${item.name}`}
                    disabled={saving || locked}
                    onClick={() => void onSaveTech(withoutTech(tech, item.name))}
                  >
                    <X className="h-3.5 w-3.5" aria-hidden="true" />
                  </Button>
                </li>
              ))}
            </ul>
          )}
          {tech_overflow > 0 ? (
            <p className="text-xs text-warning-muted-foreground">
              Portal przyjmuje 10 technologii — {tech_overflow} się nie zmieściło. Usuń mniej ważne
              albo zostaw je w wymaganiach.
            </p>
          ) : null}
          <p className="text-xs text-muted-foreground">
            Poziom wynika z wymagań rekrutacji: krytyczne → Advanced, wymagane → Regular, mile
            widziane → Nice to have.
          </p>
        </section>
      </div>

      <div className="flex min-w-0 flex-col gap-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-[13px] text-muted-foreground">
            Opis do pola „Job description”. Kopiuje się z nagłówkami i listami.
          </p>
          <div className="flex gap-2">
            <CopyButton
              label="zwykły tekst"
              copied={copied.has("jjit.text")}
              blockedReason={bodyBlockedReason}
              onClick={() => onCopy("jjit.text", "", body_text)}
            />
            <CopyButton
              label="opis"
              primary
              copied={copied.has("jjit.body")}
              blockedReason={bodyBlockedReason}
              onClick={() => onCopy("jjit.body", body_html, body_text)}
            />
          </div>
        </div>
        <article
          aria-label="Opis ogłoszenia"
          className="flex flex-col gap-3 rounded-lg border border-border bg-card px-5 py-4"
        >
          {sections.map(section)}
        </article>
      </div>
    </div>
  );
}
