"use client";

/**
 * Czarna lista (decyzja Artura 17.10.2026). Rekruterzy pytali, jak oznaczyć
 * osobę, z którą nie współpracujemy: status „Zablokowany” siedział w długim
 * „Edytuj dane” (bez powodu i autora), a czarna lista u klienta w „Konfliktach
 * i wetach” (tylko Delivery Lead i admin). Nikt z tego nie korzystał — wiedza
 * żyła w notatkach. Teraz jedno okno „Czarna lista…” w menu profilu i w panelu
 * osoby na Tablicy:
 *
 * - „U nas” — `status = blacklisted`: osoba znika z wyszukiwania pod
 *   rekrutację i nie da się jej dodać do rekrutacji (blokada serwera),
 * - „U klienta” — konflikt `blacklist` z klientem: ostrzeżenie z powodem
 *   przy rekrutacjach tego klienta, nic nie blokuje.
 *
 * Powód jest wymagany (serwer: 5–2000 znaków). Zdjąć czarną listę „u nas”
 * mogą admin, Delivery Lead i Head of Recruitment — też z powodem.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { Ban } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
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
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import { formatWarsawDay } from "@/lib/added-to-base";
import {
  candidatesApi,
  phase5Api,
  type CandidateBlacklistInfo,
  type CandidateBlacklistScope,
} from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { conflictKeys } from "@/lib/conflicts";
import { cn } from "@/lib/utils";
import { hasRole, useAuthStore } from "@/store/auth";

/** Minimalna długość powodu po przycięciu — lustro walidacji serwera. */
export const BLACKLIST_REASON_MIN = 5;
const BLACKLIST_REASON_MAX = 2000;

export const BLACKLIST_REMOVE_ROLES_HINT =
  "Zdjąć czarną listę „u nas” może Delivery Lead, Head of Recruitment albo admin — też z powodem.";

const PRE_RULE_REASON = "Powód nie został zapisany (wpis sprzed 17.10.2026).";

const FIELD_CLASS =
  "w-full rounded-md border border-border bg-card px-2 py-1.5 text-sm text-foreground focus:outline-hidden focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60";

/** Kody odmów serwera z ustrukturyzowanym `detail` (bez `message`). */
const BLACKLIST_ERROR_CODES: Record<string, string> = {
  already_blacklisted: "Osoba jest już na czarnej liście u nas.",
  not_blacklisted: "Osoba nie jest już na czarnej liście u nas — odśwież profil.",
};

function blacklistErrorMessage(error: unknown, fallback: string): string {
  const detail = (error as { response?: { data?: { detail?: unknown } } } | null)?.response
    ?.data?.detail;
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const code = (detail as { code?: unknown }).code;
    if (typeof code === "string" && BLACKLIST_ERROR_CODES[code]) return BLACKLIST_ERROR_CODES[code];
  }
  return apiErrorMessage(error, fallback);
}

function errorStatus(error: unknown): number | undefined {
  const status = (error as { response?: { status?: unknown } } | null)?.response?.status;
  return typeof status === "number" ? status : undefined;
}

export function isBlacklistReasonValid(reason: string): boolean {
  return reason.trim().length >= BLACKLIST_REASON_MIN;
}

/**
 * Zdjęcie czarnej listy „u nas” — lustro bramki serwera (admin, Delivery Lead,
 * Head of Recruitment). Podgląd cudzego konta niczego nie zapisuje.
 */
export function canRemoveBlacklist(
  user: Parameters<typeof hasRole>[0],
  isImpersonating: boolean,
): boolean {
  return !isImpersonating && hasRole(user, "admin", "delivery_lead", "head_of_recruitment");
}

/** „Od 17.10.2026 · dodał(a) Anna Nowak” — bez członów, których nie znamy. */
export function blacklistMetaLine(info: CandidateBlacklistInfo | null | undefined): string | null {
  const since = formatWarsawDay(info?.since ?? null);
  const by = info?.by_name?.trim() || null;
  const parts = [since ? `Od ${since}` : null, by ? `dodał(a) ${by}` : null].filter(Boolean);
  return parts.length > 0 ? parts.join(" · ") : null;
}

/** „Powód: …” albo zdanie o wpisie sprzed 17.10.2026 (wszystkie pola puste). */
export function blacklistReasonLine(info: CandidateBlacklistInfo | null | undefined): string {
  const reason = info?.reason?.trim();
  return reason ? `Powód: ${reason}` : PRE_RULE_REASON;
}

/**
 * Po zapisie odświeżamy wszystko, co pokazuje czarną listę: profil i panel
 * osoby (ten sam klucz), podgląd z listy, listę kandydatów, konflikty
 * (czarna lista u klienta) i oś czasu (nowy wpis aktywności).
 */
