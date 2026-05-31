//! WhatsApp listener supervisor.
//!
//! Owns the lifecycle of the persistent WhatsApp listener subprocess so it
//! survives crashes and is reliably reaped on app exit. The supervisor:
//!
//! * Kills orphaned `whatsapp-listener-run` processes from prior Tauri
//!   sessions before spawning a fresh listener.
//! * Polls `whatsapp-listener-spec` (cheap Python CLI) to learn whether the
//!   WhatsApp connector is enabled and the MCP command to use.
//! * Spawns the listener with `kill_on_drop` so a clean Tauri exit terminates
//!   the child via tokio's Drop impl.
//! * Writes `listener.pid.json` so the Python notifier (and any other status
//!   readers) see a live pid even when the connection_manager bypasses
//!   `WhatsAppListenerService.start()`.
//! * Watches the child via `child.wait()` and respawns on death with
//!   exponential backoff (capped at 60s, reset after 30s of uptime).
//! * On `RunEvent::ExitRequested`, sends SIGTERM and waits up to 5s before
//!   SIGKILL so the listener flushes Baileys state.
//!
//! sensitivity_tier: 2

use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};
use tokio::fs::OpenOptions;
use tokio::process::{Child, Command};
use tokio::sync::Notify;

#[derive(Debug, Deserialize)]
struct ListenerSpec {
    enabled: bool,
    command: Option<String>,
    #[serde(default)]
    args: Vec<String>,
    pid_path: String,
    log_path: String,
}

#[derive(Debug, Serialize)]
struct PidFile {
    pid: u32,
    started_at: String,
    command: String,
    args: Vec<String>,
}

/// Handle returned by [`Supervisor::spawn`].
///
/// Stored in Tauri app state so the `RunEvent::ExitRequested` handler can
/// request a graceful shutdown before the process exits.
pub struct Supervisor {
    shutdown: Arc<Notify>,
    cleanup_done: Arc<Notify>,
    shutting_down: Arc<AtomicBool>,
}

impl Supervisor {
    /// Start the supervisor task. Returns immediately; the loop runs in the
    /// background on the tokio runtime.
    pub fn spawn(project_root: PathBuf) -> Arc<Self> {
        let supervisor = Arc::new(Self {
            shutdown: Arc::new(Notify::new()),
            cleanup_done: Arc::new(Notify::new()),
            shutting_down: Arc::new(AtomicBool::new(false)),
        });
        let task = supervisor.clone();
        tauri::async_runtime::spawn(async move {
            run_loop(task, project_root).await;
        });
        supervisor
    }

    /// Signal the supervisor to terminate the child and exit its loop.
    /// Blocks up to `timeout` waiting for cleanup to finish.
    pub async fn shutdown(&self, timeout: Duration) {
        self.shutting_down.store(true, Ordering::Release);
        self.shutdown.notify_one();
        let _ = tokio::time::timeout(timeout, self.cleanup_done.notified()).await;
    }
}

