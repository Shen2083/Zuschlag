"use client";

import { useEffect } from "react";

import { MobileNav } from "@/components/mobile-nav";
import { GlobalShortcuts } from "@/components/shortcuts";
import { SapStatusIndicator } from "@/components/sap-status";

/**
 * Top bar of every page: title, page actions, SAP connection status, shortcut help.
 * `documentTitle` sets the browser tab title in the current language.
 */
export function PageHeader({
  title,
  documentTitle,
  meta,
  children,
}: {
  title: React.ReactNode;
  documentTitle?: string;
  meta?: React.ReactNode;
  children?: React.ReactNode;
}) {
  useEffect(() => {
    if (documentTitle) document.title = `${documentTitle} · Zuschlag.ai`;
  }, [documentTitle]);

  return (
    <header className="flex min-h-12 shrink-0 flex-wrap items-center gap-x-3 gap-y-1 border-b bg-card px-3 py-1.5 sm:px-4 print:hidden">
      <MobileNav />
      <h1 className="min-w-0 text-sm font-semibold tracking-tight">{title}</h1>
      {meta && <div className="flex min-w-0 items-center gap-2">{meta}</div>}
      <div className="ml-auto flex items-center gap-2">
        {children}
        <SapStatusIndicator />
        <GlobalShortcuts />
      </div>
    </header>
  );
}
