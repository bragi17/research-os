"use client";

import { ArrowDown, ArrowUp } from "lucide-react";

export default function ResultPageNav() {
  const scrollToTop = () => {
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const scrollToBottom = () => {
    window.scrollTo({
      top: document.documentElement.scrollHeight,
      behavior: "smooth",
    });
  };

  const controls = (
    <>
      <button
        type="button"
        onClick={scrollToTop}
        className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-primary)]/95 text-[var(--text-muted)] shadow-sm transition-colors hover:border-[var(--accent)] hover:bg-[var(--accent-soft)] hover:text-[var(--accent)]"
        title="Back to top"
        aria-label="Back to top"
      >
        <ArrowUp className="h-4 w-4" aria-hidden="true" />
      </button>
      <button
        type="button"
        onClick={scrollToBottom}
        className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-primary)]/95 text-[var(--text-muted)] shadow-sm transition-colors hover:border-[var(--accent)] hover:bg-[var(--accent-soft)] hover:text-[var(--accent)]"
        title="Go to bottom"
        aria-label="Go to bottom"
      >
        <ArrowDown className="h-4 w-4" aria-hidden="true" />
      </button>
    </>
  );

  return (
    <>
      <div className="fixed right-4 top-1/2 z-30 hidden -translate-y-1/2 flex-col gap-2 md:flex">
        {controls}
      </div>
      <div className="fixed bottom-5 right-5 z-30 flex gap-2 md:hidden">
        {controls}
      </div>
    </>
  );
}
