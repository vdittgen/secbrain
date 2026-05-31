/**
 * Skills page — manage SKILL.md-based skills following the open standard.
 *
 * Skills are procedural knowledge that agents load via progressive
 * disclosure. Users can view, edit, create, and delete skills.
 * Auto-learned skills from the skill-creator agent appear in a
 * separate section with approve/reject controls.
 *
 * sensitivity_tier: 1
 */

import { useState, useCallback, useMemo } from "react";
import { invoke } from "@tauri-apps/api/core";
import {
  Zap,
  Search,
  Plus,
  ChevronDown,
  ChevronRight,
  Trash2,
  Edit3,
  Check,
  X,
  Loader2,
  Tag,
  Shield,
  Sparkles,
  BookOpen,
  Bot,
} from "lucide-react";
import { Skeleton } from "../components/LoadingState";
import { useAsyncData } from "../hooks/useAsyncData";
import { dedupInvoke } from "../utils/requestDedup";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

// sensitivity_tier: 1
interface SkillMeta {
  readonly id: string;
  readonly name: string;
  readonly description: string;
  readonly tags: readonly string[];
  readonly sensitivity_tier: number;
  readonly source: string;
  readonly version: number;
}

// sensitivity_tier: 1
interface SkillDetail extends SkillMeta {
  readonly instructions: string;
}

