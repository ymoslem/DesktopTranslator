"""Text and language widgets"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QCompleter, QLabel, QTextEdit, QToolTip


class SourceEdit(QTextEdit):
    """The source text; a text file can be dropped on it"""

    file_dropped = Signal(str)

    def canInsertFromMimeData(self, source):
        return source.hasUrls() or super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source):
        if source.hasUrls() and source.urls()[0].isLocalFile():
            self.file_dropped.emit(source.urls()[0].toLocalFile())
        else:
            super().insertFromMimeData(source)


class LanguageBox(QComboBox):
    """A language list that can be searched by typing"""

    def __init__(self):
        super().__init__()
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.setMinimumContentsLength(16)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)

    def set_languages(self, items, searchable):
        self.blockSignals(True)
        self.clear()
        self.addItems(items)
        self.setEditable(searchable)
        if searchable:
            completer = QCompleter(items, self)
            completer.setFilterMode(Qt.MatchFlag.MatchContains)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            self.setCompleter(completer)
        # The list is as wide as its longest name, even if the box is narrower
        self.view().setMinimumWidth(self.view().sizeHintForColumn(0) + 40)
        self.blockSignals(False)

    def choose(self, text):
        """Select an entry by its name; returns False if there is no such entry"""
        index = self.findText(text, Qt.MatchFlag.MatchFixedString)
        if index < 0:
            return False
        self.setCurrentIndex(index)
        return True


class InfoSign(QLabel):
    """An (i) sign that shows its tooltip at once, instead of after the usual delay"""

    def __init__(self, text):
        super().__init__("\u24d8")
        self.setToolTip(text)
        self.setCursor(Qt.CursorShape.WhatsThisCursor)

    def enterEvent(self, event):
        QToolTip.showText(self.mapToGlobal(self.rect().bottomLeft()), self.toolTip(), self, self.rect())
        super().enterEvent(event)
