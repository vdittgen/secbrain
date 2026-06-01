//! Ollama server supervisor.
//!
//! Ties the local Ollama server's lifecycle to Arandu so Ollama only runs
//! while Arandu does. The supervisor:
//!
//! * Takes over on startup: kills any pre-existing `ollama serve` (and its
//!   model `runner` children) left by the menu-bar app, a manual launch, or an
//!   orphan from a prior Arandu session that exited ungracefully.
//! * Spawns `ollama serve` as a child with `kill_on_drop` so a clean Tauri exit
//!   terminates the server via tokio's Drop impl.
//! * Watches the child via `child.wait()` and respawns on death with
//!   exponential backoff (capped at 60s, reset after 30s of uptime).
//! * On `RunEvent::ExitRequested`, sends SIGTERM and waits up to 5s before
//!   SIGKILL so the server can stop its runners cleanly.
//!
//! Note: macOS has no "die with parent" primitive, so a hard kill of Arandu
//! (SIGKILL / crash) can orphan `ollama serve`. The startup take-over reaps any
//! such orphan on the next launch — matching `whatsapp_supervisor`'s approach.
//!
//! sensitivity_tier: 1 (server process and port only, no user data)

use std::path::Path;
use std::process::Stdio;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use tokio::process::{Child, Command};
use tokio::sync::Notify;

/// Absolute candidate paths for the `ollama` binary. A Finder-launched app has
/// a minimal PATH (no `/usr/local/bin`), so we probe known locations directly
/// rather than relying on PATH resolution.
const OLLAMA_CANDIDATES: &[&str] = &[
    "/usr/local/bin/ollama",
    "/opt/homebrew/bin/ollama",
    "/Applications/Ollama.app/Contents/Resources/ollama",
];

/// Handle returned by [`OllamaSupervisor::spawn`].
///
/// Stored in Tauri app state so the `RunEvent::ExitRequested` handler can
/// request a graceful shutdown before the process exits.
pub struct OllamaSupervisor {
    shutdown: Arc<Notify>,
    cleanup_done: Arc<Notify>,
    shutting_down: Arc<AtomicBool>,
}

impl OllamaSupervisor {
    /// Start the supervisor task. Returns immediately; the loop runs in the
    /// background on the tokio runtime.
    pub fn spawn() -> Arc<Self> {
        let supervisor = Arc::new(Self {
            shutdown: Arc::new(Notify::new()),
            cleanup_done: Arc::new(Notify::new()),
            shutting_down: Arc::new(AtomicBool::new(false)),
        });
        let task = supervisor.clone();
        tauri::async_runtime::spawn(async move {
            run_loop(task).await;
        });
        supervisor
    }

    /// Signal the supervisor to terminate the server and exit its loop.
    /// Blocks up to `timeout` waiting for cleanup to finish.
    pub async fn shutdown(&self, timeout: Duration) {
        self.shutting_down.store(true, Ordering::Release);
        self.shutdown.notify_one();
        let _ = tokio::time::timeout(timeout, self.cleanup_done.notified()).await;
    }
}

async fn run_loop(supervisor: Arc<OllamaSupervisor>) {
    // Take over: kill any Ollama server Arandu doesn't own so we are the
    // single instance and can reliably reap it on exit.
    kill_external_ollama().await;

    let mut backoff = Duration::from_secs(1);

    loop {
        if supervisor.shutting_down.load(Ordering::Acquire) {
            break;
        }

        let mut child = match spawn_ollama().await {
            Ok(c) => c,
            Err(e) => {
                eprintln!("[ollama-sup] spawn failed: {e}");
                if sleep_or_shutdown(&supervisor, backoff).await {
                    break;
                }
                backoff = next_backoff(backoff);
                continue;
            }
        };

        let pid = child.id().unwrap_or(0);
        eprintln!("[ollama-sup] ollama serve spawned (pid={pid})");

        let started = Instant::now();
        let shutdown_requested = tokio::select! {
            status = child.wait() => {
                eprintln!(
                    "[ollama-sup] ollama exited after {:.0}s: {:?}",
                    started.elapsed().as_secs_f64(),
                    status,
                );
                false
            }
            _ = supervisor.shutdown.notified() => {
                eprintln!("[ollama-sup] shutdown requested, terminating ollama");
                graceful_kill(&mut child).await;
                true
            }
        };

        if shutdown_requested || supervisor.shutting_down.load(Ordering::Acquire) {
            break;
        }

        // Reset backoff if the server stayed alive long enough that this
        // wasn't a crashloop. Otherwise grow it.
        if started.elapsed() >= Duration::from_secs(30) {
            backoff = Duration::from_secs(1);
        } else {
            backoff = next_backoff(backoff);
        }
        if sleep_or_shutdown(&supervisor, backoff).await {
            break;
        }
    }

    // Belt-and-suspenders: ensure no `ollama serve`/`runner` we started lingers
    // (e.g. if SIGTERM left a runner behind).
    kill_external_ollama().await;
    supervisor.cleanup_done.notify_one();
}

