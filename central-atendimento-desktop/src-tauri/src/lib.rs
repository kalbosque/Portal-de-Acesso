use tauri::Manager;
use tauri_plugin_notification::NotificationExt;

const APP_ID: &str = "br.com.atualrnc.central-atendimento-operador";

#[cfg(windows)]
fn register_windows_notification_identity() -> bool {
    let key = format!(r"HKCU\Software\Classes\AppUserModelId\{}", APP_ID);
    let settings_key = format!(r"HKCU\Software\Microsoft\Windows\CurrentVersion\Notifications\Settings\{}", APP_ID);
    let icon_uri = std::env::current_exe()
        .map(|path| path.display().to_string())
        .unwrap_or_default();

    let values = [
        ("DisplayName", "Central de Atendimento Operador"),
        ("IconUri", icon_uri.as_str()),
        ("IconBackgroundColor", "0"),
    ];

    for (name, value) in values {
        let status = std::process::Command::new("reg.exe")
            .args(["add", &key, "/v", name, "/t", "REG_SZ", "/d", value, "/f"])
            .status();

        match status {
            Ok(status) if status.success() => {}
            Ok(status) => eprintln!("Falha ao registrar {name} da notificacao: {status}"),
            Err(error) => eprintln!("Falha ao registrar {name} da notificacao: {error}"),
        }
    }

    // O Windows mantém a entrada exibida em Configurações por usuário.
    // Criamos somente na primeira execução para não sobrescrever a escolha do usuário.
    let settings_exists = std::process::Command::new("reg.exe")
        .args(["query", &settings_key])
        .status()
        .map(|status| status.success())
        .unwrap_or(false);

    if !settings_exists {
        let _ = std::process::Command::new("reg.exe")
            .args(["add", &settings_key, "/v", "Enabled", "/t", "REG_DWORD", "/d", "1", "/f"])
            .status();
    }

    !settings_exists
}

#[tauri::command]
fn trigger_message_alert(app: tauri::AppHandle, sender: String) {
    let body = format!("{} enviou uma nova mensagem.", sender);
    let app_title = "Central de Atendimento v0.1.4";

    // Pisca a barra de tarefas sem forçar foco (forçar foco suprime o toast do Windows)
    if let Some(window) = app.get_webview_window("main") {
        let window_clone = window.clone();
        std::thread::spawn(move || {
            for i in 0..20 {
                let flash_title = if i % 2 == 0 {
                    "⚠️ NOVA MENSAGEM"
                } else {
                    app_title
                };
                let _ = window_clone.set_title(flash_title);
                let _ = window_clone.request_user_attention(Some(tauri::UserAttentionType::Critical));
                std::thread::sleep(std::time::Duration::from_millis(500));
            }
            let _ = window_clone.set_title(app_title);
            let _ = window_clone.request_user_attention(None);
        });
    }

    // Notificação nativa Windows (toast no canto da tela)
    let result = app.notification()
        .builder()
        .title("⚠️ Nova mensagem")
        .body(&body)
        .show();
    if let Err(error) = result {
        eprintln!("Falha ao exibir notificacao do Windows (AUMID={APP_ID}): {error}");
    }
}


#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_notification::init())
        .setup(|app| {
            #[cfg(windows)]
            if register_windows_notification_identity() {
                let result = app.notification()
                    .builder()
                    .title("Central de Atendimento")
                    .body("Notificações do Windows ativadas para este usuário.")
                    .show();
                if let Err(error) = result {
                    eprintln!("Falha ao enviar notificacao inicial: {error}");
                }
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![trigger_message_alert])
        .run(tauri::generate_context!())
        .expect("erro ao iniciar a Central de Atendimento");
}
