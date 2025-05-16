from pathlib import Path
import os
from typing import Optional


class PathManager:
    def __init__(self):
        self._working_dir: Optional[Path] = None
        self._build_root: Optional[Path] = None
        self._source_root: Optional[Path] = None
        self._download_path: Optional[Path] = None

    def initialize(self, working_dir: Path) -> None:
        """Initialize path manager with working directory"""
        self._working_dir = working_dir
        self._build_root = working_dir / 'buildroot'
        self._source_root = working_dir / 'source'
        self._download_path = working_dir / 'downloads'

        # Ensure critical directories exist
        self._build_root.mkdir(parents=True, exist_ok=True)
        self._source_root.mkdir(parents=True, exist_ok=True)
        self._download_path.mkdir(parents=True, exist_ok=True)

    def get_build_path(self, *parts: str) -> Path:
        """Get path in build directory"""
        if self._build_root is None:
            raise RuntimeError("PathManager not initialized")
        return self._build_root.joinpath(*parts)

    def get_source_path(self, *parts: str) -> Path:
        """Get path in source directory"""
        if self._source_root is None:
            raise RuntimeError("PathManager not initialized")
        return self._source_root.joinpath(*parts)

    def get_download_path(self, *parts: str) -> Path:
        """Get path in downloads directory"""
        if self._download_path is None:
            raise RuntimeError("PathManager not initialized")
        return self._download_path.joinpath(*parts)

    def convert_path(self, path: str | Path) -> Path:
        """Convert any path to absolute Path object"""
        path = Path(path)
        if not path.is_absolute():
            if self._working_dir is None:
                raise RuntimeError("PathManager not initialized")
            path = self._working_dir / path
        return path

    def ensure_dir(self, path: str | Path) -> None:
        """Ensure directory exists"""
        path = self.convert_path(path)
        path.mkdir(parents=True, exist_ok=True)

    @property
    def working_dir(self) -> Path:
        """Get working directory"""
        if self._working_dir is None:
            raise RuntimeError("PathManager not initialized")
        return self._working_dir

    @property
    def build_root(self) -> Path:
        """Get build root directory"""
        if self._build_root is None:
            raise RuntimeError("PathManager not initialized")
        return self._build_root

    @property
    def source_root(self) -> Path:
        """Get source root directory"""
        if self._source_root is None:
            raise RuntimeError("PathManager not initialized")
        return self._source_root

    @property
    def download_path(self) -> Path:
        """Get downloads directory"""
        if self._download_path is None:
            raise RuntimeError("PathManager not initialized")
        return self._download_path
