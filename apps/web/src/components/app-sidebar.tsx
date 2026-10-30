"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Factory } from "lucide-react";

import { Kbd } from "@/components/ui/input";
import { Tooltip } from "@/components/ui/tooltip";
import { useI18n } from "@/i18n";
import { NAV_ITEMS } from "@/lib/nav";
import { cn } from "@/lib/utils";

export function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <span className="flex items-center gap-2.5">
      <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-sidebar-accent">
        <Factory className="size-4 text-sidebar-primary" aria-hidden />
      </span>
      <span className={cn("text-sm font-semibold tracking-tight text-white", compact && "sr-only")}>
        Zuschlag<span className="text-sidebar-primary">.ai</span>
      </span>
    </span>
  );
}

/**
 * Navigation links, shared by the sidebar and the phone drawer.
 * `rail`: icons only (labels in tooltips) below 2xl, so the BOM table has room on laptops.
 */
export function NavLinks({
  rail = false,
  onNavigate,
}: {
  rail?: boolean;
  onNavigate?: () => void;
}) {
  const pathname = usePathname();
  const { t } = useI18n();
  return (
    <nav aria-label={t("nav.main")} className="flex-1 space-y-0.5 p-2">
      {NAV_ITEMS.map(({ href, label, icon: Icon, key }) => {
        const active = pathname === href || pathname.startsWith(`${href}/`);
        const link = (
          <Link
            key={href}
            href={href}
            onClick={onNavigate}
            aria-current={active ? "page" : undefined}
            aria-keyshortcuts={`g ${key}`}
            aria-label={rail ? t(label) : undefined}
            className={cn(
              "group flex items-center gap-2.5 rounded-md px-2.5 py-2 text-[13px] transition-colors focus-visible:ring-2 focus-visible:ring-sidebar-primary focus-visible:outline-none 2xl:py-1.5",
              rail && "justify-center px-0 2xl:justify-start 2xl:px-2.5",
              active
                ? "bg-sidebar-accent font-medium text-sidebar-accent-foreground"
                : "hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground",
            )}
          >
            <Icon
              className={cn("size-4 shrink-0", active ? "text-sidebar-primary" : "opacity-70")}
              aria-hidden
            />
            <span className={cn("flex-1 truncate", rail && "hidden 2xl:inline")}>{t(label)}</span>
            <Kbd
              className={cn(
                "hidden border-sidebar-border bg-transparent text-[10px] text-sidebar-foreground opacity-60",
                rail ? "2xl:group-hover:inline-flex" : "md:group-hover:inline-flex",
              )}
            >
              g {key}
            </Kbd>
          </Link>
        );
        return rail ? (
          <Tooltip key={href} content={<span className="2xl:hidden">{t(label)}</span>} side="right">
            {link}
          </Tooltip>
        ) : (
          link
        );
      })}
    </nav>
  );
}

export function AppSidebar() {
  const { t } = useI18n();
  return (
    <aside className="hidden w-14 shrink-0 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground md:flex 2xl:w-60 print:hidden">
      <div className="flex h-12 items-center justify-center border-b border-sidebar-border px-3 2xl:justify-start 2xl:px-4">
        <span className="2xl:hidden">
          <Logo compact />
        </span>
        <span className="hidden 2xl:inline">
          <Logo />
        </span>
      </div>
      <NavLinks rail />
      <p className="hidden border-t border-sidebar-border px-4 py-3 text-[11px] opacity-60 2xl:block">
        {t("app.tagline")}
      </p>
    </aside>
  );
}
