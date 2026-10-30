"use client";

import { useState } from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { Menu, X } from "lucide-react";

import { Logo, NavLinks } from "@/components/app-sidebar";
import { useI18n } from "@/i18n";

/** Phones and small tablets: the sidebar as a slide-in drawer behind a menu button. */
export function MobileNav() {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  return (
    <DialogPrimitive.Root open={open} onOpenChange={setOpen}>
      <DialogPrimitive.Trigger
        className="-ml-1 rounded-md p-1.5 text-muted-foreground hover:bg-secondary hover:text-foreground md:hidden"
        aria-label={t("nav.open")}
      >
        <Menu className="size-5" aria-hidden />
      </DialogPrimitive.Trigger>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/50 data-[state=open]:animate-in data-[state=open]:fade-in-0" />
        <DialogPrimitive.Content className="fixed inset-y-0 left-0 z-50 flex w-72 max-w-[85vw] flex-col bg-sidebar text-sidebar-foreground shadow-xl outline-none data-[state=open]:animate-in data-[state=open]:slide-in-from-left">
          <div className="flex h-12 items-center justify-between border-b border-sidebar-border px-4">
            <DialogPrimitive.Title asChild>
              <span>
                <Logo />
              </span>
            </DialogPrimitive.Title>
            <DialogPrimitive.Description className="sr-only">
              {t("nav.main")}
            </DialogPrimitive.Description>
            <DialogPrimitive.Close
              className="rounded p-1 opacity-80 hover:opacity-100"
              aria-label={t("common.close")}
            >
              <X className="size-4" aria-hidden />
            </DialogPrimitive.Close>
          </div>
          <NavLinks onNavigate={() => setOpen(false)} />
          <p className="border-t border-sidebar-border px-4 py-3 text-[11px] opacity-60">
            {t("app.tagline")}
          </p>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
