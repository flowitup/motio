//! Engine lifecycle: spawn the Python engine (local mode) or point at a remote one.
//!
//! Local dev: `uv run python -m motio engine --port 0 --token <random> --exit-with-stdin` from the repo root.
//! The engine prints one JSON line `{"event":"ready","port":N,...}` on stdout; we keep port + token in state.
//! The child's stdin stays open while the app lives, so the engine also exits if the app crashes.

use serde::{Deserialize, Serialize};
use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::Mutex;
use tauri::{AppHandle, Emitter, Manager, State};

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "lowercase")]
pub enum Mode {
    #[default]
    Local,
    Remote,
}

/// Saved in the app config dir as engine.json.
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct EngineConfig {
    #[serde(default)]
    pub mode: Mode,
    #[serde(default)]
    pub url: String,
    #[serde(default)]
    pub token: String,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Status {
    Starting,
    Ready,
    Error,
}

#[derive(Clone, Debug, Serialize)]
pub struct EngineInfo {
    pub status: Status,
    pub mode: Mode,
    pub url: String,
    pub token: String,
    pub version: Option<String>,
    pub error: Option<String>,
}

struct Proc {
    child: Child,
    _stdin: Option<ChildStdin>,
}

pub struct Engine {
    info: Mutex<EngineInfo>,
    proc: Mutex<Option<Proc>>,
}

impl Engine {
    pub fn new() -> Self {
        Engine {
            info: Mutex::new(EngineInfo {
                status: Status::Starting,
                mode: Mode::Local,
                url: String::new(),
                token: String::new(),
                version: None,
                error: None,
            }),
            proc: Mutex::new(None),
        }
    }

    fn set(&self, app: &AppHandle, info: EngineInfo) {
        *self.info.lock().unwrap() = info.clone();
        let _ = app.emit("engine-changed", info);
    }

    pub fn stop(&self) {
        if let Some(mut p) = self.proc.lock().unwrap().take() {
            let _ = p.child.kill();
            let _ = p.child.wait();
        }
    }
}

fn config_path(app: &AppHandle) -> Option<PathBuf> {
    app.path().app_config_dir().ok().map(|d| d.join("engine.json"))
}

pub fn load_config(app: &AppHandle) -> EngineConfig {
    config_path(app)
        .and_then(|p| std::fs::read_to_string(p).ok())
        .and_then(|s| serde_json::from_str(&s).ok())
        .unwrap_or_default()
}

fn save_config(app: &AppHandle, cfg: &EngineConfig) -> Result<(), String> {
    let p = config_path(app).ok_or("no config dir")?;
    if let Some(dir) = p.parent() {
        std::fs::create_dir_all(dir).map_err(|e| e.to_string())?;
    }
    let body = serde_json::to_string_pretty(cfg).map_err(|e| e.to_string())?;
    std::fs::write(p, body).map_err(|e| e.to_string())
}

fn random_token() -> String {
    format!("{}{}", uuid::Uuid::new_v4().simple(), uuid::Uuid::new_v4().simple())
}

/// Repo root in dev builds (src-tauri is at <root>/app/src-tauri).
fn repo_root() -> PathBuf {
    let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    std::env::var_os("MOTIO_ROOT")
        .map(PathBuf::from)
        .unwrap_or_else(|| manifest.join("../..").canonicalize().unwrap_or(manifest.join("../..")))
}

/// `uv` is not on PATH when the app is started from Finder / Explorer, so also look in common places.
fn find_uv() -> Option<PathBuf> {
    if let Some(p) = std::env::var_os("MOTIO_UV") {
        return Some(PathBuf::from(p));
    }
    let exe = if cfg!(windows) { "uv.exe" } else { "uv" };
    if let Some(paths) = std::env::var_os("PATH") {
        for dir in std::env::split_paths(&paths) {
            let p = dir.join(exe);
            if p.is_file() {
                return Some(p);
            }
        }
    }
    let home = std::env::var_os(if cfg!(windows) { "USERPROFILE" } else { "HOME" }).map(PathBuf::from)?;
    let mut cands = vec![home.join(".local/bin").join(exe), home.join(".cargo/bin").join(exe)];
    if cfg!(target_os = "macos") {
        cands.push(PathBuf::from("/opt/homebrew/bin/uv"));
        cands.push(PathBuf::from("/usr/local/bin/uv"));
    }
    cands.into_iter().find(|p| p.is_file())
}

/// Dev: `uv run python -m motio` from the repo root. Release: the frozen engine shipped in resources.
fn engine_command(app: &AppHandle) -> Result<Command, String> {
    if let Some(p) = std::env::var_os("MOTIO_ENGINE") {
        return Ok(Command::new(p));
    }
    if cfg!(debug_assertions) {
        let uv = find_uv().ok_or("uv not found. Install uv or set MOTIO_UV.")?;
        let mut cmd = Command::new(uv);
        cmd.args(["run", "python", "-m", "motio"]).current_dir(repo_root());
        return Ok(cmd);
    }
    let exe = if cfg!(windows) { "motio-engine.exe" } else { "motio-engine" };
    let path = app
        .path()
        .resource_dir()
        .map_err(|e| e.to_string())?
        .join("motio-engine")
        .join(exe);
    if !path.is_file() {
        return Err(format!("Bundled engine missing: {}", path.display()));
    }
    Ok(Command::new(path))
}

fn failed(base: &EngineInfo, msg: impl Into<String>) -> EngineInfo {
    EngineInfo { status: Status::Error, error: Some(msg.into()), ..base.clone() }
}

fn spawn_local(app: &AppHandle, engine: &Engine) {
    let token = random_token();
    let starting = EngineInfo {
        status: Status::Starting,
        mode: Mode::Local,
        url: String::new(),
        token: token.clone(),
        version: None,
        error: None,
    };
    engine.set(app, starting.clone());

    let mut cmd = match engine_command(app) {
        Ok(c) => c,
        Err(e) => {
            engine.set(app, failed(&starting, e));
            return;
        }
    };
    cmd.args(["engine", "--port", "0", "--token", &token, "--exit-with-stdin"])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    }
    let mut child = match cmd.spawn() {
        Ok(c) => c,
        Err(e) => {
            engine.set(app, failed(&starting, format!("Couldn't start the engine: {e}")));
            return;
        }
    };
    let stdout = child.stdout.take().expect("piped stdout");
    let stdin = child.stdin.take();
    *engine.proc.lock().unwrap() = Some(Proc { child, _stdin: stdin });

    let app = app.clone();
    std::thread::spawn(move || {
        let engine = app.state::<Engine>();
        let mut lines = BufReader::new(stdout).lines();
        for line in lines.by_ref() {
            let Ok(line) = line else { break };
            let Ok(v) = serde_json::from_str::<serde_json::Value>(&line) else { continue };
            if v["event"] == "ready" {
                let port = v["port"].as_u64().unwrap_or(0);
                engine.set(
                    &app,
                    EngineInfo {
                        status: Status::Ready,
                        url: format!("http://127.0.0.1:{port}"),
                        version: v["version"].as_str().map(String::from),
                        ..starting.clone()
                    },
                );
                break;
            }
        }
        // Keep draining stdout so the engine never blocks on a full pipe.
        for _ in lines {}
        // stdout closed: the engine exited (unless we are restarting it on purpose).
        let cur = engine.info.lock().unwrap().clone();
        if cur.mode == Mode::Local && cur.token == token {
            engine.set(&app, failed(&starting, "The engine stopped. See the log in the terminal."));
        }
    });
}

