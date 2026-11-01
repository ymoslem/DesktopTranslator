; NSIS script for the Windows installer.
; Build with: makensis /DVERSION=0.2.4 installer.nsi
; Expects the PyInstaller output in dist\DesktopTranslator.

!include "MUI2.nsh"

!define APP_NAME "DesktopTranslator"
!ifndef VERSION
  !define VERSION "0.0.0"
!endif

Name "${APP_NAME} ${VERSION}"
OutFile "${APP_NAME}_Windows_${VERSION}.exe"
InstallDir "$PROGRAMFILES64\${APP_NAME}"
RequestExecutionLevel admin

!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Section "Install"
    SetShellVarContext all
    SetOutPath "$INSTDIR"
    File /r "dist\${APP_NAME}\*.*"
    WriteUninstaller "$INSTDIR\Uninstall.exe"

    CreateDirectory "$SMPROGRAMS\${APP_NAME}"
    CreateShortCut "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" "$INSTDIR\${APP_NAME}.exe"
    CreateShortCut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\${APP_NAME}.exe"
SectionEnd

Section "Uninstall"
    SetShellVarContext all
    Delete "$DESKTOP\${APP_NAME}.lnk"
    RMDir /r "$SMPROGRAMS\${APP_NAME}"
    RMDir /r "$INSTDIR"
SectionEnd
