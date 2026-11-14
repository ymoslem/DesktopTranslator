"""Names, links and settings shared by the windows and dialogs"""

APP_NAME = "DesktopTranslator"
VERSION = "0.4.4"
TARGET_PLACEHOLDER = "Select a language..."
DEFAULT_TEXT_SIZE = 14
DEVICES = ["CPU", "GPU (NVIDIA)"]
CPU_SPEEDS = {"Standard": "standard", "Faster": "faster", "Fastest": "fastest", "Automatic": "automatic"}  # name: key of engine.CPU_SENTENCES
QUALITY = {"Fast (beam size 2)": 2, "Balanced (beam size 3)": 3, "Thorough (beam size 5)": 5}  # name: beam size
DEFAULT_QUALITY = "Balanced (beam size 3)"
REPOSITORY_URL = "https://github.com/ymoslem/DesktopTranslator"  # shown in About; a website can be added later
NOTICE_URL = REPOSITORY_URL + "/blob/main/NOTICE.md"
RELEASES_URL = REPOSITORY_URL + "/releases"
ISSUES_URL = REPOSITORY_URL + "/issues"
DOWNLOADS = [
    ("NLLB-200 distilled 600M", "200 languages; the smallest and fastest",
     "https://github.com/ymoslem/DesktopTranslator/releases/download/models/NLLB-200_distilled_600M_int8_ct2.zip"),
    ("NLLB-200 distilled 1.3B", "200 languages; slower, needs more memory, sometimes more accurate",
     "https://github.com/ymoslem/DesktopTranslator/releases/download/models/NLLB-200_distilled_1.3B_int8_ct2.zip"),
    ("M2M-100 418M", "100 languages; small",
     "https://github.com/ymoslem/DesktopTranslator/releases/download/v0.2.1/M2M-100_418m_parameter_model_ct2.zip"),
    ("M2M-100 1.2B", "100 languages; larger",
     "https://github.com/ymoslem/DesktopTranslator/releases/download/v0.2.1/M2M-100_12b_parameter_model_ct2.zip"),
    ("French to English", "A small model to try the app",
     "https://github.com/ymoslem/DesktopTranslator/releases/download/v0.2.3/fren.zip"),
]
