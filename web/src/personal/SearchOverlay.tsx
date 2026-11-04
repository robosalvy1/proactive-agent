import { Search, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { useI18n } from "@/i18n";
import { api, type SessionSearchResult } from "@/lib/api";
import { Glass } from "./Glass";
import { usePersonalCopy } from "./copy";

interface SearchOverlayProps {
  profile: string;
  onOpen: (sessionId: string) => void;
  onClose: () => void;
}

/** Strip the FTS highlight markers the backend wraps around matched terms. */
const plainSnippet = (snippet: string) => snippet.replace(/>>>|<<</g, "");

export function SearchOverlay({ profile, onOpen, onClose }: SearchOverlayProps) {
  const { t } = useI18n();
  const p = usePersonalCopy();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SessionSearchResult[] | null>(null);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => input.current?.focus(), []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    const q = query.trim();
    if (q.length < 2) return;
    let live = true;
    const timer = window.setTimeout(() => {
      api
        .searchSessions(q, profile)
        .then((r) => live && setResults(r.results.slice(0, 12)))
        .catch(() => live && setResults([]));
    }, 200);
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, [query, profile]);

  return (
    <div role="dialog" aria-modal aria-label={p.search} className="fixed inset-0 z-50 flex justify-center bg-slate-900/20 px-4 pt-[12vh] backdrop-blur-sm" onMouseDown={onClose}>
      <Glass className="personal-rise h-fit w-full max-w-xl overflow-hidden bg-white/80" onMouseDown={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-3 border-b border-neutral-200/70 px-5 py-4">
          <Search className="h-5 w-5 text-neutral-500" />
          <input
            ref={input}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={p.searchPlaceholder}
            className="flex-1 bg-transparent text-[17px] text-neutral-900 outline-none placeholder:text-neutral-500"
          />
          <button type="button" onClick={onClose} aria-label={t.common.close} className="rounded-full p-1 text-neutral-500 hover:bg-neutral-100">
            <X className="h-4 w-4" />
          </button>
        </div>
        {results && query.trim().length >= 2 && (
          <ul className="max-h-[50vh] overflow-y-auto p-2">
            {results.length === 0 && <li className="px-4 py-3 text-[15px] text-neutral-500">{p.searchEmpty}</li>}
            {results.map((r, i) => (
              <li key={`${r.session_id}-${i}`}>
                <button type="button" onClick={() => onOpen(r.lineage_root ?? r.session_id)} className="w-full rounded-2xl px-4 py-3 text-left hover:bg-white">
                  <div className="truncate text-[15px] font-medium text-neutral-900">{r.title || p.untitled}</div>
                  <div className="line-clamp-2 text-[14px] text-neutral-600">{plainSnippet(r.snippet)}</div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </Glass>
    </div>
  );
}
