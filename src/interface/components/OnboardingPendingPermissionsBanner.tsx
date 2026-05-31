/**
 * Top-of-page banner surfacing pending macOS permissions discovered
 * by the post-onboarding follow-up.
 *
 * The wizard used to host this UI on its "Almost there" closing-slide
 * variant. Now that the heavy `toggle_connector` work happens in the
 * background after the wizard dismisses, the surface for missing
 * permissions has to live in the main app — otherwise the user lands
 * on the dashboard with no idea that the apple-* connectors they
 * picked actually need Full Disk Access to start syncing.
 *
 * Rendered by Layout above the Outlet, so it shows on every route
 * while pending permissions exist.
 *
 * sensitivity_tier: 1
 */

import { AlertTriangle } from "lucide-react";
import { invoke } from "@tauri-apps/api/core";
import { useOnboardingFollowupContext } from "../App";

function OnboardingPendingPermissionsBanner() {
  const followup = useOnboardingFollowupContext();
  if (!followup || followup.pendingPermissions.length === 0) return null;

  // Multiple connectors often need the same permission (e.g. all
  // apple-* SQLite bridges need Full Disk Access). Collapse to one
  // CTA per permission key.
  const grouped = followup.pendingPermissions.reduce<
    Map<string, { connectors: string[] }>
  >((acc, p) => {
    const existing = acc.get(p.permissionKey);
    if (existing) {
      existing.connectors.push(p.connectorName);
    } else {
      acc.set(p.permissionKey, { connectors: [p.connectorName] });
    }
    return acc;
  }, new Map());

  const openSettings = async (key: string) => {
    try {
      await invoke("open_macos_permission_settings", { permission: key });
    } catch (err) {
      console.error("open_macos_permission_settings failed:", err);
    }
  };

  return (
    <div className="border-b border-amber/30 bg-amber-soft px-10 py-3">
      <div className="flex items-start gap-3">
        <AlertTriangle
          strokeWidth={1.6}
          className="mt-0.5 h-4 w-4 shrink-0 text-amber-600"
        />
        <div className="flex flex-1 flex-col gap-2">
          <p className="text-[13px] font-semibold text-ink">
            macOS access needed to finish setup
          </p>
          <div className="flex flex-col gap-1.5">
            {Array.from(grouped.entries()).map(([key, group]) => (
              <div
                key={key}
                className="flex items-center justify-between gap-3"
              >
                <p className="text-[12px] text-ink-2">
                  <span className="font-medium text-ink">{key}</span>
                  {" — "}
                  needed by {group.connectors.join(", ")}
                </p>
                <button
                  onClick={() => openSettings(key)}
                  className="shrink-0 rounded-pill bg-indigo px-3 py-1.5 text-[11px] font-medium text-white transition-colors hover:bg-indigo/90"
                >
                  Open System Settings
                </button>
              </div>
            ))}
          </div>
        </div>
        <button
          onClick={followup.dismissPendingPermissions}
          className="shrink-0 rounded-pill border border-hairline px-3 py-1.5 text-[11px] font-medium text-ink transition-colors hover:bg-surface"
        >
          Dismiss
        </button>
      </div>
    </div>
  );
}

export default OnboardingPendingPermissionsBanner;
