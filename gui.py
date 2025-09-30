import sys
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit, QProgressBar, QLabel, QFileDialog
from PyQt6.QtCore import QThread, QObject, pyqtSignal

from organizer import get_files_to_organize, get_ai_categories, move_file

class QtLogger(QObject):
    message = pyqtSignal(str)

    def info(self, msg):
        self.message.emit(msg)

    def error(self, msg):
        self.message.emit(f"ERROR: {msg}")

class Worker(QObject):
    finished = pyqtSignal()
    progress = pyqtSignal(int)
    status = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, directory):
        super().__init__()
        self.directory = directory
        self.logger = QtLogger()
        self.logger.message.connect(self.status)

    def run(self):
        try:
            self.status.emit("Scanning directory...")
            files_to_categorize, file_path_map = get_files_to_organize(self.directory, self.logger)
            
            if not files_to_categorize:
                self.status.emit("No files to organize.")
                self.finished.emit()
                return

            self.status.emit(f"Found {len(files_to_categorize)} files to process.")
            
            self.status.emit("Categorizing files with AI...")
            categorized_files = get_ai_categories(files_to_categorize, self.logger)

            if not categorized_files:
                self.status.emit("Could not categorize files.")
                self.finished.emit()
                return

            self.status.emit("Moving files...")
            total_files = len(categorized_files)
            for i, categorized_file in enumerate(categorized_files):
                move_file(self.directory, categorized_file, file_path_map, self.logger)
                progress_value = int(((i + 1) / total_files) * 100)
                self.progress.emit(progress_value)

            self.status.emit("Organization complete.")
        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.finished.emit()

class OrganizerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AI File Organizer")
        self.setFixedSize(600, 150)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout()
        central_widget.setLayout(main_layout)

        # Directory selection
        dir_layout = QHBoxLayout()
        self.dir_label = QLineEdit()
        self.dir_label.setPlaceholderText("Select a directory to organize...")
        self.dir_label.setReadOnly(True)
        dir_layout.addWidget(self.dir_label)

        self.browse_button = QPushButton("Browse...")
        self.browse_button.clicked.connect(self.browse_directory)
        dir_layout.addWidget(self.browse_button)

        main_layout.addLayout(dir_layout)

        # Start button
        self.start_button = QPushButton("Start Organizing")
        self.start_button.clicked.connect(self.start_organization)
        main_layout.addWidget(self.start_button)

        # Progress bar
        self.progress_bar = QProgressBar()
        main_layout.addWidget(self.progress_bar)

        # Status label
        self.status_label = QLabel("Ready")
        main_layout.addWidget(self.status_label)

    def browse_directory(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Directory")
        if directory:
            self.dir_label.setText(directory)

    def start_organization(self):
        directory = self.dir_label.text()
        if not directory:
            self.status_label.setText("Please select a directory first.")
            return
        
        self.start_button.setEnabled(False)
        self.progress_bar.setValue(0)
        self.status_label.setText(f"Starting organization for: {directory}")

        self.thread = QThread()
        self.worker = Worker(directory)
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.worker.progress.connect(self.update_progress)
        self.worker.status.connect(self.update_status)
        self.worker.error.connect(self.report_error)
        self.thread.finished.connect(lambda: self.start_button.setEnabled(True))

        self.thread.start()

    def update_progress(self, value):
        self.progress_bar.setValue(value)

    def update_status(self, message):
        self.status_label.setText(message)

    def report_error(self, error):
        self.status_label.setText(f"Error: {error}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = OrganizerWindow()
    window.show()
    sys.exit(app.exec())