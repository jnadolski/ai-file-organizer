import sys
import os
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit, QProgressBar, QLabel, QFileDialog
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
    error = pyqtSignal(str)
    set_progress_determinate = pyqtSignal(bool) # New signal

    def __init__(self, directory, debug_skip_api=False):
        super().__init__()
        self.directory = directory
        self.debug_skip_api = debug_skip_api # Store debug_skip_api
        self.logger = QtLogger()
        self.logger.message.connect(self.status) # Connect logger messages to status
        self.is_cancelled = False

    def cancel(self):
        self.is_cancelled = True

    def run(self):
        try:
            self.status.emit("Scanning directory...")
            files_to_categorize, folders_to_categorize, item_path_map = get_items_to_organize(self.directory, self.logger, debug_skip_api=self.debug_skip_api)
            
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

                categorized_files = get_item_categories(files_to_categorize, self.logger, file_categorization_progress, batch_size=64, debug_skip_api=self.debug_skip_api)

                if self.is_cancelled:
                    self.status.emit("Cancelled.")
                    self.finished.emit()
                    return

                if categorized_files:
                    self.set_progress_determinate.emit(True)
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

                categorized_folders = get_item_categories(folders_to_categorize, self.logger, folder_categorization_progress, batch_size=64, debug_skip_api=self.debug_skip_api)

                if self.is_cancelled:
                    self.status.emit("Cancelled.")
                    self.finished.emit()
                    return

                if categorized_folders:
                    self.set_progress_determinate.emit(True)
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
    def __init__(self, debug_skip_api=False):
        super().__init__()
        self.setWindowTitle("AI File Organizer")
        self.setFixedSize(600, 150) # Set fixed size
        self.debug_skip_api = debug_skip_api

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

        # Action button (Start/Cancel)
        self.action_button = QPushButton("Start Organizing")
        self.action_button.clicked.connect(self.start_organization) # Initially connected to start
        main_layout.addWidget(self.action_button)

        # Progress bar
        self.progress_bar = QProgressBar()
        main_layout.addWidget(self.progress_bar)

        # Status label
        self.status_label = QLabel("Ready")
        main_layout.addWidget(self.status_label)

        self.current_directory = "" # Initialize current_directory

    def browse_directory(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Directory", os.path.expanduser("~"))
        if directory:
            self.dir_label.setText(directory)
            self.current_directory = directory # Store the selected directory

    def start_organization(self):
        self.is_cancelled = False
        directory = self.dir_label.text()
        if not directory:
            self.status_label.setText("Please select a directory first.")
            return
        
        self.current_directory = directory # Ensure current_directory is set
        self.action_button.setText("Cancel")
        self.action_button.clicked.disconnect() # Disconnect from start_organization
        self.action_button.clicked.connect(self.cancel_organization) # Connect to cancel_organization
        self.action_button.setEnabled(True) # Ensure it's enabled to be clicked for cancel
        self.progress_bar.setValue(0)
        self.progress_bar.setRange(0, 0) # Indeterminate mode
        self.status_label.setText(f"Starting organization for: {directory}")

        self.thread = QThread()
        self.worker = Worker(self.current_directory, self.debug_skip_api) # Pass debug_skip_api
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.worker.progress.connect(self.update_progress)
        self.worker.status.connect(self.update_status)
        self.worker.error.connect(self.report_error)
        self.worker.set_progress_determinate.connect(self.set_progress_determinate) # Connect new signal
        self.thread.finished.connect(self.on_organization_finished) # Connect to a new slot for cleanup

        self.thread.start()

    def cancel_organization(self):
        self.is_cancelled = True
        if self.worker:
            self.worker.cancel()
            self.status_label.setText("Cancelling organization...")

    def update_progress(self, value):
        self.progress_bar.setValue(value)

    def update_status(self, message):
        self.status_label.setText(message)

    def report_error(self, error):
        self.status_label.setText(f"Error: {error}")

    def set_progress_determinate(self, determinate):
        self.progress_bar.setRange(0, 100 if determinate else 0)

    def on_organization_finished(self):
        self.action_button.setText("Start Organizing")
        self.action_button.clicked.disconnect()
        self.action_button.clicked.connect(self.start_organization)
        self.action_button.setEnabled(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        if not self.is_cancelled:
            dialog = CompletionDialog(self, self.current_directory)
            dialog.exec()

            if dialog.result == "open_folder":
                pass
            elif dialog.result == "organize_another":
                self.dir_label.clear()
                self.status_label.setText("Ready")
            elif dialog.result == "exit":
                QApplication.instance().quit()
        else:
            self.status_label.setText("Organization Cancelled. Try Again?")

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel

class CompletionDialog(QDialog):
    def __init__(self, parent=None, organized_directory=""):
        super().__init__(parent)
        self.setWindowTitle("Organization Complete")
        self.organized_directory = organized_directory
        self.result = None # To store which button was clicked

        layout = QVBoxLayout()
        layout.addWidget(QLabel("File organization is complete!"))

        button_layout = QHBoxLayout()

        open_folder_button = QPushButton("Open Folder")
        open_folder_button.clicked.connect(self.open_organized_folder)
        button_layout.addWidget(open_folder_button)

        organize_another_button = QPushButton("Organize Another")
        organize_another_button.clicked.connect(self.organize_another)
        button_layout.addWidget(organize_another_button)

        exit_button = QPushButton("Exit")
        exit_button.clicked.connect(self.exit_application)
        button_layout.addWidget(exit_button)

        layout.addLayout(button_layout)
        self.setLayout(layout)

    def open_organized_folder(self):
        if self.organized_directory:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.organized_directory))
        self.result = "open_folder"
        self.accept() # Close the dialog

    def organize_another(self):
        self.result = "organize_another"
        self.accept() # Close the dialog

    def exit_application(self):
        self.result = "exit"
        self.accept() # Close the dialog

if __name__ == "__main__":
    app = QApplication(sys.argv)
    debug_skip_api = "--debug_skip_api" in sys.argv
    window = OrganizerWindow(debug_skip_api=debug_skip_api)
    window.show()
    sys.exit(app.exec())