fn next_backoff(current: Duration) -> Duration {
    (current * 2).min(Duration::from_secs(60))
}

/// Sleep for `duration`, returning early (with `true`) if shutdown is requested.
async fn sleep_or_shutdown(supervisor: &OllamaSupervisor, duration: Duration) -> bool {
    tokio::select! {
        _ = tokio::time::sleep(duration) => false,
        _ = supervisor.shutdown.notified() => true,
    }
}

fn resolve_ollama_binary() -> Option<String> {
    OLLAMA_CANDIDATES
        .iter()
        .find(|p| Path::new(p).exists())
        .map(|p| p.to_string())
}

async fn spawn_ollama() -> Result<Child, String> {
    let bin = resolve_ollama_binary()
        .ok_or_else(|| "ollama binary not found in known locations".to_string())?;

    let mut cmd = Command::new(&bin);
    cmd.arg("serve")
        // Single-GPU contention guard — matches src/models/ollama_manager.py.
        .env("OLLAMA_NUM_PARALLEL", "1")
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .kill_on_drop(true);

    cmd.spawn().map_err(|e| format!("spawn ollama serve: {e}"))
}

async fn graceful_kill(child: &mut Child) {
    let Some(pid) = child.id() else { return };

    let _ = Command::new("kill")
        .arg("-TERM")
        .arg(pid.to_string())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .await;

    let wait = tokio::time::timeout(Duration::from_secs(5), child.wait()).await;
    if wait.is_err() {
        eprintln!("[ollama-sup] ollama didn't exit on SIGTERM, sending SIGKILL");
        let _ = child.start_kill();
        let _ = child.wait().await;
    }
}

/// Kill any `ollama serve` and `ollama runner` processes not owned by this
/// supervisor's live child. Used for startup take-over and exit cleanup.
async fn kill_external_ollama() {
    // Kill `serve` first (it reaps its own runners on SIGTERM), then sweep any
    // straggler runners.
    for pattern in ["ollama serve", "ollama runner"] {
        let pids = pgrep(pattern).await;
        if pids.is_empty() {
            continue;
        }
        eprintln!("[ollama-sup] take-over: killing '{pattern}' pids: {pids:?}");
        signal_pids(&pids, "-TERM").await;
    }
    // Brief grace, then SIGKILL anything still alive.
    tokio::time::sleep(Duration::from_secs(2)).await;
    for pattern in ["ollama serve", "ollama runner"] {
        let pids = pgrep(pattern).await;
        if !pids.is_empty() {
            signal_pids(&pids, "-KILL").await;
        }
    }
}

async fn pgrep(pattern: &str) -> Vec<String> {
    let output = Command::new("pgrep")
        .arg("-f")
        .arg(pattern)
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .output()
        .await;
    let Ok(out) = output else {
        return Vec::new();
    };
    if !out.status.success() {
        return Vec::new();
    }
    String::from_utf8_lossy(&out.stdout)
        .split_whitespace()
        .map(|s| s.to_string())
        .collect()
}

async fn signal_pids(pids: &[String], signal: &str) {
    for pid in pids {
        let _ = Command::new("kill")
            .arg(signal)
            .arg(pid)
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .await;
    }
}
