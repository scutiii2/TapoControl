from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QFrame, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from ui import tokens as t
from ui.theme import theme


class LoginPanel(QWidget):
    """Account tab submits runtime credentials without a modal event loop."""

    submitted = Signal()

    def __init__(self, parent=None, email: str = "", message: str = ""):
        super().__init__(parent)
        theme()
        self.email = QLineEdit(email)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.email.setPlaceholderText("you@example.com")
        self.email.setAccessibleName("Tapo account email")
        self.password.setAccessibleName("Tapo account password")
        self.email.setMaximumWidth(560)
        self.password.setMaximumWidth(560)
        self.email.returnPressed.connect(self.password.setFocus)
        self.password.returnPressed.connect(self._accept)
        title = QLabel("Tapo account")
        title.setProperty("role", "heading")
        detail = QLabel("Use your Tapo app account to control plugs.")
        detail.setProperty("tone", "muted")
        detail.setWordWrap(True)
        card = QFrame()
        card.setProperty("card", True)
        form = QVBoxLayout(card)
        form.setContentsMargins(t.CARD_PAD, t.CARD_PAD, t.CARD_PAD, t.CARD_PAD)
        form.setSpacing(t.SP_XS)  # a label sits closer to its field than to the previous one
        for text, field in (("&Email", self.email), ("&Password", self.password)):
            label = QLabel(text)
            label.setBuddy(field)
            form.addWidget(label)
            form.addWidget(field)
            form.addSpacing(t.SP_MD)
        self._reveal = QCheckBox("Show password")
        self._reveal.toggled.connect(
            lambda on: self.password.setEchoMode(QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password)
        )
        form.addWidget(self._reveal)
        form.addSpacing(t.SP_SM)
        note = QLabel("Password saved in Windows Credential Manager.")
        note.setProperty("tone", "muted")
        note.setWordWrap(True)
        form.addWidget(note)
        self._message = QLabel()
        self._message.setProperty("tone", "error")
        self._message.setTextFormat(Qt.TextFormat.PlainText)
        self._message.setWordWrap(True)
        form.addWidget(self._message)
        self._submit = QPushButton("Sign in")
        self._submit.setProperty("primary", True)
        self._submit.clicked.connect(self._accept)
        form.addSpacing(t.SP_SM)
        form.addWidget(self._submit, 0, Qt.AlignmentFlag.AlignLeft)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, t.PAGE_TOP, 0, 0)
        layout.setSpacing(t.SP_SM)
        layout.addWidget(title)
        layout.addWidget(detail)
        layout.addSpacing(t.SP_SM)
        layout.addWidget(card)
        layout.addStretch()
        self.set_message(message)

    def set_message(self, message: str = "", error: bool = True) -> None:
        self._message.setText(message)
        self._message.setProperty("tone", "error" if error else "muted")
        self._message.style().unpolish(self._message)
        self._message.style().polish(self._message)
        self._message.setVisible(bool(message))
        for field in (self.email, self.password):  # tie the message to the fields it is about
            field.setAccessibleDescription(message)

    def _accept(self) -> None:
        if self.email.text().strip() and self.password.text():
            self.submitted.emit()
        else:
            self.set_message("Enter your Tapo email and password.")
            (self.email if not self.email.text().strip() else self.password).setFocus()

    def credentials(self) -> tuple[str, str]:
        return self.email.text().strip(), self.password.text()
