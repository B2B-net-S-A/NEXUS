"use client";

import { useQuery } from "@tanstack/react-query";
import { contractsApi, type ContractBenchmarkComparison } from "@/lib/api";
import { TrendingUp } from "lucide-react";
import { formatCurrency } from "@/lib/utils";

interface Props {
  contractId: number;
  currency: string;
}

export function ContractRateBenchmarkCard({ contractId, currency }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ["contract-benchmark", contractId],
    queryFn: async () => {
      const res = await contractsApi.benchmark(contractId);
      return res.data as ContractBenchmarkComparison;
    },
  });

  if (isLoading) {
    return (
      <div className="rounded-lg border border-border dark:border-border p-4 text-sm text-muted-foreground">
        Ładowanie benchmarku…
      </div>
    );
  }
  if (!data) return null;

  const contractRate = data.contract_rate_monthly;
  const internalMedian = data.internal_median_monthly;
  const marketMedian = data.market_median;

  const compareInternal =
    contractRate && internalMedian
      ? Math.round(((contractRate - internalMedian) / internalMedian) * 100)
      : null;
  const compareMarket =
    contractRate && marketMedian
      ? Math.round(((contractRate - marketMedian) / marketMedian) * 100)
      : null;

  return (
    <div className="rounded-lg border border-border dark:border-border p-4 bg-gradient-to-br from-blue-50/50 to-transparent dark:from-blue-950/20">
      <div className="flex items-center gap-2 mb-3">
        <TrendingUp className="w-4 h-4 text-primary" />
        <h3 className="text-sm font-semibold">Benchmark stawki</h3>
        {data.role_used && (
          <span className="ml-auto text-xs text-muted-foreground">
            rola: {data.role_used}
          </span>
        )}
      </div>
      <div className="grid grid-cols-3 gap-4 text-sm">
        <MetricBlock
          label="Ten kontrakt"
          value={contractRate}
          currency={currency}
        />
        <MetricBlock
          label={`Nasza mediana (${data.internal_sample_size})`}
          value={internalMedian}
          currency={currency}
          diffPct={compareInternal}
        />
        <MetricBlock
          label="Rynek (mediana)"
          value={marketMedian}
          currency={currency}
          diffPct={compareMarket}
          extra={data.market_source ? `${data.market_source}` : null}
        />
      </div>
      {!data.market_median && (
        <p className="mt-3 text-xs text-muted-foreground">
          Brak danych rynkowych dla tej roli – dodaj wpis w{" "}
          <a
            href="/settings/rate-benchmarks"
            className="underline hover:text-foreground"
          >
            Ustawieniach &gt; Benchmarki stawek
          </a>
          .
        </p>
      )}
    </div>
  );
}

interface MetricBlockProps {
  label: string;
  value: number | null;
  currency: string;
  diffPct?: number | null;
  extra?: string | null;
}

function MetricBlock({ label, value, currency, diffPct, extra }: MetricBlockProps) {
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-base font-semibold">
        {value != null ? formatCurrency(value, currency) : "–"}
      </div>
      {diffPct != null && value != null && (
        <div
          className={`text-xs mt-0.5 ${diffPct >= 0 ? "text-green-600" : "text-amber-600"}`}
        >
          {diffPct >= 0 ? "+" : ""}
          {diffPct}%
        </div>
      )}
      {extra && <div className="text-xs text-muted-foreground mt-0.5">{extra}</div>}
    </div>
  );
}
