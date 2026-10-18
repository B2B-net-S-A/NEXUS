"use client";

import { Plus, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { PackAssignee } from "@/lib/api/client-onboarding";

import {
  ASSIGNEE_LABELS,
  MAX_DAYS_AFTER,
  MAX_DAYS_BEFORE,
  TIMING_LABELS,
  emptyItem,
  joinOffset,
  offsetLabel,
  type ItemDraft,
  type Timing,
} from "./onboarding-pack-format";

/** `thing` — rzecz od nas / od klienta; `document` — dokument od konsultanta; `access` — dostęp. */
export type PackItemsKind = "thing" | "document" | "access";

interface PackItemsEditorProps {
  kind: PackItemsKind;
  /** Nazwa listy dla czytnika ekranu i etykiet pól („Od nas”, „Dokumenty”…). */
  label: string;
  items: ItemDraft[];
  onChange: (items: ItemDraft[]) => void;
  readOnly: boolean;
  assignees?: { value: PackAssignee; label: string }[];
  addLabel: string;
  namePlaceholder: string;
  notePlaceholder: string;
  emptyText: string;
}

function summary(kind: PackItemsKind, item: ItemDraft): string {
  const parts = [item.note.trim()];
  if (kind !== "thing") parts.push(offsetLabel(joinOffset(item.timing, item.days)));
  if (kind === "access") parts.push(`pilnuje: ${ASSIGNEE_LABELS[item.assignee]}`);
  if (kind !== "thing" && item.required) parts.push("wymagane");
  if (kind === "document" && item.requiresFile) parts.push("z plikiem");
  return parts.filter(Boolean).join(" · ");
}

/** Lista pozycji pakietu: edycja wierszy albo podgląd (bez prawa zapisu). */
export function PackItemsEditor({
  kind,
  label,
  items,
  onChange,
  readOnly,
  assignees = [],
  addLabel,
  namePlaceholder,
  notePlaceholder,
  emptyText,
}: PackItemsEditorProps) {
  if (readOnly) {
    return items.length === 0 ? (
      <p className="text-sm text-muted-foreground">{emptyText}</p>
    ) : (
      <ul className="space-y-1.5" aria-label={label}>
        {items.map((item) => (
          <li key={item.key} className="text-sm">
            <span className="font-medium text-foreground">{item.name}</span>
            {summary(kind, item) ? (
              <span className="block text-xs text-muted-foreground">{summary(kind, item)}</span>
            ) : null}
          </li>
        ))}
      </ul>
    );
  }

  const update = (key: string, patch: Partial<ItemDraft>) =>
    onChange(items.map((item) => (item.key === key ? { ...item, ...patch } : item)));
  const remove = (key: string) => onChange(items.filter((item) => item.key !== key));
  const add = () =>
    onChange([
      ...items,
      emptyItem(
        kind === "thing"
          ? { required: false }
          : kind === "access"
            ? { required: false, timing: "before", days: 5 }
            : {},
      ),
    ]);

  return (
    <div className="space-y-2">
      {items.length === 0 ? <p className="text-sm text-muted-foreground">{emptyText}</p> : null}
      <ul className="space-y-2" aria-label={label}>
        {items.map((item, index) => {
          const row = `${label}, pozycja ${index + 1}`;
          return (
            <li key={item.key} className="space-y-1.5 rounded-md border border-border/70 p-2">
              <div className="flex items-center gap-2">
                <Input
                  aria-label={`${row}: nazwa`}
                  className="h-8 min-w-0 flex-1"
                  placeholder={namePlaceholder}
                  maxLength={200}
                  value={item.name}
                  onChange={(event) => update(item.key, { name: event.target.value })}
                />
                <Input
                  aria-label={`${row}: uwagi`}
                  className="h-8 min-w-0 flex-1"
                  placeholder={notePlaceholder}
                  maxLength={300}
                  value={item.note}
                  onChange={(event) => update(item.key, { note: event.target.value })}
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  aria-label={`${row}: usuń`}
                  onClick={() => remove(item.key)}
                >
                  <Trash2 className="h-4 w-4" aria-hidden />
                </Button>
              </div>
              {kind === "thing" ? null : (
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs">
                  {kind === "access" ? (
                    <Select
                      value={item.assignee}
                      onValueChange={(value) => update(item.key, { assignee: value as PackAssignee })}
                    >
                      <SelectTrigger aria-label={`${row}: kto pilnuje`} className="h-7 w-40 text-xs">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {assignees.map((option) => (
                          <SelectItem key={option.value} value={option.value}>
                            {option.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  ) : null}
                  {item.timing === "day" ? null : (
                    <Input
                      aria-label={`${row}: ile dni roboczych`}
                      className="h-7 w-16 text-xs tabular-nums"
                      type="number"
                      min={1}
                      max={item.timing === "before" ? MAX_DAYS_BEFORE : MAX_DAYS_AFTER}
                      value={item.days}
                      onChange={(event) =>
                        update(item.key, { days: Math.max(1, Number(event.target.value) || 1) })
                      }
                    />
                  )}
                  <Select
                    value={item.timing}
                    onValueChange={(value) => update(item.key, { timing: value as Timing })}
                  >
                    <SelectTrigger aria-label={`${row}: kiedy`} className="h-7 w-36 text-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {(Object.keys(TIMING_LABELS) as Timing[]).map((timing) => (
                        <SelectItem key={timing} value={timing}>
                          {timing === "day" ? TIMING_LABELS.day : `dni rob. ${TIMING_LABELS[timing]}`}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <label className="inline-flex items-center gap-1.5">
                    <Checkbox
                      checked={item.required}
                      onCheckedChange={(checked) => update(item.key, { required: checked === true })}
                    />
                    wymagane
                  </label>
                  {kind === "document" ? (
                    <label className="inline-flex items-center gap-1.5">
                      <Checkbox
                        checked={item.requiresFile}
                        onCheckedChange={(checked) =>
                          update(item.key, { requiresFile: checked === true })
                        }
                      />
                      z plikiem
                    </label>
                  ) : null}
                </div>
              )}
            </li>
          );
        })}
      </ul>
      <Button type="button" variant="outline" size="sm" onClick={add}>
        <Plus className="h-4 w-4" aria-hidden />
        {addLabel}
      </Button>
    </div>
  );
}
