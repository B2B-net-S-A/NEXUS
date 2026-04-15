"use client";

import { useState, useEffect, useRef, useCallback, KeyboardEvent } from "react";
import { useRouter } from "next/navigation";
import { Search, X, Users, Briefcase, Building2, Sparkles, PhoneCall } from "lucide-react";
import api from "@/lib/api";

interface SearchResult {
  id: number;
  name: string;
  subtitle: string;
  url: string;
  score?: number | null;
}

interface GlobalSearchResults {
  query: string;
  candidates: SearchResult[];
  jobs: SearchResult[];
  clients: SearchResult[];
  contacts: SearchResult[];
}

interface SemanticCandidate {
  id: number;
  name: string;
  lastname: string;
  email?: string;
  competence_category?: string;
}

interface SemanticHit {
  candidate: SemanticCandidate;
  score: number | null;
  highlight: string;
}

interface SemanticSearchResults {
  query: string;
  results: SemanticHit[];
  total: number;
  search_type: "semantic" | "text_fallback";
}

function useDebounce<T>(value: T, delay: number): T {
  const [debouncedValue, setDebouncedValue] = useState<T>(value);
  useEffect(() => {
    const handler = setTimeout(() => setDebouncedValue(value), delay);
    return () => clearTimeout(handler);
  }, [value, delay]);
  return debouncedValue;
}

// Build a flat list of all navigable results for keyboard navigation
function buildFlatList(results: GlobalSearchResults | null): { url: string }[] {
  if (!results) return [];
  const flat: { url: string }[] = [];
  const groups = [
    results.candidates.slice(0, 3),
    results.jobs.slice(0, 3),
    results.clients.slice(0, 3),
    results.contacts.slice(0, 3),
  ];
  for (const group of groups) {
    for (const item of group) {
      flat.push({ url: item.url });
    }
  }
  return flat;
}

