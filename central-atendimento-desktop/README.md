# Central de Atendimento para Windows

Protótipo Tauri que abre somente a tela `/central-atendimento` do sistema.

## Pré-requisitos

- Node.js
- Rust com `rustup`
- WebView2 (já presente na maioria dos Windows 10/11)
- Servidor do sistema disponível em `http://192.168.1.230:3001`

## Executar em desenvolvimento

```powershell
npm.cmd install
npm.cmd run dev
```

## Gerar instalador

```powershell
npm.cmd run build
```

O instalador será criado em `src-tauri/target/release/bundle/nsis`.
