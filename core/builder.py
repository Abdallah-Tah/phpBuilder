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
        self.file_ops.set_command_executor(self.command_executor)
        self.dependency_manager = None
        self._cleanup_paths: Set[Path] = set()
        self.seven_zip_exe: Optional[str] = None

    def extract_tar_archive(self, tar_path: Path, target_path: Path, static_php_path: Path) -> bool:
        if not self.seven_zip_exe or not Path(self.seven_zip_exe).exists():
            self.logger.error("7-Zip (7z.exe) not found or path is invalid.")
            return False

        target_path.mkdir(parents=True, exist_ok=True)
        extract_cmd = f'"{self.seven_zip_exe}" x -so "{tar_path}" | tar -xf - -C "{target_path}" --strip-components=1'
        rc, out, err = self.command_executor.run_with_output(
            extract_cmd, cwd=static_php_path)
        self.logger.info(f"Extract {tar_path.name} exit code: {rc}")
        if out:
            self.logger.info("STDOUT:\n" + "\n".join(out))
        if err:
            self.logger.error("STDERR:\n" + "\n".join(err))
        return rc == 0

    def build(self, config: dict) -> None:
        try:
            Validator.validate_config(
                config, {'clone_dir', 'php_version', 'seven_zip_exe'})
            Validator.validate_php_version(config['php_version'])
            self.seven_zip_exe = config['seven_zip_exe']

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

            micro_source = static_php_path / "downloads" / "micro"
            micro_target = static_php_path / "source" / "php-src" / "sapi" / "micro"
            if micro_target.exists():
                self.file_ops.remove_directory(micro_target)
            micro_target.mkdir(parents=True, exist_ok=True)

            if micro_source.exists():
                if self.file_ops.copy_directory(micro_source, micro_target):
                    self.logger.info("✅ Copied micro source files")

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

    def _download_file(self, url: str, output_path: Path) -> bool:
        """Download a file using available tools (curl or urllib)."""
        try:
            if self.command_executor.is_command_available("curl"):
                self.logger.info(f"🌐 Downloading with curl: {url}")
                result = subprocess.run(
                    ["curl", "-L", "-f", url, "-o", str(output_path)], check=False)
                return result.returncode == 0
            else:
                self.logger.info(f"🌐 Downloading with urllib: {url}")
                import urllib.request
                urllib.request.urlretrieve(url, str(output_path))
                return True
        except Exception as e:
            self.logger.error(f"❌ Download failed: {e}")
            return False

    def _try_download_php_src(self, php_ver: str, download_dir: Path) -> Optional[Path]:
        """Try downloading PHP source from different URLs and formats."""
        formats = [".tar.xz", ".tar.gz"]
        urls = [
            f"https://www.php.net/distributions/php-{php_ver}",
            f"https://www.php.net/distributions/php-{php_ver}",
            # Additional mirror
            f"https://downloads.php.net/~patrickallaert/php-{php_ver}"
        ]

        for base_url in urls:
            for fmt in formats:
                url = base_url + fmt
                output_path = download_dir / f"php-{php_ver}{fmt}"

                if output_path.exists():
                    self.logger.info(
                        f"📦 Using existing download: {output_path}")
                    return output_path

                if self._download_file(url, output_path):
                    if output_path.exists() and output_path.stat().st_size > 0:
                        return output_path
                    else:
                        self.logger.warning(
                            f"⚠️ Download seemed successful but file is missing or empty: {output_path}")

        return None

    def _prepare_dependencies(self, static_php_path: Path, config: dict) -> bool:
        extensions = self._get_extensions(config)
        libraries = self._get_libraries(config)
        download_dir = static_php_path / "downloads"
        download_dir.mkdir(parents=True, exist_ok=True)

        for lib in libraries:
            self.logger.info(f"📥 Downloading {lib}...")
            rc, out, err = self.command_executor.run_with_output(
                f"php bin/spc download {lib}", cwd=static_php_path)

            matches = list(download_dir.glob(f"{lib}.*"))

            if rc != 0 or not matches:
                self.logger.warning(
                    f"⚠️ spc download failed for {lib}, trying manual fallback...")

                # Manual fallbacks for specific libraries
                if lib == "php-src":
                    php_ver = config['php_version']
                    manual_path = self._try_download_php_src(
                        php_ver, download_dir)
                    matches = [manual_path] if manual_path else []
                elif lib == "zlib":
                    zlib_ver = "1.3.1"  # Latest stable version as of 2024
                    output_path = download_dir / f"zlib-{zlib_ver}.tar.xz"
                    if self._download_file(f"https://zlib.net/zlib-{zlib_ver}.tar.xz", output_path):
                        matches = [output_path]
                    else:
                        # Try backup URL
                        backup_url = f"https://github.com/madler/zlib/releases/download/v{zlib_ver}/zlib-{zlib_ver}.tar.xz"
                        if self._download_file(backup_url, output_path):
                            matches = [output_path]

            if matches and matches[0]:
                lib_path = matches[0]
                extract_path = static_php_path / "source" / lib
                self.logger.info(f"📦 Extracting {lib} from {lib_path.name}...")
                if not self.extract_tar_archive(lib_path, extract_path, static_php_path):
                    self.logger.error(f"❌ Failed to extract {lib}")
                    return False
            else:
                self.logger.error(f"❌ No downloaded archive found for {lib}")
                return False

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

    def _run_composer_elevated(self, static_php_path: Path) -> bool:
        composer_lock = static_php_path / "composer.lock"
        composer_cmd = (
            "composer install --ignore-platform-reqs --no-scripts" if composer_lock.exists()
            else "composer update --no-dev --prefer-dist --no-scripts"
        )

        if not self.command_executor.is_command_available("composer"):
            raise BuildError("Composer is not installed or not found in PATH.")

        self.logger.info("Attempting composer install with --no-plugins...")
        if self.command_executor.run(f"{composer_cmd} --no-plugins", cwd=static_php_path):
            return True

        self.logger.info(
            "Regular composer install failed. Attempting with elevated privileges...")
        ps_cmd = composer_cmd.replace('"', '`"')
        elevated_cmd = (
            f'powershell -Command "Start-Process -Verb RunAs -FilePath composer '
            f'-ArgumentList \'{ps_cmd} --no-plugins\' -WorkingDirectory \'{static_php_path}\' -Wait"'
        )

        try:
            if self.command_executor.run(elevated_cmd):
                self.logger.info(
                    "✅ Composer install completed with elevated privileges")
                return True
            else:
                self.logger.error(
                    "❌ Composer install failed even with elevated privileges")
                return False
        except Exception as e:
            self.logger.error(f"❌ Error during elevated composer install: {e}")
            return False
