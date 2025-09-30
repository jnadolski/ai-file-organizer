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

def get_ai_categories_batch(item_list: list[dict], logger=None) -> list[dict]:
    """
    Sends a batch of item information to the Gemini API and requests a structured JSON list 
    of categories for all items.
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
                    "id": {"type": "integer", "description": "The unique identifier for the item."},
                    "name": {"type": "string", "description": "The exact original filename or folder name."},
                    "category": {"type": "string", "description": "A folder path for the item, up to two levels deep (e.g., 'Sims/Mods', 'Documents')."}
                },
                "required": ["id", "name", "category"]
            }
        }
        
        generation_config = GenerationConfig(
            response_mime_type="application/json",
            response_schema=json_schema
        )
        
        prompt = (
            "You are an expert file organizer. Analyze the following list of files and folders. "
            "For each item, determine a concise, descriptive folder path. "
            "Categorize files based on their name and extension, and folders based on their name. "
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
            "Items to categorize:\n" + json.dumps(item_list)
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

def get_items_to_organize(source_dir: str, logger=None) -> tuple[list[dict], list[dict], dict[int, Path]]:
    """Scans the source directory and returns separate lists of files and folders to be processed."""
    log = logger.info if logger else print
    
    source_path = Path(source_dir)
    if not source_path.is_dir():
        raise ValueError(f"Error: {source_path} is not a valid directory.")

    log(f"Scanning {source_path} and preparing batch request...")
    
    files_to_categorize = []
    folders_to_categorize = []
    item_path_map = {} 
    item_id = 0
    for item_path in source_path.rglob('*'):
        if item_path.name.startswith('.'):
            continue
        
        item_info = {
            "id": item_id,
            "name": item_path.name,
        }
        if item_path.is_file():
            item_info["type"] = "file"
            item_info["extension"] = item_path.suffix.lower()
            files_to_categorize.append(item_info)
        elif item_path.is_dir():
            item_info["type"] = "folder"
            folders_to_categorize.append(item_info)

        item_path_map[item_id] = item_path
        item_id += 1

    log(f"Found {len(files_to_categorize)} files and {len(folders_to_categorize)} folders to process.")
    return files_to_categorize, folders_to_categorize, item_path_map

def get_item_categories(items_to_categorize: list[dict], logger=None, progress_callback=None, batch_size=64) -> list[dict]:
    """Takes a list of items and gets the categories from the AI."""
    log = logger.info if logger else print
    log_error = logger.error if logger else lambda msg: print(msg, file=sys.stderr)

    if not items_to_categorize:
        log("No items found to organize.")
        return []

    log(f"Sending {len(items_to_categorize)} items to Gemini for categorization...")
    
    all_results = []

    for i in range(0, len(items_to_categorize), batch_size):
        batch = items_to_categorize[i:i + batch_size]
        log(f"Processing batch {i//batch_size + 1}/{(len(items_to_categorize) + batch_size - 1)//batch_size}...")
        results = get_ai_categories_batch(batch, logger)
        if results:
            all_results.extend(results)
        if progress_callback:
            progress_callback(i + len(batch), len(items_to_categorize))
    
    if not all_results:
        log_error("Batch categorization failed or returned empty results.")
        return []
        
    return all_results

def move_item(source_dir: str, categorized_item: dict, item_path_map: dict[int, Path], logger=None):
    """Moves a single item to its new categorized directory."""
    log = logger.info if logger else print
    log_error = logger.error if logger else lambda msg: print(msg, file=sys.stderr)
    
    source_path = Path(source_dir)
    try:
        item_id = categorized_item["id"]
        category = sanitize_foldername(categorized_item["category"])
        item_path = item_path_map.get(item_id)
        
        if not item_path:
            log_error(f"Warning: Could not find original path for item with id '{item_id}'. Skipping.")
            return

        log(f"Item: '{item_path.name}' -> Category: '{category}'")

        dest_dir = source_path / category
        dest_dir.mkdir(parents=True, exist_ok=True)
        
        new_item_path = dest_dir / item_path.name

        # Check if trying to move a directory into itself
        if item_path.is_dir() and new_item_path.is_relative_to(item_path):
            log_error(f"Error: Cannot move directory '{item_path}' into itself '{new_item_path}'. Skipping.")
            return

        shutil.move(str(item_path), str(new_item_path))
        
        log(json.dumps({
            "source": str(item_path),
            "destination": str(new_item_path),
            "category": category,
            "status": "success"
        }))

    except KeyError:
        log_error(f"Warning: Missing key in result data: {categorized_item}. Skipping.")
    except Exception as e:
        log_error(f"Error processing result for item with id {categorized_item.get('id')}: {e}")

def main():
    """Main function to orchestrate the file organization."""
    parser = argparse.ArgumentParser(description="AI-Powered File Organizer")
    parser.add_argument("source_dir", type=str, help="The directory to organize.")
    parser.add_argument("--batch_size", type=int, default=64, help="The batch size for AI categorization.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(message)s')
    logger = logging.getLogger()

    try:
        files_to_categorize, folders_to_categorize, item_path_map = get_items_to_organize(args.source_dir, logger)
        
        if files_to_categorize:
            categorized_files = get_item_categories(files_to_categorize, logger, batch_size=args.batch_size)
            if categorized_files:
                for categorized_file in categorized_files:
                    move_item(args.source_dir, categorized_file, item_path_map, logger)

        if folders_to_categorize:
            categorized_folders = get_item_categories(folders_to_categorize, logger, batch_size=args.batch_size)
            if categorized_folders:
                for categorized_folder in categorized_folders:
                    move_item(args.source_dir, categorized_folder, item_path_map, logger)

    except ValueError as e:
        logger.error(e)

if __name__ == "__main__":
    main()