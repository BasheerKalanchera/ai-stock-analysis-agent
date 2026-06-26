"""
skills_loader.py
================
Loads, matches, and manages sector-specific valuation Skills (.md files)
from the skills/ directory. Provides CRUD operations for the Streamlit UI
and a sector-matching function for the Valuation Agent.

YAML Frontmatter Format:
    ---
    sector_aliases:
      - "Banks - Private Sector"
      - "Banks - Public Sector"
    ---
    # Skill content in Markdown ...
"""
import os
import re
import logging
from typing import List, Dict, Optional

logger = logging.getLogger('skills_loader')
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - 📚 SKILLS - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.propagate = False

# --- Directory ---
SKILLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skills")


def _parse_frontmatter(content: str) -> tuple:
    """
    Splits a Markdown file into (frontmatter_dict, body).
    Returns ({}, full_content) if no YAML frontmatter is found.
    """
    # Match --- ... --- block at the start of the file
    match = re.match(r'^---\s*\n(.*?)\n---\s*\n', content, re.DOTALL)
    if not match:
        return {}, content.strip()

    yaml_block = match.group(1)
    body = content[match.end():].strip()

    # Simple YAML parser for sector_aliases list (avoids PyYAML dependency)
    frontmatter = {}
    current_key = None
    current_list = []

    for line in yaml_block.split('\n'):
        line = line.strip()
        if not line:
            continue

        # Key: value or Key:
        key_match = re.match(r'^(\w[\w_]*)\s*:\s*(.*)', line)
        if key_match and not line.startswith('-'):
            # Save previous key if it was a list
            if current_key and current_list:
                frontmatter[current_key] = current_list
            current_key = key_match.group(1)
            value = key_match.group(2).strip()
            if value:
                frontmatter[current_key] = value
                current_key = None
                current_list = []
            else:
                current_list = []
        elif line.startswith('-') and current_key:
            # List item: - "value" or - value
            item = line.lstrip('- ').strip().strip('"').strip("'")
            current_list.append(item)

    # Save last key
    if current_key and current_list:
        frontmatter[current_key] = current_list

    return frontmatter, body


def list_skills() -> List[Dict]:
    """
    Returns a list of all skill files with metadata.
    Each entry: {filename, sector_aliases, preview}
    """
    if not os.path.isdir(SKILLS_DIR):
        return []

    skills = []
    for fname in sorted(os.listdir(SKILLS_DIR)):
        if not fname.endswith('.md'):
            continue
        filepath = os.path.join(SKILLS_DIR, fname)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            fm, body = _parse_frontmatter(content)
            aliases = fm.get('sector_aliases', [])
            if isinstance(aliases, str):
                aliases = [aliases]
            # Preview: first non-empty, non-heading line
            preview_lines = [l.strip() for l in body.split('\n')
                             if l.strip() and not l.strip().startswith('#')]
            preview = preview_lines[0][:100] if preview_lines else ""

            skills.append({
                'filename': fname,
                'sector_aliases': aliases,
                'preview': preview,
            })
        except Exception as e:
            logger.warning(f"Could not read skill file {fname}: {e}")

    return skills


def load_skill_for_sector(sector: str) -> tuple:
    """
    Finds the best-matching skill file for the given sector string.
    Returns (skill_markdown_body, matched_filename).
    Falls back to _default.md if no match is found.
    """
    if not sector or sector == "Unknown":
        return _load_default()

    sector_lower = sector.lower().strip()

    if not os.path.isdir(SKILLS_DIR):
        logger.warning(f"Skills directory not found: {SKILLS_DIR}")
        return "", "_default.md"

    # Build alias map: lowercase alias -> (filename, body)
    best_match = None
    best_score = 0

    for fname in os.listdir(SKILLS_DIR):
        if not fname.endswith('.md') or fname == '_default.md':
            continue
        filepath = os.path.join(SKILLS_DIR, fname)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            fm, body = _parse_frontmatter(content)
            aliases = fm.get('sector_aliases', [])
            if isinstance(aliases, str):
                aliases = [aliases]

            for alias in aliases:
                alias_lower = alias.lower().strip()
                # Exact match
                if alias_lower == sector_lower:
                    logger.info(f"✅ Exact skill match: '{sector}' → {fname}")
                    return body, fname
                # Substring match (e.g., "Banks" in "Banks - Private Sector")
                if alias_lower in sector_lower or sector_lower in alias_lower:
                    score = len(alias_lower)  # Prefer longer (more specific) matches
                    if score > best_score:
                        best_score = score
                        best_match = (body, fname)
        except Exception as e:
            logger.warning(f"Error reading {fname}: {e}")

    if best_match:
        logger.info(f"✅ Fuzzy skill match: '{sector}' → {best_match[1]} (score={best_score})")
        return best_match

    logger.info(f"ℹ️ No skill match for '{sector}' — using _default.md")
    return _load_default()


def _load_default() -> tuple:
    """Loads the _default.md skill file."""
    default_path = os.path.join(SKILLS_DIR, "_default.md")
    if os.path.isfile(default_path):
        with open(default_path, 'r', encoding='utf-8') as f:
            content = f.read()
        _, body = _parse_frontmatter(content)
        return body, "_default.md"
    return "", "_default.md"


def read_skill(filename: str) -> str:
    """Reads the full raw content of a skill file (including frontmatter)."""
    filepath = os.path.join(SKILLS_DIR, filename)
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"Skill file not found: {filename}")
    with open(filepath, 'r', encoding='utf-8') as f:
        return f.read()


def save_skill(filename: str, content: str) -> None:
    """Writes content back to an existing skill file."""
    filepath = os.path.join(SKILLS_DIR, filename)
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"Skill file not found: {filename}")
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    logger.info(f"💾 Saved skill: {filename}")


def create_skill(filename: str, content: str) -> None:
    """Creates a new skill file. Filename must end with .md."""
    if not filename.endswith('.md'):
        filename += '.md'
    # Sanitize filename
    filename = re.sub(r'[^\w\-.]', '_', filename)
    filepath = os.path.join(SKILLS_DIR, filename)
    if os.path.isfile(filepath):
        raise FileExistsError(f"Skill file already exists: {filename}")
    os.makedirs(SKILLS_DIR, exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    logger.info(f"✨ Created new skill: {filename}")


def delete_skill(filename: str) -> None:
    """Deletes a skill file. Cannot delete _default.md."""
    if filename == '_default.md':
        raise ValueError("Cannot delete the default skill file.")
    filepath = os.path.join(SKILLS_DIR, filename)
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"Skill file not found: {filename}")
    os.remove(filepath)
    logger.info(f"🗑️ Deleted skill: {filename}")
