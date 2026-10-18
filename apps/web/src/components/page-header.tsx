import { GlobalShortcuts } from "@/components/shortcuts";
import { SapStatusIndicator } from "@/components/sap-status";

/** Top bar of every page: title, page actions, SAP connection status, shortcut help. */
export function PageHeader({
  title,
  meta,
  children,
}: {
  title: React.ReactNode;
  meta?: React.ReactNode;
  children?: React.ReactNode;
}) {
  return (
    <header className="flex h-12 shrink-0 items-center gap-3 border-b bg-card px-4 print:hidden">
      <h1 className="shrink-0 text-sm font-semibold tracking-tight whitespace-nowrap">{title}</h1>
      {meta && <div className="flex min-w-0 items-center gap-2">{meta}</div>}
      <div className="ml-auto flex items-center gap-2">
        {children}
        <SapStatusIndicator />
        <GlobalShortcuts />
      </div>
    </header>
  );
}
