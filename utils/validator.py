from pathlib import Path
from typing import Any, Dict
from .exceptions import ValidationError


class Validator:
    @staticmethod
    def validate_php_version(version: str) -> bool:
        """Validate PHP version format"""
        import re
        if not re.match(r'^\d+\.\d+\.\d+$', version):
            raise ValidationError(f"Invalid PHP version format: {version}")
        return True

    @staticmethod
    def validate_extension_name(name: str) -> bool:
        """Validate PHP extension name"""
        import re
        if not re.match(r'^[a-zA-Z0-9_]+$', name):
            raise ValidationError(f"Invalid extension name: {name}")
        return True

    @staticmethod
    def validate_library_name(name: str) -> bool:
        """Validate library name"""
        import re
        if not re.match(r'^[a-zA-Z0-9_-]+$', name):
            raise ValidationError(f"Invalid library name: {name}")
        return True

    @staticmethod
    def validate_config(config: Dict[str, Any], required_fields: set[str]) -> bool:
        """Validate configuration has required fields"""
        missing = required_fields - set(config.keys())
        if missing:
            raise ValidationError(
                f"Missing required fields: {', '.join(missing)}")
        return True

    @staticmethod
    def validate_path(path: Path) -> bool:
        """Validate path exists and is accessible"""
        if not path.exists():
            raise ValidationError(f"Path does not exist: {path}")
        try:
            path.stat()
        except (OSError, PermissionError) as e:
            raise ValidationError(f"Path is not accessible: {path} ({str(e)})")
        return True
