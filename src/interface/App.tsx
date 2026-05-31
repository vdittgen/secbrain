import { useState, useEffect, useCallback, createContext, useContext } from "react";
import { invoke } from "@tauri-apps/api/core";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import Layout from "./components/Layout";
import OnboardingWizard from "./components/OnboardingWizard";
import SetupScreen from "./components/SetupScreen";
import UpdateRequiredModal from "./components/UpdateRequiredModal";
import { useUpdateChecker } from "./hooks/useUpdateChecker";
import {
  useOnboardingFollowup,
  type OnboardingFollowupState,
} from "./hooks/useOnboardingFollowup";
import Dashboard from "./pages/Dashboard";
import Chat from "./pages/Chat";
import Data from "./pages/Data";
import Goals from "./pages/Goals";
import Tasks from "./pages/Tasks";
import Inbox from "./pages/Inbox";
import Agents from "./pages/Agents";
import SkillsPage from "./pages/SkillsPage";
import ConnectorsPage from "./pages/ExtensionsPage";
import ProfilePage from "./pages/ProfilePage";
import SettingsPage from "./pages/SettingsPage";
import KeepAwakeModal from "./components/KeepAwakeModal";
import { dedupInvoke } from "./utils/requestDedup";
import { useTheme } from "./hooks/useTheme";

// sensitivity_tier: 1 (only checks onboarding_completed flag)
interface BootSettings {
  readonly onboarding_completed: boolean;
  readonly keep_awake_modal_seen?: boolean;
  readonly theme?: string;
  readonly [key: string]: unknown;
}

interface SetupStatus {
  readonly is_bundled: boolean;
  readonly venv_ready: boolean;
  readonly needs_setup: boolean;
}

function App() {
  const [checking, setChecking] = useState(true);
  const [needsSetup, setNeedsSetup] = useState(false);
  const [showOnboarding, setShowOnboarding] = useState(false);
  const [showKeepAwake, setShowKeepAwake] = useState(false);
  const [theme, setTheme] = useState<string>("light");
  const {
    state: updateState,
    updateRequired,
    startDownload,
    restart,
    recheckNow,
  } = useUpdateChecker();

  useTheme(theme);

  // Boot sequence has two phases:
  //   1. get_setup_status (Rust-only, never fails) — decides if we need
  //      to gate the app behind first-launch venv creation.
  //   2. get_settings (goes through Python) — only safe to call once the
  //      venv exists, so we skip it while needsSetup is true.
  const loadSettings = useCallback(() => {
    dedupInvoke<BootSettings>("get_settings")
      .then((s) => {
        setShowOnboarding(!s.onboarding_completed);
        if (s.onboarding_completed && !s.keep_awake_modal_seen) {
          setShowKeepAwake(true);
        }
        if (s.theme) setTheme(s.theme);
      })
      .catch(() => {
        setShowOnboarding(false);
      })
      .finally(() => setChecking(false));
  }, []);

  useEffect(() => {
    invoke<SetupStatus>("get_setup_status")
      .then((status) => {
        if (status.needs_setup) {
          setNeedsSetup(true);
          setChecking(false);
        } else {
          loadSettings();
        }
      })
      .catch(() => {
        // If even the status probe fails, assume dev/unbundled and proceed.
        loadSettings();
      });
  }, [loadSettings]);

  const handleSetupComplete = useCallback(() => {
    setNeedsSetup(false);
    setChecking(true);
    loadSettings();
  }, [loadSettings]);

  useEffect(() => {
    const handler = (e: Event) => setTheme((e as CustomEvent).detail);
    window.addEventListener("sb-theme-change", handler);
    return () => window.removeEventListener("sb-theme-change", handler);
  }, []);

  const handleOnboardingComplete = useCallback(() => {
    setShowOnboarding(false);
  }, []);

  if (needsSetup) {
    return <SetupScreen onComplete={handleSetupComplete} />;
  }

  // Brief loading — typically <50ms
  if (checking) return null;

  if (showOnboarding) {
    return (
      <>
        <OnboardingWizard onComplete={handleOnboardingComplete} />
        {updateRequired && (
          <UpdateRequiredModal
            state={updateState}
            onStartDownload={startDownload}
            onRestart={restart}
            onRetry={recheckNow}
          />
        )}
      </>
    );
  }

  return <PostOnboarding {...{ showKeepAwake, setShowKeepAwake, updateRequired, updateState, startDownload, restart, recheckNow }} />;
}

// Children of the post-onboarding tree mount `useOnboardingFollowup`
// once via a Context so a Dashboard mount/unmount cycle (e.g. route
// change to /settings and back) doesn't re-trigger the follow-up.
const OnboardingFollowupContext = createContext<OnboardingFollowupState | null>(
  null,
);

export function useOnboardingFollowupContext(): OnboardingFollowupState | null {
  return useContext(OnboardingFollowupContext);
}

interface PostOnboardingProps {
  readonly showKeepAwake: boolean;
  readonly setShowKeepAwake: (v: boolean) => void;
  readonly updateRequired: boolean;
  readonly updateState: ReturnType<typeof useUpdateChecker>["state"];
  readonly startDownload: () => void;
  readonly restart: () => void;
  readonly recheckNow: () => void;
}

function PostOnboarding({
  showKeepAwake,
  setShowKeepAwake,
  updateRequired,
  updateState,
  startDownload,
  restart,
  recheckNow,
}: PostOnboardingProps) {
  const followup = useOnboardingFollowup();
  return (
    <OnboardingFollowupContext.Provider value={followup}>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Dashboard />} />
            <Route path="profile" element={<ProfilePage />} />
            <Route path="chat" element={<Chat />} />
            <Route path="inbox" element={<Inbox />} />
            <Route path="goals" element={<Goals />} />
            <Route path="tasks" element={<Tasks />} />
            <Route path="data" element={<Data />} />
            <Route path="explorer" element={<Navigate to="/data?tab=sources" replace />} />
            <Route path="marts" element={<Navigate to="/data" replace />} />
            <Route path="graph" element={<Navigate to="/data?tab=graph" replace />} />
            <Route path="vectors" element={<Navigate to="/data?tab=vectors" replace />} />
            <Route path="audit" element={<Navigate to="/data?tab=audit" replace />} />
            <Route path="agents" element={<Agents />} />
            <Route path="skills" element={<SkillsPage />} />
            <Route path="connectors" element={<ConnectorsPage />} />
            <Route path="discover" element={<Navigate to="/connectors" replace />} />
            <Route path="extensions" element={<Navigate to="/connectors" replace />} />
            <Route path="data-sources" element={<Navigate to="/connectors" replace />} />
            <Route path="settings" element={<SettingsPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
      {showKeepAwake && (
        <KeepAwakeModal onDismiss={() => setShowKeepAwake(false)} />
      )}
      {updateRequired && (
        <UpdateRequiredModal
          state={updateState}
          onStartDownload={startDownload}
          onRestart={restart}
          onRetry={recheckNow}
        />
      )}
    </OnboardingFollowupContext.Provider>
  );
}

export default App;
