"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Keyboard } from "lucide-react";

import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Kbd } from "@/components/ui/input";
import { useI18n, type MessageKey } from "@/i18n";
import { isTyping } from "@/lib/keyboard";
import { NAV_ITEMS } from "@/lib/nav";

const STUDIO: Array<[string[], MessageKey]> = [
  [["↑", "↓", "←", "→"], "shortcuts.tableNav"],
  [["Enter", "F2"], "shortcuts.tableEdit"],
  [["Enter"], "shortcuts.tableCommit"],
  [["Esc"], "shortcuts.tableCancel"],
  [["Space"], "shortcuts.expand"],
  [["z"], "shortcuts.zuschlag"],
  [["⇧", "A"], "shortcuts.approve"],
  [["⇧", "S"], "shortcuts.sync"],
  [["⇧", "P"], "shortcuts.print"],
  [["⇧", "R"], "shortcuts.reparse"],
];

/** Global shortcuts: "g" + key navigates, "/" focuses search, "?" shows this help. */
export function GlobalShortcuts() {
  const router = useRouter();
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const pendingG = useRef<number | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || isTyping(e) || e.metaKey || e.ctrlKey || e.altKey) return;
      if (document.querySelector("[role=dialog][data-state=open]")) return;
      if (pendingG.current !== null) {
        window.clearTimeout(pendingG.current);
        pendingG.current = null;
        const target = NAV_ITEMS.find((n) => n.key === e.key.toLowerCase());
        if (target) {
          e.preventDefault();
          router.push(target.href);
        }
        return;
      }
      if (e.key === "g") {
        pendingG.current = window.setTimeout(() => (pendingG.current = null), 1200);
      } else if (e.key === "?") {
        e.preventDefault();
        setOpen(true);
      } else if (e.key === "/") {
        const search = document.querySelector<HTMLInputElement>("[data-search]");
        if (search) {
          e.preventDefault();
          search.focus();
          search.select();
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [router]);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="hidden h-7 items-center gap-1.5 rounded-md border bg-card px-2 text-xs text-muted-foreground hover:text-foreground sm:flex"
        aria-label={t("shortcuts.open")}
        aria-keyshortcuts="?"
      >
        <Keyboard className="size-3.5" aria-hidden />
        <Kbd>?</Kbd>
      </button>
      <DialogContent closeLabel={t("common.close")} className="max-w-xl">
        <DialogTitle>{t("shortcuts.title")}</DialogTitle>
        <DialogDescription className="sr-only">{t("shortcuts.title")}</DialogDescription>
        <div className="grid gap-6 overflow-y-auto sm:grid-cols-2">
          <section>
            <h3 className="mb-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
              {t("shortcuts.global")}
            </h3>
            <dl className="space-y-1.5 text-sm">
              {NAV_ITEMS.map((n) => (
                <Row
                  key={n.href}
                  keys={["g", n.key]}
                  label={`${t("shortcuts.goTo")} ${t(n.label)}`}
                />
              ))}
              <Row keys={["/"]} label={t("shortcuts.search")} />
              <Row keys={["?"]} label={t("shortcuts.help")} />
            </dl>
          </section>
          <section>
            <h3 className="mb-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
              {t("shortcuts.studio")}
            </h3>
            <dl className="space-y-1.5 text-sm">
              {STUDIO.map(([keys, label]) => (
                <Row key={label} keys={keys} label={t(label)} />
              ))}
            </dl>
          </section>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function Row({ keys, label }: { keys: string[]; label: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt>{label}</dt>
      <dd className="flex shrink-0 gap-1">
        {keys.map((k) => (
          <Kbd key={k}>{k}</Kbd>
        ))}
      </dd>
    </div>
  );
}
