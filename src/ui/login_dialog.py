from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QLabel, QLineEdit, QPushButton

from ui import tokens as t
from ui.theme import theme
from ui.page_layout import FORM_WIDTH, ControlPage, panel, text_label


class LoginPanel(ControlPage):
    """Account tab submits runtime credentials without a modal event loop."""

    submitted = Signal()

    def __init__(self, parent=None, email: str = "", message: str = ""):
        super().__init__(parent, max_width=FORM_WIDTH)
        theme()
        self.email = QLineEdit(email)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.email.setPlaceholderText("you@example.com")
        self.email.setAccessibleName("Tapo account email")
        self.password.setAccessibleName("Tapo account password")
        self.email.returnPressed.connect(self.password.setFocus)
        self.password.returnPressed.connect(self._accept)
        card, form = panel("Tapo account")
        form.addWidget(text_label("Use the account from your Tapo app.", muted=True))
        for text, field in (("Email", self.email), ("Password", self.password)):
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
        form.addWidget(text_label("Your plugs confirm sign-in when they respond.", "caption"))
        layout = self.content
        layout.addWidget(card)
        storage, note = panel("Credential storage")
        note.addWidget(text_label("Password saved in Windows Credential Manager.", muted=True))
        note.addWidget(text_label("Email and known plugs saved on this PC.", muted=True))
        layout.addWidget(storage)
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
