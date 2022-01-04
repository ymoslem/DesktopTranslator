# DesktopTranslator
Local cross-platform machine translation GUI, based on [CTranslate2](https://github.com/OpenNMT/CTranslate2)


<kbd> ![DesktopTranslator](img/DesktopTranslator.png)


## Download Windows Installer

You can either download a ready-made Windows executable installer for DesktopTranslator, or build an installer yourself.  
[![DesktopTranslator](https://img.shields.io/badge/Download-Installer-green)](https://www.aclweb.org/anthology/2020.nlptea-1.2)




## Build Windows Installer

Alternatively, if you want to adjust the code and then build an installer yourself, you can follow these steps:

1. Install PyInstaller:
```
pip3 install pyinstaller
```

2. To use PyInstaller, specify the Python file name and the argument -w to hide the console window:
```
pyinstaller -y -w "translator.py"
```
3. Try the `\*.exe` file under "dist\translator" to make sure it works. It might complain about the Pmw library. The solution is either remove the Balloon lines, or add [this file](https://gist.github.com/ymoslem/c4b0cd287c7d5f2b7279dfce354d389b) to the same folder as the `translate.py` and run the aforementioned PyInstaller command again.
4. Compress the contents of the “dist” directory created by PyInstaller into a *.zip archive.
5. Download and install [NSIS](https://nsis.sourceforge.io/Download).
6. Launch NSIS, click **Installer based on a .ZIP file**, and then click **Open** to locate the **\*.zip** archive you have just created.
7. If you want to make the files installed (extracted) to the “Program Files” of the target user, in the **Default Folder** enter `$PROGRAMFILES`
8. If you want to add a shortcut to the internal *.exe file on the Desktop after installation, you can add something like this to the file “Modern.nsh” located at: "C:\Program Files\NSIS\Contrib\zip2exe\". Depending on your OS, the path could be at “Program Files (x86)”. Note that the exe path should be consistent with the path you selected under NSIS’s “Default Folder” drop-down menu, the folder name, and the exe file name.
```
Section "Desktop Shortcut" SectionX
    SetShellVarContext current
    CreateShortCut "$DESKTOP\DesktopTranslator.lnk" "$PROGRAMFILES\DesktopTranslator\translator.exe"
SectionEnd
```
9. Finally, click the NSIS **Generate** button, which will create the ***.exe** installer that can be shipped to other Windows machines, without the need to install any extra requirements.
10. After installation, if you applied step \#8, you should find an icon on the Desktop. To uninstall, you can simple remove the app forlder from "Program Files". For more NSIS options, check this [example](https://nsis.sourceforge.io/A_simple_installer_with_start_menu_shortcut_and_uninstaller).


