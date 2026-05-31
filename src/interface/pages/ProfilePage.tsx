import { useState, useCallback, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import {
  Check,
  X,
  Star,
  TrendingUp,
  User,
  Wand2,
  Brain,
  Pencil,
  RefreshCw,
} from "lucide-react";
import { SkeletonSection } from "../components/LoadingState";
import { useAsyncData } from "../hooks/useAsyncData";
import { dedupInvoke } from "../utils/requestDedup";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface AppSettings {
  llm_model: string;
  llm_host: string;
  llm_provider: string;
  anthropic_api_key: string | null;
  anthropic_model: string;
  external_llm_consent: boolean;
  llm_api_key: string | null;
  llm_max_parallel: number;
  max_sensitivity_tier: number;
  theme: string;
  data_dir: string;
  auto_refresh_enabled: boolean;
  auto_refresh_interval_minutes: number;
  refresh_on_launch: boolean;
  onboarding_completed: boolean;
  onboarding_completed_at: string | null;
  initial_connectors: string[];
  skipped_connectors: string[];
  ollama_configured: boolean;
  dismissed_nudges: string[];
  interest_overrides: Record<string, number>;
  notifications_enabled: boolean;
  whatsapp_notification_phone: string | null;
  user_name: string | null;
  user_birthday: string | null;
  user_location: string | null;
  user_timezone: string | null;
  user_language: string | null;
  user_bio: string | null;
  voice_transcription_enabled: boolean;
  whisper_model_size: string;
  transcribe_whatsapp_audio: boolean;
  local_inference_for_sensitive: boolean;
}

interface LearnedFactData {
  readonly id: string;
  readonly category: string;
  readonly subject: string;
  readonly predicate: string;
  readonly content: string;
  readonly confidence: number;
  readonly source_type: string;
  readonly extracted_at: string;
  readonly confirmed_at: string | null;
  readonly sensitivity_tier: number;
  readonly times_used: number;
}

interface InterestAreaData {
  readonly domain: string;
  readonly label: string;
  readonly description: string;
  readonly weight: number;
  readonly query_count: number;
  readonly queries_per_week: number;
  readonly trending: boolean;
  readonly explicit: boolean;
  readonly raw_tables: readonly string[];
  readonly mart: string | null;
}

// ---------------------------------------------------------------------------
// Section wrapper
// ---------------------------------------------------------------------------

function Section({
  title,
  icon: Icon,
  children,
}: {
  readonly title: string;
  readonly icon: typeof User;
  readonly children: React.ReactNode;
}) {
  return (
    <section className="rounded-4 border border-hairline bg-surface p-5 shadow-1">
      <div className="mb-4 flex items-center gap-2 border-b border-hairline pb-3">
        <Icon className="h-4 w-4 text-indigo" strokeWidth={1.6} />
        <h3 className="text-sm font-semibold text-ink">{title}</h3>
      </div>
      {children}
    </section>
  );
}

// ---------------------------------------------------------------------------
// User Profile section
// ---------------------------------------------------------------------------

function UserProfileSection({
  settings,
  onUpdate,
  saving,
  onRefreshSettings,
}: {
  readonly settings: AppSettings;
  readonly onUpdate: (patch: Partial<AppSettings>) => void;
  readonly saving: boolean;
  readonly onRefreshSettings: () => void;
}) {
  const [nameLocal, setNameLocal] = useState(settings.user_name ?? "");
  const [birthdayLocal, setBirthdayLocal] = useState(settings.user_birthday ?? "");
  const [locationLocal, setLocationLocal] = useState(settings.user_location ?? "");
  const [timezoneLocal, setTimezoneLocal] = useState(
    settings.user_timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone,
  );
  const [languageLocal, setLanguageLocal] = useState(settings.user_language ?? "");
  const [bioLocal, setBioLocal] = useState(settings.user_bio ?? "");
  const [detecting, setDetecting] = useState(false);

  useEffect(() => {
    setNameLocal(settings.user_name ?? "");
    setBirthdayLocal(settings.user_birthday ?? "");
    setLocationLocal(settings.user_location ?? "");
    setTimezoneLocal(
      settings.user_timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone,
    );
    setLanguageLocal(settings.user_language ?? "");
    setBioLocal(settings.user_bio ?? "");
  }, [
    settings.user_name,
    settings.user_birthday,
    settings.user_location,
    settings.user_timezone,
    settings.user_language,
    settings.user_bio,
  ]);

  const handleAutoDetect = async () => {
    setDetecting(true);
    try {
      await invoke("infer_user_profile");
      onRefreshSettings();
    } finally {
      setDetecting(false);
    }
  };

  const fieldClass =
    "w-full rounded-2 bg-surface px-3 py-2 text-sm text-ink outline-none border border-hairline focus:border-indigo";

  return (
    <Section title="Your Profile" icon={User}>
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <p className="text-[11px] text-muted">
            Helps SecBrain personalize responses. All data stays on your device.
          </p>
          <button
            onClick={handleAutoDetect}
            disabled={detecting || saving}
            className="flex items-center gap-1.5 rounded-2 bg-surface px-3 py-1.5 text-xs text-indigo hover:bg-hairline disabled:opacity-50"
          >
            <Wand2 className={`h-3 w-3 ${detecting ? "animate-spin" : ""}`} />
            {detecting ? "Detecting..." : "Auto-detect"}
          </button>
        </div>

        <div className="rounded-2 bg-surface/60 px-4 py-3">
          <label className="mb-1.5 block text-xs text-muted">Name</label>
          <input
            type="text"
            value={nameLocal}
            onChange={(e) => setNameLocal(e.target.value)}
            onBlur={() => onUpdate({ user_name: nameLocal || null })}
            placeholder="How should SecBrain call you?"
            disabled={saving}
            className={fieldClass}
          />
        </div>

        <div className="rounded-2 bg-surface/60 px-4 py-3">
          <label className="mb-1.5 block text-xs text-muted">Birthday</label>
          <input
            type="date"
            value={birthdayLocal}
            onChange={(e) => {
              setBirthdayLocal(e.target.value);
              onUpdate({ user_birthday: e.target.value || null });
            }}
            disabled={saving}
            className={fieldClass}
          />
        </div>

        <div className="rounded-2 bg-surface/60 px-4 py-3">
          <label className="mb-1.5 block text-xs text-muted">Location</label>
          <input
            type="text"
            value={locationLocal}
            onChange={(e) => setLocationLocal(e.target.value)}
            onBlur={() => onUpdate({ user_location: locationLocal || null })}
            placeholder="City, Country"
            disabled={saving}
            className={fieldClass}
          />
        </div>

        <div className="rounded-2 bg-surface/60 px-4 py-3">
          <label className="mb-1.5 block text-xs text-muted">Timezone</label>
          <input
            type="text"
            value={timezoneLocal}
            onChange={(e) => setTimezoneLocal(e.target.value)}
            onBlur={() => onUpdate({ user_timezone: timezoneLocal || null })}
            placeholder="America/Sao_Paulo"
            disabled={saving}
            className={fieldClass}
          />
          <p className="mt-1 text-[10px] text-muted">
            Detected: {Intl.DateTimeFormat().resolvedOptions().timeZone}
          </p>
        </div>

        <div className="rounded-2 bg-surface/60 px-4 py-3">
          <label className="mb-1.5 block text-xs text-muted">
            Preferred language
          </label>
          <input
            type="text"
            value={languageLocal}
            onChange={(e) => setLanguageLocal(e.target.value)}
            onBlur={() => onUpdate({ user_language: languageLocal || null })}
            placeholder="e.g. Portuguese, English"
            disabled={saving}
            className={fieldClass}
          />
        </div>

        <div className="rounded-2 bg-surface/60 px-4 py-3">
          <label className="mb-1.5 block text-xs text-muted">About you</label>
          <textarea
            value={bioLocal}
            onChange={(e) => setBioLocal(e.target.value)}
            onBlur={() => onUpdate({ user_bio: bioLocal || null })}
            placeholder="Anything you'd like SecBrain to know (family, work, hobbies...)"
            disabled={saving}
            rows={3}
            className={`${fieldClass} resize-none`}
          />
        </div>
      </div>
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Learned Facts section
// ---------------------------------------------------------------------------

const CATEGORY_LABELS: Record<string, string> = {
  preference: "Preferences",
  relationship: "Relationships",
  biographical: "Biographical",
  habit: "Habits",
  opinion: "Opinions",
  health: "Health",
  work: "Work",
  location: "Location",
};

function LearnedFactsSection() {
  const [facts, setFacts] = useState<LearnedFactData[]>([]);
  const [loading, setLoading] = useState(true);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editContent, setEditContent] = useState("");
  const [stats, setStats] = useState<{
    total: number;
    confirmed: number;
    pending_review: number;
  }>({ total: 0, confirmed: 0, pending_review: 0 });

  const loadFacts = useCallback(async () => {
    setLoading(true);
    try {
      const [factsData, statsData] = await Promise.all([
        dedupInvoke<LearnedFactData[]>("get_learned_facts"),
        dedupInvoke<{ total: number; confirmed: number; pending_review: number }>(
          "get_fact_stats",
        ),
      ]);
      setFacts(factsData);
      setStats(statsData);
    } catch {
      // Table may not exist yet
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadFacts();
  }, [loadFacts]);

  const handleConfirm = async (id: string) => {
    await invoke("confirm_fact", { factId: id });
    loadFacts();
  };

  const handleDismiss = async (id: string) => {
    await invoke("dismiss_fact", { factId: id });
    loadFacts();
  };

  const handleEdit = async (id: string) => {
    if (!editContent.trim()) return;
    await invoke("edit_fact", { factId: id, newContent: editContent });
    setEditingId(null);
    setEditContent("");
    loadFacts();
  };

  const startEdit = (fact: LearnedFactData) => {
    setEditingId(fact.id);
    setEditContent(fact.content);
  };

  const grouped: Record<string, LearnedFactData[]> = {};
  for (const f of facts) {
    const cat = f.category;
    if (!grouped[cat]) grouped[cat] = [];
    grouped[cat].push(f);
  }

  return (
    <Section title="What I've Learned" icon={Brain}>
      <div className="space-y-3">
        <div className="flex items-center gap-4 text-[11px] text-muted">
          <span>{stats.total} total facts</span>
          <span className="text-success">{stats.confirmed} confirmed</span>
          <span className="text-amber">{stats.pending_review} pending review</span>
        </div>

        {loading ? (
          <p className="text-xs text-muted">Loading...</p>
        ) : facts.length === 0 ? (
          <p className="text-xs text-muted">
            No facts learned yet. Chat with SecBrain and it will start learning about
            you over time.
          </p>
        ) : (
          Object.entries(grouped).map(([cat, catFacts]) => (
            <div key={cat} className="space-y-1.5">
              <h4 className="text-xs font-medium text-muted">
                {CATEGORY_LABELS[cat] ?? cat}
              </h4>
              {catFacts.map((fact) => (
                <div
                  key={fact.id}
                  className="flex items-start gap-2 rounded-2 bg-surface/60 px-3 py-2"
                >
                  {editingId === fact.id ? (
                    <div className="flex-1 space-y-1.5">
                      <input
                        type="text"
                        value={editContent}
                        onChange={(e) => setEditContent(e.target.value)}
                        onKeyDown={(e) => e.key === "Enter" && handleEdit(fact.id)}
                        className="w-full rounded bg-surface px-2 py-1 text-xs text-ink outline-none border border-indigo"
                        autoFocus
                      />
                      <div className="flex gap-1.5">
                        <button
                          onClick={() => handleEdit(fact.id)}
                          className="rounded bg-indigo-soft px-2 py-0.5 text-[10px] text-indigo hover:bg-indigo/30"
                        >
                          Save
                        </button>
                        <button
                          onClick={() => setEditingId(null)}
                          className="rounded bg-surface px-2 py-0.5 text-[10px] text-muted hover:bg-hairline"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : (
                    <>
                      <p className="flex-1 text-xs text-ink">{fact.content}</p>
                      <div className="flex shrink-0 items-center gap-1">
                        <span
                          className={`text-[10px] ${
                            fact.confidence >= 1.0
                              ? "text-success"
                              : fact.confidence >= 0.7
                                ? "text-amber"
                                : "text-muted"
                          }`}
                        >
                          {Math.round(fact.confidence * 100)}%
                        </span>
                        <button
                          onClick={() => startEdit(fact)}
                          className="rounded p-1 text-muted hover:bg-hairline hover:text-ink"
                          title="Edit"
                        >
                          <Pencil className="h-3 w-3" />
                        </button>
                        <button
                          onClick={() => handleConfirm(fact.id)}
                          className="rounded p-1 text-muted hover:bg-success/30 hover:text-success"
                          title="Confirm"
                        >
                          <Check className="h-3 w-3" />
                        </button>
                        <button
                          onClick={() => handleDismiss(fact.id)}
                          className="rounded p-1 text-muted hover:bg-amber/30 hover:text-danger"
                          title="Dismiss"
                        >
                          <X className="h-3 w-3" />
                        </button>
                      </div>
                    </>
                  )}
                </div>
              ))}
            </div>
          ))
        )}
      </div>
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Interests section
// ---------------------------------------------------------------------------

function InterestsSection({
  settings,
  onUpdate,
  saving,
}: {
  readonly settings: AppSettings;
  readonly onUpdate: (patch: Partial<AppSettings>) => void;
  readonly saving: boolean;
}) {
  const interestsResult = useAsyncData<InterestAreaData[]>(
    useCallback(
      () => dedupInvoke<InterestAreaData[]>("get_interest_profile"),
      [],
    ),
  );

  const interests = interestsResult.data ?? [];

  const starCount = (weight: number): number =>
    Math.max(1, Math.min(5, Math.ceil(weight * 5)));

  const hasOverrides =
    Object.keys(settings.interest_overrides ?? {}).length > 0;

  const handleResetOverrides = () => {
    onUpdate({ interest_overrides: {} });
    interestsResult.refetch();
  };

  return (
    <Section title="Your Interests" icon={Star}>
      <div className="space-y-2">
        {interestsResult.isLoading ? (
          <p className="text-[11px] text-muted">Loading interests...</p>
        ) : interests.length === 0 ? (
          <p className="text-[11px] text-muted">
            Ask questions in Chat to build your interest profile.
          </p>
        ) : (
          interests.map((area) => (
            <div
              key={area.domain}
              className="flex items-center justify-between rounded-2 bg-surface/60 px-4 py-2.5"
            >
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-sm text-ink">{area.label}</span>
                  {area.trending && (
                    <TrendingUp className="h-3 w-3 text-success" />
                  )}
                </div>
                <span className="text-[11px] text-muted">
                  {area.query_count} queries
                  {area.queries_per_week > 0 &&
                    ` · ${area.queries_per_week.toFixed(1)}/week`}
                </span>
              </div>
              <div className="flex items-center gap-0.5">
                {Array.from({ length: 5 }, (_, i) => (
                  <Star
                    key={i}
                    className={`h-3 w-3 ${
                      i < starCount(area.weight)
                        ? "fill-indigo text-indigo"
                        : "text-hairline"
                    }`}
                  />
                ))}
              </div>
            </div>
          ))
        )}
      </div>
      {hasOverrides && (
        <button
          onClick={handleResetOverrides}
          disabled={saving}
          className="mt-3 text-[11px] text-indigo hover:underline disabled:opacity-50"
        >
          Reset to automatic ordering
        </button>
      )}
      <p className="mt-3 text-[11px] text-muted">
        Stars are auto-adjusted based on your usage patterns.
      </p>
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Profile page
// ---------------------------------------------------------------------------

function ProfilePage() {
  const [saving, setSaving] = useState(false);

  const settingsResult = useAsyncData<AppSettings>(
    useCallback(() => dedupInvoke<AppSettings>("get_settings"), []),
  );

  const settings = settingsResult.data;

  const updateSettings = async (patch: Partial<AppSettings>) => {
    if (!settingsResult.data) return;
    setSaving(true);
    const updated = { ...settingsResult.data, ...patch };
    try {
      await invoke("update_settings", { settings: updated });
      settingsResult.refetch();
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex-1 space-y-6 overflow-y-auto">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-[44px] font-bold leading-none" style={{ background: "linear-gradient(135deg, var(--ink), var(--ink-2))", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", backgroundClip: "text" }}>Profile</h2>
          <p className="mt-1 text-sm text-muted">
            Your personal information, learned facts, and interests.
          </p>
        </div>
        <button
          onClick={() => settingsResult.refetch()}
          disabled={settingsResult.isLoading}
          className="flex items-center gap-2 rounded-2 bg-surface px-3 py-2 text-xs text-muted hover:text-ink disabled:opacity-50"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${settingsResult.isLoading ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>

      {settingsResult.isLoading || !settings ? (
        <>
          <SkeletonSection />
          <SkeletonSection />
          <SkeletonSection />
        </>
      ) : (
        <>
          <UserProfileSection
            settings={settings}
            onUpdate={(patch) => updateSettings(patch)}
            saving={saving}
            onRefreshSettings={() => settingsResult.refetch()}
          />

          <LearnedFactsSection />

          <InterestsSection
            settings={settings}
            onUpdate={(patch) => updateSettings(patch)}
            saving={saving}
          />
        </>
      )}
    </div>
  );
}

export default ProfilePage;
