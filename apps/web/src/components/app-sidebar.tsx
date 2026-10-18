"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Factory } from "lucide-react";

import { Kbd } from "@/components/ui/input";
import { useI18n } from "@/i18n";
import { NAV_ITEMS } from "@/lib/nav";
import { cn } from "@/lib/utils";

export function AppSidebar() {
  const pathname = usePathname();
  const { t } = useI18n();

  return (
    <aside className="hidden w-60 shrink-0 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground md:flex print:hidden">
      <div className="flex h-12 items-center gap-2.5 border-b border-sidebar-border px-4">
        <div className="flex size-7 items-center justify-center rounded-md bg-sidebar-accent">
          <Factory className="size-4 text-sidebar-primary" aria-hidden />
        </div>
        <span className="text-sm font-semibold tracking-tight text-white">
          Zuschlag<span className="text-sidebar-primary">.ai</span>
        </span>
      </div>

      <nav aria-label={t("nav.main")} className="flex-1 space-y-0.5 p-2">
        {NAV_ITEMS.map(({ href, label, icon: Icon, key }) => {
          const active = pathname === href || pathname.startsWith(`${href}/`);
          return (
            <Link
              key={href}
              href={href}
              aria-current={active ? "page" : undefined}
              aria-keyshortcuts={`g ${key}`}
              className={cn(
                "group flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[13px] transition-colors focus-visible:ring-2 focus-visible:ring-sidebar-primary focus-visible:outline-none",
                active
                  ? "bg-sidebar-accent font-medium text-sidebar-accent-foreground"
                  : "hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground",
              )}
            >
              <Icon
                className={cn("size-4", active ? "text-sidebar-primary" : "opacity-70")}
                aria-hidden
              />
              <span className="flex-1 truncate">{t(label)}</span>
              <Kbd className="hidden border-sidebar-border bg-transparent text-[10px] text-sidebar-foreground opacity-60 group-hover:inline-flex">
                g {key}
              </Kbd>
            </Link>
          );
        })}
      </nav>

      <p className="border-t border-sidebar-border px-4 py-3 text-[11px] opacity-60">
        {t("app.tagline")}
      </p>
    </aside>
  );
}
