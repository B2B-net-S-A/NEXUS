"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import {
  invalidateReviewBatch,
  saveRoleProfile,
  type ReviewBatchExcludedRole,
  type ReviewBatchRoleLevel,
  type ReviewBatchRoleProfile,
} from "@/lib/api/reviewBatch";
import { cn } from "@/lib/utils";

/**
 * Profil „Kogo szukamy” nad kartą w porcji (decyzja Artura 16.11.2026):
 * „Inna rola” to 28% odrzuceń 16.11, a w 37% decyzji tytuł rekrutacji nic
 * silnikowi nie mówi. Zespół poprawia profil sam, a lista „Nie proponujemy”
 * zatrzymuje dokładanie osób z takim stanowiskiem. Reguła:
 * `docs/claude/rekrutacja-tablica/porcja-kogo-szukamy.md`.
 */

export const LEVEL_LABEL: Record<ReviewBatchRoleLevel, string> = {
  wykonawca: "wykonawca",
  lider: "lider",
  dowolny: "dowolny poziom",
};

/** „tester · automatyzacja · Java · lider”; pusta rola = „rola nieustalona”. */
export function wantedLine(profile: ReviewBatchRoleProfile): string {
  return [
    profile.role || "rola nieustalona",
    profile.specialty,
    profile.technology,
    profile.level !== "dowolny" ? LEVEL_LABEL[profile.level] : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

function excludedLabel(entry: ReviewBatchExcludedRole): string {
  return entry.source === "manual" ? `${entry.label} (ręcznie)` : `${entry.label} (${entry.count}× z odrzuceń)`;
}

/** „Data Engineer (3× z odrzuceń), Scrum Master (ręcznie)”; `null` przy pustej liście. */
export function excludedLine(profile: ReviewBatchRoleProfile): string | null {
  return profile.excluded.length ? profile.excluded.map(excludedLabel).join(", ") : null;
}

export function RoleProfileBlock({
  profile,
  compact,
}: {
  profile: ReviewBatchRoleProfile;
  /** Po pierwszej karcie rekrutacji jedna linia: przy 1280 × 720 „Pasuje” ma zostać na ekranie. */
  compact: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const wanted = wantedLine(profile);
  const excluded = excludedLine(profile);
  const fix = (
    <button
      type="button"
      onClick={() => setEditing(true)}
      className="shrink-0 text-xs text-primary hover:underline"
      data-testid="review-role-profile-edit"
    >
      Popraw
    </button>
  );
  return (
    <div className="mt-1 text-xs leading-snug" data-testid="review-role-profile">
      {compact ? (
        <p className="flex items-baseline gap-1.5">
          <span className="min-w-0 truncate" title={`Kogo szukamy: ${wanted}${excluded ? ` · Nie proponujemy: ${excluded}` : ""}`}>
            <span className="font-medium text-muted-foreground">Kogo szukamy:</span> {wanted}
            {excluded ? (
              <>
                {" "}
                · <span className="font-medium text-muted-foreground">Nie proponujemy:</span> {excluded}
              </>
            ) : null}
          </span>
          {fix}
        </p>
      ) : (
        <>
          <p>
            <span className="font-medium text-muted-foreground">Kogo szukamy:</span> {wanted}
          </p>
          <p className="flex items-baseline gap-1.5">
            <span className="min-w-0">
              <span className="font-medium text-muted-foreground">Nie proponujemy:</span>{" "}
              {excluded ?? <span className="text-muted-foreground">nikogo (uczy się z „Inna rola”)</span>}
            </span>
            {fix}
          </p>
        </>
      )}
      {editing ? <RoleProfileDialog profile={profile} onClose={() => setEditing(false)} /> : null}
    </div>
  );
}

const LEVELS: ReviewBatchRoleLevel[] = ["wykonawca", "lider", "dowolny"];

function sameLabel(a: string, b: string): boolean {
  return a.trim().toLocaleLowerCase("pl") === b.trim().toLocaleLowerCase("pl");
}

export function RoleProfileDialog({
  profile,
  onClose,
}: {
  profile: ReviewBatchRoleProfile;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const { showError, showSuccess } = useToast();
  const [role, setRole] = useState(profile.role ?? "");
  const [specialty, setSpecialty] = useState(profile.specialty ?? "");
  const [technology, setTechnology] = useState(profile.technology ?? "");
  const [level, setLevel] = useState<ReviewBatchRoleLevel>(profile.level);
  const [excluded, setExcluded] = useState<ReviewBatchExcludedRole[]>(profile.excluded);
  const [adding, setAdding] = useState("");
  const [busy, setBusy] = useState(false);
  const learning = profile.learning.filter((l) => !l.dismissed && !excluded.some((e) => sameLabel(e.label, l.label)));

  function add() {
    const label = adding.trim();
    if (!label || excluded.some((e) => sameLabel(e.label, label))) {
      setAdding("");
      return;
    }
    setExcluded((current) => [...current, { label, count: 0, source: "manual" }]);
    setAdding("");
  }

  async function save() {
    setBusy(true);
    try {
      await saveRoleProfile(profile.job_id, {
        role: role.trim() || null,
        specialty: specialty.trim() || null,
        technology: technology.trim() || null,
        level,
        excluded: excluded.map((e) => e.label),
      });
      invalidateReviewBatch(queryClient);
      showSuccess("Zapisano profil „Kogo szukamy”. Silnik użyje go przy następnym dokładaniu osób.");
      onClose();
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się zapisać profilu „Kogo szukamy”."));
    } finally {
      setBusy(false);
    }
  }

  const field = "w-full rounded border border-border bg-background px-2 py-1 text-sm";
  return (
    <Dialog open onOpenChange={(open) => (open ? null : onClose())}>
      <DialogContent size="sm" data-testid="review-role-profile-dialog">
        <DialogHeader>
          <DialogTitle>Kogo szukamy</DialogTitle>
          <DialogDescription>
            Osób, których obecne stanowisko zawiera pozycję z „Nie proponujemy”, silnik nie dokłada do tej
            rekrutacji. Osoby, które już czekają, zostają.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="max-h-[60dvh] space-y-3 overflow-y-auto text-sm">
          <label className="block space-y-1">
            <span className="text-xs text-muted-foreground">Rola</span>
            <input value={role} maxLength={120} onChange={(e) => setRole(e.target.value)} className={field} placeholder="np. analityk biznesowy" />
          </label>
          <label className="block space-y-1">
            <span className="text-xs text-muted-foreground">Specjalizacja (opcjonalnie)</span>
            <input value={specialty} maxLength={120} onChange={(e) => setSpecialty(e.target.value)} className={field} placeholder="np. bankowość inwestycyjna" />
          </label>
          <label className="block space-y-1">
            <span className="text-xs text-muted-foreground">Główna technologia (opcjonalnie)</span>
            <input value={technology} maxLength={120} onChange={(e) => setTechnology(e.target.value)} className={field} placeholder="np. Java" />
          </label>
          <div className="space-y-1">
            <span className="text-xs text-muted-foreground">Poziom</span>
            <div className="flex gap-1" role="radiogroup" aria-label="Poziom">
              {LEVELS.map((value) => (
                <button
                  key={value}
                  type="button"
                  role="radio"
                  aria-checked={level === value}
                  onClick={() => setLevel(value)}
                  className={cn(
                    "rounded-md border px-2 py-1 text-xs",
                    level === value ? "border-primary bg-primary text-primary-foreground" : "border-border hover:bg-muted",
                  )}
                >
                  {LEVEL_LABEL[value]}
                </button>
              ))}
            </div>
          </div>
          <div className="space-y-1">
            <span className="text-xs text-muted-foreground">Nie proponujemy</span>
            <div className="flex flex-wrap gap-1" aria-label="Nie proponujemy">
              {excluded.length === 0 ? <span className="text-xs text-muted-foreground">Lista jest pusta.</span> : null}
              {excluded.map((entry) => (
                <span key={entry.label} className="inline-flex items-center gap-1 rounded bg-muted px-1.5 py-0.5 text-xs">
                  {excludedLabel(entry)}
                  <button
                    type="button"
                    aria-label={`Usuń ${entry.label}`}
                    onClick={() => setExcluded((current) => current.filter((e) => e !== entry))}
                    className="text-muted-foreground hover:text-foreground"
                  >
                    <X className="h-3 w-3" aria-hidden="true" />
                  </button>
                </span>
              ))}
            </div>
            <div className="flex gap-1">
              <input
                value={adding}
                maxLength={120}
                aria-label="Dodaj do „Nie proponujemy”"
                onChange={(e) => setAdding(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    add();
                  }
                }}
                className={field}
                placeholder="np. Scrum Master, tester manualny"
              />
              <Button type="button" size="sm" variant="outline" onClick={add} disabled={!adding.trim()}>
                Dodaj
              </Button>
            </div>
            {learning.length ? (
              <p className="text-xs text-muted-foreground">
                Z odrzuceń, jeszcze poniżej progu {profile.exclude_min}:{" "}
                {learning.map((l) => `${l.label} (${l.count}×)`).join(", ")}
              </p>
            ) : null}
          </div>
        </DialogBody>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Anuluj
          </Button>
          <Button onClick={() => void save()} disabled={busy} data-testid="review-role-profile-save">
            Zapisz
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
