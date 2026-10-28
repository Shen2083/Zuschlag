"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { DEMO } from "@/lib/demo/config";
import type { Locale } from "@/lib/format";
import { MESSAGES, type Messages } from "@/i18n/messages";

type Leaves<T, P extends string = ""> = {
  [K in keyof T & string]: T[K] extends string ? `${P}${K}` : Leaves<T[K], `${P}${K}.`>;
}[keyof T & string];
export type MessageKey = Leaves<Messages>;
export type Translate = (key: MessageKey, params?: Record<string, string | number>) => string;

export function translate(locale: Locale): Translate {
  const messages = MESSAGES[locale];
  return (key, params) => {
    let node: unknown = messages;
    for (const part of key.split(".")) node = (node as Record<string, unknown>)?.[part];
    let text = typeof node === "string" ? node : key;
    for (const [name, value] of Object.entries(params ?? {})) {
      text = text.replaceAll(`{${name}}`, String(value));
    }
    return text;
  };
}

const I18nContext = createContext<{ locale: Locale; t: Translate }>({
  locale: "de",
  t: translate("de"),
});

export function I18nProvider({
  locale: initial,
  children,
}: {
  locale: Locale;
  children: React.ReactNode;
}) {
  const [locale, setLocale] = useState(initial);
  // The static demo is rendered without a request, so it reads the cookie in the browser.
  useEffect(() => {
    if (!DEMO) return;
    const chosen = /(?:^|; )locale=(de|en)/.exec(document.cookie)?.[1] as Locale | undefined;
    if (chosen && chosen !== initial) setLocale(chosen);
  }, [initial]);
  const value = useMemo(() => ({ locale, t: translate(locale) }), [locale]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  return useContext(I18nContext);
}

/** Switch language: stored in a cookie so server-rendered HTML matches. */
export function useSetLocale() {
  return useCallback((locale: Locale) => {
    document.cookie = `locale=${locale}; path=/; max-age=31536000; samesite=lax`;
    window.location.reload();
  }, []);
}
