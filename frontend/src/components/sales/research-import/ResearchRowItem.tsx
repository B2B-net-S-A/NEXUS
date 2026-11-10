"use client";

import Link from "next/link";

import { StatusDot } from "@/components/ds/StatusDot";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { TableCell, TableRow } from "@/components/ui/table";
import type { ResearchCompany, ResearchOutcome, ResearchRow } from "@/lib/api/sales-research-import";
import { CALM_AMOUNT, CALM_EMPTY, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";

import { ClientHandoff } from "../factories/ClientHandoff";
import { safeHref } from "../format";
import { plural } from "../peoplePlural";
import { SalesSelect } from "../SalesSelect";

import {
  ACTION_LABELS,
  canCreateCard,
  cardsCount,
  LEVEL_OPTIONS,
  selectableCards,
  type CardChoice,
  type RowPhase,
  type Target,
} from "./research-import";

const NEW_CARD = "new";
const LINK = "text-primary hover:underline";

export interface ResearchItem {
  row: ResearchRow;
  company: ResearchCompany;
  target: Target | null;
  outcome: ResearchOutcome | undefined;
  phase: RowPhase;
  level: number;
}

interface ResearchRowItemProps {
  item: ResearchItem;
  choice: CardChoice | undefined;
  /** Konto założone w tej sesji: firma nie czeka już na wybór karty. */
  resolved: boolean;
  saving: boolean;
  /** Powód, dla którego nie da się teraz dodać (np. puste „Skąd lista”). */
  blockedReason: string | null;
  onLevel: (level: number) => void;
  onChoose: (choice: CardChoice) => void;
  onAccept: () => void;
}

function contactsLabel(count: number): string {
  return `${count} ${plural(count, "kontakt", "kontakty", "kontaktów")} na karcie`;
}

function CompanyCell({ item, choice, resolved, onChoose }: Pick<ResearchRowItemProps, "item" | "choice" | "resolved" | "onChoose">) {
  const { company, target, row } = item;
  if (company.state === "client") {
    return (
      <>
        <Badge variant="danger" size="sm">
          Klient NEXUSA
        </Badge>
        {company.client && (
          <p className="mt-0.5 text-xs">
            <ClientHandoff client={company.client} />
          </p>
        )}
      </>
    );
  }
  if (company.state === "blocked") {
    return (
      <>
        <Badge variant="danger" size="sm">
          Nie kontaktować
        </Badge>
        <span className={CALM_SUBLINE}>firma ma sprzeciw wobec kontaktu</span>
      </>
    );
  }
  if (company.state === "own_company") {
    return (
      <Badge variant="neutral" size="sm">
        Nasza firma
      </Badge>
    );
  }
  if (resolved || company.state === "account") {
    const account = target?.card?.account;
    return (
      <>
        <Badge variant="success" size="sm">
          Konto w Fabrykach IT
        </Badge>
        <span className={CALM_SUBLINE}>
          {account
            ? `${account.stage_name} · ${
                account.map_total === 0
                  ? "mapa jest pusta"
                  : `mapa: ${account.map_contacted} z ${account.map_total} po kontakcie`
              }`
            : "założone z tej listy"}
        </span>
      </>
    );
  }
  if (company.state === "no_card") {
    return (
      <>
        <Badge variant="neutral" size="sm">
          Brak karty
        </Badge>
        <span className={CALM_SUBLINE}>
          powstanie firma{row.domain ? ` z domeną ${row.domain}` : ""} i konto w Fabrykach IT
        </span>
      </>
    );
  }
  if (company.state === "card") {
    const card = target?.card;
    return (
      <>
        <Badge variant="info" size="sm">
          Karta bez konta
        </Badge>
        <span className={CALM_SUBLINE}>
          {card ? contactsLabel(card.contacts) : ""}
          {card?.archived_account ? " · konto w archiwum" : ""}
        </span>
      </>
    );
  }
  const cards = selectableCards(company);
  const client = company.cards.find((card) => card.client);
  const options = [
    ...cards.map((card) => ({
      value: String(card.id),
      label: [
        card.name,
        card.account ? `konto: ${card.account.stage_name}` : contactsLabel(card.contacts),
        card.known_current !== null ? `znamy teraz ${card.known_current}` : null,
      ]
        .filter(Boolean)
        .join(" · "),
    })),
    ...(canCreateCard(company) ? [{ value: NEW_CARD, label: "Nowa karta firmy" }] : []),
  ];
  return (
    <>
      <Badge variant="warning" size="sm">
        {cardsCount(company.cards.length)}
      </Badge>
      <SalesSelect
        ariaLabel={`Karta firmy: ${company.name}`}
        className="mt-1 h-7 w-full max-w-[19rem] text-xs"
        value={choice === undefined ? "" : String(choice)}
        onValueChange={(value) => {
          if (value) onChoose(value === NEW_CARD ? NEW_CARD : Number(value));
        }}
        options={options}
        anyLabel="Wybierz kartę"
      />
      {client?.client && <span className={CALM_SUBLINE}>w tym klient NEXUSA: {client.name}</span>}
    </>
  );
}

function ActionCell({ item, saving, blockedReason, onAccept }: Pick<ResearchRowItemProps, "item" | "saving" | "blockedReason" | "onAccept">) {
  const { row, company, target, outcome, phase } = item;
  if (phase === "added") {
    return (
      <span className="inline-flex items-center gap-2">
        <StatusDot tone="success">Dodano</StatusDot>
        {outcome?.opportunity_id && (
          <Link href={`/sales/opportunities/${outcome.opportunity_id}`} className={`text-xs ${LINK}`}>
            Otwórz konto
          </Link>
        )}
      </span>
    );
  }
  if (phase === "skip") {
    const opportunityId = outcome?.opportunity_id ?? row.on_map_opportunity_id;
    return (
      <span className="text-xs text-muted-foreground">
        {row.person === "repeated" && !outcome ? "Powtórzona w pliku" : "Już na mapie"}
        {opportunityId && (
          <>
            {" · "}
            <Link href={`/sales/opportunities/${opportunityId}`} className={LINK}>
              otwórz
            </Link>
          </>
        )}
      </span>
    );
  }
  if (phase === "refused") {
    return (
      <span className="text-xs text-muted-foreground">
        {company.state === "client" || outcome?.result === "client" ? "Temat dla Delivery Leada" : "Bez dodawania"}
      </span>
    );
  }
  if (phase === "choose" || !target) {
    return <span className="text-xs text-muted-foreground">Wskaż kartę firmy</span>;
  }
  const label = ACTION_LABELS[target.kind];
  return (
    <span className="inline-flex flex-col items-end gap-0.5">
      <Button
        size="sm"
        variant={target.kind === "account" ? "primary" : "outline"}
        className="h-7 px-2.5"
        aria-label={`${label}: ${row.name}`}
        loading={saving}
        disabled={blockedReason !== null}
        title={blockedReason ?? undefined}
        onClick={onAccept}
      >
        {label}
      </Button>
      {outcome?.detail && (
        <span role="alert" className="max-w-[14rem] whitespace-normal text-right text-[11px] leading-4 text-destructive">
          {outcome.detail}
        </span>
      )}
    </span>
  );
}

/** Wiersz przeglądu: osoba z pliku, stan jej firmy w NEXUSIE i jedna akcja. */
export function ResearchRowItem(props: ResearchRowItemProps) {
  const { item, onLevel } = props;
  const { row, target, phase } = item;
  const editable = phase === "ready" || phase === "choose";
  const source = safeHref(row.linkedin_url) ?? safeHref(row.source_url);
  const known = target?.card?.known_current ?? null;
  const companyId = target?.companyId ?? null;
  return (
    <TableRow className={CALM_ROW}>
      <TableCell className="sticky left-0 bg-card py-1.5">
        <span className={`font-medium ${editable ? "text-foreground" : "text-muted-foreground"}`}>{row.company}</span>
        <span className={CALM_SUBLINE}>
          {[row.name, row.role_in_company].filter(Boolean).join(" · ")}
          {source && (
            <>
              {" · "}
              <a href={source} target="_blank" rel="noreferrer" className={LINK}>
                profil
              </a>
            </>
          )}
        </span>
        {row.warnings.length > 0 && (
          <span className={`${CALM_SUBLINE} text-warning`} title={`Wiersz ${row.line} w pliku`}>
            {row.warnings.join("; ")}
          </span>
        )}
      </TableCell>
      <TableCell className="py-1.5">
        <SalesSelect
          ariaLabel={`Poziom decyzji: ${row.name}`}
          className="h-7 w-[8.25rem] text-xs"
          value={String(item.level)}
          onValueChange={(value) => onLevel(Number(value))}
          options={LEVEL_OPTIONS}
          disabled={!editable}
        />
      </TableCell>
      <TableCell className="py-1.5">
        <Badge variant={row.confidence === "confirmed" ? "success" : "neutral"} size="sm">
          {row.confidence === "confirmed" ? "Pewne" : "Do weryfikacji"}
        </Badge>
      </TableCell>
      <TableCell className="py-1.5">
        <CompanyCell {...props} />
      </TableCell>
      <TableCell className={`${CALM_AMOUNT} py-1.5 font-medium text-foreground`}>
        {known !== null && known > 0 && companyId ? (
          <Link
            href={`/sales/companies/${companyId}?tab=people`}
            aria-label={`Kto ich zna: ${row.company}`}
            title="Kto ich zna: osoby z bazy na karcie firmy"
            className={LINK}
          >
            {known}
          </Link>
        ) : known !== null ? (
          known
        ) : (
          <span className={CALM_EMPTY}>—</span>
        )}
      </TableCell>
      <TableCell className="whitespace-nowrap py-1.5 text-right">
        <ActionCell {...props} />
      </TableCell>
    </TableRow>
  );
}
