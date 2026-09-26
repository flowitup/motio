mod engine;

use tauri::{Manager, RunEvent};
use tauri_plugin_opener::OpenerExt;

/// Open a project folder in Finder / Explorer (local engine only).
#[tauri::command]
fn open_folder(app: tauri::AppHandle, path: String) -> Result<(), String> {
    app.opener().open_path(path, None::<&str>).map_err(|e| e.to_string())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_notification::init())
        .manage(engine::Engine::new())
        .setup(|app| {
            engine::start(app.handle());
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            engine::engine_info,
            engine::engine_config,
            engine::set_engine_config,
            engine::restart_engine,
            open_folder
        ])
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                app.state::<engine::Engine>().stop();
            }
        });
}
