"use client";

import { useEffect, useState } from "react";

/**
 * Resolve CSS custom properties to concrete colors for SVG libraries that set
 * presentation attributes. Re-reads when the OS color scheme changes, so
 * charts follow light/dark mode like the rest of the page.
 */
export function useCssVars<T extends string>(names: readonly T[]): Record<T, string> {
  const read = () => {
    const style = typeof window === "undefined" ? null : getComputedStyle(document.documentElement);
    return Object.fromEntries(names.map((n) => [n, style?.getPropertyValue(`--${n}`).trim() || "currentColor"])) as Record<T, string>;
  };
  const [values, setValues] = useState<Record<T, string>>(read);

  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const update = () => setValues(read());
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
    // names is a constant list per call site
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return values;
}