async fn run_loop(supervisor: Arc<Supervisor>, project_root: PathBuf) {
    // Clear any orphaned listener processes from a prior Tauri session that
    // exited ungracefully (force-quit, SIGKILL, crash). Without this the
    // fcntl lock stays held and our fresh listener exits immediately.
    kill_external_listeners().await;

    let mut backoff = Duration::from_secs(1);

    loop {
        if supervisor.shutting_down.load(Ordering::Acquire) {
            break;
        }

        let spec = match fetch_spec(&project_root).await {
            Ok(s) => s,
            Err(e) => {
                eprintln!("[wa-sup] spec fetch failed: {e}");
                if sleep_or_shutdown(&supervisor, Duration::from_secs(30)).await {
                    break;
                }
                continue;
            }
        };

        if !spec.enabled {
            remove_pid_file(&spec.pid_path).await;
            if sleep_or_shutdown(&supervisor, Duration::from_secs(15)).await {
                break;
            }
            continue;
        }

        let command = match spec.command.as_deref() {
            Some(c) if !c.is_empty() => c,
            _ => {
                eprintln!("[wa-sup] enabled but no command in spec");
                if sleep_or_shutdown(&supervisor, Duration::from_secs(30)).await {
                    break;
                }
                continue;
            }
        };

        let mut child = match spawn_listener(&project_root, &spec, command).await {
            Ok(c) => c,
            Err(e) => {
                eprintln!("[wa-sup] spawn failed: {e}");
                if sleep_or_shutdown(&supervisor, backoff).await {
                    break;
                }
                backoff = next_backoff(backoff);
                continue;
            }
        };

        let pid = child.id().unwrap_or(0);
        write_pid_file(&spec, pid, command).await;
        eprintln!("[wa-sup] listener spawned (pid={pid})");

        let started = Instant::now();
        let shutdown_requested = tokio::select! {
            status = child.wait() => {
                eprintln!(
                    "[wa-sup] listener exited after {:.0}s: {:?}",
                    started.elapsed().as_secs_f64(),
                    status,
                );
                false
            }
            _ = supervisor.shutdown.notified() => {
                eprintln!("[wa-sup] shutdown requested, terminating listener");
                graceful_kill(&mut child).await;
                true
            }
        };

        remove_pid_file(&spec.pid_path).await;

        if shutdown_requested || supervisor.shutting_down.load(Ordering::Acquire) {
            break;
        }

        // Reset backoff if the listener stayed alive long enough that this
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

    supervisor.cleanup_done.notify_one();
}

fn next_backoff(current: Duration) -> Duration {
    (current * 2).min(Duration::from_secs(60))
}

/// Sleep for `duration`, returning early (with `true`) if shutdown is requested.
async fn sleep_or_shutdown(supervisor: &Supervisor, duration: Duration) -> bool {
    tokio::select! {
        _ = tokio::time::sleep(duration) => false,
        _ = supervisor.shutdown.notified() => true,
    }
}

async fn fetch_spec(project_root: &Path) -> Result<ListenerSpec, String> {
    let python = resolve_python(project_root);
    let output = tokio::time::timeout(
        Duration::from_secs(15),
        Command::new(&python)
            .arg("-m")
            .arg("src.core.cli")
            .arg("whatsapp-listener-spec")
            .current_dir(project_root)
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .output(),
    )
    .await
    .map_err(|_| "whatsapp-listener-spec timed out".to_string())?
    .map_err(|e| format!("spawn {python}: {e}"))?;

    if !output.status.success() {
        return Err(format!(
            "spec CLI exited {}",
            output.status.code().unwrap_or(-1)
        ));
    }
    let stdout = String::from_utf8_lossy(&output.stdout);
    serde_json::from_str::<ListenerSpec>(stdout.trim())
        .map_err(|e| format!("parse spec JSON: {e}"))
}

async fn spawn_listener(
    project_root: &Path,
    spec: &ListenerSpec,
    command: &str,
) -> Result<Child, String> {
    let python = resolve_python(project_root);
    let log_file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&spec.log_path)
        .await
        .map_err(|e| format!("open log {}: {e}", spec.log_path))?
        .into_std()
        .await;
    let log_stderr = log_file
        .try_clone()
        .map_err(|e| format!("dup log fd: {e}"))?;

    let mut cmd = Command::new(&python);
    cmd.arg("-m")
        .arg("src.core.cli")
        .arg("whatsapp-listener-run")
        .arg("--mcp-command")
        .arg(command);
    for arg in &spec.args {
        cmd.arg(format!("--mcp-arg={arg}"));
    }
    cmd.current_dir(project_root)
        .stdin(Stdio::null())
        .stdout(Stdio::from(log_file))
        .stderr(Stdio::from(log_stderr))
        .kill_on_drop(true);

    cmd.spawn().map_err(|e| format!("spawn listener: {e}"))
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
        eprintln!("[wa-sup] listener didn't exit on SIGTERM, sending SIGKILL");
        let _ = child.start_kill();
        let _ = child.wait().await;
    }
}

async fn kill_external_listeners() {
    let output = Command::new("pgrep")
        .arg("-f")
        .arg("whatsapp-listener-run")
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .output()
        .await;
    let Ok(out) = output else { return };
    if !out.status.success() {
        return;
    }
    let stdout = String::from_utf8_lossy(&out.stdout);
    let pids: Vec<&str> = stdout.split_whitespace().collect();
    if pids.is_empty() {
        return;
    }
    eprintln!("[wa-sup] killing orphan listener pids: {pids:?}");
    for pid in &pids {
        let _ = Command::new("kill")
            .arg("-TERM")
            .arg(pid)
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .await;
    }
    // Brief wait, then SIGKILL stragglers.
    tokio::time::sleep(Duration::from_secs(2)).await;
    for pid in &pids {
        let _ = Command::new("kill")
            .arg("-KILL")
            .arg(pid)
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .await;
    }
}

async fn write_pid_file(spec: &ListenerSpec, pid: u32, command: &str) {
    if pid == 0 {
        return;
    }
    let payload = PidFile {
        pid,
        started_at: chrono::Utc::now().to_rfc3339(),
        command: command.to_string(),
        args: spec.args.clone(),
    };
    let Ok(json) = serde_json::to_string_pretty(&payload) else {
        return;
    };
    let path = Path::new(&spec.pid_path);
    if let Some(parent) = path.parent() {
        let _ = tokio::fs::create_dir_all(parent).await;
    }
    let tmp = path.with_extension("json.tmp");
    if tokio::fs::write(&tmp, json).await.is_ok() {
        let _ = tokio::fs::rename(&tmp, path).await;
    }
}

async fn remove_pid_file(pid_path: &str) {
    let _ = tokio::fs::remove_file(pid_path).await;
}

fn resolve_python(project_root: &Path) -> String {
    let venv_python = project_root.join(".venv").join("bin").join("python3");
    if venv_python.exists() {
        return venv_python.to_string_lossy().to_string();
    }
    "python3".to_string()
}
