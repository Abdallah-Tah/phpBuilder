from pathlib import Path
import os
from typing import Optional, List  # Added List
import shutil
import subprocess


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


def find_7zip_executable():
    """Finds the 7-Zip executable by checking PATH and common installation directories."""
    # 1. Check PATH
    seven_zip_exe = shutil.which('7z')
    if seven_zip_exe:
        return seven_zip_exe

    # 2. Check common installation paths (Windows)
    if os.name == 'nt':
        common_paths = [
            os.path.join(os.environ.get("ProgramFiles",
                         "C:\\Program Files"), "7-Zip", "7z.exe"),
            os.path.join(os.environ.get("ProgramFiles(x86)",
                         "C:\\Program Files (x86)"), "7-Zip", "7z.exe")
        ]
        for path in common_paths:
            if os.path.exists(path):
                return path
    return None


def _can_perl_load_strict(perl_exe_path: str) -> bool:
    """Checks if the given Perl executable can load the 'strict' module."""
    if not perl_exe_path or not os.path.exists(perl_exe_path):
        return False
    try:
        # Try to use strict and print a success message
        # Using a simple print to avoid issues with more complex Perl scripts
        process = subprocess.run(
            [perl_exe_path, "-Mstrict", "-e", "print 'Perl_strict_OK'"],
            capture_output=True, text=True, timeout=5, check=False
        )
        # Check if stdout contains the success message and return code is 0
        if process.returncode == 0 and "Perl_strict_OK" in process.stdout:
            return True
        # print(f"Debug: Perl strict check failed for {perl_exe_path}. RC: {process.returncode}, STDOUT: {process.stdout.strip()}, STDERR: {process.stderr.strip()}")
    except FileNotFoundError:
        # print(f"Debug: Perl executable not found at {perl_exe_path} during strict check.")
        pass  # Handled by os.path.exists above, but good to be safe
    except subprocess.TimeoutExpired:
        # print(f"Debug: Perl strict check timed out for {perl_exe_path}.")
        pass
    except Exception as e:
        # print(f"Debug: Exception during Perl strict check for {perl_exe_path}: {e}")
        pass  # Catch any other exception during the check
    return False


def find_perl_executable(project_base_path: Optional[Path] = None) -> Optional[str]:
    """Finds a suitable Perl executable.
       Prioritizes a bundled Strawberry Perl if project_base_path is provided.
       Then checks PATH and common installation directories.
       A suitable Perl executable must be able to load the 'strict' module.
    """
    candidate_paths_to_check: List[str] = []

    # 1. Check for a bundled Strawberry Perl if project_base_path is given
    if project_base_path:
        bundled_strawberry_perl_path = project_base_path / "pkgroot" / \
            "strawberry-perl-x86_64-win" / "perl" / "bin" / "perl.exe"
        if bundled_strawberry_perl_path.exists() and bundled_strawberry_perl_path.is_file():
            candidate_paths_to_check.append(str(bundled_strawberry_perl_path))
            # print(f"Debug: Added bundled Strawberry Perl to candidates: {bundled_strawberry_perl_path}")

    # 2. Check PATH next
    perl_in_path = shutil.which('perl')
    if perl_in_path:
        candidate_paths_to_check.append(perl_in_path)
        # print(f"Debug: Added Perl from PATH to candidates: {perl_in_path}")

    # 3. Check common system-wide installation paths (Windows)
    if os.name == 'nt':
        # Prioritize known distributions
        preferred_system_paths = [
            os.path.join(os.environ.get("SystemDrive", "C:"),
                         "Strawberry", "perl", "bin", "perl.exe"),
        ]
        user_profile = os.environ.get("USERPROFILE")
        if user_profile:
            scoop_perl_path = os.path.join(
                user_profile, "scoop", "apps", "perl", "current", "bin", "perl.exe")
            if os.path.exists(scoop_perl_path) and os.path.isfile(scoop_perl_path):
                preferred_system_paths.append(scoop_perl_path)

        # Add only existing and valid files from preferred_system_paths
        for psp_path_str in preferred_system_paths:
            if os.path.exists(psp_path_str) and os.path.isfile(psp_path_str):
                candidate_paths_to_check.append(psp_path_str)

        # Other common locations
        other_common_system_paths = [
            os.path.join(os.environ.get(
                "ProgramFiles", "C:\\\\Program Files"), "Git", "usr", "bin", "perl.exe"),
            os.path.join(os.environ.get(
                "ProgramFiles(x86)", "C:\\\\Program Files (x86)"), "Git", "usr", "bin", "perl.exe"),
            os.path.join(os.environ.get("LocalAppData", ""),
                         "Programs", "Git", "usr", "bin", "perl.exe"),
            os.path.join(os.environ.get("SystemDrive", "C:"),
                         "Perl64", "bin", "perl.exe"),
            os.path.join(os.environ.get("SystemDrive", "C:"),
                         "Perl", "bin", "perl.exe"),
            os.path.join(os.environ.get("ProgramFiles",
                         "C:\\\\Program Files"), "Perl", "bin", "perl.exe"),
            os.path.join(os.environ.get(
                "ProgramFiles(x86)", "C:\\\\Program Files (x86)"), "Perl", "bin", "perl.exe"),
        ]
        # Add only existing and valid files from other_common_system_paths
        for ocsp_path_str in other_common_system_paths:
            if os.path.exists(ocsp_path_str) and os.path.isfile(ocsp_path_str):
                candidate_paths_to_check.append(ocsp_path_str)

    # Deduplicate while preserving order (Python 3.7+)
    # Convert to Path objects for proper comparison if needed, then back to str if required by _can_perl_load_strict
    unique_candidate_paths = list(dict.fromkeys(candidate_paths_to_check))

    # print(f"Debug: Unique candidate Perl paths to check (in order): {unique_candidate_paths}")

    for perl_path_str in unique_candidate_paths:
        # print(f"Debug: Checking candidate Perl: {perl_path_str}")
        if _can_perl_load_strict(perl_path_str):
            # print(f"Debug: Found suitable Perl (passed strict check): {perl_path_str}")
            return perl_path_str
        # else:
            # print(f"Debug: Perl candidate failed strict check: {perl_path_str}")

    # print("Debug: No suitable Perl executable found after checking all candidates.")
    return None
