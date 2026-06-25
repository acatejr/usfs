import json
from pathlib import Path
from bs4 import BeautifulSoup
import hashlib


def save_json(
    data: dict | list,
    file_path: str | Path,
    indent: int = 2,
    ensure_ascii: bool = False,
    create_dirs: bool = True,
) -> None:
    """
    Save a dictionary or list to a JSON file.

    Args:
        data: Dictionary or list to save as JSON
        file_path: Path to the output JSON file
        indent: Number of spaces for indentation (default: 2). Set to None for compact output
        ensure_ascii: If True, escape non-ASCII characters (default: False)
        create_dirs: If True, create parent directories if they don't exist (default: True)

    Raises:
        TypeError: If data is not JSON serializable
        IOError: If file cannot be written

    Example:
        >>> data = {"title": "Example", "keywords": ["test", "demo"]}
        >>> save_json(data, "output/data.json")

        >>> documents = [{"title": "Doc 1"}, {"title": "Doc 2"}]
        >>> save_json(documents, "output/documents.json", indent=4)
    """
    file_path = Path(file_path)

    # Create parent directories if needed
    if create_dirs and not file_path.parent.exists():
        file_path.parent.mkdir(parents=True, exist_ok=True)

    # Write JSON to file
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=indent, ensure_ascii=ensure_ascii)


def load_json(file_path: str | Path) -> dict | list:
    """
    Load a JSON file and return the parsed data.

    Args:
        file_path: Path to the JSON file to load

    Returns:
        Parsed JSON data as a dictionary or list

    Raises:
        FileNotFoundError: If the file does not exist
        json.JSONDecodeError: If the file is not valid JSON

    Example:
        >>> data = load_json("output/data.json")
        >>> print(data["title"])

        >>> documents = load_json("output/documents.json")
        >>> for doc in documents:
        ...     print(doc["title"])
    """
    file_path = Path(file_path)

    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def clean_str(text: str) -> str:
    """
    Cleans the input text by removing HTML tags and extra whitespace.

    :param text: Input string to clean.
    :type text: str
    :return: Cleaned string.
    :rtype: str
    """
    if text is None:
        return ""

    cleaned_str = strip_html(text)
    cleaned_str = " ".join(cleaned_str.split())

    return cleaned_str


def strip_html(text: str) -> str:
    """Remove HTML tags from the input text.
    Args:
        text: Input string containing HTML content.
    Returns:
        String with HTML tags removed.
    """

    soup = BeautifulSoup(text, "html.parser")
    stripped_text = soup.get_text()

    return stripped_text


def hash_string(s: str) -> str:
    """Generate a SHA-256 hash of the input string."""
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def dedupe_catalog(file_path: str | Path) -> None:
    """Remove duplicate entries from a catalog JSON file based on the 'id' field.

    Reads the catalog, removes duplicates (keeping the first occurrence),
    and writes the deduplicated data back to the same file.

    Args:
        file_path: Path to the catalog JSON file.
    """
    data = load_json(file_path)
    before = len(data)
    deduped = list({doc["id"]: doc for doc in data}.values())
    after = len(deduped)
    save_json(deduped, file_path)
    print(f"Before: {before}, After: {after}, Removed: {before - after}")
