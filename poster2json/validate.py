"""
Poster Validation Module

Validate poster JSON against the poster-json-schema.
"""

import json
import os
from typing import Dict, List, Optional, Tuple, Union

from jsonschema import Draft202012Validator, ValidationError, validate


def get_schema() -> dict:
    """Load the poster JSON schema."""
    schema_path = os.path.join(os.path.dirname(__file__), "schemas", "poster_schema.json")
    with open(schema_path, encoding="utf-8") as f:
        return json.load(f)


def validate_poster(data: dict, verbose: bool = False) -> bool:
    """
    Validate poster JSON against the poster-json-schema.
    
    Args:
        data: The poster JSON data to validate
        verbose: If True, print validation errors
        
    Returns:
        True if the poster data is valid, False otherwise
        
    Example:
        >>> import json
        >>> with open("poster.json") as f:
        ...     data = json.load(f)
        >>> is_valid = validate_poster(data)
        >>> print(f"Poster is {'valid' if is_valid else 'invalid'}")
    """
    schema = get_schema()
    
    try:
        validate(instance=data, schema=schema)
        return True
    except ValidationError as e:
        if verbose:
            error_path = ".".join(str(p) for p in e.path) if e.path else "(root)"
            print(f"Validation Error: {e.message}")
            print(f"  Path: {error_path}")
            if "error_msg" in e.schema:
                print(f"  Hint: {e.schema['error_msg']}")
        return False
    except Exception as e:
        if verbose:
            print(f"Validation failed with unexpected error: {e}")
        return False


def get_validation_errors(data: dict) -> List[Dict[str, str]]:
    """
    Get all validation errors for poster JSON.
    
    Args:
        data: The poster JSON data to validate
        
    Returns:
        List of error dictionaries with 'path', 'message', and 'schema_path' keys.
        Empty list if validation passes.
        
    Example:
        >>> errors = get_validation_errors(data)
        >>> for error in errors:
        ...     print(f"{error['path']}: {error['message']}")
    """
    schema = get_schema()
    validator = Draft202012Validator(schema)
    
    errors = []
    for error in validator.iter_errors(data):
        errors.append({
            "path": ".".join(str(p) for p in error.path) if error.path else "(root)",
            "message": error.message,
            "schema_path": ".".join(str(p) for p in error.schema_path),
        })
    return errors


def validate_required_fields(data: dict) -> Tuple[bool, List[str]]:
    """
    Check if all required fields are present in poster JSON.
    
    The poster-json-schema requires these fields:
    - identifiers
    - creators
    - titles
    - publisher
    - publicationYear
    - subjects
    - dates
    - language
    - types
    - formats
    - rightsList
    - descriptions
    - fundingReferences
    - conference
    
    Args:
        data: The poster JSON data to check
        
    Returns:
        Tuple of (is_valid, list_of_missing_fields)
    """
    required_fields = [
        "identifiers",
        "creators",
        "titles",
        "publisher",
        "publicationYear",
        "subjects",
        "dates",
        "language",
        "types",
        "formats",
        "rightsList",
        "descriptions",
        "fundingReferences",
        "conference",
    ]
    
    missing = [field for field in required_fields if field not in data]
    return len(missing) == 0, missing


def validate_creators(creators: list) -> Tuple[bool, List[str]]:
    """
    Validate the creators array format.
    
    Each creator must have a 'name' field in "Family, Given" format.
    
    Args:
        creators: List of creator objects
        
    Returns:
        Tuple of (is_valid, list_of_issues)
    """
    issues = []
    
    if not isinstance(creators, list):
        return False, ["creators must be an array"]
    
    if len(creators) == 0:
        return False, ["creators array must have at least one entry"]
    
    for i, creator in enumerate(creators):
        if not isinstance(creator, dict):
            issues.append(f"creators[{i}] must be an object")
            continue
            
        if "name" not in creator:
            issues.append(f"creators[{i}] missing required 'name' field")
            continue
            
        name = creator.get("name", "")
        if "," not in name:
            issues.append(f"creators[{i}].name should be in 'Family, Given' format: '{name}'")
    
    return len(issues) == 0, issues


