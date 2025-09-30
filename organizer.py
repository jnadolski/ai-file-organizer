import os
os.environ['GRPC_VERBOSITY'] = 'NONE'

import warnings
warnings.filterwarnings(
    "ignore",
    "This feature is deprecated as of June 24, 2025",
    UserWarning
)

import argparse
import json
import shutil
from pathlib import Path
import logging
import sys
import re

import pypdf
import vertexai
from vertexai.generative_models import GenerativeModel, GenerationConfig

GCP_PROJECT_ID = "ai-file-organizer-473619"
GCP_LOCATION = "us-central1"
MAX_CONTENT_SIZE = 1 * 1024 * 1024

logging.getLogger("pypdf").setLevel(logging.ERROR)

def get_file_content(file_path: Path) -> str:
    """Extracts text content from supported file types, respecting MAX_CONTENT_SIZE."""
    if file_path.stat().st_size > MAX_CONTENT_SIZE:
        return ""
    if file_path.suffix.lower() == ".pdf":
        try:
            reader = pypdf.PdfReader(file_path)
            return "".join(page.extract_text() for page in reader.pages if page.extract_text())
        except Exception:
            return ""
    elif file_path.suffix.lower() in [".txt", ".md", ".py", ".js"]:
        return file_path.read_text(encoding='utf-8', errors='ignore')
    return ""

def sanitize_foldername(path_str: str) -> str:
    """Sanitizes each part of a path-like string."""
    sanitized_parts = []
    for part in path_str.split('/'):
        part = re.sub(r'[\\/:*?"<>|]', '', part)
        part = re.sub(r'\s+', '_', part.strip())
        part = '_'.join(word.capitalize() for word in part.split('_'))
        sanitized_parts.append(part if part else "Misc")
    return '/'.join(sanitized_parts)

def get_ai_categories_batch(file_list: list[dict], logger=None) -> list[dict]:
    """
    Sends a batch of file information to the Gemini API and requests a structured JSON list 
    of categories for all files.
    """
    log = logger.info if logger else print
    log_error = logger.error if logger else lambda msg: print(msg, file=sys.stderr)

    try:
        vertexai.init(project=GCP_PROJECT_ID, location=GCP_LOCATION)
        model = GenerativeModel("gemini-2.0-flash-lite")

        json_schema = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "description": "The unique identifier for the file."},
                    "filename": {"type": "string", "description": "The exact original filename."},
                    "category": {"type": "string", "description": "A folder path for the file, up to two levels deep (e.g., 'Sims/Mods', 'Documents')."}
                },
                "required": ["id", "filename", "category"]
            }
        }
        
        generation_config = GenerationConfig(
            response_mime_type="application/json",
            response_schema=json_schema
        )
        
        prompt = (
            "You are an expert file organizer. Analyze the following list of file names and extensions. "
            "For each file, determine a concise, descriptive folder path. "
            "The path can be one or two levels deep, using a forward slash (/) as a separator (e.g., 'Sims/Mods', 'Documents/Taxes'). "
            "Use the following standardized categories where appropriate, but you can also create new, fitting categories if needed:\n"
            "- Sims/Custom_Content\n"
            "- Sims/Mods\n"
            "- Sims/Saves\n"
            "- 3D_Assets/Models\n"
            "- 3D_Assets/Prints\n"
            "- Documents/Taxes\n"
            "- Documents/Statements\n"
            "- Software\n"
            "- Archives\n"
            "- Images\n"
            "- Torrents\n"
            "- Contacts\n"
            "- Misc\n"
            "Return ONLY a valid JSON list matching the provided schema. "
            "Files to categorize:\n" + json.dumps(file_list)
        )

        log("Sending request to Gemini API...")
        response = model.generate_content(
            [prompt],
            generation_config=generation_config
        )
        log("Received response from Gemini API.")
        
        return json.loads(response.text)

    except Exception as e:
        if isinstance(e, KeyboardInterrupt):
            raise
        log_error(f"FATAL Error during batch AI categorization: {e}")
        return []

def get_files_to_organize(source_dir: str, logger=None) -> tuple[list[dict], dict[int, Path]]:
    """Scans the source directory recursively and returns a list of files to be processed."""
    log = logger.info if logger else print
    
    source_path = Path(source_dir)
    if not source_path.is_dir():
        raise ValueError(f"Error: {source_path} is not a valid directory.")

    log(f"Scanning {source_path} recursively and preparing batch request...")
    
    files_to_categorize = []
    file_path_map = {} 
    file_id = 0
    for file_path in source_path.rglob('*'):
        if not file_path.is_file() or file_path.name.startswith('.'):
            continue
        
        file_info = {
            "id": file_id,
            "filename": file_path.name,
            "extension": file_path.suffix.lower(),
        }
        files_to_categorize.append(file_info)
        file_path_map[file_id] = file_path
        file_id += 1

    log(f"Found {len(files_to_categorize)} files to process.")
    return files_to_categorize, file_path_map

def get_ai_categories(files_to_categorize: list[dict], logger=None) -> list[dict]:
    """Takes a list of files and gets the categories from the AI."""
    log = logger.info if logger else print
    log_error = logger.error if logger else lambda msg: print(msg, file=sys.stderr)

    if not files_to_categorize:
        log("No files found to organize.")
        return []

    log(f"Sending {len(files_to_categorize)} files to Gemini for categorization...")
    
    batch_size = 20
    all_results = []

    for i in range(0, len(files_to_categorize), batch_size):
        batch = files_to_categorize[i:i + batch_size]
        log(f"Processing batch {i//batch_size + 1}/{(len(files_to_categorize) + batch_size - 1)//batch_size}...")
        results = get_ai_categories_batch(batch, logger)
        if results:
            all_results.extend(results)
    
    if not all_results:
        log_error("Batch categorization failed or returned empty results.")
        return []
        
    return all_results

def move_file(source_dir: str, categorized_file: dict, file_path_map: dict[int, Path], logger=None):
    """Moves a single file to its new categorized directory."""
    log = logger.info if logger else print
    log_error = logger.error if logger else lambda msg: print(msg, file=sys.stderr)
    
    source_path = Path(source_dir)
    try:
        file_id = categorized_file["id"]
        category = sanitize_foldername(categorized_file["category"])
        file_path = file_path_map.get(file_id)
        
        if not file_path:
            log_error(f"Warning: Could not find original path for file with id '{file_id}'. Skipping.")
            return

        log(f"File: '{file_path.name}' -> Category: '{category}'")

        dest_dir = source_path / category
        dest_dir.mkdir(parents=True, exist_ok=True)
        
        new_file_path = dest_dir / file_path.name
        shutil.move(str(file_path), str(new_file_path))
        
        log(json.dumps({
            "source": str(file_path),
            "destination": str(new_file_path),
            "category": category,
            "status": "success"
        }))

    except KeyError:
        log_error(f"Warning: Missing key in result data: {categorized_file}. Skipping.")
    except Exception as e:
        log_error(f"Error processing result for file with id {categorized_file.get('id')}: {e}")

def main():
    """Main function to orchestrate the file organization."""
    parser = argparse.ArgumentParser(description="AI-Powered File Organizer")
    parser.add_argument("source_dir", type=str, help="The directory to organize.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(message)s')
    logger = logging.getLogger()

    try:
        files_to_categorize, file_path_map = get_files_to_organize(args.source_dir, logger)
        categorized_files = get_ai_categories(files_to_categorize, logger)
        if categorized_files:
            for categorized_file in categorized_files:
                move_file(args.source_dir, categorized_file, file_path_map, logger)
    except ValueError as e:
        logger.error(e)

if __name__ == "__main__":
    main()
