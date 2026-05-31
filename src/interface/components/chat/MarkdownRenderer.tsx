/**
 * Markdown renderer for `text/markdown` parts.
 *
 * Pipeline: react-markdown + remark-gfm (tables, strikethrough,
 * footnotes, autolinks) + remark-math + rehype-katex + rehype-sanitize.
 * Sanitization happens AFTER raw HTML is converted, and the schema
 * blocks scripts, iframes, on* event handlers, and javascript: URLs.
 *
 * `code` is overridden to dispatch fenced code blocks to <CodeBlock>
 * so they get syntax highlighting and a copy button. Links open in a
 * new window with no-referrer.
 *
 * sensitivity_tier: varies (delegates to the surrounding part)
 */

import { lazy, Suspense, useMemo } from "react";
import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import { ExternalLink } from "lucide-react";
import type { MessagePart } from "../../types/chat";
import type { ArtifactRendererProps } from "./registry";

// Lazy: shiki is heavy.
const CodeBlock = lazy(() =>
  import("./CodeBlock").then((m) => ({ default: m.CodeBlock })),
);

// Sanitization schema: GFM + math, no scripts / iframes / event handlers.
const SCHEMA = {
  ...defaultSchema,
  tagNames: [
    ...(defaultSchema.tagNames ?? []),
    "math",
    "semantics",
    "mrow",
    "mi",
    "mn",
    "mo",
    "mfrac",
    "msup",
    "msub",
    "msqrt",
    "annotation",
    "annotation-xml",
    "span",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "del",
  ],
  attributes: {
    ...defaultSchema.attributes,
    "*": [
      ...(defaultSchema.attributes?.["*"] ?? []),
      ["className", /^(?:hljs|language-|katex|math)[a-z0-9_-]*$/i],
      "ariaHidden",
    ],
    code: [["className", /^language-[a-z0-9-]+$/i]],
    span: [
      ["className", /^(?:katex|math)[a-z0-9_-]*$/i],
      "style",
    ],
  },
  protocols: {
    ...defaultSchema.protocols,
    href: ["http", "https", "mailto"],
    src: ["http", "https", "data"],
  },
};

const fencedLangFromClass = (className: string | undefined): string => {
  if (!className) return "";
  const match = /language-([a-z0-9-]+)/i.exec(className);
  return match ? match[1] : "";
};

export function MarkdownRenderer({ part }: ArtifactRendererProps) {
  const text = useMemo(
    () => (typeof part.data === "string" ? part.data : ""),
    [part.data],
  );

  const components = useMemo<Components>(
    () => ({
      a({ href, children, ...rest }) {
        return (
          <a
            {...rest}
            href={href}
            target="_blank"
            rel="noopener noreferrer nofollow"
            className="text-indigo underline-offset-2 hover:underline"
          >
            {children}
            <ExternalLink className="ml-0.5 inline h-3 w-3" strokeWidth={1.6} />
          </a>
        );
      },
      code({ inline, className, children }: {
        readonly inline?: boolean;
        readonly className?: string;
        readonly children?: React.ReactNode;
      } & React.HTMLAttributes<HTMLElement>) {
        const lang = fencedLangFromClass(className);
        const raw = String(children ?? "").replace(/\n$/, "");
        if (inline || !lang) {
          return (
            <code className="rounded-1 bg-bg-2 px-1 py-0.5 font-mono text-[12.5px] text-ink">
              {children}
            </code>
          );
        }
        const innerPart: MessagePart = {
          id: `${part.id}-fence-${lang}-${raw.length}`,
          mime: `text/x-${lang}`,
          data: raw,
          display: "inline",
          sensitivity_tier: part.sensitivity_tier ?? 2,
        };
        return (
          <Suspense
            fallback={
              <pre className="overflow-x-auto rounded-2 bg-bg-2 p-2 text-xs">
                {raw}
              </pre>
            }
          >
            <CodeBlock part={innerPart} />
          </Suspense>
        );
      },
      table({ children }) {
        return (
          <div className="my-2 overflow-x-auto">
            <table className="min-w-full border-collapse text-sm">{children}</table>
          </div>
        );
      },
      th({ children }) {
        return (
          <th className="border-b border-hairline bg-bg-2 px-2 py-1 text-left font-medium">
            {children}
          </th>
        );
      },
      td({ children }) {
        return (
          <td className="border-b border-hairline/60 px-2 py-1 align-top">
            {children}
          </td>
        );
      },
      blockquote({ children }) {
        return (
          <blockquote className="my-2 border-l-2 border-indigo/60 pl-3 italic text-muted">
            {children}
          </blockquote>
        );
      },
      ul({ children }) {
        return <ul className="my-1 list-disc pl-5">{children}</ul>;
      },
      ol({ children }) {
        return <ol className="my-1 list-decimal pl-5">{children}</ol>;
      },
      h1({ children }) {
        return <h1 className="mt-2 mb-1 text-base font-semibold">{children}</h1>;
      },
      h2({ children }) {
        return <h2 className="mt-2 mb-1 text-sm font-semibold">{children}</h2>;
      },
      h3({ children }) {
        return <h3 className="mt-2 mb-1 text-sm font-semibold">{children}</h3>;
      },
      strong({ children }) {
        return (
          <strong style={{ color: 'var(--indigo-2)', fontWeight: 600 }}>
            {children}
          </strong>
        );
      },
      hr() {
        return <hr className="my-3 border-hairline" />;
      },
    }),
    [part.id, part.sensitivity_tier],
  );

  return (
    <div className="prose prose-invert max-w-none text-sm leading-relaxed text-ink">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex, [rehypeSanitize, SCHEMA]]}
        components={components}
      >
        {text}
      </ReactMarkdown>
      {part.streaming && (
        <span className="ml-0.5 inline-block h-4 w-0.5 animate-pulse bg-indigo align-text-bottom" />
      )}
    </div>
  );
}
