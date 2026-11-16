"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Search, X } from "lucide-react";

import { PageHeader } from "@/components/ds/PageHeader";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useCreateTraining,
  useTrainerApplications,
  useTrainerUserOptions,
  useTrainingsMe,
  type DirectoryUser,
  type OrderInput,
  type TrainerApplication,
} from "@/lib/api/trainings";

import { OrderFields } from "./OrderFields";
import {
  defaultDeliverables,
  deliverablesPayload,
  emptyOrder,
  orderFormProblem,
  type DeliverableDraft,
} from "./training-model";
import { useRunAction } from "./use-run-action";

type TrainerSource = "consultant" | "employee";

function EmployeePicker({
  value,
  onChange,
}: {
  value: DirectoryUser | null;
  onChange: (user: DirectoryUser | null) => void;
}) {
  const [query, setQuery] = useState("");
  const options = useTrainerUserOptions(query, value === null);
  if (value) {
    return (
      <div className="flex items-center justify-between gap-2 rounded-md border border-border px-3 py-2 text-sm">
        <span className="min-w-0 truncate">
          <span className="font-medium">{value.name}</span>
          <span className="text-muted-foreground"> · {value.email}</span>
        </span>
        <Button size="icon-sm" variant="ghost" aria-label="Zmień osobę" onClick={() => onChange(null)}>
          <X className="h-4 w-4" aria-hidden />
        </Button>
      </div>
    );
  }
  const items = options.data ?? [];
  return (
    <div className="space-y-1.5">
      <div className="relative">
        <Search
          aria-hidden
          className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
        />
        <Input
          id="trainer-user"
          className="pl-8"
          placeholder="Imię, nazwisko albo e-mail…"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>
      {options.isError ? (
        <p role="alert" className="text-xs text-destructive">
          {apiErrorMessage(options.error, "Nie udało się wyszukać osób.")}
        </p>
      ) : null}
      {options.isSuccess && items.length === 0 ? (
        <p className="text-xs text-muted-foreground">Nikogo nie znaleziono dla „{query.trim()}”.</p>
      ) : null}
      {items.length > 0 ? (
        <ul className="max-h-48 overflow-y-auto rounded-md border border-border">
          {items.slice(0, 30).map((user) => (
            <li key={user.id}>
              <button
                type="button"
                className="flex w-full justify-between gap-3 px-3 py-1.5 text-left text-sm hover:bg-muted"
                onClick={() => onChange(user)}
              >
                <span className="truncate">{user.name}</span>
                <span className="shrink-0 text-xs text-muted-foreground">{user.email}</span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function prefillFrom(application: TrainerApplication, order: OrderInput): OrderInput {
  return {
    ...order,
    title: order.title || application.proposal_title,
    topic: order.topic || application.topics.join(", ").slice(0, 200),
  };
}

/** Nowe szkolenie: trener ze zgłoszenia, z kontraktu albo pracownik; szkic Zał. 1. */
export function NewTrainingScreen() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const me = useTrainingsMe();
  const canManage = me.data?.can_manage === true;
  const applications = useTrainerApplications(canManage);
  const create = useCreateTraining();
  const run = useRunAction();

  const [source, setSource] = useState<TrainerSource>("consultant");
  const [applicationId, setApplicationId] = useState<number | null>(
    Number(searchParams.get("application")) || null,
  );
  const [contractId, setContractId] = useState("");
  const [employee, setEmployee] = useState<DirectoryUser | null>(null);
  const [order, setOrder] = useState<OrderInput>(emptyOrder);
  const [drafts, setDrafts] = useState<DeliverableDraft[]>(defaultDeliverables);
  const [problem, setProblem] = useState<string | null>(null);

  const application = applications.data?.find((item) => item.id === applicationId) ?? null;
  // Zgłoszenie z adresu (?application=) wypełnia nazwę i temat raz, gdy lista dojdzie.
  const prefilled = useRef(false);
  useEffect(() => {
    if (application && !prefilled.current) {
      prefilled.current = true;
      setOrder((current) => prefillFrom(application, current));
    }
  }, [application]);

  if (me.isLoading) return <p className="text-sm text-muted-foreground">Ładowanie…</p>;
  if (me.isError) return <QueryStateNotice state="error" onRetry={() => me.refetch()} />;
  if (!canManage) {
    return (
      <QueryStateNotice
        state="forbidden"
        description="Szkolenia zamawia Talent Community Manager albo administrator."
      />
    );
  }

  const trainerContractId =
    source === "consultant" ? application?.contract_id ?? (Number(contractId) || null) : null;

  const submit = async () => {
    const trainerProblem =
      source === "consultant"
        ? trainerContractId
          ? null
          : "Wybierz zgłoszenie trenera albo wpisz numer kontraktu."
        : employee
          ? null
          : "Wybierz pracownika, który poprowadzi szkolenie.";
    const issue = trainerProblem ?? orderFormProblem(order, source === "employee" ? [] : drafts);
    setProblem(issue);
    if (issue) return;
    const created: { id: number | null } = { id: null };
    const ok = await run(
      async () => {
        const training = await create.mutateAsync({
          ...order,
          deliverables: source === "employee" ? [] : deliverablesPayload(drafts),
          trainer_contract_id: trainerContractId,
          trainer_user_id: source === "employee" ? employee?.id ?? null : null,
          application_id: source === "consultant" ? application?.id ?? null : null,
        });
        created.id = training.id;
      },
      "Zapisano szkic zamówienia.",
      "Nie udało się zapisać zamówienia.",
    );
    if (ok && created.id !== null) router.push(`/trainings/${created.id}`);
  };

  return (
    <div className="space-y-4">
      <PageHeader
        title="Nowe szkolenie"
        description="Zamówienie to szkic Załącznika nr 1. Trener zobaczy je po wysłaniu z karty szkolenia."
        density="compact"
        breadcrumb={[{ label: "Szkolenia", href: "/trainings?tab=organize" }, { label: "Nowe" }]}
      />
      <Card size="sm" className="space-y-3 p-4">
        <h2 className="text-sm font-semibold">Kto prowadzi</h2>
        <SegmentedRadio<TrainerSource>
          label="Kto prowadzi szkolenie"
          value={source}
          onChange={setSource}
          options={[
            { value: "consultant", label: "Konsultant z umową B2B" },
            { value: "employee", label: "Pracownik" },
          ]}
        />
        {source === "consultant" ? (
          <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_12rem]">
            <FormField
              label="Zgłoszenie trenera"
              htmlFor="trainer-application"
              description={
                applications.isError
                  ? apiErrorMessage(applications.error, "Nie udało się odczytać zgłoszeń.")
                  : "Zgłoszenia z panelu konsultanta („Zostań trenerem”)."
              }
            >
              <select
                id="trainer-application"
                className="h-9 w-full rounded-md border border-border bg-background px-3 text-sm text-foreground"
                value={applicationId ?? ""}
                onChange={(event) => {
                  const next = Number(event.target.value) || null;
                  setApplicationId(next);
                  const picked = applications.data?.find((item) => item.id === next);
                  if (picked) setOrder((current) => prefillFrom(picked, current));
                }}
              >
                <option value="">— bez zgłoszenia —</option>
                {(applications.data ?? []).map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.trainer_name || `Kontrakt #${item.contract_id}`}
                    {item.proposal_title ? ` · ${item.proposal_title}` : ""}
                  </option>
                ))}
              </select>
            </FormField>
            <FormField
              label="albo numer kontraktu"
              htmlFor="trainer-contract"
              description="Z rejestru Kontrakty."
            >
              <Input
                id="trainer-contract"
                inputMode="numeric"
                value={application ? String(application.contract_id) : contractId}
                disabled={application !== null}
                onChange={(event) => setContractId(event.target.value.replace(/\D/g, ""))}
              />
            </FormField>
          </div>
        ) : (
          <FormField label="Pracownik" htmlFor="trainer-user">
            <EmployeePicker value={employee} onChange={setEmployee} />
          </FormField>
        )}
      </Card>
      <Card size="sm" className="space-y-3 p-4">
        <h2 className="text-sm font-semibold">Zamówienie (Zał. 1)</h2>
        <OrderFields
          value={order}
          onChange={setOrder}
          deliverables={drafts}
          onDeliverablesChange={setDrafts}
          disabled={create.isPending}
          employee={source === "employee"}
          teamsReady={me.data?.teams_ready === true}
          roles={me.data?.mandatory_roles ?? []}
        />
      </Card>
      {problem ? (
        <p role="alert" className="text-sm text-destructive">
          {problem}
        </p>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <Button disabled={create.isPending} onClick={submit}>
          Zapisz szkic zamówienia
        </Button>
        <Button asChild variant="ghost">
          <Link href="/trainings?tab=organize">Anuluj</Link>
        </Button>
      </div>
    </div>
  );
}
