from pathlib import Path
import json
from typing import Optional, Dict, Any


class ConfigurationManager:
    def __init__(self):
        self._config: Dict[str, Any] = {}
        self._working_dir: Optional[Path] = None

    def initialize(self, working_dir: Path) -> None:
        self._working_dir = working_dir
        self._load_configs()

    def _load_configs(self) -> None:
        """Load all configuration files"""
        config_files = {
            'source': self._working_dir / 'config' / 'source.json',
            'lib': self._working_dir / 'config' / 'lib.json',
            'ext': self._working_dir / 'config' / 'ext.json',
            'pkg': self._working_dir / 'config' / 'pkg.json',
            'pre-built': self._working_dir / 'config' / 'pre-built.json'
        }

        for key, path in config_files.items():
            if path.exists():
                with open(path, 'r', encoding='utf-8') as f:
                    self._config[key] = json.load(f)
            else:
                self._config[key] = {}

    def get_config(self, section: str, key: Optional[str] = None) -> Any:
        """Get configuration value"""
        if key is None:
            return self._config.get(section, {})
        return self._config.get(section, {}).get(key)

    def get_lib_config(self, lib_name: str, key: Optional[str] = None) -> Any:
        """Get library specific configuration"""
        libs = self._config.get('lib', {})
        if key is None:
            return libs.get(lib_name, {})
        return libs.get(lib_name, {}).get(key)

    def get_ext_config(self, ext_name: str, key: Optional[str] = None) -> Any:
        """Get extension specific configuration"""
        exts = self._config.get('ext', {})
        if key is None:
            return exts.get(ext_name, {})
        return exts.get(ext_name, {}).get(key)

    @property
    def working_dir(self) -> Path:
        """Get current working directory"""
        if self._working_dir is None:
            raise RuntimeError("ConfigurationManager not initialized")
        return self._working_dir
