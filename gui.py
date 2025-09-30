import sys
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit, QProgressBar, QLabel, QTextEdit, QFileDialog
from PyQt6.QtCore import QThread, QObject, pyqtSignal

from organizer import get_items_to_organize, get_item_categories, move_item

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
    log_message = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, directory):
        super().__init__()
        self.directory = directory
        self.logger = QtLogger()
        self.logger.message.connect(self.log_message)
        self.is_cancelled = False

    def cancel(self):
        self.is_cancelled = True

    def run(self):
        try:
            self.status.emit("Scanning directory...")
            files_to_categorize, folders_to_categorize, item_path_map = get_items_to_organize(self.directory, self.logger)
            
            if self.is_cancelled:
                self.status.emit("Cancelled.")
                self.finished.emit()
                return

            total_items_to_process = len(files_to_categorize) + len(folders_to_categorize)
            if total_items_to_process == 0:
                self.status.emit("No items to organize.")
                self.finished.emit()
                return

            self.status.emit(f"Found {len(files_to_categorize)} files and {len(folders_to_categorize)} folders to process.")
            
            processed_items_count = 0

            if files_to_categorize:
                self.status.emit("Categorizing files with AI...")
                
                def file_categorization_progress(processed, total):
                    if self.is_cancelled:
                        raise Exception("Organization cancelled.")
                    current_progress = int((processed_items_count + (processed / total)) / total_items_to_process * 100)
                    self.progress.emit(current_progress)

                categorized_files = get_item_categories(files_to_categorize, self.logger, file_categorization_progress, batch_size=64)

                if self.is_cancelled:
                    self.status.emit("Cancelled.")
                    self.finished.emit()
                    return

                if categorized_files:
                    self.status.emit("Moving files...")
                    for i, categorized_file in enumerate(categorized_files):
                        if self.is_cancelled:
                            break
                        move_item(self.directory, categorized_file, item_path_map, self.logger)
                        processed_items_count += 1
                        current_progress = int((processed_items_count / total_items_to_process) * 100)
                        self.progress.emit(current_progress)

            if self.is_cancelled:
                self.status.emit("Cancelled.")
                self.finished.emit()
                return

            if folders_to_categorize:
                self.status.emit("Categorizing folders with AI...")

                def folder_categorization_progress(processed, total):
                    if self.is_cancelled:
                        raise Exception("Organization cancelled.")
                    current_progress = int((processed_items_count + (processed / total)) / total_items_to_process * 100)
                    self.progress.emit(current_progress)

                categorized_folders = get_item_categories(folders_to_categorize, self.logger, folder_categorization_progress, batch_size=64)

                if self.is_cancelled:
                    self.status.emit("Cancelled.")
                    self.finished.emit()
                    return

                if categorized_folders:
                    self.status.emit("Moving folders...")
                    for i, categorized_folder in enumerate(categorized_folders):
                        if self.is_cancelled:
                            break
                        move_item(self.directory, categorized_folder, item_path_map, self.logger)
                        processed_items_count += 1
                        current_progress = int((processed_items_count / total_items_to_process) * 100)
                        self.progress.emit(current_progress)

            if self.is_cancelled:
                self.status.emit("Organization cancelled.")
            else:
                self.status.emit("Organization complete.")
                self.progress.emit(100) # Ensure 100% is emitted at the end
        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.finished.emit()

class OrganizerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AI File Organizer")
        self.setGeometry(100, 100, 600, 400)

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

        # Buttons
        button_layout = QHBoxLayout()
        self.start_button = QPushButton("Start Organizing")
        self.start_button.clicked.connect(self.start_organization)
        button_layout.addWidget(self.start_button)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel_organization)
        self.cancel_button.setEnabled(False)
        button_layout.addWidget(self.cancel_button)
        main_layout.addLayout(button_layout)

        # Progress bar
        self.progress_bar = QProgressBar()
        main_layout.addWidget(self.progress_bar)

        # Status label
        self.status_label = QLabel("Ready")
        main_layout.addWidget(self.status_label)

        # Log console
        self.log_console = QTextEdit()
        self.log_console.setReadOnly(True)
        main_layout.addWidget(self.log_console)

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
        self.cancel_button.setEnabled(True)
        self.progress_bar.setValue(0)
        self.log_console.clear()
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
        self.worker.log_message.connect(self.update_log)
        self.worker.error.connect(self.report_error)
        self.thread.finished.connect(lambda: self.start_button.setEnabled(True))
        self.thread.finished.connect(lambda: self.cancel_button.setEnabled(False))

        self.thread.start()

    def cancel_organization(self):
        if self.worker:
            self.worker.cancel()

    def update_progress(self, value):
        self.progress_bar.setValue(value)

    def update_status(self, message):
        self.status_label.setText(message)

    def update_log(self, message):
        self.log_console.append(message)

    def report_error(self, error):
        self.log_console.append(f"Error: {error}")
        self.status_label.setText("Error occurred.")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = OrganizerWindow()
    window.show()
    sys.exit(app.exec())
