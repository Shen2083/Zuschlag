"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Factory } from "lucide-react";

import { NAV_ITEMS } from "@/lib/nav";
import { cn } from "@/lib/utils";

export function AppSidebar() {
  const pathname = usePathname();

  return (
    <aside className="hidden w-60 shrink-0 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground md:flex">
      <div className="flex h-14 items-center gap-2.5 border-b border-sidebar-border px-5">
        <div className="flex size-8 items-center justify-center rounded-md bg-sidebar-accent">
          <Factory className="size-4 text-sidebar-primary" aria-hidden />
        </div>
        <span className="text-sm font-semibold tracking-tight text-white">
          Zuschlag<span className="text-sidebar-primary">.ai</span>
        </span>
      </div>

      <nav aria-label="Main" className="flex-1 space-y-0.5 p-3">
        {NAV_ITEMS.map(({ slug, label, icon: Icon }) => {
          const href = `/${slug}`;
          const active = pathname === href;
          return (
            <Link
              key={slug || "dashboard"}
              href={href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                active
                  ? "bg-sidebar-accent font-medium text-sidebar-accent-foreground"
                  : "hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground",
              )}
            >
              <Icon
                className={cn("size-4", active ? "text-sidebar-primary" : "opacity-70")}
                aria-hidden
              />
              {label}
            </Link>
          );
        })}
      </nav>

      <p className="border-t border-sidebar-border px-5 py-4 text-xs opacity-60">
        Hosted in the EU · GoBD audit trail
      </p>
    </aside>
  );
}
