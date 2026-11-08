"""Point d'entrée de Foulée."""
import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from foulee import APP_NAME
from foulee.paths import resource
from foulee.ui.main_window import MainWindow
from foulee.ui.theme import STYLESHEET, load_fonts


def main() -> int:
    if sys.platform == "win32":
        try:  # icône propre dans la barre des tâches
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Vedrine.Foulee")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    load_fonts()
    app.setStyleSheet(STYLESHEET)
    icon = resource("assets/foulee.ico")
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    w = MainWindow()
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