function invalidateBlacklistQueries(queryClient: QueryClient, candidateId: number): void {
  for (const queryKey of [
    candidateQueryKeys.detail(candidateId),
    candidateQueryKeys.quickView(candidateId),
    candidateQueryKeys.timelineRoot(candidateId),
    ["candidates-v2"],
    conflictKeys.all,
  ]) {
    void queryClient.invalidateQueries({ queryKey });
  }
}

interface BlacklistDialogBaseProps {
  candidateId: number;
  candidateName: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Po udanym zapisie (zapytania są już unieważnione). */
  onDone?: () => void;
}

// ── „Czarna lista…” ───────────────────────────────────────────────────────

export interface BlacklistDialogProps extends BlacklistDialogBaseProps {
  /** Osoba jest już na czarnej liście „u nas” — zostaje tylko „U klienta”. */
  alreadyBlacklisted?: boolean;
}

export function BlacklistDialog({ open, onOpenChange, ...props }: BlacklistDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="md" aria-describedby="blacklist-dialog-description">
        {/* Treść montuje się przy każdym otwarciu — formularz startuje pusty. */}
        <BlacklistForm {...props} onOpenChange={onOpenChange} />
      </DialogContent>
    </Dialog>
  );
}

function BlacklistForm({
  candidateId,
  candidateName,
  onOpenChange,
  onDone,
  alreadyBlacklisted = false,
}: Omit<BlacklistDialogProps, "open">) {
  const queryClient = useQueryClient();
  const { showSuccess } = useToast();
  const [scope, setScope] = useState<CandidateBlacklistScope>(
    alreadyBlacklisted ? "client" : "global",
  );
  const [clientId, setClientId] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  // Ta sama lista klientów i klucz co formularz konfliktów (`ConflictsWidget`).
  const clientsQuery = useQuery({
    queryKey: ["clients-lookup"],
    queryFn: () => phase5Api.clientsLookup().then((r) => r.data),
    staleTime: 5 * 60_000,
  });
  const clients = clientsQuery.data ?? [];

  const mutation = useMutation({
    mutationFn: () =>
      candidatesApi.addToBlacklist(candidateId, {
        scope,
        client_id: scope === "client" ? Number(clientId) : null,
        reason: reason.trim(),
      }),
    onSuccess: () => {
      const clientName = clients.find((c) => String(c.id) === clientId)?.name;
      showSuccess(
        scope === "client" && clientName
          ? `Dodano do czarnej listy u klienta ${clientName}`
          : "Dodano do czarnej listy",
      );
      invalidateBlacklistQueries(queryClient, candidateId);
      onDone?.();
      onOpenChange(false);
    },
    onError: (err) => {
      const fallback =
        scope === "client" && errorStatus(err) === 409
          ? "Ta osoba jest już na czarnej liście u tego klienta."
          : "Nie udało się dodać do czarnej listy.";
      setError(blacklistErrorMessage(err, fallback));
    },
  });

  const reasonLength = reason.trim().length;
  const canSubmit =
    isBlacklistReasonValid(reason) &&
    (scope === "global" ? !alreadyBlacklisted : clientId !== "") &&
    !mutation.isPending;

  const choose = (next: CandidateBlacklistScope) => {
    setScope(next);
    setError(null);
  };

  return (
    <>
      <DialogHeader>
        <DialogTitle>Czarna lista — {candidateName}</DialogTitle>
        <DialogDescription id="blacklist-dialog-description">
          Wybierz, gdzie nie współpracujemy z tą osobą.
        </DialogDescription>
      </DialogHeader>
      <DialogBody className="space-y-4">
        <fieldset className="space-y-2">
          <legend className="sr-only">Gdzie nie współpracujemy</legend>
          <div
            className={cn(
              "rounded-lg border px-3 py-2.5",
              scope === "global" ? "border-primary bg-primary/5" : "border-border",
              alreadyBlacklisted && "opacity-70",
            )}
          >
            <label className="flex cursor-pointer items-start gap-2 text-sm font-semibold text-foreground has-[:disabled]:cursor-not-allowed">
              <input
                type="radio"
                name={`blacklist-scope-${candidateId}`}
                value="global"
                checked={scope === "global"}
                disabled={alreadyBlacklisted}
                onChange={() => choose("global")}
                aria-describedby={`blacklist-global-hint-${candidateId}`}
                className="mt-0.5 accent-[hsl(var(--primary))]"
              />
              U nas — nie współpracujemy z tą osobą
            </label>
            <p id={`blacklist-global-hint-${candidateId}`} className="mt-1 pl-6 text-xs text-muted-foreground">
              {alreadyBlacklisted
                ? "Osoba jest już na czarnej liście u nas."
                : "Znika z wyszukiwania pod rekrutację i nie da się jej dodać do żadnej rekrutacji."}
            </p>
          </div>

          <div
            className={cn(
              "rounded-lg border px-3 py-2.5",
              scope === "client" ? "border-primary bg-primary/5" : "border-border",
            )}
          >
            <label className="flex cursor-pointer items-start gap-2 text-sm font-semibold text-foreground">
              <input
                type="radio"
                name={`blacklist-scope-${candidateId}`}
                value="client"
                checked={scope === "client"}
                onChange={() => choose("client")}
                aria-describedby={`blacklist-client-hint-${candidateId}`}
                className="mt-0.5 accent-[hsl(var(--primary))]"
              />
              U klienta — nie proponować do:
            </label>
            <div className="mt-1.5 pl-6">
              {/* Wybór klienta sam przełącza na „U klienta”. Select stoi poza
                  etykietą radia, bo klik w listę nie może przełączać radia. */}
              <select
                aria-label="Klient"
                value={clientId}
                onChange={(e) => {
                  setClientId(e.target.value);
                  if (e.target.value) choose("client");
                }}
                className={FIELD_CLASS}
              >
                <option value="">
                  {clientsQuery.isPending ? "Wczytywanie klientów…" : "— wybierz klienta —"}
                </option>
                {clients.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
              {clientsQuery.isError ? (
                <p role="alert" className="mt-1 text-[13px] text-destructive">
                  {apiErrorMessage(clientsQuery.error, "Nie udało się wczytać listy klientów.")}
                </p>
              ) : null}
              <p id={`blacklist-client-hint-${candidateId}`} className="mt-1 text-xs text-muted-foreground">
                Ostrzeżenie z powodem przy rekrutacjach tego klienta. Nic nie blokuje.
              </p>
            </div>
          </div>
        </fieldset>

        <div>
          <label
            htmlFor={`blacklist-reason-${candidateId}`}
            className="mb-1 block text-xs font-semibold text-muted-foreground"
          >
            Powód
          </label>
          <textarea
            id={`blacklist-reason-${candidateId}`}
            rows={3}
            required
            maxLength={BLACKLIST_REASON_MAX}
            value={reason}
            onChange={(e) => {
              setReason(e.target.value);
              setError(null);
            }}
            placeholder="np. zrezygnował dzień przed startem u klienta, 03.2026"
            className={cn(FIELD_CLASS, "resize-y")}
          />
          {reasonLength > 0 && reasonLength < BLACKLIST_REASON_MIN ? (
            <p className="mt-1 text-xs text-muted-foreground">Powód — co najmniej 5 znaków.</p>
          ) : null}
        </div>

        <p className="text-xs text-muted-foreground">{BLACKLIST_REMOVE_ROLES_HINT}</p>

        {error ? (
          <p role="alert" className="rounded-md bg-destructive-muted px-3 py-2 text-sm text-destructive-muted-foreground">
            {error}
          </p>
        ) : null}
      </DialogBody>
      <DialogFooter>
        <Button variant="outline" onClick={() => onOpenChange(false)} disabled={mutation.isPending}>
          Anuluj
        </Button>
        <Button
          variant="destructive"
          disabled={!canSubmit}
          loading={mutation.isPending}
          onClick={() => {
            setError(null);
            mutation.mutate();
          }}
        >
          Dodaj do czarnej listy
        </Button>
      </DialogFooter>
    </>
  );
}

// ── „Zdejmij z czarnej listy” ─────────────────────────────────────────────

export function BlacklistRemoveDialog({ open, onOpenChange, ...props }: BlacklistDialogBaseProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="md" aria-describedby="blacklist-remove-description">
        <BlacklistRemoveForm {...props} onOpenChange={onOpenChange} />
      </DialogContent>
    </Dialog>
  );
}

