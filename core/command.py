from pathlib import Path
import os
import shutil
import subprocess
from typing import List, Optional, Set
from utils.config_manager import ConfigurationManager
from utils.path_manager import PathManager
from utils.exceptions import BuildError, ValidationError, DependencyError
from utils.validator import Validator
from utils.logger import Logger
from .dependency_manager import DependencyManager
from .executor import CommandExecutor
from .file_operations import FileOperations


class PHPBuilder:
    def __init__(self, logger: Logger):
        self.logger = logger
        self.config_manager = ConfigurationManager()
        self.path_manager = PathManager()
        self.command_executor = CommandExecutor(logger)
        self.file_ops = FileOperations(logger)
        self.file_ops.set_command_executor(
            self.command_executor)
        self.dependency_manager = None
        self._cleanup_paths: Set[Path] = set()
        self.seven_zip_exe: Optional[str] = None

    def extract_tar_archive(self, tar_path: Path, target_path: Path, static_php_path: Path) -> bool:
        """Extract a tar archive using 7-Zip and tar. Handles .tar.xz files in two steps."""
        if not self.seven_zip_exe or not Path(self.seven_zip_exe).exists():
            self.logger.error("7-Zip (7z.exe) not found or path is invalid.")
            return False

        # Create target directory first
        self.logger.info(f"📁 Creating directory {target_path}")
        target_path.mkdir(parents=True, exist_ok=True)

        # Ensure all paths are absolute and properly formatted
        tar_path = Path(tar_path).resolve()
        target_path = Path(target_path).resolve()

        is_xz = tar_path.suffix.lower() == '.xz' and tar_path.stem.lower().endswith('.tar')

        if is_xz:
            # Step 1: Extract .tar from .tar.xz
            self.logger.info(f"📦 Extracting .tar from {tar_path.name}")
            intermediate_tar = tar_path.parent / tar_path.stem
            # First extract the .tar file from .tar.xz without -so
            extract_xz_cmd = f'"{self.seven_zip_exe}" x "{tar_path}" -o"{tar_path.parent}"'

            rc, out, err = self.command_executor.run_with_output(
                extract_xz_cmd, cwd=static_php_path)
            if rc != 0:
                self.logger.error(
                    f"❌ Failed to extract .tar from {tar_path.name}")
                if err:
                    self.logger.error("STDERR:\n" + "\n".join(err))
                return False

            tar_path = intermediate_tar

        # Now extract from .tar using streaming
        # Build the extraction command with properly escaped paths
        extract_cmd = f'"{self.seven_zip_exe}" x "{tar_path}" -so | tar -xf - -C "{target_path}" --strip-components=1'

        # Log what we're about to do
        self.logger.info(f"📦 Extracting {tar_path.name} to {target_path}")

        # Execute the command and capture output
        rc, out, err = self.command_executor.run_with_output(
            extract_cmd, cwd=static_php_path)

        self.logger.info(f"Extract exit code: {rc}")

        if out:
            self.logger.info("STDOUT:\n" + "\n".join(out))
        if err:
            self.logger.error("STDERR:\n" + "\n".join(err))

        # Clean up intermediate .tar file if we extracted from .tar.xz
        if is_xz and tar_path.exists():
            try:
                tar_path.unlink()
                self.logger.info(
                    f"🗑️ Cleaned up intermediate file {tar_path.name}")
            except Exception as e:
                self.logger.error(
                    f"Failed to clean up {tar_path.name}: {str(e)}")

        return rc == 0

    def _setup_environment(self) -> None:
        """Set up required environment variables."""
        os.environ["SPC_CONCURRENCY"] = "4"
        os.environ["SPC_PERL"] = r"C:\Program Files\Git\usr\bin\perl.exe"
        self.logger.info("✅ Environment variables set")

    def _manual_library_setup(self, static_php_path: Path) -> bool:
        """Handle manual extraction of specific libraries."""
        libraries = {
            "libwebp": "libwebp-1.3.2.tar.gz",
            "libjpeg": "libjpeg-turbo-libjpeg-turbo-3.1.0-0-g20ade4d.tar.gz",
            "freetype": "freetype-2.13.2.tar.gz"
        }

        for lib_name, archive_name in libraries.items():
            self.logger.info(f"📦 Setting up {lib_name}...")
            source_dir = static_php_path / "source" / lib_name
            archive_path = static_php_path / "downloads" / archive_name

            # Create directory if it doesn't exist
            source_dir.mkdir(parents=True, exist_ok=True)

            # Extract the archive
            if archive_path.exists():
                if not self.extract_tar_archive(archive_path, source_dir, static_php_path):
                    self.logger.error(f"❌ Failed to extract {lib_name}")
                    return False
                self.logger.info(f"✅ {lib_name} extracted successfully")
            else:
                self.logger.error(f"❌ Archive not found: {archive_name}")
                return False

        return True

    def build(self, config: dict) -> None:
        try:
            Validator.validate_config(
                config, {'clone_dir', 'php_version', 'seven_zip_exe'})
            Validator.validate_php_version(config['php_version'])
            self.seven_zip_exe = config['seven_zip_exe']

            # Set up environment variables
            self._setup_environment()

            if not self.command_executor.is_command_available("git"):
                raise BuildError("Git is not installed or not found in PATH.")

            clone_path = Path(config['clone_dir'])
            static_php_path = clone_path / "static-php-cli"

            if not static_php_path.exists():
                self.logger.info("📦 Cloning static-php-cli...")
                if not self.command_executor.run(
                    "git clone https://github.com/crazywhalecc/static-php-cli.git",
                        cwd=clone_path):
                    raise BuildError("Failed to clone static-php-cli.")
            else:
                self.logger.info("📂 static-php-cli already exists")
                for subdir in ["downloads", "source", "build"]:
                    (static_php_path / subdir).mkdir(parents=True, exist_ok=True)

            self.file_ops.patch_perl_shim(static_php_path)
            self.file_ops.patch_functions_quote(static_php_path)

            # Handle manual library setup
            if not self._manual_library_setup(static_php_path):
                raise BuildError("Failed to set up manual libraries")

            micro_source = static_php_path / "downloads" / "micro"
            micro_target = static_php_path / "source" / "php-src" / "sapi" / "micro"

            if micro_target.exists():
                self.file_ops.remove_directory(micro_target)
            if micro_source.exists():
                micro_target.mkdir(parents=True, exist_ok=True)
                if self.file_ops.copy_directory(micro_source, micro_target):
                    self.logger.info("✅ Copied micro source files")

            # Run composer with elevated privileges if needed
            if not self._run_composer_elevated(static_php_path):
                raise BuildError(
                    "Composer installation failed. Please try running with administrator privileges.")

            if not self._prepare_dependencies(static_php_path, config):
                raise BuildError("Failed to prepare dependencies")

            if not self._build_php(static_php_path, config):
                raise BuildError("Failed to build PHP")

            self._verify_build(static_php_path)

        except (ValidationError, BuildError, DependencyError) as e:
            self.logger.error(str(e))
            raise

    def _find_library_file(self, downloads_dir: Path, lib_name: str, expected_files: list) -> Optional[Path]:
        """Find the actual library file in downloads directory."""
        # First check if any of the expected files exist
        for file in expected_files:
            file_path = downloads_dir / file
            if file_path.exists():
                return file_path

        # Then check common patterns
        patterns = [
            f"{lib_name}*.tar.gz",
            f"{lib_name}*.tar.xz",
            f"{lib_name}*.tgz",
            f"v*.tar.gz",  # For version-prefixed archives
            f"v*.tar.xz"
        ]

        for pattern in patterns:
            matches = list(downloads_dir.glob(pattern))
            if matches:
                return matches[0]

        return None

    def _ensure_directory(self, path: Path) -> None:
        """Ensure directory exists, create if it doesn't."""
        if not path.exists():
            self.logger.info(f"📁 Creating directory {path}")
            path.mkdir(parents=True, exist_ok=True)

    def _prepare_dependencies(self, static_php_path: Path, config: dict) -> bool:
        """Prepare all required dependencies by downloading and extracting them."""
        extensions = self._get_extensions(config)
        libraries = self._get_libraries(config)

        # First verify all required libraries
        required_libraries = {
            "php-src": ["php-8.4.7.tar.xz"],
            "zlib": ["zlib-1.3.1.tar.gz"],
            "libxml2": ["v2.12.5.tar.gz"],
            "openssl": ["openssl-3.5.0.tar.gz"],
            "sqlite": ["sqlite-autoconf-3450200.tar.gz"],
            "unixodbc": ["unixODBC-2.3.12.tar.gz"],
            "micro": ["micro"],  # Directory
            "libpng": ["libpng"],  # Directory
            "bzip2": ["bzip2-1.0.8.tar.gz"],
            "libssh2": ["libssh2-1.11.1.tar.gz"],
            "nghttp2": ["nghttp2-1.65.0.tar.xz"],
            "curl": ["curl-8.13.0.tar.xz"],
            "xz": ["xz-5.8.1.tar.xz"],
            "libzip": ["libzip-1.11.3.tar.xz"],
            "libiconv-win": ["libiconv-win"],  # Directory
            "libjpeg": ["libjpeg-turbo-libjpeg-turbo-3.1.0-0-g20ade4d.tar.gz"],
            "freetype": ["freetype"],  # Directory
            "libwebp": ["v1.3.2.tar.gz"],
            "sqlsrv": ["sqlsrv.tgz"],
            "pdo_sqlsrv": ["pdo_sqlsrv.tgz"]
        }

        downloads_dir = static_php_path / "downloads"
        source_dir = static_php_path / "source"

        # Ensure base directories exist
        self._ensure_directory(downloads_dir)
        self._ensure_directory(source_dir)

        # Process each library
        for lib in libraries:
            lib_source_dir = source_dir / lib

            # Create source directory first
            self.logger.info(f"📁 Setting up directory for {lib}")
            self._ensure_directory(lib_source_dir)

            # Skip if it's a directory-based dependency and already exists
            if lib in ["micro", "libpng", "freetype", "libiconv-win"]:
                if any(lib_source_dir.iterdir()):
                    self.logger.info(f"📁 {lib} directory already populated")
                    continue

            # Download the library if needed
            self.logger.info(f"📥 Downloading {lib}...")
            rc, out, err = self.command_executor.run_with_output(
                f"php bin/spc download {lib}", cwd=static_php_path)

            if rc != 0:
                self.logger.error(f"❌ Failed to download {lib}")
                if err:
                    self.logger.error("Error: " + "\\n".join(err))
                return False

            # If the library is php-src, assume 'spc download' handles its extraction and source directory preparation.
            # Skip the script's manual finding and extraction steps for php-src.
            if lib == "php-src":
                self.logger.info(
                    f"ℹ️ For {lib}, 'spc download' was called. Assuming it also prepared the source directory: {lib_source_dir}.")
                # Optional: Add a check to see if lib_source_dir is populated as expected.
                if not (lib_source_dir.exists() and any(lib_source_dir.iterdir())):
                    self.logger.warning(
                        f"⚠️ Warning: Source directory {lib_source_dir} for {lib} does not appear populated after 'spc download'. The build might still fail.")
                # else:
                #    self.logger.info(f"👍 Source directory {lib_source_dir} for {lib} appears populated after 'spc download'.")
                continue  # Proceed to the next library, skipping manual extraction for php-src

            # Find the actual library file
            lib_file = self._find_library_file(
                downloads_dir, lib, required_libraries.get(lib, []))
            if not lib_file:
                self.logger.error(f"❌ Could not find archive for {lib}")
                return False

            # Extract if it's an archive
            if lib_file.is_file():
                # Ensure target directory exists and is empty
                if any(lib_source_dir.iterdir()):
                    self.logger.info(
                        f"🗑️ Cleaning {lib} directory before extraction")
                    self.file_ops.remove_directory(lib_source_dir)
                    lib_source_dir.mkdir(parents=True)

                if not self.extract_tar_archive(lib_file, lib_source_dir, static_php_path):
                    self.logger.error(f"❌ Failed to extract {lib}")
                    return False
                self.logger.info(f"✅ {lib} extracted successfully")

        return True

    def _build_php(self, static_php_path: Path, config: dict) -> bool:
        extensions = self._get_extensions(config)
        ext_str = ",".join(sorted(set(extensions)))
        os.environ["SPC_CONCURRENCY"] = "4"
        self.logger.info(
            f"🏗️ Building PHP {config['php_version']} with extensions...")
        build_cmd = f'php bin/spc build "{ext_str}" --build-cli'
        if not self.command_executor.run(build_cmd, cwd=static_php_path):
            self.logger.error("❌ Build failed")
            self.logger.info("🔍 Retrying build with debug output...")
            return self.command_executor.run(f"{build_cmd} --debug", cwd=static_php_path)
        return True

    def _verify_build(self, static_php_path: Path) -> None:
        binary = static_php_path / "buildroot" / "bin" / "php.exe"
        if binary.exists():
            self.logger.info("✅ Verifying built extensions...")
            self.command_executor.run(f'"{binary}" -m', cwd=static_php_path)
            self.logger.info("✅ Build completed successfully")
        else:
            raise BuildError("❌ Build failed — php.exe not found")

    def _get_extensions(self, config: dict) -> List[str]:
        extensions = [
            "bcmath", "bz2", "ctype", "curl", "dom", "fileinfo", "filter",
            "gd", "iconv", "mbstring", "opcache", "openssl", "pdo",
            "pdo_sqlite", "phar", "session", "simplexml", "sockets",
            "sqlite3", "tokenizer", "xml", "zip", "zlib", "soap"
        ]
        if config.get('mysql', False):
            extensions.extend(["pdo_mysql", "mysqli", "mysqlnd"])
        if config.get('sqlsrv', False):
            extensions.extend(["sqlsrv", "pdo_sqlsrv"])
        return extensions

    def _get_libraries(self, config: dict) -> List[str]:
        libraries = [
            "php-src", "zlib", "libxml2", "openssl", "sqlite", "unixodbc",
            "micro", "libpng", "bzip2", "libssh2", "nghttp2", "curl", "xz",
            "libzip", "libiconv-win", "libjpeg", "freetype", "libwebp"
        ]
        if config.get('sqlsrv', False):
            libraries.extend(["sqlsrv", "pdo_sqlsrv"])
        return libraries
