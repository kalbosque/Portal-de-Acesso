use tauri::Manager;
use tauri_plugin_notification::NotificationExt;

#[tauri::command]
fn trigger_message_alert(app: tauri::AppHandle, sender: String) {
    let body = format!("{} enviou uma nova mensagem.", sender);
    let app_title = "Central de Atendimento v0.1.1";

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
    let _ = app.notification()
        .builder()
        .title("⚠️ Nova mensagem")
        .body(&body)
        .show();
}


#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_notification::init())
        .invoke_handler(tauri::generate_handler![trigger_message_alert])
        .run(tauri::generate_context!())
        .expect("erro ao iniciar a Central de Atendimento");
}
