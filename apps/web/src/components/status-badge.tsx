"use client";

import type { QuoteStatus } from "@zuschlag/api-types";

import { Badge } from "@/components/ui/badge";
import { useI18n } from "@/i18n";

const VARIANT = {
  draft: "secondary",
  needs_review: "warning",
  approved: "success",
  synced: "accent",
} as const;

export function QuoteStatusBadge({ status }: { status: QuoteStatus }) {
  const { t } = useI18n();
  return <Badge variant={VARIANT[status]}>{t(`status.${status}`)}</Badge>;
}
