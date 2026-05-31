use tauri::Manager;
use tokio::sync::Mutex;

pub struct CaffeinateHandle {
    pid: Mutex<Option<u32>>,
}

impl CaffeinateHandle {
    pub fn new() -> Self {
        Self {
            pid: Mutex::new(None),
        }
    }
}

impl Default for CaffeinateHandle {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(target_os = "macos")]
pub async fn apply_caffeinate(
    handle: &CaffeinateHandle,
    prevent_sleep: bool,
    prevent_sleep_on_battery: bool,
) {
    let mut pid_guard = handle.pid.lock().await;

    if let Some(pid) = pid_guard.take() {
        let _ = std::process::Command::new("kill")
            .args(["-TERM", &pid.to_string()])
            .status();
    }

    if !prevent_sleep {
        return;
    }

    let mut args: Vec<&str> = vec!["-i"];
    if prevent_sleep_on_battery {
        args = vec!["-i", "-s"];
    }

    match std::process::Command::new("caffeinate")
        .args(&args)
        .spawn()
    {
        Ok(child) => {
            *pid_guard = Some(child.id());
            eprintln!(
                "[keep_awake] caffeinate started (pid={}, flags={:?})",
                child.id(),
                args,
            );
        }
        Err(e) => {
            eprintln!("[keep_awake] failed to spawn caffeinate: {e}");
        }
    }
}

#[cfg(not(target_os = "macos"))]
pub async fn apply_caffeinate(
    _handle: &CaffeinateHandle,
    _prevent_sleep: bool,
    _prevent_sleep_on_battery: bool,
) {
}

pub async fn stop_caffeinate(handle: &CaffeinateHandle) {
    let mut pid_guard = handle.pid.lock().await;
    if let Some(pid) = pid_guard.take() {
        let _ = std::process::Command::new("kill")
            .args(["-TERM", &pid.to_string()])
            .status();
        eprintln!("[keep_awake] caffeinate stopped (pid={pid})");
    }
}

#[cfg(target_os = "macos")]
pub fn apply_launch_at_login(enabled: bool) {
    let exe = match resolve_app_path() {
        Some(p) => p,
        None => {
            eprintln!("[keep_awake] could not resolve app path, skipping launch-at-login");
            return;
        }
    };

    let home = match dirs::home_dir() {
        Some(h) => h,
        None => {
            eprintln!("[keep_awake] could not determine home dir");
            return;
        }
    };

    let agents_dir = home.join("Library/LaunchAgents");
    let plist_path = agents_dir.join("com.secbrain.app.plist");

    if enabled {
        let _ = std::fs::create_dir_all(&agents_dir);
        let plist = format!(
            r#"<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.secbrain.app</string>
    <key>ProgramArguments</key>
    <array>
        <string>{}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
</dict>
</plist>"#,
            exe
        );
        match std::fs::write(&plist_path, plist) {
            Ok(()) => eprintln!("[keep_awake] LaunchAgent written to {}", plist_path.display()),
            Err(e) => eprintln!("[keep_awake] failed to write LaunchAgent: {e}"),
        }
    } else {
        match std::fs::remove_file(&plist_path) {
            Ok(()) => eprintln!("[keep_awake] LaunchAgent removed"),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
            Err(e) => eprintln!("[keep_awake] failed to remove LaunchAgent: {e}"),
        }
    }
}

#[cfg(not(target_os = "macos"))]
pub fn apply_launch_at_login(_enabled: bool) {}

#[cfg(target_os = "macos")]
fn resolve_app_path() -> Option<String> {
    let exe = std::env::current_exe().ok()?;
    exe.to_str().map(|s| s.to_string())
}

pub fn build_tray(app: &tauri::AppHandle) -> Result<(), String> {
    use tauri::tray::TrayIconBuilder;
    use tauri::menu::{MenuBuilder, MenuItemBuilder};

    if app.tray_by_id("main-tray").is_some() {
        return Ok(());
    }

    let show_item = MenuItemBuilder::with_id("show", "Show SecBrain")
        .build(app)
        .map_err(|e| format!("Failed to build menu item: {e}"))?;
    let quit_item = MenuItemBuilder::with_id("quit", "Quit SecBrain")
        .build(app)
        .map_err(|e| format!("Failed to build menu item: {e}"))?;

    let menu = MenuBuilder::new(app)
        .item(&show_item)
        .separator()
        .item(&quit_item)
        .build()
        .map_err(|e| format!("Failed to build tray menu: {e}"))?;

    let app_handle = app.clone();
    let tray_icon = tauri::image::Image::from_bytes(include_bytes!(
        "../icons/tray-iconTemplate@2x.png"
    ))
    .map_err(|e| format!("Failed to load tray icon: {e}"))?;
    TrayIconBuilder::with_id("main-tray")
        .icon(tray_icon)
        .icon_as_template(true)
        .menu(&menu)
        .on_menu_event(move |app, event| {
            match event.id().as_ref() {
                "show" => {
                    if let Some(window) = app.get_webview_window("main") {
                        let _ = window.show();
                        let _ = window.set_focus();
                    }
                }
                "quit" => {
                    app.exit(0);
                }
                _ => {}
            }
        })
        .on_tray_icon_event({
            let handle = app_handle.clone();
            move |_tray, event| {
                if let tauri::tray::TrayIconEvent::Click {
                    button: tauri::tray::MouseButton::Left,
                    ..
                } = event
                {
                    if let Some(window) = handle.get_webview_window("main") {
                        let _ = window.show();
                        let _ = window.set_focus();
                    }
                }
            }
        })
        .build(app)
        .map_err(|e| format!("Failed to build tray icon: {e}"))?;

    eprintln!("[keep_awake] tray icon created");
    Ok(())
}

pub fn remove_tray(app: &tauri::AppHandle) {
    if let Some(tray) = app.tray_by_id("main-tray") {
        let _ = tray.set_visible(false);
        eprintln!("[keep_awake] tray icon hidden");
    }
}

pub fn apply_menu_bar_mode(app: &tauri::AppHandle, enabled: bool) {
    if enabled {
        if let Err(e) = build_tray(app) {
            eprintln!("[keep_awake] failed to build tray: {e}");
        }
    } else {
        remove_tray(app);
    }
}
