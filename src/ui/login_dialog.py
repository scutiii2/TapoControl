from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QVBoxLayout


class LoginDialog(QDialog):
    """Asks for the Tapo account credentials at runtime."""

    def __init__(self, parent=None, email: str = "", message: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Tapo account")
        self.email = QLineEdit(email)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        form = QFormLayout()
        form.addRow("Email", self.email)
        form.addRow("Password", self.password)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(message or "Use the email and password of your Tapo app account."))
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _accept(self) -> None:
        if self.email.text().strip() and self.password.text():
            self.accept()

    def credentials(self) -> tuple[str, str]:
        return self.email.text().strip(), self.password.text()
