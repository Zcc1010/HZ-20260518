"use client";

import { ThemeProvider as NextThemesProvider } from "next-themes";
import type { ReactNode } from "react";
import { BRAND_THEME_STORAGE_KEY } from "../lib/branding";

export function ThemeProvider({ children }: { children: ReactNode }) {
  return (
    <NextThemesProvider
      attribute="class"
      defaultTheme="light"
      enableSystem={false}
      storageKey={BRAND_THEME_STORAGE_KEY}
    >
      {children}
    </NextThemesProvider>
  );
}
