"use client";

import * as React from"react";
import Link from"next/link";
import { useQuery } from"@tanstack/react-query";
import { ArrowRight, Briefcase } from"lucide-react";
import api from"@/lib/api";
import { Badge } from"@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from"@/components/ui/card";
import { WidgetState } from"@/components/v2/dashboard/WidgetState";

interface JobItem {
 id: number;
 title: string;
 client_id?: number | null;
 client_name?: string | null;
 status?: string | null;
 priority?: string | null;
 headcount?: number | null;
 candidate_count?: number | null;
}

/**
 * Dashboard widget listing jobs where the current user is primary owner or
 * a collaborator. Links deeper to /jobs?mine=1 for the full list.
 */
export function MyJobsWidget() {
 const { data, isLoading, isError, error, refetch } = useQuery<{
 items: JobItem[];
 total: number;
 }>({
 queryKey: ["dashboard","my-jobs"],
 queryFn: () =>
 api
 .get("/api/jobs", {
 params: { mine: true, page_size: 5 },
 })
 .then((r) => r.data),
 staleTime: 60 * 1000,
 });

 const items = data?.items ?? [];
 const total = data?.total ?? 0;

 return (
 <Card variant="default" size="md">
 <CardHeader>
 <div className="flex items-center justify-between">
 <div>
 <CardTitle className="flex items-center gap-2">
 <Briefcase className="h-4 w-4 text-primary" />
 Moje projekty
 </CardTitle>
 <CardDescription>
 Projekty, na których jesteś właścicielem lub współpracownikiem.
 </CardDescription>
 </div>
 {!isError && total > 0 ? (
 <Link
 href="/jobs?mine=1"
 className="text-xs text-primary hover:underline inline-flex items-center gap-1"
 >
 Zobacz wszystkie ({total}) <ArrowRight className="h-3 w-3" />
 </Link>
 ) : null}
 </div>
 </CardHeader>
 <CardContent>
 <WidgetState
 isLoading={isLoading}
 isError={isError}
 error={error}
 onRetry={() => refetch()}
 isEmpty={items.length === 0}
 loadingFallback={
 <div className="space-y-2">
 {Array.from({ length: 3 }).map((_, i) => (
 <div
 key={i}
 className="h-12 rounded-lg bg-[hsl(var(--border))] animate-pulse"
 />
 ))}
 </div>
 }
 emptyFallback={
 <div className="text-sm text-muted-foreground py-6 text-center">
 <Briefcase className="h-8 w-8 mx-auto mb-2 opacity-40" />
 <p>Nie masz przypisanych projektów.</p>
 <Link
 href="/jobs?mine=0&status=published"
 className="inline-flex items-center gap-1 text-primary hover:underline text-xs mt-1"
 >
 Przeglądaj otwarte oferty <ArrowRight className="h-3 w-3" />
 </Link>
 </div>
 }
 >
 <ul className="space-y-1">
 {items.map((job) => (
 <li key={job.id}>
 <Link
 href={`/jobs/${job.id}`}
 className="flex items-center justify-between gap-2 px-2 py-2 rounded-md hover:bg-primary/10 transition-colors"
 >
 <div className="min-w-0 flex-1">
 <div className="text-sm font-medium text-foreground truncate">
 {job.title}
 </div>
 {job.client_name ? (
 <div className="text-xs text-muted-foreground truncate">
 {job.client_name}
 </div>
 ) : null}
 </div>
 <div className="flex items-center gap-2 shrink-0">
 {job.priority && job.priority !== "medium" ? (
 <Badge size="sm" variant="plum">
 {job.priority}
 </Badge>
 ) : null}
 {typeof job.candidate_count === "number" ? (
 <span className="text-[10px] font-mono text-muted-foreground">
 {job.candidate_count}/{job.headcount ?? 1}
 </span>
 ) : null}
 </div>
 </Link>
 </li>
 ))}
 </ul>
 </WidgetState>
 </CardContent>
 </Card>
 );
}
