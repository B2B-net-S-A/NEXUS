"use client";

/**
 * Modal potwierdzenia wyciągnięty z `CandidateDetailV2`.
 *
 * Powód wydzielenia: edytor draftu umowy (`ContractDraftEditor`) ciągnie za
 * sobą TipTap/ProseMirror i dlatego ładuje się przez `next/dynamic`. Gdyby
 * używał `ConfirmModal` zdefiniowanego w `CandidateDetailV2`, import zwrotny
 * wciągnąłby cały tamten moduł z powrotem do chunku edytora — i odwrotnie,
 * zostawienie modala w edytorze zabrałoby go DRUGIEMU konsumentowi w profilu
 * kandydata. Wspólny, lekki moduł rozwiązuje oba naraz.
 */

import * as React from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function ConfirmModal({
 title,
 message,
 confirmLabel,
 onConfirm,
 onCancel,
}: {
 title: string;
 message: string;
 confirmLabel: string;
 onConfirm: () => void;
 onCancel: () => void;
}) {
 return (
 <div
 className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/40"
 onClick={onCancel}
 >
 <Card
 variant="default"
 size="md"
 className="max-w-md w-full mx-4"
 onClick={(e: React.MouseEvent) => e.stopPropagation()}
 >
 <CardHeader>
 <CardTitle>{title}</CardTitle>
 </CardHeader>
 <CardContent className="space-y-4">
 <p className="text-sm text-foreground">{message}</p>
 <div className="flex justify-end gap-2">
 <Button variant="outline" size="sm" onClick={onCancel}>
 Anuluj
 </Button>
 <Button size="sm" onClick={onConfirm}>
 {confirmLabel}
 </Button>
 </div>
 </CardContent>
 </Card>
 </div>
 );
}
