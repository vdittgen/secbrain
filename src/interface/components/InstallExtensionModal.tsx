/**
 * Install Connector Modal — streamlined single-page flow for adding
 * MCP server connectors.
 *
 * Flow: paste command (or pick a popular one) → auto-discover →
 * review what it will do → confirm install.
 *
 * Loading states are inline (no separate wizard steps). The user sees
 * one continuous page that progressively reveals sections.
 *
 * sensitivity_tier: 1 (connector install is infrastructure metadata)
 */

import { useState, useCallback, useEffect, useMemo } from "react";
import {
  X,
  Loader2,
  CheckCircle2,
  AlertTriangle,
  Database,
  Shield,
  Terminal,
  ExternalLink,
  Plug,
  Search,
  Plus,
  Trash2,
  Key,
} from "lucide-react";
import { dedupInvoke } from "../utils/requestDedup";

// ---------------------------------------------------------------------------
// EnvRequirement — declared by Discover catalog entries
// ---------------------------------------------------------------------------

export interface EnvRequirement {
  readonly key: string;
  readonly label?: string;
  readonly helpUrl?: string;
}

// ---------------------------------------------------------------------------
// Types (match Rust DTOs)
// ---------------------------------------------------------------------------

interface ToolPreview {
  readonly tool_name: string;
  readonly tool_type: string;
  readonly target_table: string | null;
  readonly is_new_table: boolean;
  readonly field_count: number;
  readonly sensitivity_tiers: Readonly<Record<string, number>>;
  readonly confidence: number;
  readonly warnings: readonly string[];
}

interface InstallPreview {
  readonly server_name: string;
  readonly command: string;
  readonly args: readonly string[];
  readonly tools: readonly ToolPreview[];
  readonly data_tools: number;
  readonly action_tools: number;
  readonly new_tables: readonly string[];
  readonly existing_tables: readonly string[];
  readonly overall_confidence: number;
  readonly warnings: readonly string[];
}

