import {
  BookOpenCheck,
  Boxes,
  Building2,
  FileSpreadsheet,
  Inbox,
  Settings,
  type LucideIcon,
} from "lucide-react";

import type { MessageKey } from "@/i18n";

export interface NavItem {
  href: string;
  label: MessageKey;
  icon: LucideIcon;
  /** "g" then this key navigates here */
  key: string;
}

export const NAV_ITEMS: NavItem[] = [
  { href: "/rfqs", label: "nav.rfqs", icon: Inbox, key: "r" },
  { href: "/quotes", label: "nav.quotes", icon: FileSpreadsheet, key: "q" },
  { href: "/catalog", label: "nav.catalog", icon: Boxes, key: "m" },
  { href: "/customers", label: "nav.customers", icon: Building2, key: "k" },
  { href: "/audit", label: "nav.audit", icon: BookOpenCheck, key: "a" },
  { href: "/settings", label: "nav.settings", icon: Settings, key: "s" },
];
