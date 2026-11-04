"use client";

import { useId, useMemo, useState, type FormEvent } from "react";
import { AlertCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import type { ScopeInfoDto } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";

import { groupScopeCatalog, normalizeSlug, slugError } from "./api-keys-model";

export interface ServiceAccountFormValues {
  slug: string;
  name: string;
  description: string | null;
  scopes: string[];
}

export interface ServiceAccountFormProps {
  mode: "create" | "edit";
  scopeCatalog: readonly ScopeInfoDto[];
  initial?: ServiceAccountFormValues;
  onSubmit: (values: ServiceAccountFormValues) => Promise<unknown>;
  onCancel: () => void;
}

/** Formularz konta serwisowego. Slug podaje się tylko przy zakładaniu —
 *  backend trzyma go jako niezmienny identyfikator w logach i audycie. */
export function ServiceAccountForm({
  mode,
  scopeCatalog,
  initial,
  onSubmit,
  onCancel,
}: ServiceAccountFormProps) {
  const id = useId();
  const [slug, setSlug] = useState(initial?.slug ?? "");
  const [name, setName] = useState(initial?.name ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [selected, setSelected] = useState<ReadonlySet<string>>(
    () => new Set(initial?.scopes ?? []),
  );
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const groups = useMemo(() => groupScopeCatalog(scopeCatalog), [scopeCatalog]);

  const toggle = (scope: string, checked: boolean) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (checked) next.add(scope);
      else next.delete(scope);
      return next;
    });
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (mode === "create") {
      const problem = slugError(slug);
      if (problem) {
        setError(problem);
        return;
      }
    }
    if (!name.trim()) {
      setError("Podaj nazwę konta.");
      return;
    }
    setError(null);
    setPending(true);
    try {
      await onSubmit({
        slug: normalizeSlug(slug),
        name: name.trim(),
        description: description.trim() || null,
        // Kolejność jak na ekranie — łatwiej czytać w logach i w diffie.
        scopes: groups.flatMap((g) => g.scopes.map((s) => s.value)).filter((v) => selected.has(v)),
      });
    } catch (err) {
      setError(
        apiErrorMessage(
          err,
          mode === "create" ? "Nie udało się założyć konta." : "Nie udało się zapisać zmian.",
        ),
      );
    } finally {
      setPending(false);
    }
  };

  return (
    <form
      onSubmit={submit}
      aria-label={mode === "create" ? "Nowe konto serwisowe" : "Edycja konta serwisowego"}
      className="space-y-4"
      noValidate
    >
      <div className="grid gap-4 md:grid-cols-2">
        {mode === "create" ? (
          <div>
            <label htmlFor={`${id}-slug`} className="mb-1 block text-sm font-medium text-foreground">
              Identyfikator (slug)
            </label>
            <Input
              id={`${id}-slug`}
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
              placeholder="np. rozliczenia-n8n"
              autoComplete="off"
              spellCheck={false}
              maxLength={64}
              className="font-mono"
            />
            <p className="mt-1 text-xs text-muted-foreground">
              Widać go w logach i historii zapisów. Później nie da się go zmienić.
            </p>
          </div>
        ) : null}
        <div className={mode === "edit" ? "md:col-span-2" : undefined}>
          <label htmlFor={`${id}-name`} className="mb-1 block text-sm font-medium text-foreground">
            Nazwa
          </label>
          <Input
            id={`${id}-name`}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="np. Automatyzacja rozliczeń (n8n)"
            maxLength={120}
          />
        </div>
        <div className="md:col-span-2">
          <label htmlFor={`${id}-description`} className="mb-1 block text-sm font-medium text-foreground">
            Opis <span className="font-normal text-muted-foreground">(opcjonalnie)</span>
          </label>
          <Textarea
            id={`${id}-description`}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Kto korzysta z konta i do czego."
            rows={2}
            maxLength={2000}
            className="min-h-[60px]"
          />
        </div>
      </div>

      <fieldset className="min-w-0 space-y-3">
        <legend className="text-sm font-medium text-foreground">Uprawnienia</legend>
        <p className="text-xs text-muted-foreground">
          Zapis obejmuje odczyt tego samego obszaru.
          {mode === "edit" ? " Zmiana działa od razu dla wszystkich kluczy tego konta." : ""}
        </p>
        <div className="grid gap-3 md:grid-cols-2">
          {groups.map((group) => (
            <div
              key={group.id}
              role="group"
              aria-labelledby={`${id}-group-${group.id}`}
              className="rounded-lg border border-border p-3"
            >
              <p
                id={`${id}-group-${group.id}`}
                className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground"
              >
                {group.title}
              </p>
              <ul className="space-y-1.5">
                {group.scopes.map((scope) => {
                  const inputId = `${id}-scope-${scope.value}`;
                  return (
                    <li key={scope.value} className="flex items-start gap-2">
                      <Checkbox
                        id={inputId}
                        checked={selected.has(scope.value)}
                        onCheckedChange={(checked) => toggle(scope.value, checked === true)}
                        className="mt-0.5"
                      />
                      <label htmlFor={inputId} className="min-w-0 cursor-pointer text-sm leading-snug">
                        <span className="text-foreground">{scope.label}</span>
                        <span className="ml-1.5 font-mono text-xs text-muted-foreground">{scope.value}</span>
                      </label>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </div>
      </fieldset>

      {error ? (
        <p role="alert" className="flex items-start gap-2 text-sm text-destructive">
          <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
          <span>{error}</span>
        </p>
      ) : null}

      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" onClick={onCancel} disabled={pending}>
          Anuluj
        </Button>
        <Button type="submit" loading={pending}>
          {mode === "create" ? "Załóż konto" : "Zapisz zmiany"}
        </Button>
      </div>
    </form>
  );
}
