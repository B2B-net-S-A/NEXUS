"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Card,
  CardTitle,
  CardDescription,
  Badge,
  Button,
  Input,
  Textarea,
  Label,
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from "@/components/ui";
import {
  interviewQuestionsApi,
  type InterviewQuestion,
  type JobQuestionLink,
  type InterviewQuestionSeniority,
  type InterviewQuestionTypeLiteral,
} from "@/lib/api";

const SENIORITY_OPTIONS: { value: InterviewQuestionSeniority; label: string }[] =
  [
    { value: "junior", label: "Junior" },
    { value: "mid", label: "Mid" },
    { value: "senior", label: "Senior" },
    { value: "lead", label: "Lead" },
    { value: "architect", label: "Architect" },
  ];

const TYPE_OPTIONS: {
  value: InterviewQuestionTypeLiteral;
  label: string;
}[] = [
  { value: "technical", label: "Techniczne" },
  { value: "behavioral", label: "Behawioralne" },
  { value: "motivation", label: "Motywacja" },
  { value: "experience", label: "Doświadczenie" },
];

interface QuestionBankTabProps {
  jobId: number;
  clientId: number | null;
}

export function QuestionBankTab({ jobId, clientId }: QuestionBankTabProps) {
  const [pinned, setPinned] = useState<JobQuestionLink[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [showCreate, setShowCreate] = useState(false);
  const [showSearch, setShowSearch] = useState(false);

  const loadPinned = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await interviewQuestionsApi.listForJob(jobId);
      setPinned(res.data);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Błąd wczytywania pytań";
      setError(message);
    } finally {
      setLoading(false);
    }
  }, [jobId]);

  useEffect(() => {
    void loadPinned();
  }, [loadPinned]);

  const handleUnpin = async (questionId: number) => {
    try {
      await interviewQuestionsApi.unpinFromJob(jobId, questionId);
      await loadPinned();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Błąd odpięcia";
      setError(message);
    }
  };

  const handleMove = async (questionId: number, direction: "up" | "down") => {
    const idx = pinned.findIndex((p) => p.question.id === questionId);
    if (idx === -1) return;
    const swap = direction === "up" ? idx - 1 : idx + 1;
    if (swap < 0 || swap >= pinned.length) return;

    const a = pinned[idx];
    const b = pinned[swap];
    try {
      await interviewQuestionsApi.reorder(jobId, [
        { question_id: a.question.id, order_index: b.order_index },
        { question_id: b.question.id, order_index: a.order_index },
      ]);
      await loadPinned();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Błąd zmiany kolejności";
      setError(message);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-[hsl(var(--text-title))]">
            Baza pytań projektu
          </h2>
          <CardDescription>
            Pytania przypięte tutaj zostaną użyte w prep-kicie dla każdego
            kandydata na ten projekt. Dodatkowo prep-kit automatycznie
            proponuje pytania z podobnych projektów.
          </CardDescription>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowSearch(true)}
          >
            🔎 Z bazy
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={() => setShowCreate(true)}
          >
            + Dodaj pytanie
          </Button>
        </div>
      </div>

      {error && (
        <Card variant="default" size="sm" className="border-red-200">
          <p className="text-sm text-red-700">{error}</p>
        </Card>
      )}

      {loading && <CardDescription>Wczytywanie pytań…</CardDescription>}

      {!loading && pinned.length === 0 && (
        <Card variant="default" size="md">
          <CardDescription>
            Brak przypiętych pytań. Dodaj pierwsze albo wyszukaj w globalnej bazie.
          </CardDescription>
        </Card>
      )}

      <ul className="grid gap-2">
        {pinned.map((link, idx) => (
          <li key={link.id}>
            <Card variant="default" size="sm">
              <div className="flex items-start gap-3">
                <div className="flex flex-col gap-1 shrink-0">
                  <button
                    type="button"
                    aria-label="Przesuń w górę"
                    onClick={() => handleMove(link.question.id, "up")}
                    disabled={idx === 0}
                    className="px-1.5 py-0.5 text-xs rounded hover:bg-[hsl(var(--border-subtle))] disabled:opacity-40"
                  >
                    ▲
                  </button>
                  <button
                    type="button"
                    aria-label="Przesuń w dół"
                    onClick={() => handleMove(link.question.id, "down")}
                    disabled={idx === pinned.length - 1}
                    className="px-1.5 py-0.5 text-xs rounded hover:bg-[hsl(var(--border-subtle))] disabled:opacity-40"
                  >
                    ▼
                  </button>
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex flex-wrap items-center gap-1.5 mb-1">
                    <Badge variant="success" size="sm">
                      przypięte
                    </Badge>
                    {link.question.question_type && (
                      <Badge variant="outline" size="sm">
                        {TYPE_OPTIONS.find(
                          (o) => o.value === link.question.question_type,
                        )?.label ?? link.question.question_type}
                      </Badge>
                    )}
                    {link.question.seniority && (
                      <Badge variant="neutral" size="sm">
                        {link.question.seniority}
                      </Badge>
                    )}
                    {link.question.deal_breaker && (
                      <Badge variant="danger" size="sm">
                        deal-breaker
                      </Badge>
                    )}
                    {link.question.client_id !== null && (
                      <Badge variant="warning" size="sm">
                        client-scoped
                      </Badge>
                    )}
                    {(link.question.up_votes > 0 || link.question.down_votes > 0) && (
                      <span className="text-xs text-[hsl(var(--text-muted))]">
                        👍 {link.question.up_votes} · 👎 {link.question.down_votes}
                      </span>
                    )}
                  </div>
                  <p className="text-[hsl(var(--text-body))]">
                    {link.question.text}
                  </p>
                  {link.question.ideal_answer && (
                    <p className="mt-2 text-sm text-[hsl(var(--text-muted))]">
                      <span className="font-medium">Idealna odpowiedź:</span>{" "}
                      {link.question.ideal_answer}
                    </p>
                  )}
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => handleUnpin(link.question.id)}
                >
                  Odepnij
                </Button>
              </div>
            </Card>
          </li>
        ))}
      </ul>

      {showCreate && (
        <CreateQuestionDialog
          jobId={jobId}
          clientId={clientId}
          onClose={() => setShowCreate(false)}
          onCreated={async () => {
            setShowCreate(false);
            await loadPinned();
          }}
        />
      )}

      {showSearch && (
        <SearchGlobalQuestionsDialog
          jobId={jobId}
          clientId={clientId}
          onClose={() => setShowSearch(false)}
          onPinned={async () => {
            setShowSearch(false);
            await loadPinned();
          }}
        />
      )}
    </div>
  );
}