interface InstallConfirmResult {
  readonly status: string;
  readonly connector_id: string;
  readonly tables_created: readonly string[];
  readonly tools_registered: number;
  readonly models_staged: number;
  readonly error: string | null;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function parseCommand(raw: string): { command: string; args: string[] } {
  const parts = raw.trim().split(/\s+/);
  return { command: parts[0] ?? "", args: parts.slice(1) };
}

function confidenceColor(c: number): string {
  if (c >= 0.8) return "text-success";
  if (c >= 0.5) return "text-amber";
  return "text-danger";
}

function tierLabel(tier: string): { label: string; cls: string } {
  switch (tier) {
    case "1": return { label: "Public", cls: "bg-success/15 text-success" };
    case "2": return { label: "Personal", cls: "bg-amber/15 text-amber" };
    case "3": return { label: "Sensitive", cls: "bg-danger/15 text-danger" };
    default: return { label: `Tier ${tier}`, cls: "bg-surface text-muted" };
  }
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface InstallExtensionModalProps {
  readonly open: boolean;
  readonly initialCommand?: string;
  readonly initialRequiresEnv?: ReadonlyArray<EnvRequirement>;
  readonly onClose: () => void;
  readonly onInstalled: () => void;
}

interface EnvRow {
  readonly id: string;
  readonly key: string;
  readonly value: string;
  readonly required: boolean;
  readonly label?: string;
  readonly helpUrl?: string;
}

function buildInitialEnvRows(
  requirements: ReadonlyArray<EnvRequirement> | undefined,
): EnvRow[] {
  if (!requirements || requirements.length === 0) return [];
  return requirements.map((r) => ({
    id: `req-${r.key}`,
    key: r.key,
    value: "",
    required: true,
    label: r.label,
    helpUrl: r.helpUrl,
  }));
}

function collectEnv(rows: ReadonlyArray<EnvRow>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const row of rows) {
    const key = row.key.trim();
    if (!key) continue;
    if (row.value === "") continue;
    out[key] = row.value;
  }
  return out;
}

// ---------------------------------------------------------------------------
// InstallExtensionModal
// ---------------------------------------------------------------------------

type Phase = "input" | "discovering" | "preview" | "installing" | "done" | "error";

function InstallExtensionModal({
  open,
  initialCommand,
  initialRequiresEnv,
  onClose,
  onInstalled,
}: InstallExtensionModalProps) {
  const hasInitial = Boolean(initialCommand);
  const hasRequiredEnv = (initialRequiresEnv?.length ?? 0) > 0;
  // When opened from the catalog with required env, stay on input so the
  // user can fill secrets before we try the handshake.
  const [phase, setPhase] = useState<Phase>(
    hasInitial && !hasRequiredEnv ? "discovering" : "input",
  );
  const [commandStr, setCommandStr] = useState(initialCommand ?? "");
  const [nameOverride] = useState("");
  const [envRows, setEnvRows] = useState<EnvRow[]>(() =>
    buildInitialEnvRows(initialRequiresEnv),
  );
  const [preview, setPreview] = useState<InstallPreview | null>(null);
  const [result, setResult] = useState<InstallConfirmResult | null>(null);
  const [error, setError] = useState("");

  const allRequiredFilled = useMemo(
    () => envRows.every((r) => !r.required || r.value.trim().length > 0),
    [envRows],
  );
  const customRowsValid = useMemo(
    () =>
      envRows.every(
        (r) =>
          r.required ||
          (r.key.trim() === "" && r.value === "") ||
          (r.key.trim() !== "" && /^[A-Z_][A-Z0-9_]*$/.test(r.key.trim())),
      ),
    [envRows],
  );
  const isValid =
    commandStr.trim().length > 0 && allRequiredFilled && customRowsValid;

  const updateRow = useCallback((id: string, patch: Partial<EnvRow>) => {
    setEnvRows((prev) =>
      prev.map((r) => (r.id === id ? { ...r, ...patch } : r)),
    );
  }, []);

  const addCustomRow = useCallback(() => {
    setEnvRows((prev) => [
      ...prev,
      {
        id: `custom-${Date.now()}-${prev.length}`,
        key: "",
        value: "",
        required: false,
      },
    ]);
  }, []);

  const removeRow = useCallback((id: string) => {
    setEnvRows((prev) => prev.filter((r) => r.id !== id || r.required));
  }, []);

  const discover = useCallback(
    async (cmd?: string, rowsOverride?: ReadonlyArray<EnvRow>) => {
      const raw = cmd ?? commandStr;
      if (!raw.trim()) return;
      setPhase("discovering");
      setError("");
      try {
        const { command, args } = parseCommand(raw);
        const env = collectEnv(rowsOverride ?? envRows);
        const p = await dedupInvoke<InstallPreview>(
          "install_extension_discover",
          {
            command,
            args,
            name: nameOverride || undefined,
            env: Object.keys(env).length > 0 ? env : undefined,
          },
        );
        setPreview(p);
        setPhase("preview");
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
        setPhase("error");
      }
    },
    [commandStr, nameOverride, envRows],
  );

  const install = useCallback(async () => {
    if (!preview) return;
    setPhase("installing");
    setError("");
    try {
      const env = collectEnv(envRows);
      const r = await dedupInvoke<InstallConfirmResult>(
        "install_extension_confirm",
        {
          previewJson: JSON.stringify(preview),
          name: nameOverride || undefined,
          env: Object.keys(env).length > 0 ? env : undefined,
        },
      );
      if (r.error) {
        setError(r.error);
        setPhase("error");
      } else {
        setResult(r);
        setPhase("done");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setPhase("error");
    }
  }, [preview, nameOverride, envRows]);

  // Auto-discover when opened with initialCommand AND no required env vars.
  useEffect(() => {
    if (hasInitial && !hasRequiredEnv && initialCommand) {
      void discover(initialCommand);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const reset = useCallback(() => {
    setPhase("input");
    setPreview(null);
    setResult(null);
    setError("");
  }, []);

  const handleClose = useCallback(() => {
    if (phase === "done") onInstalled();
    else onClose();
  }, [phase, onInstalled, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="relative flex max-h-[85vh] w-full max-w-2xl flex-col rounded-4 border border-hairline bg-bg-2 shadow-2xl">
        {/* Header */}
        <div className="flex shrink-0 items-center justify-between border-b border-hairline px-5 py-4">
          <div className="flex items-center gap-2">
            <Plug strokeWidth={1.6} className="h-4 w-4 text-indigo" />
            <h3 className="text-sm font-semibold text-ink">
              {phase === "done" ? "Connector Installed" : "Add Connector"}
            </h3>
          </div>
          <button
            onClick={handleClose}
            className="rounded-2 p-1.5 text-muted transition-colors hover:bg-surface hover:text-ink"
          >
            <X strokeWidth={1.6} className="h-4 w-4" />
          </button>
        </div>

        {/* Content */}
        <div className="min-h-0 overflow-y-auto px-5 py-4">
          {/* ---- Input phase ---- */}
          {phase === "input" && (
            <div className="space-y-4">
              <div>
                <div className="flex items-center gap-2 rounded-2 bg-surface px-3 py-2.5 ring-1 ring-hairline focus-within:ring-indigo">
                  <Search strokeWidth={1.6} className="h-4 w-4 shrink-0 text-muted" />
                  <input
                    type="text"
                    placeholder="npx -y @example/mcp-server"
                    value={commandStr}
                    onChange={(e) => setCommandStr(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && isValid) void discover();
                    }}
                    className="flex-1 bg-transparent font-mono text-sm text-ink placeholder-muted outline-none"
                    autoFocus={!hasRequiredEnv}
                  />
                  <button
                    onClick={() => void discover()}
                    disabled={!isValid}
                    className={`shrink-0 rounded-md px-3 py-1 text-xs font-medium transition-colors ${
                      isValid
                        ? "bg-indigo text-white hover:bg-indigo/90"
                        : "bg-hairline text-muted"
                    }`}
                  >
                    Connect
                  </button>
                </div>
                <div className="mt-2 flex items-center justify-between">
                  <p className="text-[10px] text-muted">
                    Paste the MCP server command. Arandu will connect and auto-detect capabilities.
                  </p>
                  <a
                    href="https://mcp.so"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex shrink-0 items-center gap-1 text-[10px] text-indigo hover:underline"
                  >
                    Browse MCP servers
                    <ExternalLink strokeWidth={1.6} className="h-2.5 w-2.5" />
                  </a>
                </div>
              </div>

              <EnvVarSection
                rows={envRows}
                onChange={updateRow}
                onAdd={addCustomRow}
                onRemove={removeRow}
              />
            </div>
          )}

          {/* ---- Discovering phase ---- */}
          {phase === "discovering" && (
            <div className="flex flex-col items-center gap-4 py-12">
              <Loader2 strokeWidth={1.6} className="h-8 w-8 animate-spin text-indigo" />
              <div className="text-center">
                <p className="text-sm font-medium text-ink">Connecting...</p>
                <p className="mt-1 text-[11px] text-muted">
                  Discovering tools and analyzing data structure
                </p>
              </div>
            </div>
          )}

          {/* ---- Preview phase ---- */}
          {phase === "preview" && preview && (
            <div className="space-y-4">
              {/* Server info */}
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-ink">{preview.server_name}</p>
                  <p className="font-mono text-[11px] text-muted">
                    {preview.command} {preview.args.join(" ")}
                  </p>
                </div>
                <span className={`text-xs font-medium ${confidenceColor(preview.overall_confidence)}`}>
                  {Math.round(preview.overall_confidence * 100)}% match
                </span>
              </div>

              {/* What it will do */}
              <div className="rounded-2 border border-hairline bg-surface/60 p-3">
                <p className="mb-2 text-xs font-medium text-ink">This connector will:</p>
                <div className="space-y-1.5">
                  {preview.data_tools > 0 && (
                    <div className="flex items-center gap-2 text-xs text-success">
                      <CheckCircle2 strokeWidth={1.6} className="h-3.5 w-3.5" />
                      Read data via {preview.data_tools} tool{preview.data_tools > 1 ? "s" : ""}
                    </div>
                  )}
                  {preview.new_tables.length > 0 && (
                    <div className="flex items-center gap-2 text-xs text-success">
                      <CheckCircle2 strokeWidth={1.6} className="h-3.5 w-3.5" />
                      Create {preview.new_tables.length} new table{preview.new_tables.length > 1 ? "s" : ""}:
                      {" "}{preview.new_tables.join(", ")}
                    </div>
                  )}
                  {preview.existing_tables.length > 0 && (
                    <div className="flex items-center gap-2 text-xs text-amber">
                      <AlertTriangle strokeWidth={1.6} className="h-3.5 w-3.5" />
                      Write to {preview.existing_tables.length} existing table{preview.existing_tables.length > 1 ? "s" : ""}
                    </div>
                  )}
                  {preview.action_tools > 0 && (
                    <div className="flex items-center gap-2 text-xs text-muted">
                      <Terminal strokeWidth={1.6} className="h-3.5 w-3.5" />
                      {preview.action_tools} action tool{preview.action_tools > 1 ? "s" : ""}
                    </div>
                  )}
                </div>
              </div>

              {/* Tools detail */}
              {preview.tools.length > 0 && (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs">
                    <thead>
                      <tr className="border-b border-hairline text-[11px] uppercase tracking-wider text-muted">
                        <th className="px-3 py-2">Tool</th>
                        <th className="px-3 py-2">Type</th>
                        <th className="px-3 py-2">Table</th>
                        <th className="px-3 py-2">Fields</th>
                        <th className="px-3 py-2">Sensitivity</th>
                      </tr>
                    </thead>
                    <tbody>
                      {preview.tools.map((tool) => (
                        <tr key={tool.tool_name} className="border-b border-hairline/30">
                          <td className="px-3 py-2 font-mono text-ink">{tool.tool_name}</td>
                          <td className="px-3 py-2">
                            <span
                              className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${
                                tool.tool_type === "data"
                                  ? "bg-indigo-soft text-indigo"
                                  : "bg-amber/15 text-amber"
                              }`}
                            >
                              {tool.tool_type}
                            </span>
                          </td>
                          <td className="px-3 py-2 text-muted">
                            {tool.target_table ? (
                              <span className="flex items-center gap-1">
                                <Database strokeWidth={1.6} className="h-3 w-3" />
                                {tool.target_table}
                                {tool.is_new_table && (
                                  <span className="rounded bg-success/15 px-1 py-0.5 text-[9px] font-semibold text-success">
                                    NEW
                                  </span>
                                )}
                              </span>
                            ) : "—"}
                          </td>
                          <td className="px-3 py-2 text-muted">{tool.field_count}</td>
                          <td className="px-3 py-2">
                            <div className="flex gap-1">
                              {Object.entries(tool.sensitivity_tiers).map(([tier, count]) => {
                                const { label, cls } = tierLabel(tier);
                                return (
                                  <span key={tier} className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${cls}`}>
                                    {count} {label}
                                  </span>
                                );
                              })}
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {/* Warnings */}
              {preview.warnings.length > 0 && (
                <div className="space-y-1">
                  {preview.warnings.map((w, i) => (
                    <div key={i} className="flex items-start gap-2 text-xs text-amber">
                      <AlertTriangle strokeWidth={1.6} className="mt-0.5 h-3 w-3 shrink-0" />
                      {w}
                    </div>
                  ))}
                </div>
              )}

              {/* Actions */}
              <div className="flex justify-end gap-2 border-t border-hairline pt-3">
                <button
                  onClick={reset}
                  className="rounded-2 px-4 py-2 text-xs text-muted transition-colors hover:text-ink"
                >
                  Back
                </button>
                <button
                  onClick={() => void install()}
                  className="flex items-center gap-1.5 rounded-2 bg-indigo px-4 py-2 text-xs font-medium text-white transition-colors hover:bg-indigo/90"
                >
                  <Shield strokeWidth={1.6} className="h-3.5 w-3.5" />
                  Install Connector
                </button>
              </div>
            </div>
          )}

          {/* ---- Installing phase ---- */}
          {phase === "installing" && (
            <div className="flex flex-col items-center gap-4 py-12">
              <Loader2 strokeWidth={1.6} className="h-8 w-8 animate-spin text-indigo" />
              <div className="text-center">
                <p className="text-sm font-medium text-ink">Installing...</p>
                <p className="mt-1 text-[11px] text-muted">
                  Creating tables and registering tools
                </p>
              </div>
            </div>
          )}

          {/* ---- Done phase ---- */}
          {phase === "done" && result && (
            <div className="space-y-4">
              <div className="flex flex-col items-center gap-3 py-4">
                <CheckCircle2 strokeWidth={1.6} className="h-10 w-10 text-success" />
                <p className="text-sm font-medium text-ink">Connector Installed</p>
              </div>
              <div className="space-y-2 rounded-2 border border-hairline bg-surface/60 p-3">
                <div className="flex justify-between text-xs">
                  <span className="text-muted">Connector</span>
                  <span className="font-mono text-ink">{result.connector_id}</span>
                </div>
                {result.tables_created.length > 0 && (
                  <div className="flex justify-between text-xs">
                    <span className="text-muted">Tables created</span>
                    <span className="text-ink">{result.tables_created.join(", ")}</span>
                  </div>
                )}
                <div className="flex justify-between text-xs">
                  <span className="text-muted">Tools</span>
                  <span className="text-ink">{result.tools_registered}</span>
                </div>
              </div>
              <div className="flex justify-end pt-2">
                <button
                  onClick={handleClose}
                  className="rounded-2 bg-indigo px-4 py-2 text-xs font-medium text-white transition-colors hover:bg-indigo/90"
                >
                  Done
                </button>
              </div>
            </div>
          )}

          {/* ---- Error phase ---- */}
          {phase === "error" && (
            <div className="space-y-4">
              <div className="flex flex-col items-center gap-3 py-4">
                <AlertTriangle strokeWidth={1.6} className="h-10 w-10 text-amber" />
                <p className="text-sm font-medium text-ink">Connection Failed</p>
              </div>
              <div className="rounded-2 border border-amber-soft bg-amber/5 px-4 py-3 text-xs text-amber">
                {error}
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <button
                  onClick={handleClose}
                  className="rounded-2 px-4 py-2 text-xs text-muted transition-colors hover:text-ink"
                >
                  Cancel
                </button>
                <button
                  onClick={reset}
                  className="rounded-2 bg-indigo px-4 py-2 text-xs font-medium text-white transition-colors hover:bg-indigo/90"
                >
                  Try Again
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// EnvVarSection — collects MCP server secrets (Tier 3) before discovery
// ---------------------------------------------------------------------------

interface EnvVarSectionProps {
  readonly rows: ReadonlyArray<EnvRow>;
  readonly onChange: (id: string, patch: Partial<EnvRow>) => void;
  readonly onAdd: () => void;
  readonly onRemove: (id: string) => void;
}

function EnvVarSection({ rows, onChange, onAdd, onRemove }: EnvVarSectionProps) {
  const hasRequired = rows.some((r) => r.required);
  const hasAny = rows.length > 0;

  return (
    <div className="rounded-2 border border-hairline bg-surface/40 p-3">
      <div className="mb-2 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Key strokeWidth={1.6} className="h-3.5 w-3.5 text-muted" />
          <p className="text-xs font-medium text-ink">
            Environment variables
          </p>
          {hasRequired && (
            <span className="rounded bg-amber/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-amber">
              Required
            </span>
          )}
        </div>
        <button
          onClick={onAdd}
          type="button"
          className="flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-muted transition-colors hover:bg-surface hover:text-ink"
        >
          <Plus strokeWidth={1.6} className="h-3 w-3" />
          Add variable
        </button>
      </div>

      {!hasAny && (
        <p className="text-[11px] text-muted">
          Optional. Add API tokens or other secrets the server needs at
          startup. Values are stored locally with the connector.
        </p>
      )}

      {hasAny && (
        <div className="space-y-2">
          {rows.map((row) => (
            <EnvRowField
              key={row.id}
              row={row}
              onChange={onChange}
              onRemove={onRemove}
            />
          ))}
        </div>
      )}
    </div>
  );
}

interface EnvRowFieldProps {
  readonly row: EnvRow;
  readonly onChange: (id: string, patch: Partial<EnvRow>) => void;
  readonly onRemove: (id: string) => void;
}

function EnvRowField({ row, onChange, onRemove }: EnvRowFieldProps) {
  return (
    <div className="space-y-1">
      <div className="flex items-center gap-2">
        {row.required ? (
          <div className="w-48 shrink-0 truncate font-mono text-[11px] text-ink">
            {row.key}
            <span className="ml-1 text-amber">*</span>
          </div>
        ) : (
          <input
            type="text"
            placeholder="KEY"
            value={row.key}
            onChange={(e) =>
              onChange(row.id, { key: e.target.value.toUpperCase() })
            }
            className="w-48 shrink-0 rounded-md bg-surface px-2 py-1 font-mono text-[11px] text-ink placeholder-muted outline-none ring-1 ring-hairline focus:ring-indigo"
          />
        )}
        <input
          type="password"
          placeholder={row.required ? "Required" : "value"}
          value={row.value}
          onChange={(e) => onChange(row.id, { value: e.target.value })}
          className="flex-1 rounded-md bg-surface px-2 py-1 font-mono text-[11px] text-ink placeholder-muted outline-none ring-1 ring-hairline focus:ring-indigo"
          autoFocus={row.required && row.value === ""}
        />
        {!row.required && (
          <button
            onClick={() => onRemove(row.id)}
            type="button"
            className="rounded p-1 text-muted transition-colors hover:bg-surface hover:text-amber"
            aria-label="Remove"
          >
            <Trash2 strokeWidth={1.6} className="h-3 w-3" />
          </button>
        )}
      </div>
      {(row.label || row.helpUrl) && (
        <div className="ml-50 flex items-center gap-2 pl-2 text-[10px] text-muted">
          {row.label && <span>{row.label}</span>}
          {row.helpUrl && (
            <a
              href={row.helpUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-0.5 text-indigo hover:underline"
            >
              How to get this
              <ExternalLink strokeWidth={1.6} className="h-2.5 w-2.5" />
            </a>
          )}
        </div>
      )}
    </div>
  );
}

export default InstallExtensionModal;
