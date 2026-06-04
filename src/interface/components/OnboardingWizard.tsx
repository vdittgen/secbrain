/**
 * Onboarding wizard — full-screen overlay shown on first launch.
 *
 * 7 slides: Welcome, Profile, Mode, System, Sources, Notifications, Ready.
 * Reuses existing IPC commands — no new backend endpoints needed.
 *
 * sensitivity_tier: 1 (infrastructure/setup metadata only)
 */

import { useState, useCallback, useEffect, useRef } from "react";
import { invoke } from "@tauri-apps/api/core";
import {
  Check,
  Lock,
  Power,
  Download,
  Server,
  ChevronLeft,
  ChevronRight,
  UserCircle,
  Calendar,
  Users,
  Mail,
  FileText,
  StickyNote,
  MessageCircle,
  Loader2,
  CheckCircle2,
} from "lucide-react";
import { dedupInvoke } from "../utils/requestDedup";
import {
  WhatsAppPairingPanel,
  type WhatsappListenerStatus,
} from "./WhatsAppPairingPanel";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Slide = 1 | 2 | 3 | 4 | 5 | 6 | 7;

type Mode = "local" | "remote";

interface OllamaStatusResponse {
  readonly server_reachable: boolean;
  readonly chat_model: string;
  readonly chat_model_status: string;
  readonly embed_model: string;
  readonly embed_model_status: string;
  readonly server_version: string;
}

interface CatalogEntry {
  readonly connector_id: string;
  readonly name: string;
  readonly icon: string;
  readonly description: string;
  readonly category: string;
  readonly enabled: boolean;
  readonly status: string;
  readonly missing_requirements: readonly {
    readonly type: string;
    readonly key: string;
    readonly label: string;
    readonly action: string;
  }[];
  readonly default_schedule: string;
  readonly note: string | null;
}

interface AppSettings {
  readonly [key: string]: unknown;
}

interface OnboardingWizardProps {
  readonly onComplete: () => void;
}

// ---------------------------------------------------------------------------
// Slide labels for top bar
// ---------------------------------------------------------------------------

const SLIDE_LABELS: Record<Slide, string> = {
  1: "Welcome",
  2: "Profile",
  3: "Mode",
  4: "System",
  5: "Sources",
  6: "Notifications",
  7: "Ready",
};

// ---------------------------------------------------------------------------
// Connector definitions for slide 4
// ---------------------------------------------------------------------------

interface ConnectorDef {
  readonly id: string;
  readonly name: string;
  readonly description: string;
  readonly icon: typeof Calendar;
  readonly color: string;
  readonly defaultChecked: boolean;
  readonly tag?: string;
}

const CONNECTOR_DEFS: readonly ConnectorDef[] = [
  {
    id: "apple-calendar",
    name: "Calendar & Reminders",
    description: "Events, reminders, and schedules",
    icon: Calendar,
    color: "text-danger",
    defaultChecked: true,
  },
  {
    id: "apple-contacts",
    name: "Contacts",
    description: "People and relationships",
    icon: Users,
    color: "text-personal-ink",
    defaultChecked: true,
  },
  {
    id: "apple-mail",
    name: "Mail",
    description: "Email messages and threads",
    icon: Mail,
    color: "text-work-ink",
    defaultChecked: true,
  },
  {
    id: "filesystem",
    name: "Files & Documents",
    description: "Local files, PDFs, and documents",
    icon: FileText,
    color: "text-amber",
    defaultChecked: true,
  },
  {
    id: "apple-notes",
    name: "Notes",
    description: "Apple Notes and memos",
    icon: StickyNote,
    color: "text-amber",
    defaultChecked: false,
  },
  {
    id: "notion",
    name: "Notion",
    description: "Pages, databases, and wikis",
    icon: FileText,
    color: "text-ink",
    defaultChecked: false,
    tag: "Official",
  },
];

// ---------------------------------------------------------------------------
// Gradient constant
// ---------------------------------------------------------------------------

const HEADLINE_GRADIENT =
  "linear-gradient(135deg, oklch(0.55 0.20 265) 0%, oklch(0.62 0.18 220) 60%, oklch(0.72 0.15 175) 100%)";

// ---------------------------------------------------------------------------
// Shared: Toggle
// ---------------------------------------------------------------------------

function Toggle({
  on,
  onToggle,
}: {
  readonly on: boolean;
  readonly onToggle: () => void;
}) {
  return (
    <button
      onClick={onToggle}
      className={`relative h-[22px] w-[38px] shrink-0 rounded-full transition-colors ${on ? "bg-indigo" : "bg-hairline-2"}`}
    >
      <span
        className={`absolute top-[2px] left-[2px] h-[18px] w-[18px] rounded-full bg-white shadow-sm transition-transform ${on ? "translate-x-4" : ""}`}
      />
    </button>
  );
}

// ---------------------------------------------------------------------------
// Shared: Trust Chip
// ---------------------------------------------------------------------------

