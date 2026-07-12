import { Search, X } from "lucide-react";
import type { ChangeEvent, ReactNode } from "react";

/**
 * Lockverity filter bar.
 *
 * Renders a search input, a row of optional child filters, and a
 * "clear" affordance. The component is purely presentational; the
 * owning page owns state. Status is announced via `aria-live` so
 * screen-reader users know when filters change.
 */
export function FilterBar({
  search,
  onSearchChange,
  searchPlaceholder = "Search…",
  children,
  onClear,
  resultCount,
  resultLabel = "results",
  ariaLabel = "Filters",
}: {
  search: string;
  onSearchChange: (value: string) => void;
  searchPlaceholder?: string;
  children?: ReactNode;
  onClear?: () => void;
  resultCount?: number;
  resultLabel?: string;
  ariaLabel?: string;
}) {
  return (
    <div
      className="flex flex-col gap-3 rounded-md border border-ink-200 bg-white p-3 sm:flex-row sm:items-center sm:justify-between"
      role="region"
      aria-label={ariaLabel}
    >
      <div className="flex flex-1 flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative flex-1 sm:max-w-xs">
          <label htmlFor="filterbar-search" className="sr-only">
            Search
          </label>
          <Search
            aria-hidden="true"
            className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400"
          />
          <input
            id="filterbar-search"
            type="search"
            className="input pl-8"
            placeholder={searchPlaceholder}
            value={search}
            onChange={(e: ChangeEvent<HTMLInputElement>) => onSearchChange(e.target.value)}
            autoComplete="off"
          />
        </div>
        <div className="flex flex-wrap items-center gap-2">{children}</div>
      </div>
      <div className="flex items-center gap-3 text-sm text-ink-500">
        {typeof resultCount === "number" ? (
          <span aria-live="polite">
            {resultCount} {resultLabel}
          </span>
        ) : null}
        {onClear ? (
          <button
            type="button"
            onClick={onClear}
            className="btn-secondary"
            aria-label="Clear filters"
          >
            <X aria-hidden="true" className="h-4 w-4" />
            Clear
          </button>
        ) : null}
      </div>
    </div>
  );
}

export interface SelectFilterOption {
  value: string;
  label: string;
}

export function SelectFilter({
  id,
  label,
  value,
  onChange,
  options,
  className = "",
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: SelectFilterOption[];
  className?: string;
}) {
  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <label htmlFor={id} className="text-xs font-medium text-ink-500">
        {label}
      </label>
      <select
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-md border border-ink-200 bg-white px-2 py-1 text-sm text-ink-700 shadow-sm focus:border-accent-500 focus:outline-none focus:ring-1 focus:ring-accent-500"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}
