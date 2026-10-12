"use client";

/**
 * Zakładka Pracuj.pl: pola w kolejności formularza portalu, każde kopiowane
 * osobno. Wybory z list formularza (poziom, umowa, tryb) stoją na górze jako
 * podpowiedź — to nie jest tekst do wklejenia.
 */

import type { AdContent, AdFinding, RenderedAd, RenderedField } from "@/lib/api/jobAd";

import { AdBlock, type AdBlockTone } from "./AdBlock";
import {
  editorText,
  findingsByField,
  isEditKey,
  type AdDrafts,
  type AdEditKey,
} from "./job-ad-edit";

export interface AdTabProps {
  content: AdContent;
  rendered: RenderedAd;
  findings: AdFinding[];
  saving: boolean;
  /** Trwa przygotowanie nowej treści. */
  locked: boolean;
  /** Niezapisane teksty pól — wspólne dla obu zakładek. */
  drafts: AdDrafts;
  copied: ReadonlySet<string>;
  copyBlockedReason: string | null;
  onCopy: (key: string, html: string, text: string) => void;
  onDraftChange: (key: AdEditKey, text: string | null) => void;
  onSaveField: (key: AdEditKey, text: string) => Promise<boolean>;
}

const EDIT_HINTS: Partial<Record<AdEditKey, string>> = {
  title: "Wpisz samą nazwę stanowiska — dopisek do tytułu dokłada się sam.",
  lead: "Jedno zdanie: kogo szukamy i do czego.",
  about: "Akapity oddziel pustą linią.",
  responsibilities: "Jedna pozycja w wierszu.",
  requirements: "Jedna pozycja w wierszu.",
  nice_to_have: "Jedna pozycja w wierszu.",
  offer:
    "Jedna pozycja w wierszu. Tu wpisujesz punkty z projektu — warunki z rekrutacji i stały blok firmy dopisują się same.",
};

export function editHint(key: AdEditKey): string | undefined {
  return EDIT_HINTS[key];
}

export function toneOf(findings: AdFinding[] | undefined): AdBlockTone {
  if (!findings?.length) return null;
  return findings.some((f) => f.severity === "block") ? "block" : "advise";
}

/** Pola formularza Pracuj.pl ułożone w dwie kolumny, jak na ekranie 1280 px. */
const LEFT_COLUMN = new Set(["title", "about", "responsibilities", "process"]);

export function PracujTab({
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
}: AdTabProps) {
  const byField = findingsByField(findings);
  const { fields, params } = rendered.pracuj;

  const block = (field: RenderedField) => {
    const editKey = isEditKey(field.key) ? field.key : null;
    const copyKey = `pracuj.${field.key}`;
    return (
      <AdBlock
        key={field.key}
        fieldKey={field.key}
        label={field.label}
        kind={field.kind}
        text={field.text}
        items={field.items}
        autoCount={field.auto_count}
        fixedCount={field.fixed_count}
        tone={toneOf(byField.get(field.key))}
        editValue={editKey ? editorText(content, editKey) : undefined}
        editHint={editKey ? editHint(editKey) : undefined}
        draft={editKey ? (drafts[editKey] ?? null) : null}
        onDraftChange={editKey ? (text) => onDraftChange(editKey, text) : undefined}
        onSave={editKey ? (text) => onSaveField(editKey, text) : undefined}
        saving={saving}
        locked={locked}
        copied={copied.has(copyKey)}
        copyBlockedReason={copyBlockedReason}
        onCopy={() => onCopy(copyKey, field.kind === "text" ? "" : field.html, field.text)}
      />
    );
  };

  return (
    <div className="flex flex-col gap-3">
      <p className="text-[13px] text-muted-foreground">
        Pola w kolejności formularza Pracuj.pl. Każde kopiujesz osobno i wklejasz w odpowiednie
        miejsce.
      </p>
      {params.length > 0 ? (
        <div className="flex flex-wrap items-center gap-1.5 text-xs">
          <span className="text-muted-foreground">Wybierz w formularzu:</span>
          {params.map((param) => (
            <span key={param} className="rounded-full bg-muted px-2 py-0.5 text-foreground">
              {param}
            </span>
          ))}
        </div>
      ) : null}
      <div className="grid grid-cols-1 items-start gap-3 min-[1100px]:grid-cols-2">
        <div className="flex flex-col gap-3">
          {fields.filter((f) => LEFT_COLUMN.has(f.key)).map(block)}
        </div>
        <div className="flex flex-col gap-3">
          {fields.filter((f) => !LEFT_COLUMN.has(f.key)).map(block)}
        </div>
      </div>
    </div>
  );
}
