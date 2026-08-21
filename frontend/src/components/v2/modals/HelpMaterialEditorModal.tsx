"use client";

import { useEffect, useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";

import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { extractErrorMsg } from "@/lib/api";
import {
  HelpMaterial,
  HelpMaterialCreateInput,
  HelpMaterialUpdateInput,
  helpMaterialsApi,
} from "@/lib/api/help-materials";

/**
 * `url` trafia wprost do `<a href>`, więc schemat linku waliduje też backend
 * (422). Tutaj ta sama reguła po stronie klienta — żeby admin dostał czytelny
 * komunikat zanim wyśle `javascript:`/`data:` do bazy.
 */
const HTTP_SCHEME_MESSAGE = "Link musi zaczynać się od http:// lub https://";

/**
 * Kolumna `sort_order` to INTEGER (int32). Bez tych granic admin mógł wysłać
 * np. 9999999999, dostać 500 z bazy i generyczny komunikat „Nie udało się
 * zapisać materiału" — bez wskazania, które pole jest złe.
 */
const SORT_ORDER_MIN = -2_147_483_648;
const SORT_ORDER_MAX = 2_147_483_647;
const SORT_ORDER_RANGE_MESSAGE = "Kolejność musi mieścić się w zakresie liczby całkowitej";

function isHttpUrl(value: string): boolean {
  try {
    const parsed = new URL(value.trim());
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch {
    return false;
  }
}

/**
 * Lustro CHECK-a `ck_help_materials_link_or_template` i walidatora w API.
 *
 * Bez tego admin nie mógłby w ogóle edytować zaseedowanego szablonu: pole
 * „Link" było wymagane, a szablon zaproszenia go NIE MA — otwarcie edytora
 * kończyło się błędem walidacji na polu, którego ta pozycja nie używa.
 */
const LINK_OR_TEMPLATE_MESSAGE =
  "Podaj link do dokumentu albo treść szablonu — pozycja bez jednego i drugiego " +
  "wyświetli się w Pomocy bez żadnej akcji";

const materialSchema = z
  .object({
    category: z
      .string()
      .trim()
      .min(2, "Kategoria jest wymagana")
      .max(120, "Kategoria za długa"),
    title: z
      .string()
      .trim()
      .min(3, "Tytuł jest za krótki")
      .max(255, "Tytuł za długi"),
    // Pusty = „ta pozycja nie jest linkiem". Schemat http(s) sprawdzamy dopiero
    // dla niepustej wartości, żeby szablon nie wywracał się na pustym polu.
    url: z
      .string()
      .trim()
      .refine((v) => v === "" || isHttpUrl(v), HTTP_SCHEME_MESSAGE),
    description: z.string().max(1000, "Opis za długi"),
    template_subject: z.string().trim().max(255, "Temat szablonu za długi"),
    template_body: z.string().max(10_000, "Treść szablonu za długa"),
    is_editable_template: z.boolean(),
    sort_order: z.coerce
      .number()
      .int("Kolejność musi być liczbą całkowitą")
      .min(SORT_ORDER_MIN, SORT_ORDER_RANGE_MESSAGE)
      .max(SORT_ORDER_MAX, SORT_ORDER_RANGE_MESSAGE),
    is_published: z.boolean(),
  })
  .superRefine((values, ctx) => {
    if (values.url.trim() === "" && values.template_body.trim() === "") {
      // Błąd przypięty do OBU pól — admin nie musi zgadywać, które uzupełnić.
      for (const path of ["url", "template_body"] as const) {
        ctx.addIssue({ code: "custom", path: [path], message: LINK_OR_TEMPLATE_MESSAGE });
      }
    }
  });

// zod 4: z.coerce.number() ma wejście `unknown`, więc typ pól formularza
// (input) i typ po walidacji (output) muszą być rozróżnione w useForm.
type MaterialFormInput = z.input<typeof materialSchema>;
type MaterialFormData = z.output<typeof materialSchema>;

interface Props {
  material: HelpMaterial | null;
  open: boolean;
  /** Kategorie już użyte — podpowiedzi w datalist (pole zostaje wolnym tekstem). */
  categorySuggestions?: string[];
  onOpenChange: (open: boolean) => void;
  onSaved: (saved: HelpMaterial) => void;
}

function defaultsFor(material: HelpMaterial | null): MaterialFormData {
  return {
    category: material?.category ?? "",
    title: material?.title ?? "",
    url: material?.url ?? "",
    description: material?.description ?? "",
    template_subject: material?.template_subject ?? "",
    template_body: material?.template_body ?? "",
    is_editable_template: material?.is_editable_template ?? false,
    sort_order: material?.sort_order ?? 0,
    is_published: material?.is_published ?? true,
  };
}

function apiErrorMessage(error: unknown): string {
  const status = (error as { response?: { status?: number } })?.response?.status;
  if (status === 403) {
    return "Brak uprawnień — materiały może dodawać i edytować tylko administrator.";
  }
  if (status === 422) {
    return extractErrorMsg(error) || "Formularz zawiera nieprawidłowe dane.";
  }
  return extractErrorMsg(error) || "Nie udało się zapisać materiału.";
}

export function HelpMaterialEditorModal({
  material,
  open,
  categorySuggestions = [],
  onOpenChange,
  onSaved,
}: Props) {
  const editing = material !== null;
  const queryClient = useQueryClient();
  const [apiError, setApiError] = useState<string | null>(null);
  // Jedna instancja modala naraz — stały id wystarczy i jest stabilny w SSR.
  const categoryListId = "help-material-category-options";

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<MaterialFormInput, unknown, MaterialFormData>({
    resolver: zodResolver(materialSchema),
    defaultValues: defaultsFor(material),
  });

  useEffect(() => {
    reset(defaultsFor(material));
    setApiError(null);
  }, [material, reset]);

  const mutation = useMutation({
    mutationFn: async (values: MaterialFormData) => {
      // Puste pole to `null`, nie `""`: backend normalizuje jedno i drugie, ale
      // `""` przechodziłby CHECK w bazie (kolumna jest wtedy NOT NULL) i dawał
      // szablon bez treści — pozycję, która wygląda na sprawną, a nic nie robi.
      const payload: HelpMaterialCreateInput | HelpMaterialUpdateInput = {
        category: values.category.trim(),
        title: values.title.trim(),
        url: values.url.trim() || null,
        description: values.description.trim() || null,
        template_subject: values.template_subject.trim() || null,
        template_body: values.template_body.trim() || null,
        is_editable_template: values.is_editable_template,
        sort_order: values.sort_order ?? 0,
        is_published: values.is_published,
      };
      if (editing && material) {
        return helpMaterialsApi.update(material.id, payload);
      }
      return helpMaterialsApi.create(payload as HelpMaterialCreateInput);
    },
    onSuccess: (saved) => {
      queryClient.invalidateQueries({ queryKey: ["help-materials"] });
      onSaved(saved);
    },
    onError: (err: unknown) => setApiError(apiErrorMessage(err)),
  });

  const onSubmit = handleSubmit((values) => {
    setApiError(null);
    mutation.mutate(values);
  });

  const title = useMemo(
    () => (editing ? "Edytuj materiał" : "Nowy materiał"),
    [editing],
  );

  const uniqueSuggestions = useMemo(
    () => Array.from(new Set(categorySuggestions.filter(Boolean))).sort(),
    [categorySuggestions],
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="lg" className="flex flex-col max-h-[90vh]">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>

        <form onSubmit={onSubmit} className="contents">
          <DialogBody className="space-y-4 flex-1">
            <div>
              <label
                htmlFor="material-category"
                className="block text-sm font-medium text-foreground mb-1.5"
              >
                Kategoria
              </label>
              <Input
                id="material-category"
                list={uniqueSuggestions.length ? categoryListId : undefined}
                placeholder="Np. Szablony i wzory"
                {...register("category")}
                invalid={!!errors.category}
                aria-describedby={
                  errors.category ? "material-category-error" : undefined
                }
              />
              {uniqueSuggestions.length > 0 && (
                <datalist id={categoryListId}>
                  {uniqueSuggestions.map((c) => (
                    <option key={c} value={c} />
                  ))}
                </datalist>
              )}
              {errors.category && (
                <p id="material-category-error" className="text-xs text-primary mt-1">
                  {errors.category.message}
                </p>
              )}
            </div>

            <div>
              <label
                htmlFor="material-title"
                className="block text-sm font-medium text-foreground mb-1.5"
              >
                Tytuł
              </label>
              <Input
                id="material-title"
                placeholder="Np. Profil Championa"
                {...register("title")}
                invalid={!!errors.title}
                aria-describedby={errors.title ? "material-title-error" : undefined}
              />
              {errors.title && (
                <p id="material-title-error" className="text-xs text-primary mt-1">
                  {errors.title.message}
                </p>
              )}
            </div>

            <div>
              <label
                htmlFor="material-url"
                className="block text-sm font-medium text-foreground mb-1.5"
              >
                Link do SharePointa
              </label>
              <Input
                id="material-url"
                placeholder="https://firma.sharepoint.com/:w:/g/…"
                {...register("url")}
                invalid={!!errors.url}
                aria-describedby={errors.url ? "material-url-error" : "material-url-hint"}
              />
              {errors.url ? (
                <p id="material-url-error" className="text-xs text-primary mt-1">
                  {errors.url.message}
                </p>
              ) : (
                <p id="material-url-hint" className="text-xs text-muted-foreground mt-1">
                  Wklej link „Udostępnij" z SharePointa. Dokument zostaje w
                  SharePoincie — NEXUS trzyma tylko odnośnik. Zostaw puste, jeśli
                  ta pozycja jest samym szablonem treści.
                </p>
              )}
            </div>

            {/* Sekcja szablonu. Ramka i nagłówek są po to, żeby admin widział,
                że wypełnia DRUGI wariant pozycji, a nie kolejne opcjonalne pole
                — ale wypełnienie OBU jest legalne (CHECK w bazie to OR, nie
                XOR) i wiersz pokazuje wtedy i link, i akcje zaproszenia.
                Wymagane jest co najmniej jedno z dwojga. */}
            <fieldset className="rounded-lg border border-border p-3 space-y-3">
              <legend className="px-1 text-sm font-medium text-foreground">
                Szablon treści
              </legend>
              <p className="text-xs text-muted-foreground">
                Dla pozycji, które nie są plikiem — np. zaproszenia
                kalendarzowego. Rekruter dostanie z niej gotowy plik `.ics`
                i pop-out w Outlook Web. Można wypełnić razem z linkiem — wiersz
                pokaże wtedy obie akcje.
              </p>

              <div>
                <label
                  htmlFor="material-template-subject"
                  className="block text-sm font-medium text-foreground mb-1.5"
                >
                  Temat
                </label>
                <Input
                  id="material-template-subject"
                  placeholder="Np. Przygotowanie do spotkania z (nazwa Klienta)"
                  {...register("template_subject")}
                  invalid={!!errors.template_subject}
                />
                {errors.template_subject && (
                  <p className="text-xs text-primary mt-1">
                    {errors.template_subject.message}
                  </p>
                )}
              </div>

              <div>
                <label
                  htmlFor="material-template-body"
                  className="block text-sm font-medium text-foreground mb-1.5"
                >
                  Treść
                </label>
                <Textarea
                  id="material-template-body"
                  rows={10}
                  placeholder="Dzień dobry,&#10;&#10;Zapraszam na spotkanie…"
                  className="font-mono text-xs"
                  {...register("template_body")}
                  invalid={!!errors.template_body}
                  aria-describedby="material-template-body-hint"
                />
                {errors.template_body ? (
                  <p className="text-xs text-primary mt-1">
                    {errors.template_body.message}
                  </p>
                ) : (
                  <p
                    id="material-template-body-hint"
                    className="text-xs text-muted-foreground mt-1"
                  >
                    Nawiasy — np. „(nazwa Klienta)" — zostają widoczne i
                    uzupełnia je rekruter. Puste linie są zachowywane. Nie wpisuj
                    tu uwag wewnętrznych: całą treść widzi kandydat.
                  </p>
                )}
              </div>
            </fieldset>

            <div>
              <label
                htmlFor="material-description"
                className="block text-sm font-medium text-foreground mb-1.5"
              >
                Opis (opcjonalnie)
              </label>
              <Textarea
                id="material-description"
                rows={3}
                placeholder="Krótko: do czego służy ten dokument."
                {...register("description")}
                invalid={!!errors.description}
              />
              {errors.description && (
                <p className="text-xs text-primary mt-1">
                  {errors.description.message}
                </p>
              )}
            </div>

            <label className="flex items-start gap-2 text-sm">
              <input
                type="checkbox"
                className="h-4 w-4 mt-0.5 rounded border-border accent-[hsl(var(--primary))]"
                {...register("is_editable_template")}
              />
              <span>
                <span className="font-medium text-foreground">
                  Nasz wzór — pokaż skrót do edycji w Word Online
                </span>
                <span className="block text-xs text-muted-foreground">
                  Zaznacz dla własnych szablonów, które poprawiamy na bieżąco.
                  Formularze klientów zostaw odznaczone.
                </span>
              </span>
            </label>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div>
                <label
                  htmlFor="material-sort-order"
                  className="block text-sm font-medium text-foreground mb-1.5"
                >
                  Kolejność
                </label>
                <Input
                  id="material-sort-order"
                  type="number"
                  step={1}
                  min={SORT_ORDER_MIN}
                  max={SORT_ORDER_MAX}
                  {...register("sort_order")}
                />
                <p className="text-xs text-muted-foreground mt-1">
                  Niższa wartość = wyżej na liście. Domyślnie 0.
                </p>
              </div>
              <div className="flex items-end">
                <label className="inline-flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    className="h-4 w-4 rounded border-border accent-[hsl(var(--primary))]"
                    {...register("is_published")}
                  />
                  <span>Opublikowane (widoczne dla zespołu)</span>
                </label>
              </div>
            </div>

            {apiError && (
              <p role="alert" className="text-sm text-primary">
                {apiError}
              </p>
            )}
          </DialogBody>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={isSubmitting}
            >
              Anuluj
            </Button>
            <Button type="submit" variant="primary" loading={isSubmitting}>
              {editing ? "Zapisz zmiany" : "Dodaj materiał"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
