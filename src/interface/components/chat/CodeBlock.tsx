/**
 * Syntax-highlighted code block for `text/x-{lang}` parts.
 *
 * Uses shiki with a lazily-created highlighter. While shiki is loading
 * (first call only), we render the code as plain `<pre>` so streaming
 * doesn't stall behind the highlighter import.
 *
 * sensitivity_tier: varies
 */

import { useEffect, useMemo, useState } from "react";
import { Check, Copy } from "lucide-react";
import type { ArtifactRendererProps } from "./registry";

type Highlighter = {
  codeToHtml: (
    code: string,
    options: { lang: string; theme: string },
  ) => string;
};

let highlighterPromise: Promise<Highlighter> | null = null;

const SUPPORTED_LANGS = new Set([
  "bash",
  "c",
  "cpp",
  "css",
  "diff",
  "go",
  "graphql",
  "html",
  "java",
  "javascript",
  "json",
  "jsx",
  "kotlin",
  "lua",
  "markdown",
  "python",
  "ruby",
  "rust",
  "shell",
  "sh",
  "sql",
  "swift",
  "toml",
  "tsx",
  "typescript",
  "xml",
  "yaml",
]);

const LANG_ALIASES: Record<string, string> = {
  js: "javascript",
  ts: "typescript",
  py: "python",
  rb: "ruby",
  rs: "rust",
  zsh: "shell",
  shellscript: "shell",
};

function resolveLang(raw: string): string {
  const lc = raw.toLowerCase();
  const aliased = LANG_ALIASES[lc] ?? lc;
  return SUPPORTED_LANGS.has(aliased) ? aliased : "text";
}

async function getHighlighter(): Promise<Highlighter> {
  if (highlighterPromise) return highlighterPromise;
  highlighterPromise = (async () => {
    const shiki = await import("shiki");
    const hl = await shiki.createHighlighter({
      themes: ["github-dark"],
      langs: Array.from(SUPPORTED_LANGS),
    });
    return hl as unknown as Highlighter;
  })();
  return highlighterPromise;
}

function langFromMime(mime: string): string {
  if (!mime.startsWith("text/x-")) return "text";
  return resolveLang(mime.slice("text/x-".length));
}

export function CodeBlock({ part }: ArtifactRendererProps) {
  const code = useMemo(
    () => (typeof part.data === "string" ? part.data : String(part.data ?? "")),
    [part.data],
  );
  const lang = useMemo(() => langFromMime(part.mime), [part.mime]);
  const [html, setHtml] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let mounted = true;
    void getHighlighter()
      .then((hl) => {
        if (!mounted) return;
        try {
          setHtml(hl.codeToHtml(code, { lang, theme: "github-dark" }));
        } catch {
          setHtml(null);
        }
      })
      .catch(() => {
        if (mounted) setHtml(null);
      });
    return () => {
      mounted = false;
    };
  }, [code, lang]);

  const onCopy = () => {
    void navigator.clipboard.writeText(code);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="group relative my-2">
      <div className="absolute right-1 top-1 flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
        <button
          onClick={onCopy}
          title={copied ? "Copied" : "Copy code"}
          className="rounded-1 bg-surface-2/80 p-1 text-muted hover:text-ink"
        >
          {copied ? (
            <Check className="h-3.5 w-3.5 text-success" strokeWidth={1.6} />
          ) : (
            <Copy className="h-3.5 w-3.5" strokeWidth={1.6} />
          )}
        </button>
      </div>
      <div className="rounded-2 bg-[#0d1117] text-xs leading-relaxed">
        <div className="border-b border-hairline/50 px-3 py-1 font-mono text-[10px] uppercase tracking-wide text-muted">
          {lang}
        </div>
        {html ? (
          <div
            className="overflow-x-auto px-3 py-2 [&_pre]:!bg-transparent [&_pre]:!p-0 [&_pre]:!m-0"
            dangerouslySetInnerHTML={{ __html: html }}
          />
        ) : (
          <pre className="overflow-x-auto px-3 py-2 font-mono text-xs text-ink">
            {code}
          </pre>
        )}
      </div>
    </div>
  );
}
