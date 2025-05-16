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
from .command import CommandExecutor
from .file_operations import FileOperations


class PHPBuilder:
    def __init__(self, logger: Logger):
        self.logger = logger
        self.config_manager = ConfigurationManager()
        self.path_manager = PathManager()
        self.command_executor = CommandExecutor(logger)
        self.file_ops = FileOperations(logger)
        self.file_ops.set_command_executor(
            self.command_executor)  # Set command executor
        self.dependency_manager = None
        self._cleanup_paths: Set[Path] = set()

    def build(self, config: dict) -> None:
        """Main build process"""
        try:
            # Validate configuration
            Validator.validate_config(config, {'clone_dir', 'php_version'})
            Validator.validate_php_version(config['php_version'])

            # Check for essential command-line tools
            if not self.command_executor.is_command_available("git"):
                raise BuildError(
                    "Git is not installed or not found in PATH. Please install Git and ensure it is in your PATH.")

            # Setup paths
            clone_path = Path(config['clone_dir'])
            static_php_path = clone_path / "static-php-cli"

            # Clone or update repository
            if not static_php_path.exists():
                self.logger.info("📦 Cloning static-php-cli...")
                if not self.command_executor.run(
                    "git clone https://github.com/crazywhalecc/static-php-cli.git",
                    cwd=clone_path
                ):
                    # Check if the clone directory is empty or contains a failed git clone
                    if not any(static_php_path.iterdir()):  # Directory is empty
                        raise BuildError(
                            "Failed to clone repository. The target directory is empty. Check network connection and git installation.")
                    else:  # Directory is not empty, possibly a partial clone
                        raise BuildError(
                            "Failed to clone repository. The target directory is not empty but may contain an incomplete clone. Consider removing it and retrying.")
            else:
                self.logger.info("📂 static-php-cli already exists")
                # Just ensure directories exist
                for subdir in ["downloads", "source", "build"]:
                    (static_php_path / subdir).mkdir(parents=True, exist_ok=True)

            # Create and apply the Perl shim before any build operations
            self.file_ops.patch_perl_shim(static_php_path)

            # Also patch functions.php to properly quote commands
            self.file_ops.patch_functions_quote(static_php_path)

            # Set proper paths for micro source
            micro_source = static_php_path / "downloads" / "micro"
            micro_target = static_php_path / "source" / "php-src" / "sapi" / "micro"

            # Clean up micro directory if it exists
            if micro_target.exists():
                self.file_ops.remove_directory(micro_target)
            micro_target.mkdir(parents=True, exist_ok=True)

            # Copy micro source files if they exist
            if micro_source.exists():
                if self.file_ops.copy_directory(micro_source, micro_target):
                    self.logger.info("✅ Copied micro source files")

            # Run composer install/update
            composer_lock = static_php_path / "composer.lock"
            composer_cmd = (
                "composer install --ignore-platform-reqs" if composer_lock.exists()
                else "composer update --no-dev --prefer-dist"
            )
            if not self.command_executor.is_command_available("composer"):
                raise BuildError(
                    "Composer is not installed or not found in PATH. Please install Composer and ensure it is in your PATH.")
            if not self.command_executor.run(composer_cmd, cwd=static_php_path):
                raise BuildError("Composer install/update failed")

            # Download and extract dependencies
            try:
                if not self._prepare_dependencies(static_php_path, config):
                    raise BuildError("Failed to prepare dependencies")
            except Exception as e:
                self.logger.error(f"Dependency preparation failed: {str(e)}")
                raise BuildError("Failed to prepare dependencies") from e

            # Build PHP
            try:
                if not self._build_php(static_php_path, config):
                    raise BuildError("Failed to build PHP")
            except Exception as e:
                self.logger.error(f"PHP build failed: {str(e)}")
                raise BuildError("Failed to build PHP") from e

            # Verify build
            try:
                self._verify_build(static_php_path)
            except Exception as e:
                self.logger.error(f"Build verification failed: {str(e)}")
                raise BuildError("Failed to verify build") from e

        except (ValidationError, BuildError, DependencyError) as e:
            self.logger.error(str(e))
            raise

    def _prepare_dependencies(self, static_php_path: Path, config: dict) -> bool:
        """Prepare build dependencies with detailed logging"""
        extensions = self._get_extensions(config)
        libraries = self._get_libraries(config)
        image_libs = ["libjpeg", "libwebp", "freetype", "bzip2"]

        self.logger.info(
            f"Preparing dependencies for PHP version: {config.get('php_version')}")
        self.logger.info(f"static_php_path: {static_php_path}")
        self.logger.info(f"Libraries to download: {libraries}")
        self.logger.info(f"Image libs: {image_libs}")

        # Check for curl availability
        curl_ok = self.command_executor.is_command_available("curl")
        self.logger.info(f"curl available: {curl_ok}")
        if not curl_ok:
            self.logger.error(
                "cURL is not installed or not found in PATH. It is required to download PHP source and other dependencies.")
            return False

        self.logger.info(
            "📥 Downloading and extracting libraries one by one...")
        for lib in libraries:
            self.logger.info(f"Downloading {lib}...")
            rc, out, err = self.command_executor.run_with_output(
                f"php bin/spc download {lib}",
                cwd=static_php_path
            )
            self.logger.info(f"Download {lib} exit code: {rc}")
            if out:
                self.logger.info("STDOUT:\n" + "\n".join(out))
            if err:
                self.logger.error("STDERR:\n" + "\n".join(err))
            if rc != 0:
                self.logger.error(f"Failed to download {lib}")
                return False

            # Extract certain libraries that need it
            if lib in image_libs or lib in ["bzip2", "sqlsrv", "pdo_sqlsrv"]:
                self.logger.info(f"📦 Extracting {lib}...")
                result = self.file_ops.extract_library(static_php_path, lib)
                self.logger.info(f"extract_library({lib}) result: {result}")
                if not result:
                    self.logger.warning(
                        f"Failed to extract {lib}, skipping...")
                    continue

        # Handle PHP source specially
        php_version = config['php_version']
        php_tar = f"php-{php_version}.tar.xz"
        php_tar_path = static_php_path / "downloads" / php_tar
        php_src_path = static_php_path / "source" / "php-src"

        self.logger.info(f"PHP tar path: {php_tar_path}")
        self.logger.info(f"PHP source path: {php_src_path}")

        # Download PHP source if needed
        if not php_tar_path.exists():
            self.logger.info(f"Downloading PHP source: {php_tar}")
            rc, out, err = self.command_executor.run_with_output(
                f'curl -L -o "{php_tar_path}" https://www.php.net/distributions/{php_tar}'
            )
            self.logger.info(f"curl exit code: {rc}")
            if out:
                self.logger.info("STDOUT:\n" + "\n".join(out))
            if err:
                self.logger.error("STDERR:\n" + "\n".join(err))
            if rc != 0:
                self.logger.error("Failed to download PHP source")
                return False

        # Extract PHP source
        if php_src_path.exists():
            self.logger.info(
                f"Removing existing PHP source directory: {php_src_path}")
            self.file_ops.remove_directory(php_src_path)
        php_src_path.mkdir(parents=True, exist_ok=True)

        self.logger.info("📦 Extracting PHP source...")
        # Check for 7-Zip availability
        seven_zip_ok = self.command_executor.is_command_available("7z")
        self.logger.info(f"7z available: {seven_zip_ok}")
        if not seven_zip_ok:
            self.logger.error(
                "7-Zip (7z.exe) is not installed or not found in PATH. It is required to extract PHP source.")
            # Attempt to use tar as a fallback if on a system that might have it (not Windows by default)
            if os.name != 'nt':
                self.logger.info(
                    "Attempting to use 'tar' as a fallback for extraction.")
                extract_cmd_fallback = f'tar -xf "{php_tar_path}" -C "{php_src_path}" --strip-components=1'
                rc, out, err = self.command_executor.run_with_output(
                    extract_cmd_fallback, cwd=static_php_path)
                self.logger.info(f"tar fallback exit code: {rc}")
                if out:
                    self.logger.info("STDOUT:\n" + "\n".join(out))
                if err:
                    self.logger.error("STDERR:\n" + "\n".join(err))
                if rc != 0:
                    self.logger.error(
                        "Failed to extract PHP source using tar fallback.")
                    return False
            else:
                self.logger.error(
                    "No fallback extraction method available on Windows without 7-Zip.")
                return False
        else:
            extract_cmd = (
                f'"C:\\Program Files\\7-Zip\\7z.exe" x "{php_tar_path}" -so | '
                f'"C:\\Program Files\\7-Zip\\7z.exe" x -si -ttar -o"{php_src_path}"'
            )
            rc, out, err = self.command_executor.run_with_output(
                extract_cmd, cwd=static_php_path)
            self.logger.info(f"7z extract exit code: {rc}")
            if out:
                self.logger.info("STDOUT:\n" + "\n".join(out))
            if err:
                self.logger.error("STDERR:\n" + "\n".join(err))
            if rc != 0:
                self.logger.error("Failed to extract PHP source using 7-Zip")
                # Attempt to clean up potentially corrupted extraction
                if php_src_path.exists():
                    self.file_ops.remove_directory(php_src_path)
                    php_src_path.mkdir(parents=True, exist_ok=True)
                return False

        # Move files from nested directory if needed
        nested_path = php_src_path / f"php-{php_version}"
        if nested_path.exists():
            self.logger.info(
                f"Flattening nested PHP source directory: {nested_path}")
            for item in nested_path.iterdir():
                shutil.move(str(item), str(php_src_path))
            self.file_ops.remove_directory(nested_path)

        self.logger.info("Dependency preparation completed successfully.")
        return True

    def _build_php(self, static_php_path: Path, config: dict) -> bool:
        """Build PHP with specified configuration"""
        extensions = self._get_extensions(config)
        ext_str = ",".join(sorted(set(extensions)))

        # Set concurrency for faster builds
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
        """Verify the build was successful"""
        binary = static_php_path / "buildroot" / "bin" / "php.exe"
        if binary.exists():
            self.logger.info("✅ Verifying built extensions...")
            self.command_executor.run(f'"{binary}" -m', cwd=static_php_path)
            self.logger.info("✅ Build completed successfully")
        else:
            raise BuildError("❌ Build failed — php.exe not found")

    def _get_extensions(self, config: dict) -> List[str]:
        """Get list of extensions to build"""
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
        """Get list of libraries to build"""
        libraries = [
            "php-src", "zlib", "libxml2", "openssl", "sqlite", "unixodbc",
            "micro", "libpng", "bzip2", "libssh2", "nghttp2", "curl", "xz",
            "libzip", "libiconv-win", "libjpeg", "freetype", "libwebp"
        ]

        if config.get('sqlsrv', False):
            libraries.extend(["sqlsrv", "pdo_sqlsrv"])

        return libraries
