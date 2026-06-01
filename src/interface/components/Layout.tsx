import { useState, useEffect, createContext } from "react";
import { Outlet } from "react-router-dom";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import Sidebar from "./Sidebar";
import TopBar from "./TopBar";
import PipelineRefreshModal from "./PipelineRefreshModal";
import OnboardingPendingPermissionsBanner from "./OnboardingPendingPermissionsBanner";
import { ModelStatusBanner } from "./ModelStatusBanner";
import { usePipelineProgress } from "../hooks/usePipelineProgress";
import { useAutoRefresh } from "../hooks/useAutoRefresh";

const COLLAPSE_BREAKPOINT = 768;

export const PipelineRefreshContext = createContext<{
  readonly openRefreshModal: () => void;
}>({ openRefreshModal: () => {} });

function Layout() {
  const [collapsed, setCollapsed] = useState(
    () => window.innerWidth < COLLAPSE_BREAKPOINT,
  );

  const pipelineProgress = usePipelineProgress();

  useAutoRefresh();

  useEffect(() => {
    const onResize = () => {
      setCollapsed(window.innerWidth < COLLAPSE_BREAKPOINT);
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  useEffect(() => {
    let unlisten: UnlistenFn | null = null;
    void listen("arandu:proactive-refreshed", () => {
      window.dispatchEvent(
        new CustomEvent("arandu:proactive-refreshed"),
      );
    }).then((fn) => {
      unlisten = fn;
    });
    return () => {
      if (unlisten) unlisten();
    };
  }, []);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "r") {
        e.preventDefault();
        if (pipelineProgress.step === "idle" || pipelineProgress.step === "minimized") {
          pipelineProgress.openModal();
        }
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [pipelineProgress.step, pipelineProgress.openModal]);

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar collapsed={collapsed} onToggle={() => setCollapsed((c) => !c)} />

      <PipelineRefreshContext.Provider
        value={{ openRefreshModal: pipelineProgress.openModal }}
      >
        <div className="flex flex-1 flex-col overflow-hidden">
          <TopBar />
          <ModelStatusBanner />
          <OnboardingPendingPermissionsBanner />
          <main className="flex-1 overflow-y-auto px-10 py-8">
            <Outlet />
          </main>
        </div>
      </PipelineRefreshContext.Provider>

      {pipelineProgress.step !== "idle" && pipelineProgress.step !== "minimized" && (
        <PipelineRefreshModal
          state={pipelineProgress}
          onStartRun={pipelineProgress.startRun}
          onCancel={pipelineProgress.cancelRun}
          onClose={pipelineProgress.closeModal}
          onRetry={pipelineProgress.retry}
          onForceRefresh={() => pipelineProgress.startRun("force", "full")}
        />
      )}
    </div>
  );
}

export default Layout;
