/**
 * Sandboxed HTML/JS renderer for `text/html` parts.
 *
 * - <iframe sandbox="allow-scripts" srcdoc=…> with no same-origin and
 *   no top navigation. Cookies and storage are blocked by the lack of
 *   allow-same-origin. The iframe cannot read window.parent.
 * - referrerpolicy="no-referrer" — no leaking the chat URL.
 * - Tier 3 content is refused; we show a "preview blocked" card with a
 *   "Show source" reveal that switches to a read-only code block.
 *
 * Iframes auto-resize via a small bootstrap script that postMessage's
 * its scrollHeight on every animation frame.
 *
 * sensitivity_tier: varies (Tier 3 is hard-blocked from JS exec)
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { Lock } from "lucide-react";
import type { ArtifactRendererProps } from "./registry";

const RESIZE_BOOTSTRAP = `
<script>
(function(){
  function send() {
    try {
      var h = document.documentElement.scrollHeight;
      window.parent.postMessage({__sbResize: true, height: h}, '*');
    } catch(e) {}
  }
  window.addEventListener('load', send);
  var ro = new ResizeObserver(send);
  ro.observe(document.documentElement);
})();
</script>
`;

function buildSrcdoc(html: string): string {
  const hasHtmlTag = /<html[\s>]/i.test(html);
  const baseStyle = `
    <style>
      :root { color-scheme: dark; }
      body {
        font: 13px/1.5 ui-sans-serif, system-ui, sans-serif;
        color: #E0E7EE;
        background: #243447;
        margin: 8px;
      }
      a { color: #2E86AB; }
      *, *::before, *::after { box-sizing: border-box; }
    </style>
  `;
  if (hasHtmlTag) return `${baseStyle}${html}${RESIZE_BOOTSTRAP}`;
  return `<!doctype html><html><head>${baseStyle}</head><body>${html}${RESIZE_BOOTSTRAP}</body></html>`;
}

export function HtmlSandbox({ part }: ArtifactRendererProps) {
  const tier = part.sensitivity_tier ?? 2;
  const html = useMemo(
    () => (typeof part.data === "string" ? part.data : ""),
    [part.data],
  );
  const [showSource, setShowSource] = useState(false);
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const [height, setHeight] = useState<number>(120);

  useEffect(() => {
    if (tier >= 3) return;
    const onMessage = (event: MessageEvent) => {
      // Ignore messages whose origin is not the iframe's null origin.
      if (event.source !== iframeRef.current?.contentWindow) return;
      const data = event.data as { __sbResize?: boolean; height?: number };
      if (data && data.__sbResize && typeof data.height === "number") {
        setHeight(Math.min(800, Math.max(80, data.height + 12)));
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [tier]);

  if (tier >= 3) {
    return (
      <div className="space-y-2">
        <div className="flex items-start gap-2 rounded border border-amber/40 bg-amber-soft p-2 text-xs text-ink">
          <Lock strokeWidth={1.6} className="mt-0.5 h-3.5 w-3.5 shrink-0 text-danger" />
          <div>
            <p className="font-medium">Sensitive content — preview blocked.</p>
            <p className="mt-0.5 text-muted">
              HTML/JS rendering is disabled for Tier 3 (sensitive) content.
              You can still inspect the source.
            </p>
            <button
              onClick={() => setShowSource((s) => !s)}
              className="mt-1 text-[11px] text-indigo hover:underline"
            >
              {showSource ? "Hide source" : "Show source"}
            </button>
          </div>
        </div>
        {showSource && (
          <pre className="overflow-x-auto rounded bg-[#0d1117] p-2 font-mono text-[11px] text-ink">
            {html}
          </pre>
        )}
      </div>
    );
  }

  return (
    <iframe
      ref={iframeRef}
      title={part.title || "HTML preview"}
      sandbox="allow-scripts"
      referrerPolicy="no-referrer"
      srcDoc={buildSrcdoc(html)}
      style={{ width: "100%", height, border: 0, background: "transparent" }}
      className="rounded"
    />
  );
}
