import { useSyncExternalStore } from "react";
import { commonEn } from "./locales/common.en";
import { appEn } from "./locales/app.en";
import { dialogsEn } from "./locales/dialogs.en";
import { graphEn } from "./locales/graph.en";
import { inspectorsEn } from "./locales/inspectors.en";
import { notesEn } from "./locales/notes.en";
import { deliveryEn } from "./locales/delivery.en";
import { progressionEn } from "./locales/progression.en";

import { originsEn } from "./locales/origins.en";
import { focusEn } from "./locales/focus.en";

export type Locale = "en" | "zh-CN";
export const LANGUAGE_KEY = "exp-observer-language";
export const englishMessages: Readonly<Record<string, string>> = {
  ...originsEn,
  ...focusEn,
  ...dialogsEn,
  ...graphEn,
  ...inspectorsEn,
  ...notesEn,
  ...deliveryEn,
  ...progressionEn,
  ...appEn,
  ...commonEn,
};

export function preferredLocale(storage?: Pick<Storage, "getItem">): Locale {
  try {
    return storage?.getItem(LANGUAGE_KEY) === "zh-CN" ? "zh-CN" : "en";
  } catch {
    return "en";
  }
}

function initialLocale(): Locale {
  try {
    return preferredLocale(
      typeof localStorage === "undefined" ? undefined : localStorage,
    );
  } catch {
    return "en";
  }
}
let locale: Locale = initialLocale();
const listeners = new Set<() => void>();

export const getLocale = (): Locale => locale;
export const intlLocale = (): string => (locale === "en" ? "en-US" : "zh-CN");

function applyLocale(next: Locale) {
  locale = next;
  if (typeof document !== "undefined") document.documentElement.lang = next;
  listeners.forEach((listener) => listener());
}

export function setLocale(next: Locale) {
  if (next !== "en" && next !== "zh-CN") return;
  try {
    localStorage.setItem(LANGUAGE_KEY, next);
  } catch {
    // Language selection still works when browser storage is unavailable.
  }
  applyLocale(next);
}

const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
};

export function useLocale() {
  return {
    locale: useSyncExternalStore(subscribe, getLocale, getLocale),
    setLocale,
  };
}

export function translate(
  message: string,
  language: Locale,
  values: Record<string, string | number> = {},
): string {
  const template =
    language === "en" && Object.hasOwn(englishMessages, message)
      ? englishMessages[message]
      : message;
  return template.replace(/\{(\w+)\}/g, (match, key: string) =>
    Object.hasOwn(values, key) ? String(values[key]) : match,
  );
}

// Only application messages pass through t(). Research text and protocol IDs
// stay verbatim, so changing language cannot rewrite an experiment.
export const t = (
  message: string,
  values?: Record<string, string | number>,
): string => translate(message, locale, values);

if (typeof document !== "undefined") document.documentElement.lang = locale;
if (typeof window !== "undefined") {
  window.addEventListener("storage", (event) => {
    if (event.key === LANGUAGE_KEY || event.key === null) {
      applyLocale(event.newValue === "zh-CN" ? "zh-CN" : "en");
    }
  });
}
