"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  DragDropContext,
  Droppable,
  Draggable,
  type DropResult,
} from "@hello-pangea/dnd";
import Link from "next/link";
import {
  ArrowLeft,
  Plus,
  Archive,
  ArchiveRestore,
  Loader2,
  AlertCircle,
  GripVertical,
  Sparkles,
} from "lucide-react";
import {
  entityFieldsApi,
  type EntityFieldDefDto,
  type EntityType,
  type FieldType,
  type FieldTypeInfoDto,
} from "@/lib/api";
import { cn } from "@/lib/utils";

// ── Constants ────────────────────────────────────────────────────────────────

const SECTIONS: Array<{ id: string; label: string }> = [
  { id: "left", label: "Lewa kolumna" },
  { id: "middle", label: "Środkowa kolumna" },
  { id: "right", label: "Prawa kolumna" },
];

const ENTITY_OPTIONS: Array<{ id: EntityType; label: string }> = [
  { id: "candidate", label: "Kandydat" },
  { id: "job", label: "Rekrutacja" },
];

// ── Add field form ───────────────────────────────────────────────────────────

interface AddFieldFormProps {
  entity: EntityType;
  fieldTypes: FieldTypeInfoDto[];
  onCreated: () => void;
  onCancel: () => void;
}

function AddFieldForm({
  entity,
  fieldTypes,
  onCreated,
  onCancel,
}: AddFieldFormProps) {
  const [key, setKey] = useState("");
  const [labelPl, setLabelPl] = useState("");
  const [fieldType, setFieldType] = useState<FieldType>("text");
  const [section, setSection] = useState("middle");
  const [error, setError] = useState<string | null>(null);

  const queryClient = useQueryClient();
  const create = useMutation({
    mutationFn: () =>
      entityFieldsApi
        .create({
          entity_type: entity,
          key: key.trim(),
          label_pl: labelPl.trim(),
          field_type: fieldType,
          section,
        })
        .then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["entity-schema", entity] });
      onCreated();
    },
    onError: (err: unknown) => {
      setError(err instanceof Error ? err.message : "Nie udało się utworzyć");
    },
  });

  const submit = () => {
    if (!/^[a-z][a-z0-9_]*$/.test(key.trim())) {
      setError("Klucz musi pasować do /^[a-z][a-z0-9_]*$/");
      return;
    }
    if (!labelPl.trim()) {
      setError("Etykieta jest wymagana");
      return;
    }
    setError(null);
    create.mutate();
  };

  return (
    <div className="bg-card border border-border rounded-xl p-5 mb-4">
      <h3 className="text-base font-semibold text-foreground mb-3">
        Nowe pole
      </h3>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div>
          <label className="text-xs font-medium text-muted-foreground block mb-1">
            Klucz (JSON key)
          </label>
          <input
            value={key}
            onChange={(e) => setKey(e.target.value)}
            placeholder="np. preferred_locations"
            className="w-full px-3 py-1.5 bg-background border border-input rounded-md text-sm font-mono focus:outline-none focus:ring-2 focus:ring-ring"
          />
        </div>
        <div>
          <label className="text-xs font-medium text-muted-foreground block mb-1">
            Etykieta PL
          </label>
          <input
            value={labelPl}
            onChange={(e) => setLabelPl(e.target.value)}
            placeholder="np. Preferowane lokalizacje"
            className="w-full px-3 py-1.5 bg-background border border-input rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          />
        </div>
        <div>
          <label className="text-xs font-medium text-muted-foreground block mb-1">
            Typ pola
          </label>
          <select
            value={fieldType}
            onChange={(e) => setFieldType(e.target.value as FieldType)}
            className="w-full px-3 py-1.5 bg-background border border-input rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          >
            {fieldTypes.map((ft) => (
              <option key={ft.value} value={ft.value}>
                {ft.label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-xs font-medium text-muted-foreground block mb-1">
            Sekcja
          </label>
          <select
            value={section}
            onChange={(e) => setSection(e.target.value)}
            className="w-full px-3 py-1.5 bg-background border border-input rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          >
            {SECTIONS.map((s) => (
              <option key={s.id} value={s.id}>
                {s.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {error && (
        <div className="mt-3 text-sm text-rose-500 flex items-center gap-1">
          <AlertCircle className="w-4 h-4" />
          {error}
        </div>
      )}

      <div className="flex gap-2 justify-end mt-4">
        <button
          type="button"
          onClick={onCancel}
          className="px-4 py-1.5 text-sm text-muted-foreground hover:text-foreground"
        >
          Anuluj
        </button>
        <button
          type="button"
          onClick={submit}
          disabled={create.isPending}
          className="px-4 py-1.5 text-sm bg-primary text-primary-foreground rounded-md disabled:opacity-50"
        >
          {create.isPending ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            "Utwórz"
          )}
        </button>
      </div>
    </div>
  );
}

// ── Field card (draggable) ───────────────────────────────────────────────────

interface FieldCardProps {
  field: EntityFieldDefDto;
  entity: EntityType;
  fieldTypes: FieldTypeInfoDto[];
}

function FieldCard({ field, entity, fieldTypes }: FieldCardProps) {
  const queryClient = useQueryClient();
  const typeLabel =
    fieldTypes.find((t) => t.value === field.field_type)?.label ??
    field.field_type;

  const update = useMutation({
    mutationFn: (
      payload: Parameters<typeof entityFieldsApi.update>[1],
    ) => entityFieldsApi.update(field.id, payload).then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["entity-schema", entity] });
    },
  });

  const toggleArchived = () => update.mutate({ archived: !field.archived });
  const toggleRequired = () => update.mutate({ required: !field.required });

  return (
    <div
      className={cn(
        "flex items-center gap-3 px-3 py-2 bg-card border border-border rounded-lg",
        field.archived && "opacity-50",
      )}
    >
      <GripVertical className="w-4 h-4 text-muted-foreground cursor-grab shrink-0" />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-foreground truncate">
            {field.label_pl}
          </span>
          {field.required && (
            <span className="text-xs px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-500">
              wymagane
            </span>
          )}
        </div>
        <div className="text-xs text-muted-foreground font-mono mt-0.5 truncate">
          {field.key} · <span className="font-sans">{typeLabel}</span>
        </div>
      </div>
      <div className="flex items-center gap-1 shrink-0">
        <button
          type="button"
          onClick={toggleRequired}
          className={cn(
            "text-xs px-2 py-1 rounded transition-colors",
            field.required
              ? "bg-amber-500/10 text-amber-500 hover:bg-amber-500/20"
              : "text-muted-foreground hover:bg-muted",
          )}
          title={field.required ? "Zdejmij wymóg" : "Oznacz jako wymagane"}
        >
          *
        </button>
        <button
          type="button"
          onClick={toggleArchived}
          className="p-1.5 text-muted-foreground hover:text-foreground rounded-md"
          title={field.archived ? "Przywróć" : "Archiwizuj"}
        >
          {field.archived ? (
            <ArchiveRestore className="w-3.5 h-3.5" />
          ) : (
            <Archive className="w-3.5 h-3.5" />
          )}
        </button>
      </div>
    </div>
  );
}

// ── Section column ───────────────────────────────────────────────────────────

interface SectionColumnProps {
  sectionId: string;
  sectionLabel: string;
  fields: EntityFieldDefDto[];
  entity: EntityType;
  fieldTypes: FieldTypeInfoDto[];
}

function SectionColumn({
  sectionId,
  sectionLabel,
  fields,
  entity,
  fieldTypes,
}: SectionColumnProps) {
  return (
    <div className="space-y-2">
      <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
        {sectionLabel}
      </h3>
      <Droppable droppableId={sectionId}>
        {(provided, snapshot) => (
          <div
            ref={provided.innerRef}
            {...provided.droppableProps}
            className={cn(
              "min-h-[120px] p-2 rounded-lg border-2 border-dashed transition-colors",
              snapshot.isDraggingOver
                ? "border-primary bg-primary/5"
                : "border-border bg-muted/30",
            )}
          >
            {fields.length === 0 && (
              <p className="text-xs text-muted-foreground italic text-center py-4">
                Upuść tutaj
              </p>
            )}
            {fields.map((field, index) => (
              <Draggable
                key={field.id}
                draggableId={String(field.id)}
                index={index}
              >
                {(dragProvided, dragSnapshot) => (
                  <div
                    ref={dragProvided.innerRef}
                    {...dragProvided.draggableProps}
                    {...dragProvided.dragHandleProps}
                    className={cn(
                      "mb-2 last:mb-0",
                      dragSnapshot.isDragging && "opacity-80 shadow-lg",
                    )}
                  >
                    <FieldCard
                      field={field}
                      entity={entity}
                      fieldTypes={fieldTypes}
                    />
                  </div>
                )}
              </Draggable>
            ))}
            {provided.placeholder}
          </div>
        )}
      </Droppable>
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function EntityFieldsPage() {
  const [entity, setEntity] = useState<EntityType>("candidate");
  const [showAddForm, setShowAddForm] = useState(false);
  const [showArchived, setShowArchived] = useState(false);
  const queryClient = useQueryClient();

  const schemaQuery = useQuery({
    queryKey: ["entity-schema", entity, showArchived],
    queryFn: () =>
      entityFieldsApi
        .schema(entity, showArchived)
        .then((r) => r.data.fields),
  });

  const fieldTypesQuery = useQuery({
    queryKey: ["entity-field-types"],
    queryFn: () => entityFieldsApi.fieldTypes().then((r) => r.data),
  });

  // Optimistic local copy so drag-drop feels instant; we sync back to the
  // server on drop end via PATCH calls.
  const [localFields, setLocalFields] = useState<EntityFieldDefDto[]>([]);
  useEffect(() => {
    if (schemaQuery.data) setLocalFields(schemaQuery.data);
  }, [schemaQuery.data]);

  const update = useMutation({
    mutationFn: ({
      id,
      payload,
    }: {
      id: number;
      payload: Parameters<typeof entityFieldsApi.update>[1];
    }) => entityFieldsApi.update(id, payload).then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["entity-schema", entity] });
    },
  });

  const onDragEnd = (result: DropResult) => {
    const { source, destination, draggableId } = result;
    if (!destination) return;
    if (
      source.droppableId === destination.droppableId &&
      source.index === destination.index
    ) {
      return;
    }
    const fieldId = Number(draggableId);
    const movedSection = destination.droppableId;
    const movedOrdinal = destination.index;

    // Update local state optimistically (re-bucket + re-ordinal).
    const next = localFields.map((f) => ({ ...f }));
    const moved = next.find((f) => f.id === fieldId);
    if (!moved) return;
    moved.section = movedSection;

    // Re-pack ordinals within the destination section.
    const inDest = next
      .filter((f) => f.section === movedSection && f.id !== fieldId)
      .sort((a, b) => a.ordinal - b.ordinal);
    inDest.splice(movedOrdinal, 0, moved);
    inDest.forEach((f, i) => {
      f.ordinal = i;
    });
    setLocalFields(next);

    // Persist (single PATCH per moved field; sibling re-ordering follows in
    // separate PATCH calls — small data set, no batching needed).
    update.mutate({
      id: fieldId,
      payload: { section: movedSection, ordinal: movedOrdinal },
    });
  };

  const fieldsBySection = useMemo(() => {
    const buckets: Record<string, EntityFieldDefDto[]> = {
      left: [],
      middle: [],
      right: [],
    };
    for (const field of localFields) {
      if (!showArchived && field.archived) continue;
      const key = field.section ?? "middle";
      if (!buckets[key]) buckets[key] = [];
      buckets[key].push(field);
    }
    for (const key of Object.keys(buckets)) {
      buckets[key].sort((a, b) => a.ordinal - b.ordinal);
    }
    return buckets;
  }, [localFields, showArchived]);

  const isLoading = schemaQuery.isLoading || fieldTypesQuery.isLoading;
  const fieldTypes = fieldTypesQuery.data ?? [];

  if (isLoading) {
    return (
      <div className="container max-w-6xl mx-auto py-8 px-4 flex items-center justify-center min-h-[400px]">
        <Loader2 className="w-8 h-8 text-muted-foreground animate-spin" />
      </div>
    );
  }

  return (
    <div className="container max-w-6xl mx-auto py-8 px-4">
      <div className="mb-6">
        <Link
          href="/settings"
          className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="w-4 h-4" />
          Ustawienia
        </Link>
        <h1 className="text-2xl font-bold text-foreground mt-2">
          Konfiguracja pól
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          Definiuj własne pola na profilu kandydata i rekrutacji bez deploya.
          Przeciągnij i upuść między kolumnami, aby zmienić układ.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3 mb-6">
        <div className="inline-flex rounded-md border border-border bg-card overflow-hidden">
          {ENTITY_OPTIONS.map((opt) => (
            <button
              key={opt.id}
              type="button"
              onClick={() => setEntity(opt.id)}
              className={cn(
                "px-4 py-2 text-sm transition-colors",
                entity === opt.id
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-muted",
              )}
            >
              {opt.label}
            </button>
          ))}
        </div>

        <label className="inline-flex items-center gap-2 text-sm cursor-pointer">
          <input
            type="checkbox"
            checked={showArchived}
            onChange={(e) => setShowArchived(e.target.checked)}
            className="rounded"
          />
          Pokaż zarchiwizowane
        </label>

        <div className="ml-auto">
          {!showAddForm && (
            <button
              type="button"
              onClick={() => setShowAddForm(true)}
              className="inline-flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-md text-sm hover:bg-primary/90"
            >
              <Plus className="w-4 h-4" />
              Dodaj pole
            </button>
          )}
        </div>
      </div>

      {showAddForm && (
        <AddFieldForm
          entity={entity}
          fieldTypes={fieldTypes}
          onCreated={() => setShowAddForm(false)}
          onCancel={() => setShowAddForm(false)}
        />
      )}

      {localFields.length === 0 ? (
        <div className="p-8 text-center bg-muted/30 rounded-xl border border-dashed">
          <Sparkles className="w-8 h-8 text-muted-foreground mx-auto mb-2" />
          <p className="text-sm text-muted-foreground">
            Brak zdefiniowanych pól dla{" "}
            {entity === "candidate" ? "kandydata" : "rekrutacji"}. Dodaj
            pierwsze pole powyżej.
          </p>
        </div>
      ) : (
        <DragDropContext onDragEnd={onDragEnd}>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {SECTIONS.map((s) => (
              <SectionColumn
                key={s.id}
                sectionId={s.id}
                sectionLabel={s.label}
                fields={fieldsBySection[s.id] ?? []}
                entity={entity}
                fieldTypes={fieldTypes}
              />
            ))}
          </div>
        </DragDropContext>
      )}
    </div>
  );
}