function BlacklistRemoveForm({
  candidateId,
  candidateName,
  onOpenChange,
  onDone,
}: Omit<BlacklistDialogBaseProps, "open">) {
  const queryClient = useQueryClient();
  const { showSuccess } = useToast();
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () => candidatesApi.removeFromBlacklist(candidateId, { reason: reason.trim() }),
    onSuccess: () => {
      showSuccess("Zdjęto z czarnej listy");
      invalidateBlacklistQueries(queryClient, candidateId);
      onDone?.();
      onOpenChange(false);
    },
    onError: (err) => setError(blacklistErrorMessage(err, "Nie udało się zdjąć z czarnej listy.")),
  });

  const canSubmit = isBlacklistReasonValid(reason) && !mutation.isPending;

  return (
    <>
      <DialogHeader>
        <DialogTitle>Zdjąć z czarnej listy — {candidateName}?</DialogTitle>
        <DialogDescription id="blacklist-remove-description">
          Osoba wróci do wyszukiwania pod rekrutację i będzie ją można dodać do rekrutacji.
          Zdjęcie z powodem zostaje w historii profilu.
        </DialogDescription>
      </DialogHeader>
      <DialogBody className="space-y-3">
        <div>
          <label
            htmlFor={`blacklist-remove-reason-${candidateId}`}
            className="mb-1 block text-xs font-semibold text-muted-foreground"
          >
            Powód
          </label>
          <textarea
            id={`blacklist-remove-reason-${candidateId}`}
            rows={3}
            required
            maxLength={BLACKLIST_REASON_MAX}
            value={reason}
            onChange={(e) => {
              setReason(e.target.value);
              setError(null);
            }}
            placeholder="np. wyjaśnione z klientem, wraca do współpracy"
            className={cn(FIELD_CLASS, "resize-y")}
          />
        </div>
        {error ? (
          <p role="alert" className="rounded-md bg-destructive-muted px-3 py-2 text-sm text-destructive-muted-foreground">
            {error}
          </p>
        ) : null}
      </DialogBody>
      <DialogFooter>
        <Button variant="outline" onClick={() => onOpenChange(false)} disabled={mutation.isPending}>
          Anuluj
        </Button>
        <Button
          variant="primary"
          disabled={!canSubmit}
          loading={mutation.isPending}
          onClick={() => {
            setError(null);
            mutation.mutate();
          }}
        >
          Zdejmij z czarnej listy
        </Button>
      </DialogFooter>
    </>
  );
}