// ─── Create dialog ───────────────────────────────────────────────────────────

interface CreateQuestionDialogProps {
  jobId: number;
  clientId: number | null;
  onClose: () => void;
  onCreated: () => void;
}

function CreateQuestionDialog({
  jobId,
  clientId,
  onClose,
  onCreated,
}: CreateQuestionDialogProps) {
  const [text, setText] = useState("");
  const [idealAnswer, setIdealAnswer] = useState("");
  const [dealBreaker, setDealBreaker] = useState(false);
  const [seniority, setSeniority] =
    useState<InterviewQuestionSeniority | "">("");
  const [qType, setQType] = useState<InterviewQuestionTypeLiteral | "">("");
  const [scope, setScope] = useState<"client" | "global">("client");
  const [tagsInput, setTagsInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const handleSubmit = async () => {
    if (!text.trim() || text.trim().length < 3) {
      setErr("Treść pytania musi mieć min. 3 znaki");
      return;
    }
    setSaving(true);
    setErr(null);
    const skillTags = tagsInput
      .split(",")
      .map((t) => t.trim().toLowerCase())
      .filter(Boolean);
    try {
      await interviewQuestionsApi.create({
        text: text.trim(),
        ideal_answer: idealAnswer.trim() || null,
        deal_breaker: dealBreaker,
        seniority: seniority || null,
        question_type: qType || null,
        skill_tags: skillTags,
        client_id: scope === "client" ? clientId : null,
        job_id: jobId,
      });
      onCreated();
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Błąd zapisu";
      setErr(msg);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Nowe pytanie</DialogTitle>
        </DialogHeader>

        <div className="grid gap-4">
          <div>
            <Label htmlFor="q-text">Treść pytania *</Label>
            <Textarea
              id="q-text"
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="np. Jak zaimplementowałbyś idempotentny endpoint?"
              rows={3}
            />
          </div>

          <div>
            <Label htmlFor="q-ideal">Idealna odpowiedź (opcjonalnie)</Label>
            <Textarea
              id="q-ideal"
              value={idealAnswer}
              onChange={(e) => setIdealAnswer(e.target.value)}
              rows={2}
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>Typ pytania</Label>
              <Select
                value={qType}
                onValueChange={(v) =>
                  setQType(v as InterviewQuestionTypeLiteral | "")
                }
              >
                <SelectTrigger>
                  <SelectValue placeholder="— wybierz —" />
                </SelectTrigger>
                <SelectContent>
                  {TYPE_OPTIONS.map((o) => (
                    <SelectItem key={o.value} value={o.value}>
                      {o.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label>Seniority</Label>
              <Select
                value={seniority}
                onValueChange={(v) =>
                  setSeniority(v as InterviewQuestionSeniority | "")
                }
              >
                <SelectTrigger>
                  <SelectValue placeholder="— dowolne —" />
                </SelectTrigger>
                <SelectContent>
                  {SENIORITY_OPTIONS.map((o) => (
                    <SelectItem key={o.value} value={o.value}>
                      {o.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div>
            <Label htmlFor="q-tags">
              Skill tags (oddzielone przecinkami)
            </Label>
            <Input
              id="q-tags"
              value={tagsInput}
              onChange={(e) => setTagsInput(e.target.value)}
              placeholder="python, async, fastapi"
            />
          </div>

          <div className="flex items-center gap-4 flex-wrap">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={dealBreaker}
                onChange={(e) => setDealBreaker(e.target.checked)}
              />
              Deal-breaker
            </label>

            <div className="flex items-center gap-3 text-sm">
              <span>Zakres:</span>
              <label className="flex items-center gap-1">
                <input
                  type="radio"
                  name="scope"
                  checked={scope === "client"}
                  onChange={() => setScope("client")}
                  disabled={clientId === null}
                />
                Ten klient{clientId === null && " (brak klienta)"}
              </label>
              <label className="flex items-center gap-1">
                <input
                  type="radio"
                  name="scope"
                  checked={scope === "global"}
                  onChange={() => setScope("global")}
                />
                Globalne
              </label>
            </div>
          </div>

          {err && <p className="text-sm text-red-600">{err}</p>}
        </div>

        <DialogFooter>
          <Button variant="ghost" size="sm" onClick={onClose}>
            Anuluj
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={handleSubmit}
            disabled={saving}
          >
            {saving ? "Zapisuję..." : "Dodaj i przypnij"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ─── Search dialog (z globalnej bazy) ────────────────────────────────────────

interface SearchDialogProps {
  jobId: number;
  clientId: number | null;
  onClose: () => void;
  onPinned: () => void;
}

function SearchGlobalQuestionsDialog({
  jobId,
  clientId,
  onClose,
  onPinned,
}: SearchDialogProps) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<InterviewQuestion[]>([]);
  const [searching, setSearching] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const handleSearch = async () => {
    setSearching(true);
    setErr(null);
    try {
      const res = await interviewQuestionsApi.list({
        q: query.trim() || undefined,
        limit: 50,
      });
      // Tenant safety: filtruj pytania innego klienta po stronie UI
      const safe = res.data.filter(
        (q) => q.client_id === null || q.client_id === clientId,
      );
      setResults(safe);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Błąd wyszukiwania";
      setErr(msg);
    } finally {
      setSearching(false);
    }
  };

  const handlePin = async (qid: number) => {
    try {
      await interviewQuestionsApi.pinToJob(jobId, { question_id: qid });
      onPinned();
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Błąd przypięcia";
      setErr(msg);
    }
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>Wyszukaj pytania w bazie</DialogTitle>
        </DialogHeader>

        <div className="flex gap-2">
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Wpisz frazę (lub pozostaw puste by zobaczyć ostatnie)"
            onKeyDown={(e) => {
              if (e.key === "Enter") void handleSearch();
            }}
          />
          <Button variant="primary" size="sm" onClick={handleSearch}>
            Szukaj
          </Button>
        </div>

        {err && <p className="text-sm text-red-600 mt-2">{err}</p>}
        {searching && <CardDescription>Wyszukiwanie…</CardDescription>}

        <div className="max-h-[50vh] overflow-y-auto grid gap-2 mt-2">
          {results.map((q) => (
            <Card key={q.id} variant="default" size="sm">
              <div className="flex items-start justify-between gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex flex-wrap items-center gap-1.5 mb-1">
                    {q.question_type && (
                      <Badge variant="outline" size="sm">
                        {q.question_type}
                      </Badge>
                    )}
                    {q.seniority && (
                      <Badge variant="neutral" size="sm">
                        {q.seniority}
                      </Badge>
                    )}
                    {q.client_id !== null && (
                      <Badge variant="warning" size="sm">
                        client #{q.client_id}
                      </Badge>
                    )}
                    {q.client_id === null && (
                      <Badge variant="info" size="sm">
                        globalne
                      </Badge>
                    )}
                  </div>
                  <p className="text-[hsl(var(--text-body))]">{q.text}</p>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => handlePin(q.id)}
                >
                  Przypnij
                </Button>
              </div>
            </Card>
          ))}
          {!searching && results.length === 0 && (
            <CardDescription>
              Brak wyników. Spróbuj innej frazy.
            </CardDescription>
          )}
        </div>

        <DialogFooter>
          <Button variant="ghost" size="sm" onClick={onClose}>
            Zamknij
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
