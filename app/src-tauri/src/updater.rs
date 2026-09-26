//! Self-update from the public GitHub Releases of flowitup/motio.
//!
//! The endpoint in tauri.conf.json is the latest.json that release.yml attaches to every release. GitHub serves
//! `releases/latest/download/…` from the newest published release only, so drafts are never offered. Bundles are
//! verified against the public key in tauri.conf.json before anything is installed.

use crate::engine::Engine;
use serde::Serialize;
use std::sync::Mutex;
use tauri::{AppHandle, Emitter, Manager, State};
use tauri_plugin_updater::{Update, UpdaterExt};

const RELEASES: &str = "https://github.com/flowitup/motio/releases";

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct UpdaterStatus {
    current: String,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct UpdateCheck {
    current: String,
    /// Newer version on GitHub, or None when the app is up to date.
    version: Option<String>,
    notes: Option<String>,
    url: Option<String>,
}

#[derive(Clone, Serialize)]
struct Progress {
    downloaded: u64,
    total: Option<u64>,
}

/// The update found by the last check, kept until the user installs it.
#[derive(Default)]
pub struct Pending(Mutex<Option<Update>>);

/// 0.3.0 kept a GitHub token for the then-private repo in updater.json; the repo is public now, so drop it.
pub fn forget_token(app: &AppHandle) {
    if let Ok(dir) = app.path().app_config_dir() {
        let _ = std::fs::remove_file(dir.join("updater.json"));
    }
}

#[tauri::command]
pub fn updater_status(app: AppHandle) -> UpdaterStatus {
    UpdaterStatus { current: app.package_info().version.to_string() }
}

#[tauri::command]
pub async fn check_update(app: AppHandle, pending: State<'_, Pending>) -> Result<UpdateCheck, String> {
    let err = |e: tauri_plugin_updater::Error| format!("Lỗi kiểm tra cập nhật: {e}");
    let engine_app = app.clone();
    let update = app
        .updater_builder()
        // Windows: the installer takes over right after download, stop the local engine first.
        .on_before_exit(move || engine_app.state::<Engine>().stop())
        .build()
        .map_err(err)?
        .check()
        .await
        .map_err(err)?;

    let check = UpdateCheck {
        current: app.package_info().version.to_string(),
        version: update.as_ref().map(|u| u.version.clone()),
        notes: update.as_ref().and_then(|u| u.body.clone()),
        url: Some(match &update {
            Some(u) => format!("{RELEASES}/tag/v{}", u.version),
            None => format!("{RELEASES}/latest"),
        }),
    };
    *pending.0.lock().unwrap() = update;
    Ok(check)
}

/// Download, verify and install the update found by `check_update`, then restart the app.
#[tauri::command]
pub async fn install_update(app: AppHandle, pending: State<'_, Pending>) -> Result<(), String> {
    let update = pending.0.lock().unwrap().clone().ok_or("Hãy kiểm tra cập nhật trước.")?;
    let (mut downloaded, mut sent) = (0u64, 0u64);
    update
        .download_and_install(
            |chunk, total| {
                downloaded += chunk as u64;
                // About one event per percent (per 512 KB when the size is unknown).
                let step = total.map_or(512 * 1024, |t| (t / 100).max(1));
                if downloaded - sent >= step || Some(downloaded) == total {
                    sent = downloaded;
                    let _ = app.emit("update-progress", Progress { downloaded, total });
                }
            },
            || {},
        )
        .await
        .map_err(|e| format!("Cập nhật lỗi: {e}"))?;
    app.state::<Engine>().stop();
    app.restart()
}
