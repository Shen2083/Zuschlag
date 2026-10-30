"use client";

import Link from "next/link";
import { FileQuestion } from "lucide-react";

import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/i18n";
import { DEMO } from "@/lib/demo/config";

export function NotFound() {
  const { t } = useI18n();
  return (
    <>
      <PageHeader title={t("notFound.title")} documentTitle={t("notFound.title")} />
      <div className="flex flex-1 flex-col items-center justify-center gap-3 p-8 text-center">
        <FileQuestion className="size-10 text-muted-foreground" aria-hidden />
        <h2 className="text-base font-semibold">{t("notFound.title")}</h2>
        <p className="max-w-md text-muted-foreground">
          {t("notFound.body")} {DEMO && t("notFound.demo")}
        </p>
        <div className="mt-2 flex gap-2">
          <Button asChild size="sm">
            <Link href="/quotes">{t("notFound.quotes")}</Link>
          </Button>
          <Button asChild size="sm" variant="outline">
            <Link href="/rfqs">{t("nav.rfqs")}</Link>
          </Button>
        </div>
      </div>
    </>
  );
}
