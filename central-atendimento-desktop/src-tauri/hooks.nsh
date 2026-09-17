!macro NSIS_HOOK_POSTINSTALL
  Delete "$DESKTOP\Central de Atendimento.lnk"
  CreateShortCut "$DESKTOP\Central de Atendimento.lnk" "$INSTDIR\central-atendimento-desktop.exe" "" "$INSTDIR\central-atendimento-desktop.exe" 0 SW_SHOWNORMAL "" "Abrir a Central de Atendimento"
!macroend
