!macro NSIS_HOOK_POSTINSTALL
  Delete "$DESKTOP\Central de Atendimento.lnk"
  CreateShortCut "$DESKTOP\Central de Atendimento Operador.lnk" "$INSTDIR\central-atendimento-operador.exe" "" "$INSTDIR\central-atendimento-operador.exe" 0 SW_SHOWNORMAL "" "Abrir a Central de Atendimento Operador"
!macroend
