//! Self-update from the GitHub Releases of flowitup/motio.
//!
//! The repo is private, so the app reads its releases through the GitHub API with a read-only token the owner saves
//! in Cài đặt (app config dir, updater.json; never compiled into the app). Releases made by release.yml carry
//! latest.json, the Tauri updater manifest, whose bundle URLs are API asset URLs (…/releases/assets/<id>): with the
//! token and `Accept: application/octet-stream` GitHub redirects them to the file (reqwest drops the token on the
//! cross-host redirect). Bundles are verified against the public key in tauri.conf.json before anything is installed.

use crate::engine::Engine;
use reqwest::header::{ACCEPT, AUTHORIZATION, USER_AGENT};
use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use std::sync::Mutex;
use tauri::{AppHandle, Emitter, Manager, State};
use tauri_plugin_updater::{Update, UpdaterExt};

const REPO: &str = "flowitup/motio";

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
struct UpdaterConfig {
    #[serde(default)]
    token: String,
}

/// What the settings screen shows. The token itself never goes back to the UI.
#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct UpdaterStatus {
    current: String,
    has_token: bool,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct UpdateCheck {
    current: String,
    /// Newer version on GitHub, or None when the app is up to date.
    version: Option<String>,
    notes: Option<String>,
    date: Option<String>,
    url: Option<String>,
}

#[derive(Clone, Serialize)]
struct Progress {
    downloaded: u64,
    total: Option<u64>,
}

#[derive(Deserialize)]
struct Release {
    tag_name: String,
    body: Option<String>,
    html_url: String,
    published_at: Option<String>,
    assets: Vec<Asset>,
}

#[derive(Deserialize)]
struct Asset {
    name: String,
    url: String,
}

/// The update found by the last check, kept until the user installs it.
#[derive(Default)]
pub struct Pending(Mutex<Option<Update>>);

fn config_path(app: &AppHandle) -> Option<PathBuf> {
    app.path().app_config_dir().ok().map(|d| d.join("updater.json"))
}

fn load_config(app: &AppHandle) -> UpdaterConfig {
    config_path(app)
        .and_then(|p| std::fs::read_to_string(p).ok())
        .and_then(|s| serde_json::from_str(&s).ok())
        .unwrap_or_default()
}

fn save_config(app: &AppHandle, cfg: &UpdaterConfig) -> Result<(), String> {
    let p = config_path(app).ok_or("no config dir")?;
    if let Some(dir) = p.parent() {
        std::fs::create_dir_all(dir).map_err(|e| e.to_string())?;
    }
    let body = serde_json::to_string_pretty(cfg).map_err(|e| e.to_string())?;
    std::fs::write(p, body).map_err(|e| e.to_string())
}

fn status(app: &AppHandle, cfg: &UpdaterConfig) -> UpdaterStatus {
    UpdaterStatus { current: app.package_info().version.to_string(), has_token: !cfg.token.is_empty() }
}

/// Latest published (non-draft, non-prerelease) release.
async fn latest_release(token: &str) -> Result<Release, String> {
    // reqwest is built without a default TLS provider (same as the updater plugin), so pick ring once.
    let _ = rustls::crypto::ring::default_provider().install_default();
    let client = reqwest::Client::builder().build().map_err(|e| e.to_string())?;
    let mut req = client
        .get(format!("https://api.github.com/repos/{REPO}/releases/latest"))
        .header(ACCEPT, "application/vnd.github+json")
        .header(USER_AGENT, "motio-updater")
        .header("X-GitHub-Api-Version", "2022-11-28");
    if !token.is_empty() {
        req = req.bearer_auth(token);
    }
    let res = req.send().await.map_err(|e| format!("Không kết nối được GitHub: {e}"))?;
    match res.status().as_u16() {
        200 => res.json().await.map_err(|e| format!("GitHub trả về dữ liệu lạ: {e}")),
        401 => Err("GitHub từ chối token (sai hoặc hết hạn). Nhập token mới.".into()),
        403 | 429 => Err("GitHub từ chối (403): token thiếu quyền Contents: Read, hoặc đã hết lượt gọi.".into()),
        404 if token.is_empty() => Err(format!("Repo {REPO} là riêng tư: nhập GitHub token để kiểm tra cập nhật.")),
        404 => Err("Không thấy bản phát hành: token không đọc được repo, hoặc chưa có release nào được Publish.".into()),
        s => Err(format!("GitHub lỗi {s}")),
    }
}

#[tauri::command]
pub fn updater_status(app: AppHandle) -> UpdaterStatus {
    status(&app, &load_config(&app))
}

/// Save (or clear, with an empty string) the GitHub token used to read releases.
#[tauri::command]
pub fn set_update_token(app: AppHandle, token: String) -> Result<UpdaterStatus, String> {
    let cfg = UpdaterConfig { token: token.trim().to_string() };
    save_config(&app, &cfg)?;
    Ok(status(&app, &cfg))
}

#[tauri::command]
pub async fn check_update(app: AppHandle, pending: State<'_, Pending>) -> Result<UpdateCheck, String> {
    let token = load_config(&app).token;
    let release = latest_release(&token).await?;
    let manifest = release
        .assets
        .iter()
        .find(|a| a.name == "latest.json")
        .ok_or_else(|| format!("Bản {} trên GitHub không có latest.json nên không tự cập nhật được.", release.tag_name))?;

    let err = |e: tauri_plugin_updater::Error| format!("Lỗi kiểm tra cập nhật: {e}");
    let endpoint = manifest.url.parse().map_err(|e| format!("URL latest.json sai: {e}"))?;
    let engine_app = app.clone();
    let mut builder = app
        .updater_builder()
        .endpoints(vec![endpoint])
        .map_err(err)?
        // Same header for latest.json and the bundle: both are GitHub asset downloads.
        .header(ACCEPT, "application/octet-stream")
        .map_err(err)?
        // Windows: the installer takes over right after download, stop the local engine first.
        .on_before_exit(move || engine_app.state::<Engine>().stop());
    if !token.is_empty() {
        builder = builder.header(AUTHORIZATION, format!("Bearer {token}")).map_err(err)?;
    }
    let update = builder.build().map_err(err)?.check().await.map_err(err)?;

    let found = update.as_ref().map(|u| u.version.clone());
    *pending.0.lock().unwrap() = update;
    Ok(UpdateCheck {
        current: app.package_info().version.to_string(),
        notes: found.as_ref().and(release.body),
        version: found,
        date: release.published_at,
        url: Some(release.html_url),
    })
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
