import {
  Inbox,
  LayoutDashboard,
  Package,
  RefreshCw,
  Settings,
  FileText,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  slug: string;
  label: string;
  icon: LucideIcon;
}

export const NAV_ITEMS: NavItem[] = [
  { slug: "", label: "Dashboard", icon: LayoutDashboard },
  { slug: "inbound", label: "Inbound Requests", icon: Inbox },
  { slug: "quotes", label: "Quotes", icon: FileText },
  { slug: "catalog", label: "Parts Catalog", icon: Package },
  { slug: "erp-sync", label: "ERP Sync", icon: RefreshCw },
  { slug: "settings", label: "Settings", icon: Settings },
];
