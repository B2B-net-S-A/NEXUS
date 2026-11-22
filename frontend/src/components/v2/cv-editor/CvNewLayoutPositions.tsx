"use client";

/**
 * „Stanowiska” w edytorze nowego CV (22.11.2026): lista stanowisk z CV
 * (`cvOutline` — zakres od akapitu `role` do następnego) z przestawianiem
 * i formularz wybranego. Każde pole pisze do akapitów stanowiska
 * W DOKUMENCIE edytora (`lib/cv-new-layout-form.ts`), z gramatyką szablonu
 * Worda: nazwa pogrubiona na początku linii `role`, daty za nią, firma
 * w akapicie `employer`, etykiety „Zakres zadań:” / „Technologie:” z
 * `CV_TEMPLATE_LABELS`.
 */

import type { Editor } from "@tiptap/core";
import { ArrowDown, ArrowUp, Plus, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { canMoveRoleAt, cvOutline, insertRole, moveRoleAt, type CvLang } from "@/lib/cv-editor-blocks";
import {
  addRoleDuty,
  allRoleFields,
  companyName,
  joinPeriod,
  removeRoleDuty,
  roleDuration,
  setRoleCompany,
  setRoleDuty,
  setRolePeriod,
  setRoleTechnologies,
  setRoleTitle,
  splitPeriod,
  type CvRoleFields,
} from "@/lib/cv-new-layout-form";
import { cn } from "@/lib/utils";

import { DocInput, DocTextarea, dispatchCv, useEditorDoc } from "./cv-new-layout-fields";

export interface CvNewLayoutPositionsProps {
  editor: Editor;
  lang: CvLang;
  disabled: boolean;
  selected: number;
  onSelect: (index: number) => void;
}

export function CvNewLayoutPositions({ editor, lang, disabled, selected, onSelect }: CvNewLayoutPositionsProps) {
  const { doc } = useEditorDoc(editor);
  const roles = allRoleFields(doc);
  const outline = cvOutline(doc);
  const current = roles[Math.min(selected, roles.length - 1)] ?? null;

  const move = (index: number, direction: -1 | 1) => {
    if (dispatchCv(editor, moveRoleAt(index, direction))) onSelect(index + direction);
  };
  const add = () => {
    const after = current ? current.index : undefined;
    if (dispatchCv(editor, insertRole(lang, after))) onSelect(current ? current.index + 1 : 0);
  };

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col @3xl:flex-row" data-testid="cv-new-positions">
      <section
        aria-label="Stanowiska"
        className="flex min-h-0 flex-none flex-col border-b border-border @3xl:w-[43%] @3xl:max-w-[22rem] @3xl:border-b-0 @3xl:border-r"
      >
        <div className="flex items-center gap-2 px-3 pb-2 pt-3">
          <h2 className="whitespace-nowrap text-base font-semibold text-foreground">Stanowiska ({roles.length})</h2>
          <Button type="button" size="sm" variant="outline" className="ml-auto" disabled={disabled} onClick={add}>
            <Plus aria-hidden className="mr-1 h-3.5 w-3.5" /> Dodaj
          </Button>
        </div>
        {roles.length === 0 ? (
          <p className="px-3 pb-3 text-sm text-muted-foreground">
            CV nie ma oznaczonych stanowisk. Dodaj je tutaj albo w „Cały tekst” („Więcej” → „Typ akapitu”).
          </p>
        ) : (
          <ol className="min-h-0 flex-1 space-y-1 overflow-auto px-2 pb-3">
            {roles.map((role) => {
              const active = role.index === current?.index;
              return (
                <li key={role.index}>
                  <div
                    className={cn(
                      "group flex items-start gap-1 rounded-lg px-2 py-1.5",
                      active ? "bg-primary/10" : "hover:bg-muted/60",
                    )}
                  >
                    <button
                      type="button"
                      aria-current={active ? "true" : undefined}
                      onClick={() => onSelect(role.index)}
                      className="min-w-0 flex-1 text-left focus-visible:outline-hidden"
                    >
                      <span className="line-clamp-2 text-sm font-semibold text-foreground">
                        {companyName(role.company) || "Bez firmy"}
                      </span>
                      <span className="block truncate text-xs text-muted-foreground">{role.title || "Bez nazwy"}</span>
                      <span className="block text-xs tabular-nums text-muted-foreground">{role.period || "Bez dat"}</span>
                    </button>
                    <div className="flex flex-none flex-col">
                      <Button
                        type="button"
                        size="icon-sm"
                        variant="ghost"
                        aria-label={`Przesuń wyżej: ${companyName(role.company) || role.title}`}
                        disabled={disabled || !canMoveRoleAt(outline, role.index, -1)}
                        onClick={() => move(role.index, -1)}
                      >
                        <ArrowUp aria-hidden className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        type="button"
                        size="icon-sm"
                        variant="ghost"
                        aria-label={`Przesuń niżej: ${companyName(role.company) || role.title}`}
                        disabled={disabled || !canMoveRoleAt(outline, role.index, 1)}
                        onClick={() => move(role.index, 1)}
                      >
                        <ArrowDown aria-hidden className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </div>
                </li>
              );
            })}
          </ol>
        )}
      </section>
      {current ? (
        <RoleForm key={current.index} editor={editor} lang={lang} role={current} disabled={disabled} />
      ) : null}
    </div>
  );
}

