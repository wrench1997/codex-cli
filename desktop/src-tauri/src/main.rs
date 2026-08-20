use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{fs, io::{BufRead, BufReader, Write}, path::PathBuf, process::{Child, ChildStdin, Command, Stdio}, sync::Mutex};
use tauri::{AppHandle, Emitter, Manager, State};

struct Backend(Mutex<Option<Child>>);
struct BackendInput(Mutex<Option<ChildStdin>>);

#[derive(Deserialize, Serialize)]
struct StartOptions {
    python: Option<String>,
    workdir: String,
    api: Option<String>,
    model: Option<String>,
    api_mode: Option<String>,
    tool_transport: Option<String>,
    temperature: Option<f64>,
    auto_approve: Option<bool>,
    no_agent: Option<bool>,
    bundled: Option<bool>,
}

fn source_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).parent().unwrap().parent().unwrap().to_path_buf()
}

fn default_workdir(app: &AppHandle) -> Result<String, String> {
    let root = app.path().document_dir().map_err(|err| err.to_string())?.join("mCodex Workspace");
    fs::create_dir_all(&root).map_err(|err| err.to_string())?;
    Ok(root.to_string_lossy().to_string())
}

fn bundled_backend(app: &AppHandle) -> Option<PathBuf> {
    let resource = app.path().resource_dir().ok()?;
    [resource.join("codex-backend.exe"), resource.join("resources").join("codex-backend.exe")]
        .into_iter().find(|path| path.is_file())
}

fn send_line(input: &BackendInput, payload: Value) -> Result<(), String> {
    let mut guard = input.0.lock().map_err(|_| "backend input lock failed")?;
    let stdin = guard.as_mut().ok_or("desktop backend is not running")?;
    serde_json::to_writer(&mut *stdin, &payload).map_err(|err| err.to_string())?;
    stdin.write_all(b"\n").map_err(|err| err.to_string())?;
    stdin.flush().map_err(|err| err.to_string())
}

fn start_backend_inner(app: &AppHandle, backend: &Backend, input: &BackendInput, options: StartOptions) -> Result<(), String> {
    if backend.0.lock().map_err(|_| "backend lock failed")?.is_some() {
        return Err("desktop backend is already running".into());
    }
    let bundled = options.bundled.unwrap_or(true);
    let (program, arguments, launch_dir) = if bundled {
        if let Some(sidecar) = bundled_backend(app) {
            (sidecar, Vec::<String>::new(), PathBuf::from(&options.workdir))
        } else {
            let python = options.python.clone().unwrap_or_else(|| "python".into());
            (PathBuf::from(python), vec!["-m".into(), "src.codex.desktop_bridge".into()], source_root())
        }
    } else {
        let python = options.python.clone().unwrap_or_else(|| "python".into());
        (PathBuf::from(python), vec!["-m".into(), "src.codex.desktop_bridge".into()], source_root())
    };
    let mut child = Command::new(program)
        .args(arguments)
        .current_dir(launch_dir)
        .stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::piped())
        .spawn().map_err(|err| format!("cannot start Python CLI backend: {err}"))?;
    let stdout = child.stdout.take().ok_or("backend stdout unavailable")?;
    let stderr = child.stderr.take().ok_or("backend stderr unavailable")?;
    let stdin = child.stdin.take().ok_or("backend stdin unavailable")?;
    *input.0.lock().map_err(|_| "backend input lock failed")? = Some(stdin);
    *backend.0.lock().map_err(|_| "backend lock failed")? = Some(child);
    let events = app.clone();
    std::thread::spawn(move || for line in BufReader::new(stdout).lines().map_while(Result::ok) {
        let payload = serde_json::from_str::<Value>(&line).unwrap_or_else(|_| json!({"type":"protocol_error", "line": line}));
        let _ = events.emit("backend-event", payload);
    });
    let logs = app.clone();
    std::thread::spawn(move || for line in BufReader::new(stderr).lines().map_while(Result::ok) {
        let _ = logs.emit("backend-log", line);
    });
    send_line(input, json!({"action":"start", "options": options}))
}

#[tauri::command]
fn start_backend(app: AppHandle, backend: State<Backend>, input: State<BackendInput>, options: StartOptions) -> Result<(), String> {
    start_backend_inner(&app, &backend, &input, options)
}

#[tauri::command]
fn send_message(input: State<BackendInput>, text: String) -> Result<(), String> {
    send_line(&input, json!({"action":"message", "text": text}))
}

#[tauri::command]
fn send_backend(input: State<BackendInput>, payload: Value) -> Result<(), String> {
    send_line(&input, payload)
}

#[tauri::command]
fn stop_backend(backend: State<Backend>, input: State<BackendInput>) -> Result<(), String> {
    let _ = send_line(&input, json!({"action":"shutdown"}));
    *input.0.lock().map_err(|_| "backend input lock failed")? = None;
    if let Some(mut child) = backend.0.lock().map_err(|_| "backend lock failed")?.take() {
        let _ = child.kill();
    }
    Ok(())
}

#[tauri::command]
fn switch_project(app: AppHandle, backend: State<Backend>, input: State<BackendInput>, workdir: String) -> Result<(), String> {
    stop_backend(backend.clone(), input.clone())?;
    start_backend_inner(&app, &backend, &input, StartOptions {
        python: None, workdir, api: None, model: None, api_mode: None, tool_transport: None,
        temperature: None, auto_approve: Some(true), no_agent: Some(false), bundled: Some(true),
    })
}

#[tauri::command]
fn choose_project() -> Option<String> {
    rfd::FileDialog::new().pick_folder().map(|path| path.to_string_lossy().to_string())
}

fn main() {
    tauri::Builder::default()
        .manage(Backend(Mutex::new(None)))
        .manage(BackendInput(Mutex::new(None)))
        .setup(|app| {
            let handle = app.handle();
            let workdir = default_workdir(&handle)?;
            let backend = app.state::<Backend>();
            let input = app.state::<BackendInput>();
            if let Err(error) = start_backend_inner(&handle, &backend, &input, StartOptions {
                python: None, workdir, api: None, model: None, api_mode: None, tool_transport: None,
                temperature: None, auto_approve: Some(true), no_agent: Some(false), bundled: Some(true),
            }) { let _ = handle.emit("backend-event", json!({"type":"error", "message": error})); }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![start_backend, send_message, send_backend, stop_backend, switch_project, choose_project])
        .run(tauri::generate_context!())
        .expect("failed to run mCodex Desktop");
}
