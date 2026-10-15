!macro NSIS_HOOK_POSTINSTALL
  WriteRegStr HKLM "Software\Classes\AppUserModelId\br.com.atualrnc.central-atendimento-operador" "DisplayName" "Central de Atendimento Operador"
  WriteRegStr HKLM "Software\Classes\AppUserModelId\br.com.atualrnc.central-atendimento-operador" "IconUri" "$INSTDIR\central-atendimento-operador.exe"
  WriteRegStr HKLM "Software\Classes\AppUserModelId\br.com.atualrnc.central-atendimento-operador" "IconBackgroundColor" "0"
  WriteRegStr HKCU "Software\Classes\AppUserModelId\br.com.atualrnc.central-atendimento-operador" "DisplayName" "Central de Atendimento Operador"
  WriteRegStr HKCU "Software\Classes\AppUserModelId\br.com.atualrnc.central-atendimento-operador" "IconUri" "$INSTDIR\central-atendimento-operador.exe"
  WriteRegStr HKCU "Software\Classes\AppUserModelId\br.com.atualrnc.central-atendimento-operador" "IconBackgroundColor" "0"
  Delete "$DESKTOP\Central de Atendimento.lnk"
  CreateShortCut "$DESKTOP\Central de Atendimento Operador.lnk" "$INSTDIR\central-atendimento-operador.exe" "" "$INSTDIR\central-atendimento-operador.exe" 0 SW_SHOWNORMAL "" "Abrir a Central de Atendimento Operador"
  !insertmacro SetLnkAppUserModelId "$DESKTOP\Central de Atendimento Operador.lnk"
  CreateDirectory "$SMPROGRAMS\Central de Atendimento"
  CreateShortCut "$SMPROGRAMS\Central de Atendimento\Central de Atendimento Operador.lnk" "$INSTDIR\central-atendimento-operador.exe" "" "$INSTDIR\central-atendimento-operador.exe" 0 SW_SHOWNORMAL "" "Abrir a Central de Atendimento Operador"
  !insertmacro SetLnkAppUserModelId "$SMPROGRAMS\Central de Atendimento\Central de Atendimento Operador.lnk"
!macroend

!macro NSIS_HOOK_POSTUNINSTALL
  DeleteRegKey HKLM "Software\Classes\AppUserModelId\br.com.atualrnc.central-atendimento-operador"
  DeleteRegKey HKCU "Software\Classes\AppUserModelId\br.com.atualrnc.central-atendimento-operador"
  Delete "$DESKTOP\Central de Atendimento Operador.lnk"
  Delete "$SMPROGRAMS\Central de Atendimento\Central de Atendimento Operador.lnk"
  RMDir "$SMPROGRAMS\Central de Atendimento"
!macroend