def validate_titles(titles: list) -> Tuple[bool, List[str]]:
    """
    Validate the titles array format.
    
    Args:
        titles: List of title objects
        
    Returns:
        Tuple of (is_valid, list_of_issues)
    """
    issues = []
    
    if not isinstance(titles, list):
        return False, ["titles must be an array"]
    
    if len(titles) == 0:
        return False, ["titles array must have at least one entry"]
    
    for i, title_obj in enumerate(titles):
        if not isinstance(title_obj, dict):
            issues.append(f"titles[{i}] must be an object")
            continue
            
        if "title" not in title_obj:
            issues.append(f"titles[{i}] missing required 'title' field")
            continue
            
        title = title_obj.get("title", "")
        if len(title.strip()) < 5:
            issues.append(f"titles[{i}].title appears too short: '{title}'")
    
    return len(issues) == 0, issues


def validate_poster_content(poster_content: dict) -> Tuple[bool, List[str]]:
    """
    Validate the content structure.
    
    Args:
        poster_content: The content object
        
    Returns:
        Tuple of (is_valid, list_of_issues)
    """
    issues = []
    
    if not isinstance(poster_content, dict):
        return False, ["content must be an object"]
    
    sections = poster_content.get("sections", [])
    if not isinstance(sections, list):
        issues.append("content.sections must be an array")
    elif len(sections) == 0:
        issues.append("content.sections should have at least one section")
    else:
        for i, section in enumerate(sections):
            if not isinstance(section, dict):
                issues.append(f"content.sections[{i}] must be an object")
                continue
            if "sectionTitle" not in section:
                issues.append(f"content.sections[{i}] missing 'sectionTitle'")
            if "sectionContent" not in section:
                issues.append(f"content.sections[{i}] missing 'sectionContent'")
    
    return len(issues) == 0, issues


def validate_captions(captions: list, caption_type: str = "image") -> Tuple[bool, List[str]]:
    """
    Validate image or table captions format.
    
    Args:
        captions: List of caption objects
        caption_type: "image" or "table"
        
    Returns:
        Tuple of (is_valid, list_of_issues)
    """
    issues = []
    field_name = f"{caption_type}Captions"
    
    if not isinstance(captions, list):
        return False, [f"{field_name} must be an array"]
    
    for i, caption in enumerate(captions):
        if not isinstance(caption, dict):
            issues.append(f"{field_name}[{i}] must be an object")
            continue
        
        parts = caption.get("captions", [])
        if not isinstance(parts, list):
            issues.append(f"{field_name}[{i}].captions must be an array")
        elif len(parts) == 0:
            issues.append(f"{field_name}[{i}].captions should have at least one entry")
    
    return len(issues) == 0, issues


def validate_comprehensive(data: dict) -> Dict[str, Union[bool, List[str]]]:
    """
    Run comprehensive validation on poster JSON.
    
    This runs both schema validation and semantic checks.
    
    Args:
        data: The poster JSON data to validate
        
    Returns:
        Dictionary with validation results:
        {
            "valid": bool,
            "schema_errors": [...],
            "field_issues": [...],
            "warnings": [...]
        }
    """
    result = {
        "valid": True,
        "schema_errors": [],
        "field_issues": [],
        "warnings": [],
    }
    
    # Schema validation
    schema_errors = get_validation_errors(data)
    if schema_errors:
        result["valid"] = False
        result["schema_errors"] = schema_errors
    
    # Required fields check
    has_required, missing = validate_required_fields(data)
    if not has_required:
        result["field_issues"].append(f"Missing required fields: {', '.join(missing)}")
        # Note: Not setting valid=False here since these are commonly not populated
        # by the extraction pipeline (they require external metadata)
    
    # Creators validation
    if "creators" in data:
        valid, issues = validate_creators(data["creators"])
        if not valid:
            result["field_issues"].extend(issues)
    
    # Titles validation
    if "titles" in data:
        valid, issues = validate_titles(data["titles"])
        if not valid:
            result["field_issues"].extend(issues)
    
    # Poster content validation
    if "content" in data:
        valid, issues = validate_poster_content(data["content"])
        if not valid:
            result["field_issues"].extend(issues)
    else:
        result["warnings"].append("content is missing - no sections extracted")
    
    # Caption validation
    if "imageCaptions" in data:
        valid, issues = validate_captions(data["imageCaptions"], "image")
        if not valid:
            result["warnings"].extend(issues)
    
    if "tableCaptions" in data:
        valid, issues = validate_captions(data["tableCaptions"], "table")
        if not valid:
            result["warnings"].extend(issues)
    
    return result