/// Start (or restart) according to the saved config.
pub fn start(app: &AppHandle) {
    let engine = app.state::<Engine>();
    engine.stop();
    let cfg = load_config(app);
    match cfg.mode {
        Mode::Local => spawn_local(app, &engine),
        Mode::Remote => engine.set(
            app,
            EngineInfo {
                status: if cfg.url.is_empty() { Status::Error } else { Status::Ready },
                mode: Mode::Remote,
                url: cfg.url.trim_end_matches('/').to_string(),
                token: cfg.token,
                version: None,
                error: cfg.url.is_empty().then(|| "No remote engine URL set".to_string()),
            },
        ),
    }
}

#[tauri::command]
pub fn engine_info(engine: State<Engine>) -> EngineInfo {
    engine.info.lock().unwrap().clone()
}

#[tauri::command]
pub fn engine_config(app: AppHandle) -> EngineConfig {
    load_config(&app)
}

#[tauri::command]
pub async fn set_engine_config(app: AppHandle, config: EngineConfig) -> Result<EngineInfo, String> {
    save_config(&app, &config)?;
    start(&app);
    Ok(app.state::<Engine>().info.lock().unwrap().clone())
}

#[tauri::command]
pub async fn restart_engine(app: AppHandle) -> EngineInfo {
    start(&app);
    app.state::<Engine>().info.lock().unwrap().clone()
}