function RoleForm({
  editor,
  lang,
  role,
  disabled,
}: {
  editor: Editor;
  lang: CvLang;
  role: CvRoleFields;
  disabled: boolean;
}) {
  const index = role.index;
  const period = splitPeriod(role.period);
  const duration = roleDuration(role.period);
  const write = (command: Parameters<typeof dispatchCv>[1]) => dispatchCv(editor, command);

  return (
    <section
      aria-label={`Stanowisko: ${role.title || companyName(role.company)}`}
      className="min-h-0 min-w-0 flex-1 space-y-3 overflow-auto p-3"
      data-testid="cv-new-role-form"
    >
      <div className="space-y-1">
        <span className="block text-xs font-medium text-foreground">Okres</span>
        <div className="flex flex-wrap items-center gap-1.5">
          <DocInput
            editor={editor}
            label="Okres od"
            value={period.start}
            placeholder="MM.RRRR"
            disabled={disabled}
            className="w-28"
            onChange={(value) => write(setRolePeriod(index, joinPeriod(value, period.end)))}
          />
          <span aria-hidden className="text-muted-foreground">
            –
          </span>
          <DocInput
            editor={editor}
            label="Okres do"
            value={period.end}
            placeholder="obecnie"
            disabled={disabled}
            className="w-28"
            onChange={(value) => write(setRolePeriod(index, joinPeriod(period.start, value)))}
          />
          {duration ? <span className="text-xs text-muted-foreground">({duration})</span> : null}
        </div>
      </div>
      <div className="space-y-1">
        <span className="block text-xs font-medium text-foreground">Firma</span>
        <DocInput
          editor={editor}
          label="Firma"
          value={role.company ?? ""}
          disabled={disabled}
          onChange={(value) => write(setRoleCompany(index, value))}
        />
      </div>
      <DocTextarea
        editor={editor}
        label="Stanowisko"
        value={role.title}
        disabled={disabled}
        maxRows={3}
        onChange={(value) => write(setRoleTitle(index, value))}
      />
      <div className="space-y-1.5">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-foreground">Zakres zadań</span>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="ml-auto h-7 px-2 text-xs"
            disabled={disabled}
            onClick={() => write(addRoleDuty(index, lang))}
          >
            <Plus aria-hidden className="mr-1 h-3.5 w-3.5" /> Punkt
          </Button>
        </div>
        {role.duties.length === 0 ? (
          <p className="text-xs text-muted-foreground">Stanowisko nie ma jeszcze punktów zakresu zadań.</p>
        ) : null}
        {role.duties.map((duty, dutyIndex) => (
          <DocTextarea
            // Punkt ma tylko numer: po usunięciu kolejne pola dostają tekst następnych punktów.
            key={dutyIndex}
            editor={editor}
            srLabel
            label={`Punkt ${dutyIndex + 1} zakresu zadań`}
            value={duty}
            disabled={disabled}
            onChange={(value) => write(setRoleDuty(index, dutyIndex, value))}
            trailing={
              <Button
                type="button"
                size="icon-sm"
                variant="ghost"
                aria-label={`Usuń punkt ${dutyIndex + 1}`}
                title="Usuń punkt — „Cofnij” przywróci"
                disabled={disabled}
                onClick={() => write(removeRoleDuty(index, dutyIndex))}
              >
                <X aria-hidden className="h-3.5 w-3.5" />
              </Button>
            }
          />
        ))}
      </div>
      <DocTextarea
        editor={editor}
        label="Technologie"
        value={role.technologies ?? ""}
        disabled={disabled}
        maxRows={4}
        placeholder="Po przecinku, np. Java, Spring Boot"
        hint="Po przecinku. Pogrubienia z CV zostają."
        onChange={(value) => write(setRoleTechnologies(index, value, lang))}
      />
    </section>
  );
}