// sensitivity_tier: 1
interface AgentSkillInfo {
  readonly agent_id: string;
  readonly name: string;
  readonly editable: boolean;
  readonly enabled_skills: readonly string[];
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function tierDotColor(tier: number): string {
  switch (tier) {
    case 1: return "bg-success";
    case 2: return "bg-amber";
    case 3: return "bg-danger";
    default: return "bg-gray-500";
  }
}

function sourceLabel(source: string): { label: string; className: string } {
  switch (source) {
    case "builtin":
      return { label: "Built-in", className: "bg-surface text-muted" };
    case "auto-learned":
      return { label: "Auto-learned", className: "bg-indigo-soft text-indigo" };
    default:
      return { label: "User", className: "bg-indigo-soft text-indigo" };
  }
}

const SKILL_TEMPLATE = `---
name: My New Skill
description: Describe when this skill should activate
version: 1
tags: []
sensitivity_tier: 1
source: user
resources: []  # optional: list relative paths to bundled files (templates, checklists, etc.)
---

## When to Use

Describe the situations where this skill applies.

## Procedure

1. Step one
2. Step two
3. Step three

If this skill has resource files, reference them like:
"Load the template from \`templates/my_template.md\` using \`load_skill_resource\`"

## Output Format

Describe the expected output structure.

## Pitfalls

- Things to watch out for
`;

// ---------------------------------------------------------------------------
// SkillCard
// ---------------------------------------------------------------------------

function SkillCard({
  skill,
  agents,
  onRefresh,
}: {
  readonly skill: SkillMeta;
  readonly agents: readonly AgentSkillInfo[];
  readonly onRefresh: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [detail, setDetail] = useState<SkillDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editContent, setEditContent] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const toggleExpand = useCallback(async () => {
    if (expanded) {
      setExpanded(false);
      setEditing(false);
      return;
    }
    if (detail) {
      setExpanded(true);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const resp = await dedupInvoke<SkillDetail>("get_skill_detail_v2", {
        skillId: skill.id,
      });
      setDetail(resp);
      setExpanded(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [expanded, detail, skill.id]);

  const startEdit = useCallback(() => {
    if (!detail) return;
    setEditContent(detail.instructions);
    setEditing(true);
  }, [detail]);

  const cancelEdit = useCallback(() => {
    setEditing(false);
  }, []);

  const saveEdit = useCallback(async () => {
    setSaving(true);
    setError(null);
    try {
      await invoke("update_skill_v2", {
        skillId: skill.id,
        content: editContent,
      });
      setDetail(null);
      setEditing(false);
      onRefresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }, [skill.id, editContent, onRefresh]);

  const handleDelete = useCallback(async () => {
    if (!confirmDelete) {
      setConfirmDelete(true);
      return;
    }
    setError(null);
    setConfirmDelete(false);
    try {
      await invoke("delete_skill_v2", { skillId: skill.id });
      onRefresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [skill.id, confirmDelete, onRefresh]);

  const handleApprove = useCallback(async () => {
    setError(null);
    try {
      await invoke("approve_skill", { skillId: skill.id });
      onRefresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [skill.id, onRefresh]);

  const src = sourceLabel(skill.source);
  const isPending = skill.source === "auto-learned";

  return (
    <div className="rounded-4 border border-hairline bg-surface">
      {/* Header row */}
      <div
        onClick={toggleExpand}
        className="flex cursor-pointer items-center justify-between gap-2 px-4 py-3 transition-colors hover:bg-surface/80"
      >
        <div className="flex flex-1 items-center gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-2 bg-indigo-soft">
            <Zap className="h-4 w-4 text-indigo" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-ink">{skill.name}</span>
              <span className={`rounded px-2 py-0.5 text-[10px] font-medium ${src.className}`}>
                {src.label}
              </span>
              <span className="flex items-center gap-1 text-[10px] text-muted">
                <span className={`h-1.5 w-1.5 rounded-full ${tierDotColor(skill.sensitivity_tier)}`} />
                Tier {skill.sensitivity_tier}
              </span>
            </div>
            <p className="mt-0.5 text-[11px] text-muted">{skill.description}</p>
            {skill.tags.length > 0 && (
              <div className="mt-1 flex flex-wrap gap-1">
                {skill.tags.map((tag) => (
                  <span
                    key={tag}
                    className="inline-flex items-center gap-0.5 rounded-full border border-hairline px-1.5 py-0.5 text-[9px] text-muted"
                  >
                    <Tag className="h-2 w-2" />
                    {tag}
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2">
          {isPending && (
            <button
              onClick={(e) => { e.stopPropagation(); void handleApprove(); }}
              className="flex items-center gap-1 rounded-2 bg-success/15 px-2.5 py-1.5 text-xs font-medium text-success transition-colors hover:bg-success/25"
            >
              <Check className="h-3 w-3" />
              Approve
            </button>
          )}
          {skill.source !== "builtin" && (
            <button
              onClick={(e) => { e.stopPropagation(); void handleDelete(); }}
              onBlur={() => setConfirmDelete(false)}
              className={`rounded-2 p-1.5 transition-colors ${
                confirmDelete
                  ? "bg-danger/15 text-danger"
                  : "text-muted hover:bg-hairline hover:text-ink"
              }`}
              title={confirmDelete ? "Click again to confirm" : "Delete"}
            >
              <Trash2 className="h-3.5 w-3.5" strokeWidth={1.6} />
            </button>
          )}
          {loading
            ? <Loader2 className="h-4 w-4 animate-spin text-muted" />
            : expanded
              ? <ChevronDown className="h-4 w-4 text-muted" />
              : <ChevronRight className="h-4 w-4 text-muted" />}
        </div>
      </div>

      {/* Expanded detail */}
      {expanded && detail && !editing && (
        <div className="border-t border-hairline px-4 py-3">
          <div className="flex items-center justify-between">
            <span className="flex items-center gap-1 text-[10px] uppercase tracking-wider text-muted">
              <BookOpen className="h-3 w-3" />
              SKILL.md
            </span>
            {skill.source !== "builtin" && (
              <button
                onClick={startEdit}
                className="flex items-center gap-1 rounded-md border border-hairline px-2 py-1 text-[11px] text-muted hover:bg-surface"
              >
                <Edit3 className="h-3 w-3" />
                Edit
              </button>
            )}
          </div>
          <div className="mt-2 max-h-80 overflow-y-auto rounded-2 bg-bg p-3">
            <pre className="whitespace-pre-wrap font-mono text-[11px] leading-relaxed text-ink/90">
              {detail.instructions}
            </pre>
          </div>
          {/* Agent toggles */}
          <AgentSkillToggles skillId={skill.id} agents={agents} onChanged={onRefresh} />
        </div>
      )}

      {/* Editing mode */}
      {expanded && editing && (
        <div className="border-t border-hairline px-4 py-3">
          <textarea
            value={editContent}
            onChange={(e) => setEditContent(e.target.value)}
            spellCheck={false}
            className="h-64 w-full resize-y rounded-2 border border-hairline bg-bg p-3 font-mono text-[11px] leading-relaxed text-ink/90 outline-none focus:ring-1 focus:ring-indigo"
          />
          <div className="mt-2 flex items-center justify-end gap-2">
            <button
              onClick={cancelEdit}
              className="rounded-md border border-hairline px-3 py-1.5 text-[12px] text-muted hover:bg-surface"
            >
              Cancel
            </button>
            <button
              onClick={() => void saveEdit()}
              disabled={saving}
              className="inline-flex items-center gap-1 rounded-md bg-indigo px-3 py-1.5 text-[12px] text-white hover:bg-indigo/90 disabled:opacity-50"
            >
              {saving && <Loader2 className="h-3 w-3 animate-spin" />}
              Save
            </button>
          </div>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="border-t border-amber/40 px-4 py-2 text-[11px] text-amber">
          {error}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// AgentSkillToggles — enable/disable a skill per user agent
// ---------------------------------------------------------------------------

function AgentSkillToggles({
  skillId,
  agents,
  onChanged,
}: {
  readonly skillId: string;
  readonly agents: readonly AgentSkillInfo[];
  readonly onChanged: () => void;
}) {
  const editableAgents = useMemo(
    () => agents.filter((a) => a.editable),
    [agents],
  );
  const [pending, setPending] = useState<Set<string>>(() => new Set());

  const toggle = useCallback(async (agent: AgentSkillInfo, enable: boolean) => {
    setPending((prev) => new Set(prev).add(agent.agent_id));
    try {
      const current = new Set(agent.enabled_skills);
      if (enable) current.add(skillId);
      else current.delete(skillId);
      await invoke("update_agent_config", {
        agentId: agent.agent_id,
        patch: { enabled_skills: [...current] },
      });
      onChanged();
    } catch (e) {
      console.error("toggle skill failed:", e);
    } finally {
      setPending((prev) => { const n = new Set(prev); n.delete(agent.agent_id); return n; });
    }
  }, [skillId, onChanged]);

  if (editableAgents.length === 0) return null;

  return (
    <div className="mt-3 border-t border-hairline/60 pt-3">
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-muted">
        <Bot className="h-3 w-3" />
        Agents
      </div>
      <div className="mt-2 flex flex-wrap gap-2">
        {editableAgents.map((agent) => {
          const on = agent.enabled_skills.includes(skillId);
          const busy = pending.has(agent.agent_id);
          return (
            <button
              key={agent.agent_id}
              onClick={() => void toggle(agent, !on)}
              disabled={busy}
              className={`rounded-full border px-2.5 py-1 text-[11px] transition-colors ${
                on
                  ? "border-indigo bg-indigo-soft text-indigo"
                  : "border-hairline text-muted hover:border-indigo/40 hover:text-ink"
              } ${busy ? "animate-pulse" : ""}`}
            >
              {agent.name}
            </button>
          );
        })}
      </div>
      <p className="mt-1.5 text-[10px] text-muted">
        Brain and Chat use all skills automatically. Toggle above to enable for user agents.
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// CreateSkillModal
// ---------------------------------------------------------------------------

function CreateSkillModal({
  onClose,
  onCreated,
}: {
  readonly onClose: () => void;
  readonly onCreated: () => void;
}) {
  const [content, setContent] = useState(SKILL_TEMPLATE);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const nameMatch = content.match(/^name:\s*(.+)$/m);
  const skillName = nameMatch?.[1]?.trim() ?? "";

  const handleCreate = useCallback(async () => {
    if (!skillName) return;
    setSaving(true);
    setError(null);
    try {
      await invoke("create_skill_v2", {
        name: skillName,
        content,
      });
      onCreated();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }, [skillName, content, onCreated]);

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-4">
      <div className="flex max-h-full w-full max-w-3xl flex-col rounded-4 border border-hairline bg-surface shadow-xl">
        <div className="flex items-center justify-between border-b border-hairline px-5 py-3">
          <h2 className="text-base font-semibold text-ink">New Skill</h2>
          <button onClick={onClose} className="rounded-md p-1 text-muted hover:bg-surface">
            <X size={14} />
          </button>
        </div>
        <div className="flex-1 overflow-auto px-5 py-4">
          <p className="mb-3 text-[11px] text-muted">
            Edit the SKILL.md below. The YAML frontmatter defines metadata;
            the markdown body contains instructions agents will follow.
          </p>
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            spellCheck={false}
            className="h-96 w-full resize-y rounded-2 border border-hairline bg-bg p-3 font-mono text-[12px] leading-relaxed text-ink/90 outline-none focus:ring-1 focus:ring-indigo"
          />
          {error && (
            <div className="mt-2 rounded-md border border-amber/60 bg-amber/10 px-3 py-2 text-[12px] text-amber">
              {error}
            </div>
          )}
        </div>
        <div className="flex items-center justify-end gap-2 border-t border-hairline px-5 py-3">
          <button
            onClick={onClose}
            className="rounded-md border border-hairline px-3 py-1.5 text-[12px] text-muted hover:bg-surface"
          >
            Cancel
          </button>
          <button
            onClick={() => void handleCreate()}
            disabled={saving || !skillName}
            className="inline-flex items-center gap-1 rounded-md bg-indigo px-3 py-1.5 text-[12px] text-white hover:bg-indigo/90 disabled:opacity-50"
          >
            {saving ? <Loader2 size={12} className="animate-spin" /> : <Plus size={12} />}
            Create Skill
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// SkillsPage
// ---------------------------------------------------------------------------

function SkillsPage() {
  const [search, setSearch] = useState("");
  const [showCreateModal, setShowCreateModal] = useState(false);

  const {
    data: skills,
    error: skillsError,
    isLoading,
    refetch,
  } = useAsyncData<SkillMeta[]>(
    useCallback(() => dedupInvoke<SkillMeta[]>("list_skills_v2"), []),
  );

  const {
    data: rawAgents,
    refetch: refetchAgents,
  } = useAsyncData<readonly AgentSkillInfo[]>(
    useCallback(async () => {
      interface AgentRow {
        readonly agent_id: string;
        readonly name: string;
        readonly editable: boolean;
        readonly config?: { readonly enabled_skills?: readonly string[] };
      }
      const resp = await dedupInvoke<{ agents: readonly AgentRow[] }>(
        "list_pydantic_agents",
      );
      return resp.agents.map((a) => ({
        agent_id: a.agent_id,
        name: a.name,
        editable: a.editable,
        enabled_skills: a.config?.enabled_skills ?? [],
      }));
    }, []),
  );
  const agents: readonly AgentSkillInfo[] = rawAgents ?? [];

  const handleRefresh = useCallback(() => {
    void refetch();
    void refetchAgents();
  }, [refetch, refetchAgents]);

  const filtered = useMemo(() => {
    if (!skills) return [];
    const q = search.toLowerCase();
    if (!q) return skills;
    return skills.filter(
      (s) =>
        s.name.toLowerCase().includes(q) ||
        s.description.toLowerCase().includes(q) ||
        s.tags.some((t) => t.toLowerCase().includes(q)),
    );
  }, [skills, search]);

  const pendingSkills = useMemo(
    () => filtered.filter((s) => s.source === "auto-learned"),
    [filtered],
  );
  const activeSkills = useMemo(
    () => filtered.filter((s) => s.source !== "auto-learned"),
    [filtered],
  );

  return (
    <div className="flex-1 space-y-6 overflow-y-auto p-6">
      {/* Header */}
      <div>
        <h2 className="text-[44px] font-bold leading-none" style={{ background: "linear-gradient(135deg, var(--ink), var(--ink-2))", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", backgroundClip: "text" }}>Skills</h2>
        <p className="mt-1 text-sm text-muted">
          Skills are procedural knowledge that agents load on demand.
          Each skill is a SKILL.md file with instructions, procedures, and guidelines.
        </p>
      </div>

      {/* Actions bar */}
      <div className="flex items-center gap-3">
        <div className="flex flex-1 items-center gap-2 rounded-2 bg-surface px-3 py-2">
          <Search className="h-4 w-4 shrink-0 text-muted" strokeWidth={1.6} />
          <input
            type="text"
            placeholder="Search skills..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="flex-1 bg-transparent text-sm text-ink placeholder-muted outline-none"
          />
          {search && (
            <button onClick={() => setSearch("")} className="text-xs text-muted hover:text-ink">
              &times;
            </button>
          )}
        </div>
        <button
          onClick={() => setShowCreateModal(true)}
          className="flex shrink-0 items-center gap-1.5 rounded-2 bg-indigo px-3 py-2 text-xs font-medium text-white transition-colors hover:bg-indigo/90"
        >
          <Plus className="h-3.5 w-3.5" strokeWidth={1.6} />
          New Skill
        </button>
      </div>

      {/* Content */}
      {isLoading && !skills ? (
        <div className="space-y-3">
          <Skeleton className="h-20 w-full rounded-4" />
          <Skeleton className="h-20 w-full rounded-4" />
          <Skeleton className="h-20 w-full rounded-4" />
        </div>
      ) : skillsError && !skills ? (
        <div className="rounded-4 border border-amber/30 bg-amber/5 px-4 py-3 text-sm text-amber">
          {skillsError}
        </div>
      ) : !skills || skills.length === 0 ? (
        <div className="flex flex-col items-center gap-3 py-12">
          <Sparkles className="h-10 w-10 text-muted" />
          <p className="text-sm text-muted">No skills installed yet.</p>
          <p className="text-xs text-muted">
            Create your first skill or wait for the auto-learner to discover patterns from your conversations.
          </p>
        </div>
      ) : (
        <div className="space-y-6">
          {/* Pending auto-learned skills */}
          {pendingSkills.length > 0 && (
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <Sparkles className="h-4 w-4 text-indigo" />
                <h3 className="text-sm font-medium text-ink">Auto-learned</h3>
                <span className="rounded-full bg-indigo-soft px-2 py-0.5 text-[10px] font-medium text-indigo">
                  {pendingSkills.length} pending
                </span>
              </div>
              <p className="text-[11px] text-muted">
                These skills were generated from your conversation patterns. Approve to activate.
              </p>
              {pendingSkills.map((skill) => (
                <SkillCard key={skill.id} skill={skill} agents={agents} onRefresh={handleRefresh} />
              ))}
            </div>
          )}

          {/* Active skills */}
          {activeSkills.length > 0 && (
            <div className="space-y-3">
              {pendingSkills.length > 0 && (
                <div className="flex items-center gap-2">
                  <Shield className="h-4 w-4 text-muted" />
                  <h3 className="text-sm font-medium text-ink">Active Skills</h3>
                </div>
              )}
              <p className="text-[11px] text-muted">
                {activeSkills.length} skill{activeSkills.length !== 1 ? "s" : ""} available to agents
              </p>
              {activeSkills.map((skill) => (
                <SkillCard key={skill.id} skill={skill} agents={agents} onRefresh={handleRefresh} />
              ))}
            </div>
          )}

          {filtered.length === 0 && search && (
            <p className="py-8 text-center text-sm text-muted">
              No skills match &ldquo;{search}&rdquo;
            </p>
          )}
        </div>
      )}

      {/* Create modal */}
      {showCreateModal && (
        <CreateSkillModal
          onClose={() => setShowCreateModal(false)}
          onCreated={() => {
            setShowCreateModal(false);
            handleRefresh();
          }}
        />
      )}
    </div>
  );
}

export default SkillsPage;