export function GlobalSearchBar() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<GlobalSearchResults | null>(null);
  const [semanticResults, setSemanticResults] = useState<SemanticSearchResults | null>(null);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [aiMode, setAiMode] = useState(false);
  const [searchType, setSearchType] = useState<"semantic" | "text_fallback" | null>(null);
  const [activeIndex, setActiveIndex] = useState(-1);
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const debouncedQuery = useDebounce(query, 350);

  // Text search
  useEffect(() => {
    if (aiMode) return;
    if (debouncedQuery.length < 2) {
      setResults(null);
      setOpen(false);
      setActiveIndex(-1);
      return;
    }
    let cancelled = false;
    setLoading(true);
    api
      .get(`/api/search/global?q=${encodeURIComponent(debouncedQuery)}`)
      .then((res) => {
        if (!cancelled) {
          setResults(res.data);
          setOpen(true);
          setActiveIndex(-1);
        }
      })
      .catch(() => {
        if (!cancelled) setResults(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [debouncedQuery, aiMode]);

  // Semantic search
  useEffect(() => {
    if (!aiMode) return;
    if (debouncedQuery.length < 3) {
      setSemanticResults(null);
      setOpen(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    api
      .post(`/api/search/semantic`, { query: debouncedQuery, top_k: 10 })
      .then((res) => {
        if (!cancelled) {
          setSemanticResults(res.data);
          setSearchType(res.data.search_type ?? null);
          setOpen(true);
        }
      })
      .catch(() => {
        if (!cancelled) setSemanticResults(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [debouncedQuery, aiMode]);

  // Close on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
        setActiveIndex(-1);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  // Global Escape key
  useEffect(() => {
    function handleKey(e: globalThis.KeyboardEvent) {
      if (e.key === "Escape") {
        setOpen(false);
        setActiveIndex(-1);
        inputRef.current?.blur();
      }
    }
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, []);

  const flatList = buildFlatList(results);

  const handleSelect = useCallback(
    (url: string) => {
      setOpen(false);
      setQuery("");
      setActiveIndex(-1);
      router.push(url);
    },
    [router]
  );

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (!open || aiMode) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((i) => Math.min(i + 1, flatList.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, -1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (activeIndex >= 0 && flatList[activeIndex]) {
        handleSelect(flatList[activeIndex].url);
      }
    }
  };

  const toggleAiMode = () => {
    setAiMode((v) => !v);
    setResults(null);
    setSemanticResults(null);
    setOpen(false);
    setSearchType(null);
    setActiveIndex(-1);
    inputRef.current?.focus();
  };

  const clearSearch = () => {
    setQuery("");
    setResults(null);
    setSemanticResults(null);
    setOpen(false);
    setActiveIndex(-1);
  };

  const hasTextResults =
    results &&
    (results.candidates.length > 0 || results.jobs.length > 0 ||
     results.clients.length > 0 || (results.contacts?.length ?? 0) > 0);

  const hasSemanticResults = semanticResults && semanticResults.results.length > 0;

  // Build absolute index offsets per group for active highlighting
  let globalIdx = 0;
  const groups: {
    icon: React.ReactNode;
    label: string;
    key: string;
    items: SearchResult[];
    allHref: string;
    startIdx: number;
  }[] = [];

  if (results) {
    const defs = [
      { key: "candidates", label: "Kandydaci", icon: <Users className="w-3.5 h-3.5" />, allHref: "/candidates", items: results.candidates.slice(0, 3) },
      { key: "jobs", label: "Oferty pracy", icon: <Briefcase className="w-3.5 h-3.5" />, allHref: "/jobs", items: results.jobs.slice(0, 3) },
      { key: "clients", label: "Klienci", icon: <Building2 className="w-3.5 h-3.5" />, allHref: "/clients", items: results.clients.slice(0, 3) },
      { key: "contacts", label: "Kontakty", icon: <PhoneCall className="w-3.5 h-3.5" />, allHref: "/contacts", items: (results.contacts ?? []).slice(0, 3) },
    ];
    for (const d of defs) {
      if (d.items.length > 0) {
        groups.push({ ...d, startIdx: globalIdx });
        globalIdx += d.items.length;
      }
    }
  }

  return (
    <div ref={containerRef} className="relative w-full max-w-xl">
      {/* Input row */}
      <div className="relative flex items-center gap-1.5">
        <div className={`relative flex-1 transition-all duration-200 ${
          aiMode ? "ring-2 ring-purple-500 rounded-xl shadow-[0_0_12px_2px_rgba(168,85,247,0.35)]" : ""
        }`}>
          <Search
            className={`absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 pointer-events-none transition-colors ${
              aiMode ? "text-purple-400" : "text-gray-400"
            }`}
          />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            onFocus={() => {
              if (aiMode ? hasSemanticResults : hasTextResults) setOpen(true);
            }}
            placeholder={
              aiMode
                ? "AI Search — opisz kandydata... (⌘K)"
                : "Szukaj kandydatów, ofert, klientów... (⌘K)"
            }
            data-global-search="true"
            className={`w-full pl-9 pr-9 py-2.5 border rounded-xl text-sm focus:outline-none bg-white dark:bg-gray-800 dark:text-gray-100 placeholder:text-gray-400 dark:placeholder:text-gray-500 shadow-sm transition-all ${
              aiMode
                ? "border-purple-400 dark:border-purple-600 focus:ring-0"
                : "border-gray-200 dark:border-gray-600 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            }`}
          />
          {loading && (
            <div className="absolute right-3 top-1/2 -translate-y-1/2">
              <div
                className={`w-3.5 h-3.5 border-2 border-t-transparent rounded-full animate-spin ${
                  aiMode ? "border-purple-400" : "border-blue-400"
                }`}
              />
            </div>
          )}
          {!loading && query && (
            <button
              onClick={clearSearch}
              title="Wyczyść"
              className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>

        {/* AI toggle button */}
        <button
          onClick={toggleAiMode}
          title={aiMode ? "Wyłącz AI Search" : "Włącz AI Search (semantyczne)"}
          className={`flex items-center gap-1 px-2.5 py-2 rounded-xl text-xs font-semibold border transition-all duration-200 shrink-0 ${
            aiMode
              ? "bg-purple-600 border-purple-600 text-white shadow-[0_0_10px_2px_rgba(168,85,247,0.4)] hover:bg-purple-700"
              : "bg-white dark:bg-gray-800 border-gray-200 dark:border-gray-600 text-gray-500 dark:text-gray-400 hover:border-purple-400 hover:text-purple-500 dark:hover:text-purple-400"
          }`}
        >
          <Sparkles className="w-3.5 h-3.5" />
          <span className="hidden sm:inline">AI</span>
        </button>
      </div>

      {/* AI mode indicator */}
      {aiMode && (
        <div className="flex items-center gap-1.5 mt-1 ml-1">
          <Sparkles className="w-3 h-3 text-purple-500" />
          <span className="text-xs text-purple-500 font-medium">
            AI Search aktywny
            {searchType === "text_fallback" && (
              <span className="text-gray-400 font-normal ml-1">(fallback tekstowy)</span>
            )}
          </span>
        </div>
      )}

      {/* Dropdown */}
      {open && (
        <div className="absolute top-full mt-1.5 left-0 right-0 bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 shadow-xl z-50 overflow-hidden max-h-[80vh] overflow-y-auto">

          {/* --- Semantic results --- */}
          {aiMode && (
            <>
              {!hasSemanticResults && !loading && (
                <div className="px-4 py-6 text-center text-sm text-gray-400 dark:text-gray-500">
                  Brak wyników AI dla „{debouncedQuery}"
                </div>
              )}
              {hasSemanticResults && (
                <div>
                  <div className="flex items-center gap-1.5 px-3 pt-2.5 pb-1 text-xs font-semibold text-purple-500 dark:text-purple-400 uppercase tracking-wide">
                    <Sparkles className="w-3.5 h-3.5" />
                    Kandydaci — AI
                  </div>
                  {semanticResults!.results.map((hit) => (
                    <button
                      key={hit.candidate.id}
                      onClick={() => handleSelect(`/candidates/${hit.candidate.id}`)}
                      className="w-full flex items-start gap-3 px-3 py-2 hover:bg-purple-50 dark:hover:bg-purple-900/30 transition-colors text-left group"
                    >
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <p className="text-sm font-medium text-gray-900 dark:text-gray-100 group-hover:text-purple-700 dark:group-hover:text-purple-400 truncate">
                            {hit.candidate.name} {hit.candidate.lastname}
                          </p>
                          {hit.score !== null && hit.score !== undefined && (
                            <span className="shrink-0 inline-flex items-center px-1.5 py-0.5 rounded-full text-[10px] font-semibold bg-purple-100 dark:bg-purple-900/50 text-purple-700 dark:text-purple-300">
                              {Math.round(hit.score * 100)}%
                            </span>
                          )}
                        </div>
                        {hit.highlight && (
                          <p className="text-xs text-gray-400 dark:text-gray-500 truncate">{hit.highlight}</p>
                        )}
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </>
          )}

          {/* --- Text results (grouped) --- */}
          {!aiMode && (
            <>
              {!hasTextResults && !loading && (
                <div className="px-4 py-6 text-center text-sm text-gray-400 dark:text-gray-500">
                  Brak wyników dla „{debouncedQuery}"
                </div>
              )}
              {groups.map((group) => (
                <ResultGroup
                  key={group.key}
                  icon={group.icon}
                  label={group.label}
                  count={
                    group.key === "candidates" ? results!.candidates.length :
                    group.key === "jobs" ? results!.jobs.length :
                    group.key === "clients" ? results!.clients.length :
                    (results!.contacts?.length ?? 0)
                  }
                  items={group.items}
                  allHref={group.allHref}
                  activeIndex={activeIndex}
                  startIdx={group.startIdx}
                  onSelect={handleSelect}
                />
              ))}
            </>
          )}
        </div>
      )}
    </div>
  );
}

function ResultGroup({
  icon,
  label,
  count,
  items,
  allHref,
  activeIndex,
  startIdx,
  onSelect,
}: {
  icon: React.ReactNode;
  label: string;
  count: number;
  items: { id: number; name: string; subtitle: string; url: string }[];
  allHref: string;
  activeIndex: number;
  startIdx: number;
  onSelect: (url: string) => void;
}) {
  return (
    <div>
      {/* Group header */}
      <div className="flex items-center justify-between px-3 pt-2.5 pb-1">
        <div className="flex items-center gap-1.5 text-xs font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-wide">
          {icon}
          {label}
          <span className="ml-1 inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400 text-[10px] font-bold normal-case tracking-normal">
            {count}
          </span>
        </div>
        <a
          href={allHref}
          onClick={(e) => { e.preventDefault(); onSelect(allHref); }}
          className="text-[11px] text-blue-500 hover:underline font-medium"
        >
          Zobacz wszystkie →
        </a>
      </div>
      {/* Items */}
      {items.map((item, i) => {
        const globalItemIdx = startIdx + i;
        const isActive = globalItemIdx === activeIndex;
        return (
          <button
            key={item.id}
            onClick={() => onSelect(item.url)}
            className={`w-full flex items-start gap-3 px-3 py-2 transition-colors text-left group ${
              isActive
                ? "bg-blue-50 dark:bg-blue-900/30"
                : "hover:bg-blue-50 dark:hover:bg-blue-900/30"
            }`}
          >
            <div className="flex-1 min-w-0">
              <p className={`text-sm font-medium truncate ${
                isActive ? "text-blue-700 dark:text-blue-400" : "text-gray-900 dark:text-gray-100 group-hover:text-blue-700 dark:group-hover:text-blue-400"
              }`}>
                {item.name}
              </p>
              {item.subtitle && (
                <p className="text-xs text-gray-400 dark:text-gray-500 truncate">{item.subtitle}</p>
              )}
            </div>
          </button>
        );
      })}
    </div>
  );
}