function TrustChip({ children }: { readonly children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-pill bg-bg-2 px-3 py-1 text-[11px] font-medium text-muted">
      {children}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Shared: Brand Row
// ---------------------------------------------------------------------------

function BrandRow() {
  return (
    <div className="flex items-center gap-3 mb-16">
      <img
        src="/icon.svg"
        alt="Arandu"
        className="h-8 w-8 rounded-[9px]"
      />
      <span className="text-[17px] font-semibold tracking-tight text-ink">
        Arandu
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shared: Top Bar
// ---------------------------------------------------------------------------

function TopBar({
  slide,
  onBack,
}: {
  readonly slide: Slide;
  readonly onBack: (() => void) | null;
}) {
  const progressPct = Math.round((slide / 7) * 100);

  return (
    <div
      className="flex items-center gap-3 px-5 py-3"
      style={{
        background: "oklch(1 0 0 / 0.6)",
        backdropFilter: "blur(20px)",
      }}
    >
      {/* Traffic light dots */}
      <div className="flex items-center gap-1.5">
        <div className="h-3 w-3 rounded-full bg-[#ff5f57]" />
        <div className="h-3 w-3 rounded-full bg-[#febc2e]" />
        <div className="h-3 w-3 rounded-full bg-[#28c840]" />
      </div>

      {/* Back button */}
      {onBack ? (
        <button
          onClick={onBack}
          className="flex items-center gap-1 text-xs text-muted transition-colors hover:text-ink"
        >
          <ChevronLeft strokeWidth={1.6} className="h-3.5 w-3.5" />
          Back
        </button>
      ) : (
        <div className="w-10" />
      )}

      {/* Step label */}
      <span className="ml-auto text-[11px] font-medium text-muted">
        {SLIDE_LABELS[slide]}
      </span>

      {/* Progress bar */}
      <div className="ml-2 h-1 w-24 overflow-hidden rounded-full bg-hairline">
        <div
          className="h-full rounded-full bg-indigo transition-all duration-500"
          style={{ width: `${progressPct}%` }}
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shared: Slide transition wrapper
// ---------------------------------------------------------------------------

function SlideTransition({
  slideKey,
  direction,
  children,
}: {
  readonly slideKey: number;
  readonly direction: "forward" | "back";
  readonly children: React.ReactNode;
}) {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    setVisible(false);
    const t = requestAnimationFrame(() => setVisible(true));
    return () => cancelAnimationFrame(t);
  }, [slideKey]);

  return (
    <div
      key={slideKey}
      className={`transition-all duration-300 ${
        visible
          ? "translate-x-0 opacity-100"
          : direction === "forward"
            ? "translate-x-4 opacity-0"
            : "-translate-x-4 opacity-0"
      }`}
    >
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Slide 1: Welcome
// ---------------------------------------------------------------------------

function WelcomeSlide({
  onGetStarted,
}: {
  readonly onGetStarted: () => void;
}) {
  return (
    <div className="flex flex-1 flex-col px-[88px] py-14">
      <BrandRow />

      <div className="flex min-h-0 flex-1 flex-col justify-center">
        <h1
          className="font-semibold text-ink"
          style={{
            fontSize: "clamp(56px, min(9vw, 12vh), 128px)",
            lineHeight: 0.92,
            letterSpacing: "-0.04em",
            margin: "0 0 28px",
          }}
        >
          A mind,
          <br />
          <span
            style={{
              background: HEADLINE_GRADIENT,
              WebkitBackgroundClip: "text",
              WebkitTextFillColor: "transparent",
              backgroundClip: "text",
            }}
          >
            just for you.
          </span>
        </h1>

        <p className="max-w-[52ch] text-[19px] leading-[1.5] text-ink-2">
          Arandu is a personal AI that quietly organizes your entire life
          — calendars, messages, notes, health — all on your Mac. We'll
          set it up together in about a minute.
        </p>
      </div>

      <div className="mt-auto pt-10 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <TrustChip>
            <Lock strokeWidth={1.6} className="h-3 w-3" />
            Local-first
          </TrustChip>
          <TrustChip>Honest about what it does</TrustChip>
          <TrustChip>Auditable</TrustChip>
        </div>

        <button
          onClick={onGetStarted}
          className="flex items-center gap-2 rounded-pill px-7 py-4 text-[15.5px] font-semibold text-white shadow-2 transition-all hover:-translate-y-px hover:shadow-3"
          style={{ background: "oklch(0.55 0.20 265)" }}
          onMouseEnter={(e) => { (e.target as HTMLElement).style.background = "oklch(0.46 0.20 265)"; }}
          onMouseLeave={(e) => { (e.target as HTMLElement).style.background = "oklch(0.55 0.20 265)"; }}
        >
          Get started
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}><path d="M5 12h14M13 5l7 7-7 7" /></svg>
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Slide 2: Profile
// ---------------------------------------------------------------------------

function ProfileSlide({
  firstName,
  onChange,
  onContinue,
}: {
  readonly firstName: string;
  readonly onChange: (name: string) => void;
  readonly onContinue: () => void;
}) {
  return (
    <div className="flex flex-1 flex-col px-10 py-10">
      <BrandRow />

      <h2 className="text-[28px] font-semibold tracking-tight text-ink">
        What should I call you?
      </h2>
      <p className="mt-2 text-sm text-muted">
        Just a first name — it stays on your Mac, and you can change it
        anytime from your profile.
      </p>

      <div className="mt-8 flex items-center gap-3 rounded-4 border border-hairline bg-surface px-5 py-4 shadow-1">
        <UserCircle strokeWidth={1.6} className="h-5 w-5 shrink-0 text-muted" />
        <input
          type="text"
          autoFocus
          value={firstName}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") onContinue();
          }}
          placeholder="Your first name"
          className="w-full bg-transparent text-base text-ink outline-none placeholder:text-faint"
        />
      </div>

      <div className="mt-auto pt-10 flex items-center justify-end">
        <button
          onClick={onContinue}
          className="flex items-center gap-2 rounded-pill bg-indigo px-6 py-3 text-sm font-medium text-white transition-colors hover:bg-indigo/90"
        >
          Continue
          <ChevronRight strokeWidth={1.6} className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Slide 3: Mode Chooser
// ---------------------------------------------------------------------------

// Models offered during onboarding. llama3.1:70b is the recommended default
// and is first; everything below it is `belowMin` (usable, but acceptable
// results are not guaranteed).
const ONBOARDING_MODELS: ReadonlyArray<{
  readonly id: string;
  readonly label: string;
  readonly note: string;
  readonly belowMin: boolean;
  readonly testingOnly: boolean;
}> = [
  {
    id: "llama3.1:70b",
    label: "Llama 3.1 70B",
    note: "Default · recommended · Apple Silicon Ultra, 64–128 GB RAM",
    belowMin: false,
    testingOnly: false,
  },
  { id: "gemma4:e4b", label: "Gemma 4 E4B", note: "~5 GB RAM", belowMin: true, testingOnly: false },
  { id: "gemma4:e2b", label: "Gemma 4 E2B", note: "~2 GB RAM", belowMin: false, testingOnly: true },
  { id: "llama3.2:3b", label: "Llama 3.2 3B", note: "~2 GB RAM", belowMin: false, testingOnly: true },
  { id: "qwen3.5:2b", label: "Qwen 3.5 2B", note: "~1 GB RAM", belowMin: false, testingOnly: true },
  { id: "llama3.1:8b", label: "Llama 3.1 8B", note: "~8 GB RAM", belowMin: true, testingOnly: false },
  { id: "mistral:7b", label: "Mistral 7B", note: "~8 GB RAM", belowMin: true, testingOnly: false },
  { id: "llama3.2:1b", label: "Llama 3.2 1B", note: "Interface testing only · ~1 GB RAM", belowMin: false, testingOnly: true },
  { id: "gemma3:1b", label: "Gemma 3 1B", note: "Interface testing only · ~1 GB RAM", belowMin: false, testingOnly: true },
];

function ModeChooserSlide({
  mode,
  onModeChange,
  llmModel,
  onModelChange,
  onBack,
  onContinue,
}: {
  readonly mode: Mode;
  readonly onModeChange: (m: Mode) => void;
  readonly llmModel: string;
  readonly onModelChange: (m: string) => void;
  readonly onBack: () => void;
  readonly onContinue: () => void;
}) {
  const canContinue = true;
  const continueLabel = "Continue with Local only";
  const selectedModel =
    ONBOARDING_MODELS.find((m) => m.id === llmModel) ?? ONBOARDING_MODELS[0];

  const modeTile = (
    id: Mode,
    icon: React.ReactNode,
    name: string,
    tagText: string,
    tagBg: string,
    description: string,
    pros: string[],
    tileBg: string,
    requirement?: string,
    span2?: boolean,
    providerPills?: string[],
  ) => {
    const selected = mode === id;
    return (
      <button
        key={id}
        onClick={() => onModeChange(id)}
        className={`relative flex flex-col items-start gap-2 rounded-3 border p-4 text-left transition-all ${
          span2 ? "col-span-2" : ""
        } ${
          selected
            ? "border-indigo shadow-glow"
            : "border-hairline hover:border-hairline-2"
        } ${tileBg}`}
      >
        {/* Check badge */}
        {selected && (
          <div className="absolute top-3 right-3 flex h-5 w-5 items-center justify-center rounded-full bg-indigo">
            <Check strokeWidth={2} className="h-3 w-3 text-white" />
          </div>
        )}

        {/* Icon */}
        <div className="flex h-9 w-9 items-center justify-center rounded-[10px] bg-white/80 shadow-sm">
          {icon}
        </div>

        {/* Name + tag */}
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-ink">{name}</span>
          <span
            className={`rounded-pill px-2 py-0.5 text-[10px] font-medium ${tagBg}`}
          >
            {tagText}
          </span>
        </div>

        {/* Description */}
        <p className="text-xs text-muted">{description}</p>

        {/* Pros */}
        <ul className="space-y-1">
          {pros.map((pro) => (
            <li key={pro} className="flex items-center gap-1.5 text-[11px] text-ink">
              <Check strokeWidth={1.6} className="h-3 w-3 text-indigo" />
              {pro}
            </li>
          ))}
        </ul>

        {/* Hardware requirement */}
        {requirement && (
          <p className="text-sm font-medium text-indigo">{requirement}</p>
        )}

        {/* Provider pills */}
        {providerPills && (
          <div className="flex flex-wrap gap-1.5 mt-1">
            {providerPills.map((pill) => (
              <span
                key={pill}
                className="rounded-pill bg-white/60 px-2 py-0.5 text-[10px] font-medium text-muted"
              >
                {pill}
              </span>
            ))}
          </div>
        )}
      </button>
    );
  };

  return (
    <div className="flex flex-1 flex-col px-10 py-7">
      <BrandRow />

      <h2 className="text-[28px] font-semibold tracking-tight text-ink">
        How should Arandu think?
      </h2>
      <p className="mt-2 text-sm text-muted">
        Choose how your AI processes data. You can change this anytime.
      </p>

      <div className="mt-5 grid grid-cols-1 gap-3">
        {modeTile(
          "local",
          <Lock strokeWidth={1.6} className="h-5 w-5 text-success" />,
          "Local Only",
          "On-device",
          "bg-success-soft text-success",
          "Every prompt runs on your Mac. Nothing ever leaves your device.",
          ["Maximum privacy"],
          "bg-gradient-to-br from-indigo-tint to-indigo-soft",
          "Needs ≥ M2/M3 Ultra + 64–128 GB RAM + 1–2 TB SSD",
        )}
      </div>

      {/* Model selection + hardware warning */}
      <div className="mt-4">
        <label className="mb-1.5 block text-xs text-muted">
          Model (you can change this anytime)
        </label>
        <select
          value={llmModel}
          onChange={(e) => onModelChange(e.target.value)}
          className="w-full rounded-2 border border-hairline bg-white/80 px-3 py-2 text-sm text-ink outline-none"
        >
          {ONBOARDING_MODELS.map((m) => (
            <option key={m.id} value={m.id}>
              {m.label} — {m.note}
            </option>
          ))}
        </select>

        <div className="mt-3 rounded-3 border border-amber/30 bg-amber-soft p-3.5">
          {selectedModel.testingOnly ? (
            <>
              <p className="text-[13px] font-semibold text-ink">
                Interface testing only.
              </p>
              <p className="mt-1 text-[13px] text-ink-2">
                A 1B model is far too small for real answers — use it to try
                the app's interface on a low-RAM machine. Expect incoherent
                or empty responses.
              </p>
            </>
          ) : selectedModel.belowMin ? (
            <>
              <p className="text-[13px] font-semibold text-ink">
                Results not guaranteed below Llama 3.1 70B.
              </p>
              <p className="mt-1 text-[13px] text-ink-2">
                This model runs on lighter machines, but Arandu can't
                guarantee acceptable results with it.
              </p>
            </>
          ) : (
            <>
              <p className="text-[13px] font-semibold text-ink">
                This is a demanding default.
              </p>
              <p className="mt-1 text-[13px] text-ink-2">
                On hardware weaker than the spec above, llama3.1:70b can
                starve the OS and make your computer unresponsive. Pick a
                lighter model above if your machine doesn't meet it.
              </p>
            </>
          )}
        </div>
      </div>

      <div className="mt-auto pt-6 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button
            onClick={onBack}
            className="text-sm font-medium text-muted transition-colors hover:text-ink"
          >
            Back
          </button>
          <TrustChip>Audit log shows every egress</TrustChip>
          <TrustChip>Change anytime</TrustChip>
        </div>

        <button
          onClick={onContinue}
          disabled={!canContinue}
          className={`flex items-center gap-2 rounded-pill px-6 py-3 text-sm font-medium text-white transition-colors ${
            canContinue
              ? "bg-indigo hover:bg-indigo/90"
              : "cursor-not-allowed bg-indigo/40"
          }`}
        >
          {continueLabel}
          <ChevronRight strokeWidth={1.6} className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Slide 4: Keep Awake (System)
// ---------------------------------------------------------------------------

function KeepAwakeSlide({
  preventSleep,
  launchAtLogin,
  menuBarMode,
  onToggle,
  onContinue,
}: {
  readonly preventSleep: boolean;
  readonly launchAtLogin: boolean;
  readonly menuBarMode: boolean;
  readonly onToggle: (key: "prevent_sleep" | "launch_at_login" | "menu_bar_mode") => void;
  readonly onContinue: () => void;
}) {
  return (
    <div className="flex flex-1 flex-col px-10 py-10">
      <BrandRow />

      <h2 className="text-[28px] font-semibold tracking-tight text-ink">
        Keep me awake.
      </h2>
      <p className="mt-2 text-sm text-muted">
        These settings help Arandu stay ready to work for you.
      </p>

      {/* Toggle card */}
      <div className="mt-8 rounded-4 border border-hairline bg-surface p-1 shadow-1">
        {/* Row 1 */}
        <div className="flex items-center justify-between px-5 py-4">
          <div className="flex items-center gap-3">
            <Power strokeWidth={1.6} className="h-5 w-5 text-ink" />
            <div>
              <p className="text-sm font-medium text-ink">
                Prevent Mac from sleeping
              </p>
              <p className="text-[11px] text-muted">
                Keeps your Mac awake while Arandu is open
              </p>
            </div>
          </div>
          <Toggle on={preventSleep} onToggle={() => onToggle("prevent_sleep")} />
        </div>
        <div className="mx-5 border-t border-hairline" />

        {/* Row 2 */}
        <div className="flex items-center justify-between px-5 py-4">
          <div className="flex items-center gap-3">
            <Download strokeWidth={1.6} className="h-5 w-5 text-ink" />
            <div>
              <p className="text-sm font-medium text-ink">
                Launch at login
              </p>
              <p className="text-[11px] text-muted">
                Start Arandu automatically when you log in
              </p>
            </div>
          </div>
          <Toggle on={launchAtLogin} onToggle={() => onToggle("launch_at_login")} />
        </div>
        <div className="mx-5 border-t border-hairline" />

        {/* Row 3 */}
        <div className="flex items-center justify-between px-5 py-4">
          <div className="flex items-center gap-3">
            <Server strokeWidth={1.6} className="h-5 w-5 text-ink" />
            <div>
              <p className="text-sm font-medium text-ink">
                Run in menu bar when window closes
              </p>
              <p className="text-[11px] text-muted">
                Keeps indexing and notifications active in the background
              </p>
            </div>
          </div>
          <Toggle on={menuBarMode} onToggle={() => onToggle("menu_bar_mode")} />
        </div>
      </div>

      {/* Callout */}
      <div className="mt-4 rounded-3 bg-indigo-tint px-4 py-3">
        <p className="text-[12px] text-indigo-2">
          These toggles only affect sleep while the app is open. Your Mac
          will sleep normally when Arandu is fully quit.
        </p>
      </div>

      <div className="mt-auto pt-10 flex items-center justify-end">
        <button
          onClick={onContinue}
          className="flex items-center gap-2 rounded-pill bg-indigo px-6 py-3 text-sm font-medium text-white transition-colors hover:bg-indigo/90"
        >
          Continue
          <ChevronRight strokeWidth={1.6} className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Slide 5: Connectors (Sources)
// ---------------------------------------------------------------------------

function ConnectorsSlide({
  selected,
  onToggle,
  onContinue,
}: {
  readonly selected: Set<string>;
  readonly onToggle: (id: string) => void;
  readonly onContinue: () => void;
}) {
  const canContinue = selected.size > 0;

  return (
    <div className="flex flex-1 flex-col px-10 py-10">
      <BrandRow />

      <h2 className="text-[28px] font-semibold tracking-tight text-ink">
        Connect your life.
      </h2>
      <p className="mt-2 text-sm text-muted">
        Choose the data sources Arandu should index. You can add more later.
      </p>

      {/* Connector grid */}
      <div className="mt-8 grid grid-cols-2 gap-3">
        {CONNECTOR_DEFS.map((c) => {
          const isSelected = selected.has(c.id);
          const Icon = c.icon;
          return (
            <button
              key={c.id}
              onClick={() => onToggle(c.id)}
              className={`relative flex items-center gap-3 rounded-3 border p-4 text-left transition-all ${
                isSelected
                  ? "border-indigo shadow-2"
                  : "border-hairline hover:border-hairline-2"
              }`}
            >
              {/* Icon */}
              <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-[10px] bg-surface ${c.color}`}>
                <Icon strokeWidth={1.6} className="h-5 w-5" />
              </div>

              {/* Text */}
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <p className="text-sm font-medium text-ink">{c.name}</p>
                  {c.tag && (
                    <span className="rounded-pill bg-indigo-soft px-1.5 py-0.5 text-[9px] font-medium text-indigo">
                      {c.tag}
                    </span>
                  )}
                </div>
                <p className="text-[11px] text-muted">{c.description}</p>
              </div>

              {/* Circular checkbox */}
              <div
                className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full border-2 transition-colors ${
                  isSelected
                    ? "border-indigo bg-indigo"
                    : "border-hairline-2 bg-transparent"
                }`}
              >
                {isSelected && (
                  <Check strokeWidth={2.5} className="h-3.5 w-3.5 text-white" />
                )}
              </div>
            </button>
          );
        })}
      </div>

      <p className="mt-4 text-[11px] text-muted">
        More integrations available in Settings &rarr; Connectors &rarr; Discover
      </p>

      <div className="mt-auto pt-10 flex items-center justify-between">
        <TrustChip>
          <Lock strokeWidth={1.6} className="h-3 w-3" />
          All indexed locally
        </TrustChip>

        <button
          onClick={onContinue}
          disabled={!canContinue}
          className={`flex items-center gap-2 rounded-pill px-6 py-3 text-sm font-medium text-white transition-colors ${
            canContinue
              ? "bg-indigo hover:bg-indigo/90"
              : "cursor-not-allowed bg-indigo/40"
          }`}
        >
          Continue
          <ChevronRight strokeWidth={1.6} className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Slide 6: Notifications
// ---------------------------------------------------------------------------

function NotificationsSlide({
  whatsappNotifications,
  whatsappPhone,
  whatsappPairingStarted,
  whatsappPairingError,
  whatsappStartingPair,
  whatsappPaired,
  onToggle,
  onPhoneChange,
  onStartWhatsappPairing,
  onWhatsappConnected,
  onContinue,
}: {
  readonly whatsappNotifications: boolean;
  readonly whatsappPhone: string;
  readonly whatsappPairingStarted: boolean;
  readonly whatsappPairingError: string | null;
  readonly whatsappStartingPair: boolean;
  readonly whatsappPaired: boolean;
  readonly onToggle: (key: "whatsapp_notifications") => void;
  readonly onPhoneChange: (phone: string) => void;
  readonly onStartWhatsappPairing: () => void;
  readonly onWhatsappConnected: () => void;
  readonly onContinue: () => void;
}) {
  const phoneValid =
    !whatsappNotifications || /^\+\d{7,15}$/.test(whatsappPhone.replace(/\s/g, ""));

  return (
    <div className="flex flex-1 flex-col px-10 py-10">
      <BrandRow />

      <h2 className="text-[28px] font-semibold tracking-tight text-ink">
        How should I reach you?
      </h2>
      <p className="mt-2 text-sm text-muted">
        Choose how Arandu sends you updates and alerts.
      </p>

      {/* Toggle card */}
      <div className="mt-8 rounded-4 border border-hairline bg-surface p-1 shadow-1">
        {/* WhatsApp */}
        <div className="px-5 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <MessageCircle strokeWidth={1.6} className="h-5 w-5 text-green-500" />
              <div>
                <p className="text-sm font-medium text-ink">WhatsApp</p>
                <p className="text-[11px] text-muted">
                  Get briefs and alerts via WhatsApp
                </p>
              </div>
            </div>
            <Toggle
              on={whatsappNotifications}
              onToggle={() => onToggle("whatsapp_notifications")}
            />
          </div>
          {whatsappNotifications && (
            <div className="mt-3 ml-8 space-y-3">
              <div className="flex items-center gap-2">
                <input
                  type="tel"
                  value={whatsappPhone}
                  onChange={(e) => onPhoneChange(e.target.value)}
                  placeholder="+1 555 123 4567"
                  disabled={whatsappPairingStarted}
                  className="w-full max-w-xs rounded-2 border border-hairline bg-bg-2 px-3 py-2 font-mono text-sm text-ink outline-none placeholder:text-faint focus:border-indigo disabled:cursor-not-allowed disabled:opacity-60"
                />
                {!whatsappPairingStarted && (
                  <button
                    onClick={onStartWhatsappPairing}
                    disabled={!phoneValid || whatsappStartingPair}
                    className={`rounded-pill px-4 py-2 text-xs font-medium text-white transition-colors ${
                      phoneValid && !whatsappStartingPair
                        ? "bg-indigo hover:bg-indigo/90"
                        : "cursor-not-allowed bg-indigo/40"
                    }`}
                  >
                    {whatsappStartingPair ? "Starting..." : "Pair WhatsApp"}
                  </button>
                )}
                {whatsappPaired && (
                  <span className="flex items-center gap-1 text-xs font-medium text-success">
                    <CheckCircle2 strokeWidth={2} className="h-4 w-4" />
                    Paired
                  </span>
                )}
              </div>
              {whatsappPhone && !phoneValid && !whatsappPairingStarted && (
                <p className="text-[10px] text-amber-500">
                  Enter a valid phone number with country code (e.g. +1 555 123 4567)
                </p>
              )}
              {whatsappPairingError && (
                <p className="text-[10px] text-amber-500">
                  {whatsappPairingError}
                </p>
              )}
              {whatsappPairingStarted && (
                <WhatsAppPairingPanel
                  enabled={true}
                  onConnected={onWhatsappConnected}
                />
              )}
            </div>
          )}
        </div>
      </div>

      <div className="mt-auto pt-10 flex items-center justify-end">
        <button
          onClick={onContinue}
          disabled={whatsappNotifications && !phoneValid}
          className={`flex items-center gap-2 rounded-pill px-6 py-3 text-sm font-medium text-white transition-colors ${
            !whatsappNotifications || phoneValid
              ? "bg-indigo hover:bg-indigo/90"
              : "cursor-not-allowed bg-indigo/40"
          }`}
        >
          Continue
          <ChevronRight strokeWidth={1.6} className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Slide 7: Closing (Ready)
// ---------------------------------------------------------------------------

function ClosingSlide({
  firstName,
  connectedCount,
  modeName,
  notifyChannels,
  finishing,
  onOpen,
}: {
  readonly firstName: string;
  readonly connectedCount: number;
  readonly modeName: string;
  readonly notifyChannels: string[];
  readonly finishing: boolean;
  readonly onOpen: () => void;
}) {

  return (
    <div className="flex flex-1 flex-col px-10 py-10">
      <BrandRow />

      <h1 className="text-[42px] font-semibold leading-tight tracking-tight text-ink">
        You're
        <br />
        <span
          style={{
            background: HEADLINE_GRADIENT,
            WebkitBackgroundClip: "text",
            WebkitTextFillColor: "transparent",
            backgroundClip: "text",
          }}
        >
          set.
        </span>
      </h1>

      <p className="mt-6 max-w-md text-[15px] leading-relaxed text-muted">
        Welcome, {firstName || "friend"}. I've started indexing your data and
        I'll quietly begin organizing. Your first morning brief lands tomorrow
        at 7 a.m.
      </p>

      {/* Summary cards */}
      <div className="mt-10 grid grid-cols-3 gap-3">
        <div className="rounded-3 border border-hairline bg-surface p-4 shadow-1">
          <p className="text-[11px] font-medium text-muted">Indexed</p>
          <p className="mt-1 text-lg font-semibold text-ink">
            {connectedCount} source{connectedCount !== 1 ? "s" : ""}
          </p>
        </div>
        <div className="rounded-3 border border-hairline bg-surface p-4 shadow-1">
          <p className="text-[11px] font-medium text-muted">Mode</p>
          <p className="mt-1 text-lg font-semibold text-ink">{modeName}</p>
        </div>
        <div className="rounded-3 border border-hairline bg-surface p-4 shadow-1">
          <p className="text-[11px] font-medium text-muted">Notify via</p>
          <p className="mt-1 text-sm font-semibold text-ink">
            {notifyChannels.length > 0 ? notifyChannels.join(", ") : "None"}
          </p>
        </div>
      </div>

      <div className="mt-auto pt-10 flex items-center justify-between">
        <TrustChip>
          <Lock strokeWidth={1.6} className="h-3 w-3" />
          Indexing locally
        </TrustChip>

        {finishing ? (
          <div
            role="status"
            aria-live="polite"
            className="flex items-center gap-2 rounded-pill bg-indigo px-6 py-3 text-sm font-medium text-white"
            style={{ opacity: 0.85 }}
          >
            <Loader2 strokeWidth={1.6} className="h-4 w-4 animate-spin" />
            Setting up...
          </div>
        ) : (
          <button
            onClick={onOpen}
            className="flex items-center gap-2 rounded-pill bg-indigo px-6 py-3 text-sm font-medium text-white transition-colors hover:bg-indigo/90"
          >
            Open Arandu
            <ChevronRight strokeWidth={1.6} className="h-4 w-4" />
          </button>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Orchestrator
// ---------------------------------------------------------------------------

function OnboardingWizard({ onComplete }: OnboardingWizardProps) {
  const [slide, setSlide] = useState<Slide>(1);
  const [direction, setDirection] = useState<"forward" | "back">("forward");

  // --- Slide 2: Mode ---
  const [mode, setMode] = useState<Mode>("local");
  // Recommended default model. Users can downgrade here, but Arandu only
  // guarantees acceptable results at llama3.1:70b — see the warning on the slide.
  const [llmModel, setLlmModel] = useState("llama3.1:70b");

  // --- Slide 3: Keep Awake ---
  const [preventSleep, setPreventSleep] = useState(true);
  const [launchAtLogin, setLaunchAtLogin] = useState(true);
  const [menuBarMode, setMenuBarMode] = useState(true);

  // --- Slide 4: Connectors ---
  const [selectedConnectors, setSelectedConnectors] = useState<Set<string>>(
    () => new Set(CONNECTOR_DEFS.filter((c) => c.defaultChecked).map((c) => c.id)),
  );
  const catalogLoaded = useRef(false);

  // --- Slide 2: Profile ---
  const [firstName, setFirstName] = useState("");

  // --- Slide 5: Notifications ---
  const [whatsappNotifications, setWhatsappNotifications] = useState(true);
  const [whatsappPhone, setWhatsappPhone] = useState("");
  const [whatsappPairingStarted, setWhatsappPairingStarted] = useState(false);
  const [whatsappStartingPair, setWhatsappStartingPair] = useState(false);
  const [whatsappPairingError, setWhatsappPairingError] = useState<string | null>(null);
  const [whatsappPaired, setWhatsappPaired] = useState(false);

  // Briefly true while the wizard's handleFinish saves settings before
  // dismissing. The heavy `toggle_connector` work no longer happens here
  // — see useOnboardingFollowup — so this typically flashes for <1s.
  const [finishing, setFinishing] = useState(false);

  // --- IPC: Ollama status (for mode validation) ---
  const [ollamaStatus, setOllamaStatus] =
    useState<OllamaStatusResponse | null>(null);

  // --- IPC: Catalog entries (for connector enable calls) ---
  const [, setCatalogEntries] = useState<CatalogEntry[]>([]);

  // Pre-check Ollama on mount
  useEffect(() => {
    let active = true;
    invoke<OllamaStatusResponse>("get_ollama_status")
      .then((status) => {
        if (active) setOllamaStatus(status);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, []);

  // Load connector catalog on mount
  useEffect(() => {
    if (catalogLoaded.current) return;
    catalogLoaded.current = true;
    let active = true;
    dedupInvoke<CatalogEntry[]>("get_connector_catalog")
      .then((entries) => {
        if (active) setCatalogEntries(entries);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, []);

  // Pre-fill the name + WhatsApp phone if already saved (e.g. re-running
  // onboarding).
  useEffect(() => {
    let active = true;
    dedupInvoke<AppSettings>("get_settings")
      .then((s) => {
        if (!active) return;
        if (typeof s.user_name === "string") setFirstName(s.user_name);
        if (typeof s.whatsapp_notification_phone === "string") {
          setWhatsappPhone(s.whatsapp_notification_phone);
        }
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, []);

  // Reflect an already-connected listener on the Notifications slide. The
  // only thing that polls listener status is WhatsAppPairingPanel, and it
  // doesn't mount until the user clicks "Pair WhatsApp" — so a WhatsApp that
  // was paired in a prior session shows no status feedback (and prompts a
  // needless re-pair) until we surface it here on mount.
  useEffect(() => {
    let active = true;
    dedupInvoke<WhatsappListenerStatus>("get_whatsapp_listener_status")
      .then((status) => {
        if (!active) return;
        if (status?.status_file?.phase === "connected") {
          setWhatsappPairingStarted(true);
          setWhatsappPaired(true);
        }
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, []);

  // --- Navigation ---

  const goTo = useCallback(
    (target: Slide, dir: "forward" | "back" = "forward") => {
      setDirection(dir);
      setSlide(target);
    },
    [],
  );

  const goBack = useCallback(() => {
    if (slide > 1) {
      goTo((slide - 1) as Slide, "back");
    }
  }, [slide, goTo]);

  const goForward = useCallback(() => {
    if (slide < 7) {
      goTo((slide + 1) as Slide, "forward");
    }
  }, [slide, goTo]);

  // --- Toggle handlers ---

  const handleKeepAwakeToggle = useCallback(
    (key: "prevent_sleep" | "launch_at_login" | "menu_bar_mode") => {
      if (key === "prevent_sleep") setPreventSleep((v) => !v);
      else if (key === "launch_at_login") setLaunchAtLogin((v) => !v);
      else if (key === "menu_bar_mode") setMenuBarMode((v) => !v);
    },
    [],
  );

  const handleConnectorToggle = useCallback((id: string) => {
    setSelectedConnectors((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const handleNotificationToggle = useCallback(
    (key: "whatsapp_notifications") => {
      if (key === "whatsapp_notifications") setWhatsappNotifications((v) => !v);
    },
    [],
  );

  // Kick off WhatsApp pairing inline on the Notifications slide:
  // 1. Save the phone (canonical settings key: whatsapp_notification_phone)
  //    and flip notifications_enabled so the pipeline worker picks it up.
  // 2. Enable the whatsapp connector — this starts the Baileys listener
  //    subprocess, which begins emitting QR codes via status_file.
  // 3. The WhatsAppPairingPanel renders below the input and polls
  //    get_whatsapp_listener_status; once phase === "connected" it
  //    fires onConnected (handleWhatsappConnected here).
  // Idempotent w.r.t. handleFinish: it doesn't iterate "whatsapp" in
  // selectedConnectors (sources slide), so the connector won't be
  // re-enabled at finish time.
  const handleStartWhatsappPairing = useCallback(async () => {
    const normalized = whatsappPhone.replace(/\s/g, "");
    if (!/^\+\d{7,15}$/.test(normalized)) {
      setWhatsappPairingError(
        "Enter a valid phone number with country code first.",
      );
      return;
    }
    setWhatsappPairingError(null);
    setWhatsappStartingPair(true);
    try {
      const current = await dedupInvoke<AppSettings>("get_settings");
      await invoke("update_settings", {
        settings: {
          ...current,
          whatsapp_notification_phone: normalized,
          notifications_enabled: true,
        },
      });
      await invoke("toggle_connector", {
        connectorId: "whatsapp",
        enabled: true,
      });
      setWhatsappPairingStarted(true);
    } catch (err) {
      console.error("WhatsApp pairing start failed:", err);
      setWhatsappPairingError(
        err instanceof Error ? err.message : String(err),
      );
    } finally {
      setWhatsappStartingPair(false);
    }
  }, [whatsappPhone]);

  const handleWhatsappConnected = useCallback(() => {
    setWhatsappPaired(true);
  }, []);

  // --- Finish: persist everything ---

  // Persist the user's choices to settings, mark the post-onboarding
  // follow-up as pending, then dismiss the wizard immediately. The
  // Dashboard's `useOnboardingFollowup` hook picks up
  // `onboarding_followup_pending` on mount and runs the actual
  // `toggle_connector` calls in the background — that work used to
  // happen here and could take minutes, leaving the user staring at
  // a wizard that looked dead. Pending-permission detection still
  // happens; it now surfaces as a Dashboard banner instead of the
  // closing-slide "Almost there" variant.
  const handleFinish = useCallback(async () => {
    setFinishing(true);
    const connectorIds = Array.from(selectedConnectors);

    const providerMap: Record<Mode, string> = {
      local: "ollama",
      remote: "ollama",
    };

    const notificationSettings: Record<string, unknown> = {
      notifications_enabled: whatsappNotifications,
      whatsapp_notifications: whatsappNotifications,
    };
    if (whatsappNotifications && whatsappPhone) {
      notificationSettings.whatsapp_notification_phone =
        whatsappPhone.replace(/\s/g, "");
    }

    try {
      const current = await dedupInvoke<AppSettings>("get_settings");
      const updated = {
        ...current,
        user_name: firstName.trim() || current.user_name || null,
        llm_provider: providerMap[mode],
        llm_model: llmModel,
        prevent_sleep: preventSleep,
        launch_at_login: launchAtLogin,
        menu_bar_mode: menuBarMode,
        ...notificationSettings,
        initial_connectors: connectorIds,
        ollama_configured:
          mode === "local" && ollamaStatus?.server_reachable === true,
        onboarding_completed: true,
        onboarding_completed_at: new Date().toISOString(),
        onboarding_followup_pending: connectorIds.length > 0,
      };
      await invoke("update_settings", { settings: updated });
      // Pull + load the chosen model now that it's saved. Fire-and-forget:
      // it can take a while (a large model downloads first), and progress
      // surfaces via the "Preparing model" background task / status indicator.
      void invoke("preload_ollama_model").catch(() => {});
    } catch (err) {
      console.error("Failed to save onboarding state:", err);
    }

    setFinishing(false);
    onComplete();
  }, [
    selectedConnectors,
    mode,
    llmModel,
    firstName,
    preventSleep,
    launchAtLogin,
    menuBarMode,
    whatsappNotifications,
    whatsappPhone,
    ollamaStatus,
    onComplete,
  ]);

  // --- Derived values for closing slide ---

  const modeNames: Record<Mode, string> = {
    local: "Local only",
    remote: "Full remote",
  };

  const notifyChannels: string[] = [];
  if (whatsappNotifications) notifyChannels.push("WhatsApp");

  // --- Render ---

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{
        background: "var(--bg)",
        backgroundImage:
          "radial-gradient(circle at 0% 0%, oklch(0.94 0.04 265 / 0.4), transparent 40%), radial-gradient(circle at 100% 100%, oklch(0.95 0.04 165 / 0.25), transparent 50%)",
      }}
    >
      <div className="mx-4 flex w-full max-w-3xl flex-col overflow-hidden rounded-[20px] border border-hairline shadow-3"
        style={{
          height: "min(680px, calc(100vh - 80px))",
          background: "var(--surface)",
          backgroundImage:
            "radial-gradient(circle at 0% 0%, oklch(0.94 0.04 265 / 0.3), transparent 40%), radial-gradient(circle at 100% 100%, oklch(0.95 0.04 165 / 0.2), transparent 50%)",
        }}
      >
        <TopBar slide={slide} onBack={slide > 1 ? goBack : null} />

        <div className="flex flex-1 flex-col overflow-y-auto">
          <SlideTransition slideKey={slide} direction={direction}>
            {slide === 1 && (
              <WelcomeSlide onGetStarted={goForward} />
            )}
            {slide === 2 && (
              <ProfileSlide
                firstName={firstName}
                onChange={setFirstName}
                onContinue={goForward}
              />
            )}
            {slide === 3 && (
              <ModeChooserSlide
                mode={mode}
                onModeChange={setMode}
                llmModel={llmModel}
                onModelChange={setLlmModel}
                onBack={goBack}
                onContinue={goForward}
              />
            )}
            {slide === 4 && (
              <KeepAwakeSlide
                preventSleep={preventSleep}
                launchAtLogin={launchAtLogin}
                menuBarMode={menuBarMode}
                onToggle={handleKeepAwakeToggle}
                onContinue={goForward}
              />
            )}
            {slide === 5 && (
              <ConnectorsSlide
                selected={selectedConnectors}
                onToggle={handleConnectorToggle}
                onContinue={goForward}
              />
            )}
            {slide === 6 && (
              <NotificationsSlide
                whatsappNotifications={whatsappNotifications}
                whatsappPhone={whatsappPhone}
                whatsappPairingStarted={whatsappPairingStarted}
                whatsappPairingError={whatsappPairingError}
                whatsappStartingPair={whatsappStartingPair}
                whatsappPaired={whatsappPaired}
                onToggle={handleNotificationToggle}
                onPhoneChange={setWhatsappPhone}
                onStartWhatsappPairing={handleStartWhatsappPairing}
                onWhatsappConnected={handleWhatsappConnected}
                onContinue={goForward}
              />
            )}
            {slide === 7 && (
              <ClosingSlide
                firstName={firstName}
                connectedCount={selectedConnectors.size}
                modeName={modeNames[mode]}
                notifyChannels={notifyChannels}
                finishing={finishing}
                onOpen={handleFinish}
              />
            )}
          </SlideTransition>
        </div>
      </div>
    </div>
  );
}

export default OnboardingWizard;
