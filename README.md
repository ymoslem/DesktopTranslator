[![DesktopTranslator](https://img.shields.io/badge/Download-Windows_Installer-blue)](https://bit.ly/3sNz8qh)
[![DesktopTranslator](https://img.shields.io/badge/Download-macOS_App-red)](https://bit.ly/3rTS6wa)

# DesktopTranslator
Local cross-platform machine translation GUI, based on [CTranslate2](https://github.com/OpenNMT/CTranslate2)

![DesktopTranslator](img/DesktopTranslator-NEW.png)

**Table of contents**

1. [Download DesktopTranslator](#download-desktoptranslator)
1. [Translation Models](#translation-models)
    * [French-to-English Generic Model](#french-to-english-generic-model)
    * [M2M-100 Multilingual Model](#m2m-100-multilingual-model)
1. [[Optional] Build Stand-alone Executable](#build-stand-alone-executable)
   * [Build Windows Installer](#build-windows-installer)
   * [Build macOS App](#build-macos-app)
1. [References](#references)

    
## Download DesktopTranslator
   
[![DesktopTranslator](https://img.shields.io/badge/Download-Windows_Installer-blue)](https://bit.ly/3sNz8qh)
[![DesktopTranslator](https://img.shields.io/badge/Download-macOS_App-red)](https://bit.ly/3rTS6wa)

<img src="img/installer.png" width="60%">


## Translation Models

Currently, DesktopTranslator supports CTranslate2 models, and SentencePiece subwording models (you need both). If you have a model for OpenNMT-py, OpenNMT-tf, or FairSeq, you can [convert it to the CTranslate2 format](https://github.com/OpenNMT/CTranslate2#quickstart).

### French-to-English Generic Model

If you would like to try out the app and you do not have a model, you can download my [French-to-English generic model here](https://pretrained-nmt-models.s3.us-west-2.amazonaws.com/CTranslate2/fren/fren.zip). 
1. Unzip the `fren.zip` archive of the French-to-English generic model you just downloaded. It has two folders, `ct2_model` for the CTranslate2 model and `sp_model` for the SentencePiece subwording models of French (source) and English (target).
2. In DesktopTranslator, click the <kbd>CTranslate2 Model</kbd> button, and select the `ct2_model` folder.
3. Click the <kbd>SentencePiece Model</kbd> button, navigate to the `sp_model` folder, and select `fr.model`.
4. The default <kbd>Beam Size</kbd> is 3. You can increase it to 5, which can be slower, but sometimes results in better translation quality.
5. In the left input text-area, type some text in French or use the <kbd>File</kbd> menu \> <kbd>Open...</kbd> to open a *.txt file.
6. Click the <kbd>Translate</kbd> button.

### M2M-100 Multilingual Model

Now, DesktopTranslator supports [**M2M-100**](https://github.com/pytorch/fairseq/tree/main/examples/m2m_100) ([Fan et al., 2020](https://arxiv.org/abs/2010.11125)), a multilingual model that can translate between 100 languages.
    
<kbd> ![DesktopTranslator](img/DesktopTranslator_M2M-100.png)

To use M2M-100 models in DesktopTranslator, please follow these steps:
1. Download one of the M2M-100 models, converted to the CTranslate2 format:  
    a. [M2M-100 418M-parameter model](https://bit.ly/33fM1AO); smaller and faster, but sometimes less accurate; or  
    b. [M2M-100 1.2B-parameter model](https://bit.ly/3GYiaed); bigger and somehow slower, but sometimes more accurate.
2. Extract the *.zip arhieve of the model you downloaded.
3. In DesktopTranslator, click the <kbd>CTranslate2 Model</kbd> button, and select the `m2m100_418m` or `m2m100_12b` folder.
4. Click the <kbd>SentencePiece Model</kbd> button, and from the same model folder, select `sentencepiece.model`.
5. **Important:** From the <kbd>M2M-100</kbd> dropdown list, select the target language to which you want to translate. This step is different between M2M-100 and some other models. M2M-100 models require a language code prefix. For other models that do not require this, keep the "None" option.
6. The default <kbd>Beam Size</kbd> is 3. You can increase it to 5, which can be slower, but sometimes results in better translation quality.
7. In the left input text-area, type some text in any language or your choice of use the <kbd>File</kbd> menu \> <kbd>Open...</kbd> to open a *.txt file.
8. Click the <kbd>Translate</kbd> button.
   
### OPUS Models

OPUS models ([Tatoeba-Challenge](https://github.com/Helsinki-NLP/Tatoeba-Challenge/tree/master/models)) can be used and they can be more efficient. As of now, only _bilingual_ models are supported by DesktopTranslator. Note: You must convert an OPUS model to the CTranslate2 format first. Example command:
```
ct2-opus-mt-converter --model_dir opus_model_dir --output_dir ct2_model_dir --quantization int8
```
The source and target tokenization SentencePiece models can be found in the same archive of the downloaded model.

## [Optional] Build Stand-alone Executable
   
### Build Windows Installer

If you want to adjust the code and then build an installer yourself, you can follow these steps:

1. Install PyInstaller:
```
pip3 install pyinstaller
```

2. To use PyInstaller, specify the Python file name and the argument -w to hide the console window:
```
pyinstaller -y -w "translator.py"
```
If you would like to add an extra folder, e.g. "utils", the command will be:
```
pyinstaller -y -w --add-data="utils/*;utils/" "translator.py"
```
3. Try the `*.exe` file under "dist\translator" to make sure it works. It might complain about the Pmw library. The solution is either remove the Balloon lines, or add [this file](https://gist.github.com/ymoslem/c4b0cd287c7d5f2b7279dfce354d389b) to the same folder as the `translate.py` and run the aforementioned PyInstaller command again.
4. Compress the contents of the “dist” directory created by PyInstaller into a *.zip archive. For example, you can find a folder called "translator"; give it the name you like, e.g. "DesktopTranslator", and add it to a *.zip archive.
5. Download and install [NSIS](https://nsis.sourceforge.io/Download).
6. Launch NSIS, click **Installer based on a .ZIP file**, and then click **Open** to locate the **\*.zip** archive you have just created.
7. If you want to make the files installed (extracted) to the “Program Files” of the target user, in the **Default Folder** enter `$PROGRAMFILES`
8. If you want to add a shortcut to the internal *.exe file on the Desktop after installation, you can add something like this to the file “Modern.nsh” located at: "C:\Program Files\NSIS\Contrib\zip2exe\". Depending on your OS, the path could be at “Program Files (x86)”. Note that the EXE file path should be consistent with the path you selected under NSIS’s “Default Folder” drop-down menu, the folder name, and the EXE file name.
```
Section "Desktop Shortcut" SectionX
    SetShellVarContext current
    CreateShortCut "$DESKTOP\DesktopTranslator.lnk" "$PROGRAMFILES\DesktopTranslator\translator.exe"
SectionEnd
```
If you get a permission error while trying to save the edited version of “Modern.nsh”, right-click your text editor (e.g. _Notepad_), and select "Run as administrator". Then, copy the contents of the file into a new file, and save it to the original location.  
9. Finally, click the NSIS **Generate** button, which will create the ***.exe** installer that can be shipped to other Windows machines, without the need to install any extra requirements.
10. After installation, if you applied step \#8, you should find an icon on the Desktop. To uninstall, you can simply remove the app folder from "Program Files". For more NSIS options, check this [example](https://nsis.sourceforge.io/A_simple_installer_with_start_menu_shortcut_and_uninstaller).

### Build macOS App

1. Install `py2app`
```
pip3 install py2app==0.25
```
2. Create a [setup.py](https://gist.github.com/ymoslem/e0c88f30181191d57c374b6cdad9317c) file in the same directory.
3. Run this command in the Terminal. You can add the option `-A` to test the app first.
```
python3 setup.py py2app
```


## References

* [Efficient and High-Quality Neural Machine Translation with OpenNMT, Klein et al., 2020](https://aclanthology.org/2020.ngt-1.25/)
* [Beyond English-Centric Multilingual Machine Translation, Fan et al., 2020](https://arxiv.org/abs/2010.11125)
