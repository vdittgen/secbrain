/**
 * Reusable loading state components for Arandu.
 *
 * Provides skeleton loaders for common UI patterns and a LoadingWrapper
 * that manages the loading → loaded → error state transition.
 *
 * sensitivity_tier: N/A (UI infrastructure)
 */

import type { ReactNode } from "react";

// ---------------------------------------------------------------------------
// Skeleton variants
// ---------------------------------------------------------------------------

interface SkeletonProps {
  readonly className?: string;
}

/** Base skeleton pulse element. */
export function Skeleton({ className = "" }: SkeletonProps) {
  return (
    <div className={`animate-pulse rounded-2 bg-surface ${className}`} />
  );
}

/** Skeleton for a stat card (used in QuickStatsRow). */
export function SkeletonCard() {
  return (
    <div className="rounded-4 border border-hairline bg-surface px-4 py-4">
      <Skeleton className="h-12 w-full" />
    </div>
  );
}

/** Skeleton for a list item row (events, messages). */
export function SkeletonListItem() {
  return <Skeleton className="h-14 w-full" />;
}

/** Skeleton for a table with header and N body rows. */
export function SkeletonTable({
  rows = 5,
}: {
  readonly rows?: number;
}) {
  return (
    <div className="space-y-2 p-4">
      <Skeleton className="h-8 w-full" />
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-12 w-full" />
      ))}
    </div>
  );
}

/** Skeleton for a chat message bubble. */
export function SkeletonChatMessage({
  isUser = false,
}: {
  readonly isUser?: boolean;
}) {
  return (
    <div
      className={`flex items-start gap-3 ${isUser ? "flex-row-reverse" : ""}`}
    >
      <Skeleton className="h-8 w-8 shrink-0 rounded-full" />
      <div className="max-w-[75%] space-y-2">
        <Skeleton className="h-4 w-48" />
        <Skeleton className="h-4 w-32" />
      </div>
    </div>
  );
}

/** Skeleton for a full-width content section with title. */
export function SkeletonSection() {
  return (
    <div className="space-y-3 rounded-4 border border-hairline bg-surface p-5">
      <Skeleton className="h-4 w-32" />
      <Skeleton className="h-16 w-full" />
      <Skeleton className="h-16 w-full" />
    </div>
  );
}

// ---------------------------------------------------------------------------
// LoadingWrapper
// ---------------------------------------------------------------------------

type LoadingStatus = "loading" | "loaded" | "error";

interface LoadingWrapperProps<T> {
  readonly status: LoadingStatus;
  readonly data: T | null;
  readonly error?: string | null;
  readonly skeleton: ReactNode;
  readonly children: (data: T) => ReactNode;
  readonly emptyMessage?: string;
}

/**
 * Renders skeleton, error, empty, or content based on loading status.
 *
 * Usage:
 *   <LoadingWrapper status={status} data={data} skeleton={<SkeletonTable />}>
 *     {(data) => <MyTable data={data} />}
 *   </LoadingWrapper>
 */
export function LoadingWrapper<T>({
  status,
  data,
  error,
  skeleton,
  children,
  emptyMessage = "No data to display.",
}: LoadingWrapperProps<T>) {
  if (status === "loading") return <>{skeleton}</>;

  if (status === "error") {
    return (
      <div className="flex items-center justify-center py-8 text-sm text-amber">
        {error ?? "Something went wrong."}
      </div>
    );
  }

  if (data === null || (Array.isArray(data) && data.length === 0)) {
    return (
      <p className="py-6 text-center text-sm text-muted">
        {emptyMessage}
      </p>
    );
  }

  return <>{children(data)}</>;
}