// ── Baner w profilu ───────────────────────────────────────────────────────

export interface BlacklistNoticeProps {
  candidateId: number;
  candidateName: string;
  blacklist: CandidateBlacklistInfo | null | undefined;
}

/**
 * Baner pod paskiem osoby, gdy osoba jest na czarnej liście „u nas”: kto,
 * kiedy i dlaczego. Zastępuje dawną plakietkę „Czarna lista” w pasku.
 */
export function BlacklistNotice({ candidateId, candidateName, blacklist }: BlacklistNoticeProps) {
  const user = useAuthStore((state) => state.user);
  const isImpersonating = useAuthStore((state) => state.realUser !== null);
  const canRemove = canRemoveBlacklist(user, isImpersonating);
  const [removeOpen, setRemoveOpen] = useState(false);
  const meta = blacklistMetaLine(blacklist);

  return (
    <div
      data-testid="blacklist-notice"
      className="flex flex-wrap items-start gap-3 rounded-xl border border-destructive/20 bg-destructive-muted px-4 py-3 text-destructive-muted-foreground"
    >
      <Ban className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div className="min-w-0 flex-1 basis-60 space-y-0.5">
        <p className="text-sm font-semibold">Czarna lista — nie współpracujemy z tą osobą</p>
        {meta ? <p className="text-xs">{meta}</p> : null}
        <p className="break-words text-xs">{blacklistReasonLine(blacklist)}</p>
      </div>
      {canRemove ? (
        <>
          <Button size="sm" variant="outline" className="min-h-9 bg-card" onClick={() => setRemoveOpen(true)}>
            Zdejmij…
          </Button>
          <BlacklistRemoveDialog
            open={removeOpen}
            onOpenChange={setRemoveOpen}
            candidateId={candidateId}
            candidateName={candidateName}
          />
        </>
      ) : null}
    </div>
  );
}

// ── Pigułki ───────────────────────────────────────────────────────────────

/** Pigułka „Czarna lista” — lista kandydatów (wiersz ma stałą wysokość). */
export function BlacklistBadge({ className }: { className?: string }) {
  return (
    <Badge
      variant="danger"
      size="sm"
      className={cn("shrink-0", className)}
      title="Czarna lista — nie współpracujemy z tą osobą"
      data-testid="blacklist-badge"
    >
      <Ban className="size-2.5" aria-hidden />
      Czarna lista
    </Badge>
  );
}

/**
 * Pigułka w panelu osoby na Tablicy: głowa panelu się nie przewija (treść
 * pod nią ma ~390 px przy 1280 × 650), więc kto, kiedy i dlaczego są
 * w dymku po kliknięciu — jak „Pracuje u nas” (`EmploymentPopoverPill`).
 */
export function BlacklistPopoverPill({
  blacklist,
}: {
  blacklist: CandidateBlacklistInfo | null | undefined;
}) {
  const meta = blacklistMetaLine(blacklist);
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="inline-flex rounded-full focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
          aria-label="Czarna lista — szczegóły"
        >
          <Badge variant="danger" size="sm" className="cursor-pointer">
            <Ban className="size-2.5" aria-hidden />
            Czarna lista
          </Badge>
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-80 max-w-[calc(100vw-1rem)] space-y-1 p-3 text-xs text-foreground">
        <p className="text-sm font-semibold">Nie współpracujemy z tą osobą</p>
        {meta ? <p className="text-muted-foreground">{meta}</p> : null}
        <p className="break-words">{blacklistReasonLine(blacklist)}</p>
      </PopoverContent>
    </Popover>
  );
}
