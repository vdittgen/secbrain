import { useEffect } from "react";

type Theme = "dark" | "light";

function applyTheme(theme: Theme) {
  const root = document.documentElement;
  if (theme === "dark") {
    root.classList.add("dark");
  } else {
    root.classList.remove("dark");
  }
}

export function useTheme(theme: string | undefined) {
  useEffect(() => {
    applyTheme((theme ?? "light") as Theme);
  }, [theme]);
}

export function broadcastThemeChange(theme: string) {
  window.dispatchEvent(new CustomEvent("sb-theme-change", { detail: theme }));
}
