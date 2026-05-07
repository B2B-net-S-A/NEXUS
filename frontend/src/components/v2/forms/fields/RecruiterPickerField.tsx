"use client";

import * as React from"react";
import { Controller, useFormContext } from"react-hook-form";
import { useQuery } from"@tanstack/react-query";
import api from"@/lib/api";
import { ROLE_LABELS, type UserRole } from"@/store/auth";
import type { UserBrief } from"@/components/v2/jobs/ownership-types";
import {
 Select,
 SelectContent,
 SelectItem,
 SelectTrigger,
 SelectValue,
} from"@/components/ui/select";

interface RecruiterPickerFieldProps {
 name: string;
 /** Roles eligible to be picked. Defaults to ownership-eligible roles. */
 roles?: UserRole[];
 placeholder?: string;
 disabled?: boolean;
 /**
 * When true, the caller is editing the primary owner — empty value becomes
 * null (unassigned). When false, the caller wants a required user_id and
 * empty is treated as"please select".
 */
 allowEmpty?: boolean;
}

const DEFAULT_ROLES: UserRole[] = ["admin","delivery_lead","tac","recruiter","sourcer",
];

/**
 * Combobox-style picker that loads active ownership-eligible users from
 * `/api/users` and integrates with react-hook-form. Field value is the numeric
 * user id (or null when `allowEmpty`).
 */
export function RecruiterPickerField({
 name,
 roles = DEFAULT_ROLES,
 placeholder ="Wybierz rekrutera…",
 disabled,
 allowEmpty = true,
}: RecruiterPickerFieldProps) {
 const { control, formState } = useFormContext();
 const error = name
 .split(".")
 .reduce<unknown>((acc, key) => {
 if (acc && typeof acc === "object") {
 return (acc as Record<string, unknown>)[key];
 }
 return undefined;
 }, formState.errors);

 const { data, isLoading } = useQuery<UserBrief[]>({
 queryKey: ["users","directory", roles.join(",")],
 queryFn: async () => {
 const params = new URLSearchParams();
 roles.forEach((r) => params.append("roles", r));
 const resp = await api.get(`/api/users?${params.toString()}`);
 return resp.data as UserBrief[];
 },
 staleTime: 5 * 60 * 1000,
 });

 return (
 <Controller
 name={name}
 control={control}
 render={({ field }) => (
 <Select
 value={field.value != null ? String(field.value) : "__none__"}
 onValueChange={(v) => {
 if (v === "__none__") {
 field.onChange(allowEmpty ? null : undefined);
 } else {
 field.onChange(Number(v));
 }
 }}
 disabled={disabled || isLoading}
 >
 <SelectTrigger id={name} invalid={!!error}>
 <SelectValue placeholder={isLoading ?"Ładowanie…" : placeholder} />
 </SelectTrigger>
 <SelectContent>
 {allowEmpty ? (
 <SelectItem value="__none__">— nieprzypisany —</SelectItem>
 ) : null}
 {(data ?? []).map((u) => (
 <SelectItem key={u.id} value={String(u.id)}>
 {u.name}
 <span className="text-muted-foreground ml-2 text-xs">
 {ROLE_LABELS[u.role]}
 </span>
 </SelectItem>
 ))}
 </SelectContent>
 </Select>
 )}
 />
 );
}
