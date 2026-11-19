"use client";
// B · Sprzęt — karty urządzeń zamiast tabeli z kolorowymi plakietkami: ikona
// rodzaju, model, numer, data wydania, protokół i stan zwrotu. Pasek akcji:
// „Wydaj z magazynu” (outline) i „Dodaj sprzęt” (ghost). Pusty stan mówi
// jednym zdaniem, czy to normalne — bez kursywy. Sprzęt z rejestru „Sprzęt”
// i ze starej tabeli kontraktu (model urządzenia w `StartA`).
import { FileText } from "lucide-react";
import { StatusDot } from "@/components/ds/StatusDot";
import { Button } from "@/components/ui/button";
import { CALM_EMPTY } from "@/lib/calm-table";
import { cn } from "@/lib/utils";
import { useMkContract, useMkDocuments } from "../shared/data";
import { plural } from "../shared/format";
import { deviceIssued, deviceReturn, equipmentDocument, useMkDevices, useMkProvider, type MkDevice } from "./StartA";
import type { TabProps } from "./types";

function DeviceCard({ d }: { d: MkDevice }) {
  const Icon = d.icon;
  const issued = deviceIssued(d);
  const ret = deviceReturn(d);
  const atConsultant = !d.returnedOn && !d.lost;
  return (
    <li className={cn("flex flex-col rounded-xl border border-border bg-card shadow-xs", !atConsultant && "opacity-80")}>
      <div className="flex items-start gap-3 px-3.5 pt-3.5">
        <span className="inline-flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
          <Icon className="size-[18px]" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-[13.5px] font-semibold leading-5 text-foreground" title={d.title}>
            {d.title}
          </p>
          <p className="text-[12px] leading-4 text-muted-foreground">
            {[d.title === d.kind ? null : d.kind, d.ours === false ? "sprzęt klienta" : d.ours ? "nasz" : null]
              .filter(Boolean)
              .join(" · ") || " "}
          </p>
        </div>
      </div>
      <dl className="grid grid-cols-[64px_minmax(0,1fr)] gap-x-2 gap-y-0.5 px-3.5 pb-3 pt-2.5 text-[12.5px] leading-5">
        <dt className="text-muted-foreground">Numer</dt>
        <dd className="min-w-0 truncate tabular-nums text-foreground" title={d.number ?? undefined}>
          {d.number ?? <span className={CALM_EMPTY}>—</span>}
          {d.numberNote ? <span className="text-muted-foreground"> · {d.numberNote}</span> : null}
        </dd>
        <dt className="text-muted-foreground">Wydano</dt>
        <dd className="tabular-nums text-foreground">
          {issued.main}
          {d.fromImport ? <span className="text-muted-foreground"> · wpis z importu</span> : null}
        </dd>
        <dt className="text-muted-foreground">Protokół</dt>
        <dd className={d.protocol ? "text-foreground" : "text-muted-foreground"}>{d.protocol ?? "brak protokołu wydania"}</dd>
      </dl>
      <div className="mt-auto flex items-center justify-between gap-2 border-t border-border/70 px-3.5 py-2">
        <StatusDot tone={ret.tone} note={ret.note}>
          {ret.label}
        </StatusDot>
        {atConsultant ? (
          <Button type="button" variant="ghost" size="sm" className="-mr-2 h-7">
            Przyjmij zwrot
          </Button>
        ) : null}
      </div>
    </li>
  );
}

export function SprzetB({ contractId }: TabProps) {
  const c = useMkContract(contractId).data;
  const docs = useMkDocuments(contractId).data;
  const { devices, isLoading, isError } = useMkDevices(contractId);
  const provider = useMkProvider(c?.client_id).data?.equipment_provider;
  const doc = equipmentDocument(docs);
  const active = devices.filter((d) => !d.returnedOn && !d.lost).length;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-card px-4 py-2.5 shadow-xs">
        <p className="text-[13px] text-muted-foreground">
          <span className="font-semibold text-foreground">Sprzęt u konsultanta</span>
          {devices.length ? (
            <>
              {" · "}
              {plural(active, ["urządzenie", "urządzenia", "urządzeń"])}
              {devices.length > active ? `, ${devices.length - active} zwrócone` : ""}
            </>
          ) : null}
        </p>
        <div className="flex items-center gap-1.5">
          <Button type="button" variant="ghost" size="sm">
            Dodaj sprzęt
          </Button>
          <Button type="button" variant="outline" size="sm">
            Wydaj z magazynu
          </Button>
        </div>
      </div>

      {isLoading ? (
        <p className="px-1 text-[13px] text-muted-foreground">Wczytywanie sprzętu…</p>
      ) : isError ? (
        <p className="px-1 text-[13px] text-destructive">Nie udało się pobrać sprzętu.</p>
      ) : devices.length === 0 ? (
        <div className="space-y-1.5 rounded-xl border border-border bg-card px-4 py-3.5 text-[13px] shadow-xs">
          <p className="text-foreground">
            {provider === "klienta"
              ? "Nie wydano sprzętu — u tego klienta konsultanci pracują na sprzęcie klienta, więc nic tu nie dodawaj."
              : "Nie wydano sprzętu. Jeśli konsultant pracuje na sprzęcie klienta, nic tu nie dodawaj."}
          </p>
          {doc ? (
            <p className="flex items-center gap-1.5 text-muted-foreground">
              <FileText className="size-3.5 shrink-0" aria-hidden />
              W dokumentach jest „{doc.filename}” — sprawdź, czy ten sprzęt nie powinien być w rejestrze.
            </p>
          ) : null}
        </div>
      ) : (
        <ul className="grid grid-cols-2 gap-3">
          {devices.map((d) => (
            <DeviceCard key={d.key} d={d} />
          ))}
        </ul>
      )}
    </div>
  );
}
