"use client";

import { useEffect, useState } from "react";
import { MapPin } from "lucide-react";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { Input } from "@/components/ui/input";

interface LocationInputProps {
  value: string;
  onChange: (location: string) => void;
  placeholder?: string;
}

/**
 * Free-text location filter. Backend does ILIKE against candidates.location,
 * so any substring works. We debounce 300 ms so typing doesn't spam
 * the list query.
 */
export function LocationInput({
  value,
  onChange,
  placeholder = "np. Warszawa",
}: LocationInputProps) {
  const [local, setLocal] = useState(value);
  const debounced = useDebouncedValue(local, 300);

  // Propagate debounced changes outward.
  useEffect(() => {
    if (debounced !== value) onChange(debounced);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debounced]);

  // Pull in external resets (e.g. clear-all filters).
  useEffect(() => {
    setLocal(value);
  }, [value]);

  return (
    <Input
      leadingIcon={<MapPin className="h-4 w-4" />}
      placeholder={placeholder}
      value={local}
      onChange={(e) => setLocal(e.target.value)}
    />
  );
}
