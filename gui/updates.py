"""The check for a newer version of the app, which runs only when the user asks for it"""
import json
import re
import urllib.request

from gui.constants import APP_NAME, RELEASES_URL, VERSION

LATEST_URL = "https://api.github.com/repos/ymoslem/DesktopTranslator/releases/latest"


def version_numbers(text):
    """The first three numbers of a version such as v0.4.2 or 0.4.2-dev, as a tuple"""
    return tuple(int(number) for number in re.findall(r"\d+", text)[:3])


def is_newer(latest, current):
    return version_numbers(latest) > version_numbers(current)


def fetch_latest(timeout=10):
    """The tag and the page of the latest release; the request sends the name and version of the app, and the address of the computer"""
    request = urllib.request.Request(LATEST_URL, headers={"Accept": "application/vnd.github+json", "User-Agent": APP_NAME + "/" + VERSION})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.load(response)
    return data["tag_name"], data.get("html_url") or RELEASES_URL
