import os
from pathlib import Path
import random

test_dir = Path("test_files")
test_dir.mkdir(exist_ok=True)

file_types = {
    "document": [".pdf", ".docx", ".txt", ".xlsx", ".pptx"],
    "image": [".jpg", ".png", ".gif"],
    "archive": [".zip", ".tar.gz", ".rar"],
    "audio": [".mp3", ".wav"],
    "video": [".mp4", ".avi"],
    "sims_mod": [".package", ".zip"],
    "report": [".pdf", ".docx"],
    "misc": [".log", ".ini", ".tmp"]
}

categories = list(file_types.keys())

for i in range(1, 51):
    category = random.choice(categories)
    extension = random.choice(file_types[category])
    file_name = f"{category}_{i}{extension}"
    file_path = test_dir / file_name
    file_path.touch()

print(f"Created 50 test files with descriptive names in {test_dir}")