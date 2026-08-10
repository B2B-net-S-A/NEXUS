"use client";

import { useState, useEffect, useCallback } from "react";
import {
  DragDropContext,
  Droppable,
  Draggable,
  DropResult,
} from "@hello-pangea/dnd";
import {
  pipelineTemplatesApi,
  PipelineTemplateSummary,
  PipelineTemplateDetail,
  StageDef,
  RejectionReasonDef,
} from "@/lib/api";
import {
  Plus,
  Copy,
  Archive,
  Trash2,
  GripVertical,
  CheckCircle2,
  AlertCircle,
  Loader2,
  ClipboardList,
  Bell,
} from "lucide-react";
import { ScorecardSchemaBuilder } from "@/components/ScorecardSchemaBuilder";
import { StageNotificationRulesModal } from "@/components/StageNotificationRulesModal";

const CATEGORY_LABELS: Record<string, string> = {
  internal: "Wewnętrzny",
  external: "Zewnętrzny",
  terminal: "Końcowy",
};

const CATEGORY_COLORS: Record<string, string> = {
  internal: "bg-primary/15 text-primary border-primary/30",
  external: "bg-amber-100 text-amber-700 border-amber-300",
  terminal: "bg-slate-100 text-slate-700 border-slate-300",
};

export function PipelineTemplatesTab() {
  const [templates, setTemplates] = useState<PipelineTemplateSummary[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<PipelineTemplateDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [savingOrder, setSavingOrder] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [scorecardEditor, setScorecardEditor] = useState<{
    stageDefId: number;
    stageName: string;
  } | null>(null);
  const [notifEditor, setNotifEditor] = useState<{
    stageDefId: number;
    stageName: string;
  } | null>(null);

  const loadTemplates = useCallback(async () => {
    try {
      const res = await pipelineTemplatesApi.list();
      setTemplates(res.data);
      if (!selectedId && res.data.length > 0) {
        setSelectedId(res.data[0].id);
      }
    } catch (err) {
      setError("Nie udało się pobrać listy procesów.");
      console.error(err);
    }
  }, [selectedId]);

  const loadDetail = useCallback(async (id: number) => {
    setLoading(true);
    try {
      const res = await pipelineTemplatesApi.get(id);
      setDetail(res.data);
    } catch (err) {
      setError("Nie udało się pobrać szczegółów procesu.");
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadTemplates();
  }, [loadTemplates]);

  useEffect(() => {
    if (selectedId !== null) loadDetail(selectedId);
  }, [selectedId, loadDetail]);

  const handleCreate = async () => {
    const name = prompt("Nazwa nowego procesu rekrutacyjnego: ");
    if (!name?.trim()) return;
    try {
      const res = await pipelineTemplatesApi.create({ name: name.trim() });
      await loadTemplates();
      setSelectedId(res.data.id);
    } catch (err: unknown) {
      const message =
        err && typeof err === "object" && "response" in err
          ? ((err as { response?: { data?: { detail?: string } } }).response?.data?.detail ?? "Błąd.")
          : "Błąd.";
      alert(`Nie udało się utworzyć: ${message}`);
    }
  };

  const handleClone = async () => {
    if (!detail) return;
    const name = prompt(`Nazwa nowego procesu (klon z "${detail.name}"):`);
    if (!name?.trim()) return;
    try {
      const res = await pipelineTemplatesApi.clone(detail.id, name.trim());
      await loadTemplates();
      setSelectedId(res.data.id);
    } catch (err: unknown) {
      const message =
        err && typeof err === "object" && "response" in err
          ? ((err as { response?: { data?: { detail?: string } } }).response?.data?.detail ?? "Błąd.")
          : "Błąd.";
      alert(`Nie udało się sklonować: ${message}`);
    }
  };

  const handleArchive = async () => {
    if (!detail) return;
    if (!confirm(`Zarchiwizować proces "${detail.name}"?`)) return;
    try {
      await pipelineTemplatesApi.archive(detail.id);
      setSelectedId(null);
      await loadTemplates();
    } catch (err: unknown) {
      const message =
        err && typeof err === "object" && "response" in err
          ? ((err as { response?: { data?: { detail?: string } } }).response?.data?.detail ?? "Błąd.")
          : "Błąd.";
      alert(`Nie udało się zarchiwizować: ${message}`);
    }
  };

  const handleToggleDefault = async () => {
    if (!detail) return;
    try {
      await pipelineTemplatesApi.update(detail.id, { is_default: !detail.is_default });
      await loadTemplates();
      await loadDetail(detail.id);
    } catch (err: unknown) {
      console.error(err);
      alert("Nie udało się zapisać zmian.");
    }
  };

  const handleAddStage = async () => {
    if (!detail) return;
    const name = prompt("Nazwa nowego etapu: ");
    if (!name?.trim()) return;
    const category =
      (prompt("Kategoria (internal / external / terminal): ", "internal") ?? "").trim() as
        | "internal"
        | "external"
        | "terminal";
    if (!["internal", "external", "terminal"].includes(category)) {
      alert("Nieprawidłowa kategoria.");
      return;
    }
    const maxOrder = Math.max(...detail.stages.map((s) => s.order), -1);
    try {
      await pipelineTemplatesApi.addStage(detail.id, {
        name: name.trim(),
        order: maxOrder + 1,
        category,
        is_terminal: category === "terminal",
        terminal_type: category === "terminal" ? "rejected" : null,
      });
      await loadDetail(detail.id);
      await loadTemplates();
    } catch (err: unknown) {
      const message =
        err && typeof err === "object" && "response" in err
          ? ((err as { response?: { data?: { detail?: string } } }).response?.data?.detail ?? "Błąd.")
          : "Błąd.";
      alert(`Nie udało się dodać etapu: ${message}`);
    }
  };

  const handleDeleteStage = async (stage: StageDef) => {
    if (!detail) return;
    if (!confirm(`Usunąć etap "${stage.name}"?`)) return;
    try {
      await pipelineTemplatesApi.deleteStage(detail.id, stage.id);
      await loadDetail(detail.id);
    } catch (err: unknown) {
      const message =
        err && typeof err === "object" && "response" in err
          ? ((err as { response?: { data?: { detail?: string } } }).response?.data?.detail ?? "Błąd.")
          : "Błąd.";
      alert(`Nie udało się usunąć: ${message}`);
    }
  };

  const handleRenameStage = async (stage: StageDef) => {
    if (!detail) return;
    const name = prompt("Nowa nazwa etapu: ", stage.name);
    if (!name?.trim() || name === stage.name) return;
    try {
      await pipelineTemplatesApi.updateStage(detail.id, stage.id, { name: name.trim() });
      await loadDetail(detail.id);
    } catch (err) {
      console.error(err);
    }
  };

  const handleDragEnd = async (result: DropResult) => {
    if (!detail || !result.destination) return;
    if (result.destination.index === result.source.index) return;

    const reordered = [...detail.stages];
    const [moved] = reordered.splice(result.source.index, 1);
    reordered.splice(result.destination.index, 0, moved);
    const newStages = reordered.map((s, i) => ({ ...s, order: i }));

    setDetail({ ...detail, stages: newStages });
    setSavingOrder(true);
    try {
      await pipelineTemplatesApi.reorderStages(
        detail.id,
        newStages.map((s) => ({ stage_id: s.id, order: s.order }))
      );
    } catch (err) {
      console.error(err);
      alert("Nie udało się zapisać nowej kolejności.");
      await loadDetail(detail.id);
    } finally {
      setSavingOrder(false);
    }
  };

  const handleAddReason = async () => {
    if (!detail) return;
    const name = prompt("Powód (np. Za wysokie oczekiwania): ");
    if (!name?.trim()) return;
    const cat = (prompt("Kategoria (rejected / withdrawn): ", "rejected") ?? "").trim() as
      | "rejected"
      | "withdrawn";
    if (!["rejected", "withdrawn"].includes(cat)) {
      alert("Nieprawidłowa kategoria.");
      return;
    }
    const maxOrder = Math.max(
      ...detail.rejection_reasons.filter((r) => r.category === cat).map((r) => r.order),
      -1
    );
    try {
      await pipelineTemplatesApi.addRejectionReason(detail.id, {
        name: name.trim(),
        category: cat,
        order: maxOrder + 1,
      });
      await loadDetail(detail.id);
    } catch (err: unknown) {
      const message =
        err && typeof err === "object" && "response" in err
          ? ((err as { response?: { data?: { detail?: string } } }).response?.data?.detail ?? "Błąd.")
          : "Błąd.";
      alert(`Nie udało się dodać powodu: ${message}`);
    }
  };

  const handleToggleDisqualifies = async (reason: RejectionReasonDef) => {
    if (!detail) return;
    const next = !reason.disqualifies_person;
    // Turning it ON acts retroactively — every past rejection with this reason
    // starts blocking. Turning it OFF only relaxes, so it needs no confirm.
    if (
      next &&
      !confirm(
        `Włączyć blokadę dla powodu "${reason.name}"?\n\n` +
          "Zadziała wstecz — wszystkie dotychczasowe odrzucenia z tym powodem " +
          "zaczną blokować ponowne zgłoszenie do tego samego hiring managera."
      )
    ) {
      return;
    }
    try {
      await pipelineTemplatesApi.updateRejectionReason(detail.id, reason.id, {
        disqualifies_person: next,
      });
      await loadDetail(detail.id);
    } catch (err) {
      console.error(err);
      alert("Nie udało się zmienić blokady dla tego powodu.");
    }
  };

  const handleDeactivateReason = async (reason: RejectionReasonDef) => {
    if (!detail) return;
    if (!confirm(`Wyłączyć powód "${reason.name}"?`)) return;
    try {
      await pipelineTemplatesApi.deactivateRejectionReason(detail.id, reason.id);
      await loadDetail(detail.id);
    } catch (err) {
      console.error(err);
    }
  };

  return (
    <>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-2xl font-bold text-foreground dark:text-foreground">
            Procesy rekrutacyjne
          </h2>
          <p className="text-sm text-muted-foreground mt-1">
            Zdefiniuj strukturę pipeline&apos;ów używanych w rekrutacjach. Domyślny proces
            zostaje automatycznie przypisany do nowych rekrutacji.
          </p>
        </div>
        <button
          onClick={handleCreate}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-white hover:bg-primary/90 transition"
        >
          <Plus className="w-4 h-4" />
          Dodaj proces
        </button>
      </div>

      {error && (
        <div className="mb-4 flex items-center gap-2 rounded-md bg-destructive/10 border border-destructive/20 px-3 py-2 text-sm text-destructive">
          <AlertCircle className="w-4 h-4" /> {error}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
        <aside className="bg-card dark:bg-muted rounded-lg border border-border dark:border-border p-3">
          <h3 className="text-sm font-medium text-foreground dark:text-muted-foreground uppercase tracking-wide mb-2">
            Lista procesów
          </h3>
          <ul className="space-y-1">
            {templates.map((t) => (
              <li key={t.id}>
                <button
                  onClick={() => setSelectedId(t.id)}
                  className={`w-full text-left rounded-md px-3 py-2 text-sm transition ${
                    selectedId === t.id
                      ? "bg-primary/10 dark:bg-primary/30 text-primary dark:text-primary font-medium"
                      : "hover:bg-muted dark:hover:bg-muted/50 text-foreground dark:text-muted-foreground"
                  }`}
                  data-testid={`template-item-${t.id}`}
                >
                  <div className="flex items-center justify-between">
                    <span>{t.name}</span>
                    {t.is_default && (
                      <span className="flex items-center gap-0.5 text-xs text-green-600">
                        <CheckCircle2 className="w-3 h-3" />
                      </span>
                    )}
                  </div>
                  <div className="text-xs text-muted-foreground mt-0.5">
                    {t.stage_count} etapów
                  </div>
                </button>
              </li>
            ))}
            {templates.length === 0 && (
              <li className="text-sm text-muted-foreground px-3 py-2">Brak procesów</li>
            )}
          </ul>
        </aside>

        <main className="md:col-span-3">
          {loading && (
            <div className="bg-card dark:bg-muted rounded-lg p-8 flex justify-center">
              <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
            </div>
          )}
          {!loading && detail && (
            <div className="space-y-6">
              <div className="bg-card dark:bg-muted rounded-lg border border-border dark:border-border p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-lg font-semibold">{detail.name}</h3>
                    <p className="text-sm text-muted-foreground mt-1">
                      {detail.description ?? "Brak opisu."}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={detail.is_default}
                        onChange={handleToggleDefault}
                        className="rounded"
                      />
                      Domyślny proces
                    </label>
                    <button
                      onClick={handleClone}
                      className="flex items-center gap-1 px-3 py-1.5 rounded-md border border-border dark:border-border text-sm hover:bg-muted dark:hover:bg-muted"
                      title="Klonuj"
                    >
                      <Copy className="w-4 h-4" />
                      Klonuj
                    </button>
                    {!detail.is_default && (
                      <button
                        onClick={handleArchive}
                        className="flex items-center gap-1 px-3 py-1.5 rounded-md border border-red-300 text-sm text-destructive hover:bg-destructive/10"
                        title="Archiwizuj"
                      >
                        <Archive className="w-4 h-4" />
                        Archiwizuj
                      </button>
                    )}
                  </div>
                </div>
              </div>

              <div className="bg-card dark:bg-muted rounded-lg border border-border dark:border-border p-4">
                <div className="flex items-center justify-between mb-3">
                  <h3 className="font-medium">Etapy ({detail.stages.length})</h3>
                  <div className="flex items-center gap-2">
                    {savingOrder && (
                      <span className="text-xs text-muted-foreground flex items-center gap-1">
                        <Loader2 className="w-3 h-3 animate-spin" /> Zapis…
                      </span>
                    )}
                    <button
                      onClick={handleAddStage}
                      className="flex items-center gap-1 px-3 py-1.5 rounded-md bg-primary text-white text-sm hover:bg-primary/90"
                      data-testid="add-stage"
                    >
                      <Plus className="w-4 h-4" />
                      Dodaj etap
                    </button>
                  </div>
                </div>

                <DragDropContext onDragEnd={handleDragEnd}>
                  <Droppable droppableId="stages">
                    {(provided) => (
                      <ul
                        ref={provided.innerRef}
                        {...provided.droppableProps}
                        className="space-y-1.5"
                      >
                        {detail.stages.map((stage, idx) => (
                          <Draggable
                            key={stage.id}
                            draggableId={String(stage.id)}
                            index={idx}
                          >
                            {(p) => (
                              <li
                                ref={p.innerRef}
                                {...p.draggableProps}
                                className="flex items-center gap-3 rounded-md border border-border dark:border-border bg-muted dark:bg-card/40 px-3 py-2"
                                data-testid={`stage-${stage.id}`}
                              >
                                <span {...p.dragHandleProps} className="cursor-grab text-muted-foreground">
                                  <GripVertical className="w-4 h-4" />
                                </span>
                                <span className="font-mono text-xs text-muted-foreground w-6 text-right">
                                  {idx + 1}
                                </span>
                                <span className="font-medium text-sm flex-1">
                                  {stage.name}
                                </span>
                                <span
                                  className={`text-xs px-2 py-0.5 rounded-full border ${CATEGORY_COLORS[stage.category]}`}
                                >
                                  {CATEGORY_LABELS[stage.category]}
                                  {stage.terminal_type ? ` · ${stage.terminal_type}` : ""}
                                </span>
                                <button
                                  onClick={() =>
                                    setScorecardEditor({
                                      stageDefId: stage.id,
                                      stageName: stage.name,
                                    })
                                  }
                                  title="Edytuj scorecard etapu"
                                  className={`text-xs flex items-center gap-1 px-2 py-0.5 rounded transition-colors ${
                                    stage.scorecard_schema &&
                                    Array.isArray(stage.scorecard_schema.questions) &&
                                    stage.scorecard_schema.questions.length > 0
                                      ? "text-primary hover:bg-primary/10 dark:hover:bg-primary/30"
                                      : "text-muted-foreground hover:text-foreground dark:hover:text-muted-foreground"
                                  }`}
                                >
                                  <ClipboardList className="w-3.5 h-3.5" />
                                  Scorecard
                                  {stage.scorecard_schema &&
                                    Array.isArray(stage.scorecard_schema.questions) &&
                                    stage.scorecard_schema.questions.length > 0 && (
                                      <span className="text-[10px] bg-primary/15 text-primary px-1.5 py-0.5 rounded-full">
                                        {stage.scorecard_schema.questions.length}
                                      </span>
                                    )}
                                </button>
                                <button
                                  onClick={() =>
                                    setNotifEditor({
                                      stageDefId: stage.id,
                                      stageName: stage.name,
                                    })
                                  }
                                  title="Konfiguruj powiadomienia dla etapu"
                                  className="text-xs flex items-center gap-1 px-2 py-0.5 rounded text-muted-foreground hover:bg-primary/10 dark:hover:bg-primary/30 hover:text-primary transition-colors"
                                >
                                  <Bell className="w-3.5 h-3.5" />
                                  Powiadomienia
                                </button>
                                <button
                                  onClick={() => handleRenameStage(stage)}
                                  className="text-xs text-muted-foreground hover:text-foreground dark:hover:text-muted-foreground"
                                >
                                  Zmień nazwę
                                </button>
                                <button
                                  onClick={() => handleDeleteStage(stage)}
                                  disabled={stage.is_terminal}
                                  title={
                                    stage.is_terminal
                                      ? "Nie można usunąć etapu końcowego"
                                      : "Usuń etap"
                                  }
                                  className="text-red-400 hover:text-destructive disabled:opacity-30 disabled:cursor-not-allowed"
                                >
                                  <Trash2 className="w-4 h-4" />
                                </button>
                              </li>
                            )}
                          </Draggable>
                        ))}
                        {provided.placeholder}
                      </ul>
                    )}
                  </Droppable>
                </DragDropContext>
              </div>

              <div className="bg-card dark:bg-muted rounded-lg border border-border dark:border-border p-4">
                <div className="flex items-center justify-between mb-3">
                  <h3 className="font-medium">Powody odrzucenia / wycofania</h3>
                  <button
                    onClick={handleAddReason}
                    className="flex items-center gap-1 px-3 py-1.5 rounded-md bg-primary text-white text-sm hover:bg-primary/90"
                  >
                    <Plus className="w-4 h-4" />
                    Dodaj powód
                  </button>
                </div>

                <p className="text-xs text-muted-foreground mb-3">
                  <span className="font-medium">„Blokuje u tego managera"</span> —
                  po odrzuceniu z tym powodem kandydat nie zostanie ponownie dodany
                  do żadnej rekrutacji prowadzonej przez tego samego hiring managera.
                  Blokada jest bezterminowa; kandydat pozostaje widoczny na listach.
                  Zaznaczaj powody będące oceną osoby (np. „Nie spełnia wymagań
                  technicznych"), a nie sytuacyjne (np. „Za wysokie oczekiwania
                  finansowe").
                </p>

                {(["rejected", "withdrawn"] as const).map((cat) => {
                  const reasons = detail.rejection_reasons.filter(
                    (r) => r.category === cat
                  );
                  if (reasons.length === 0) return null;
                  return (
                    <div key={cat} className="mb-3">
                      <h4 className="text-xs uppercase tracking-wider text-muted-foreground mb-1">
                        {cat === "rejected" ? "Odrzucony" : "Wycofany"}
                      </h4>
                      <ul className="space-y-1">
                        {reasons.map((r) => (
                          <li
                            key={r.id}
                            className="flex items-center justify-between rounded-md border border-border dark:border-border bg-muted dark:bg-card/40 px-3 py-1.5 text-sm"
                          >
                            <span>{r.name}</span>
                            <div className="flex items-center gap-3">
                              <label
                                className={`flex items-center gap-1.5 text-xs ${
                                  cat === "rejected"
                                    ? "cursor-pointer text-muted-foreground"
                                    : "cursor-not-allowed text-muted-foreground/50"
                                }`}
                                title={
                                  cat === "rejected"
                                    ? "Blokuje ponowne zgłoszenie do tego hiring managera"
                                    : "Wycofanie to decyzja kandydata, nie werdykt managera"
                                }
                              >
                                <input
                                  type="checkbox"
                                  checked={r.disqualifies_person}
                                  disabled={cat !== "rejected"}
                                  onChange={() => handleToggleDisqualifies(r)}
                                  className="h-3.5 w-3.5 rounded border-border accent-primary disabled:opacity-40"
                                  aria-label={`Blokuje ponowne zgłoszenie do tego hiring managera: ${r.name}`}
                                />
                                Blokuje u tego managera
                              </label>
                              <button
                                onClick={() => handleDeactivateReason(r)}
                                className="text-red-400 hover:text-destructive text-xs"
                              >
                                Wyłącz
                              </button>
                            </div>
                          </li>
                        ))}
                      </ul>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
          {!loading && !detail && (
            <div className="bg-card dark:bg-muted rounded-lg border border-border dark:border-border p-8 text-center text-muted-foreground">
              Wybierz proces z listy po lewej lub utwórz nowy.
            </div>
          )}
        </main>
      </div>

      {scorecardEditor && (
        <ScorecardSchemaBuilder
          stageDefId={scorecardEditor.stageDefId}
          stageName={scorecardEditor.stageName}
          onClose={() => setScorecardEditor(null)}
          onSaved={() => {
            setScorecardEditor(null);
            if (selectedId) {
              void loadDetail(selectedId);
            }
          }}
        />
      )}
      {notifEditor && selectedId !== null && (
        <StageNotificationRulesModal
          templateId={selectedId}
          stageDefId={notifEditor.stageDefId}
          stageName={notifEditor.stageName}
          onClose={() => setNotifEditor(null)}
        />
      )}
    </>
  );
}

export default PipelineTemplatesTab;
