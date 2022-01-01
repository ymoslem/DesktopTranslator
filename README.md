# DesktopTranslator
Local cross-platform machine translation GUI, based on CTranslate2


## Installer

You can either download a ready-made installer or build an installer yourself.

### Download Installer

You can download a ready installer for DesktopTranslator here.

### Build Installer

If you rather want to adjust the code and then build an installer yourself, you can follow these steps:

* Install PyInstaller:
```
pip3 install pyinstaller
```

* To use PyInstaller, specify the Python file name and the argument -w to hide the console window:
```
pyinstaller -y -w "translator.py"
```

* Compress the contents of the “dist” directory created by PyInstaller into a *.zip archive.
* Download and install [NSIS](https://nsis.sourceforge.io/Download).
* Launch NSIS, click **Installer based on a .ZIP file**, and then click **Open** to locate the **\*.zip** archive you have just created.
* If you want to make the files installed (extracted) to the “Program Files” of the target user, in the **Default Folder** enter `$PROGRAMFILES`
* If you want to add a shortcut to the internal *.exe file on the Desktop after installation, you can add something like this to the file “Modern.nsh” located at: "C:\Program Files\NSIS\Contrib\zip2exe\". Depending on your OS, the path could be at “Program Files (x86)”. Note that the exe path should be consistent with the path you selected under NSIS’s “Default Folder” drop-down menu, the folder name, and the exe file name.
```
Section "Desktop Shortcut" SectionX
    SetShellVarContext current
    CreateShortCut "$DESKTOP\DesktopTranslator.lnk" "$PROGRAMFILES\DesktopTranslator\translator.exe"
SectionEnd
```
* Finally, click the NSIS **Generate** button, which will create the ***.exe** installer that can be shipped to other Windows machines, without the need to install any extra requirements.

