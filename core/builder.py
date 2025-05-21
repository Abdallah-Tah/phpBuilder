from pathlib import Path
import os
import shutil
import subprocess
import time
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

    def _find_main_source_dir(self, temp_dir: Path, lib_name: str) -> Path:
        """Find the main source directory in extracted contents"""
        contents = list(temp_dir.iterdir())
        for item in contents:
            if item.is_dir():
                if item.name == lib_name or item.name.startswith(f"{lib_name}-"):
                    return item
        dirs = [d for d in contents if d.is_dir()]
        if len(dirs) == 1:
            return dirs[0]
        return temp_dir

    def extract_tar_archive(self, tar_path: Path, target_path: Path) -> bool: # Removed static_php_path
        self.logger.info(f"📦 Extracting {tar_path.name} to {target_path}...")
        target_path.mkdir(parents=True, exist_ok=True)
        temp_extract_dir = target_path.parent / f"__temp_extract_{target_path.name}"
        try:
            if temp_extract_dir.exists():
                shutil.rmtree(temp_extract_dir)
            temp_extract_dir.mkdir(parents=True, exist_ok=True)

            if tar_path.name.endswith(('.tar.gz', '.tgz')):
                import tarfile
                with tarfile.open(tar_path, 'r:gz') as tar:
                    tar.extractall(path=temp_extract_dir)
            elif tar_path.name.endswith('.tar.xz'):
                import tarfile
                with tarfile.open(tar_path, 'r:xz') as tar:
                    tar.extractall(path=temp_extract_dir)
            elif tar_path.name.endswith('.tar.bz2'):
                import tarfile
                with tarfile.open(tar_path, 'r:bz2') as tar:
                    tar.extractall(path=temp_extract_dir)
            elif tar_path.name.endswith('.zip'):
                import zipfile
                with zipfile.ZipFile(tar_path, 'r') as zip_ref:
                    zip_ref.extractall(temp_extract_dir)
            else:
                self.logger.error(f"Unsupported archive format: {tar_path.name}")
                return False

            lib_name = target_path.name
            source_dir_in_archive = self._find_main_source_dir(temp_extract_dir, lib_name)
            self.logger.info(f"Found source directory in archive: {source_dir_in_archive}")

            if target_path.exists():
                shutil.rmtree(target_path)
            target_path.mkdir(parents=True, exist_ok=True)

            for item in source_dir_in_archive.iterdir():
                src_item_path = source_dir_in_archive / item.name
                dest_item_path = target_path / item.name
                if src_item_path.is_dir():
                    shutil.copytree(src_item_path, dest_item_path, dirs_exist_ok=True)
                else:
                    shutil.copy2(src_item_path, dest_item_path)
            self.logger.info(f"✅ Successfully extracted {tar_path.name} to {target_path}")
            return True
        except Exception as e:
            self.logger.error(f"❌ Extraction error for {tar_path.name}: {str(e)}")
            return False
        finally:
            if temp_extract_dir.exists():
                shutil.rmtree(temp_extract_dir)

    def build(self, config: dict) -> None:
        try:
            Validator.validate_config(config, {'clone_dir', 'php_version'}) # Removed seven_zip_exe
            Validator.validate_php_version(config['php_version'])
            # self.seven_zip_exe assignment removed

            if not self.command_executor.is_command_available("git"):
                raise BuildError("Git is not installed or not found in PATH.")

            clone_path = Path(config['clone_dir'])
            static_php_path = clone_path / "static-php-cli"

            # Clone repository if needed
            if not static_php_path.exists():
                self.logger.info("📦 Cloning static-php-cli...")
                if not self.command_executor.run(
                    "git clone https://github.com/crazywhalecc/static-php-cli.git",
                        cwd=clone_path):
                    raise BuildError("Failed to clone static-php-cli.")
            else:
                self.logger.info("📂 static-php-cli already exists")

            # Create necessary directories
            for subdir in ["downloads", "source", "build"]:
                (static_php_path / subdir).mkdir(parents=True, exist_ok=True)

            # Run composer install and doctor fix together
            if not self._run_composer_elevated(static_php_path):
                raise BuildError(
                    "Composer installation failed. Please try running with administrator privileges.")

            doctor_cmd = "php bin/spc doctor --auto-fix"
            self.logger.info(
                "🔧 Running 'php bin/spc doctor --auto-fix' to fix macro and other requirements...")
            if not self.command_executor.run(doctor_cmd, cwd=static_php_path):
                raise BuildError("Failed to run doctor fix")

            # Download dependencies
            if not self._prepare_dependencies(static_php_path, config):
                raise BuildError("Failed to prepare dependencies")

            # Removed call to extract_sources.main(str(static_php_path))

            # Handle patches and micro setup
            self.file_ops.patch_perl_shim(static_php_path)
            self.file_ops.patch_functions_quote(static_php_path)

            micro_source = static_php_path / "downloads" / "micro"
            micro_target = static_php_path / "source" / "micro"
            sapi_micro = static_php_path / "source" / "php-src" / "sapi" / "micro"

            # Handle micro files
            if micro_target.exists():
                self.file_ops.remove_directory(micro_target)
            micro_target.mkdir(parents=True, exist_ok=True)
            if sapi_micro.exists():
                self.file_ops.remove_directory(sapi_micro)
            sapi_micro.mkdir(parents=True, exist_ok=True)

            if micro_source.exists():
                # Copy micro files
                if self.file_ops.copy_directory(micro_source, micro_target):
                    self.logger.info(
                        "✅ Copied micro source files to source/micro")
                    if self.file_ops.copy_directory(micro_source, sapi_micro):
                        self.logger.info(
                            "✅ Copied micro source files to sapi/micro")
                    else:
                        self.logger.error(
                            "❌ Failed to copy micro files to sapi/micro")
                        raise BuildError(
                            "Failed to copy micro files to sapi location")
                else:
                    self.logger.error(
                        "❌ Failed to copy micro files to source/micro")
                    raise BuildError("Failed to copy micro files")

            # Finally run the build
            if not self._build_php(static_php_path, config):
                raise BuildError("Failed to build PHP")

            self._verify_build(static_php_path)

        except (ValidationError, BuildError, DependencyError) as e:
            self.logger.error(str(e))
            raise

    def _download_file(self, url: str, output_path: Path) -> bool:
        """Download a file using available tools (curl or urllib)."""
        max_retries = 3
        retry_count = 0

        while retry_count < max_retries:
            try:
                if self.command_executor.is_command_available("curl"):
                    self.logger.info(f"🌐 Downloading with curl: {url}")
                    # Use --retry option with curl
                    result = subprocess.run(
                        ["curl", "-L", "-f", "--retry", "3", "--retry-delay", "2",
                         "--connect-timeout", "30", url, "-o", str(output_path)],
                        check=False)
                    if result.returncode == 0:
                        if output_path.exists() and output_path.stat().st_size > 0:
                            return True
                        else:
                            self.logger.warning(
                                "Download succeeded but file is empty")
                else:
                    self.logger.info(f"🌐 Downloading with urllib: {url}")
                    import urllib.request
                    opener = urllib.request.build_opener()
                    opener.addheaders = [('User-Agent', 'Mozilla/5.0')]
                    urllib.request.install_opener(opener)
                    urllib.request.urlretrieve(url, str(output_path))
                    if output_path.exists() and output_path.stat().st_size > 0:
                        return True
                    else:
                        self.logger.warning(
                            "Download succeeded but file is empty")

            except Exception as e:
                self.logger.warning(
                    f"⚠️ Download attempt {retry_count + 1} failed: {e}")
                if output_path.exists():
                    output_path.unlink()  # Remove failed download

            retry_count += 1
            if retry_count < max_retries:
                self.logger.info(
                    f"Retrying download in 2 seconds... (Attempt {retry_count + 1}/{max_retries})")
                time.sleep(2)

        self.logger.error(f"❌ Download failed after {max_retries} attempts")
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

    def _get_library_version(self, lib: str) -> tuple[str, dict[str, str]]:
        """Get the latest stable version and download URLs for a library."""
        versions = {
            "zlib": ("1.3.1", {
                "main": "https://zlib.net/zlib-{ver}.tar.xz",
                "backup": "https://github.com/madler/zlib/releases/download/v{ver}/zlib-{ver}.tar.xz"
            }),
            "libxml2": ("2.12.5", {
                "main": "https://download.gnome.org/sources/libxml2/{major_ver}/libxml2-{ver}.tar.xz",
                "backup": "https://github.com/GNOME/libxml2/releases/download/v{ver}/libxml2-{ver}.tar.xz",
                "source": "https://github.com/GNOME/libxml2/archive/refs/tags/v{ver}.tar.gz"
            }),
            "openssl": ("3.2.1", {
                "main": "https://www.openssl.org/source/openssl-{ver}.tar.gz",
                "backup": "https://github.com/openssl/openssl/releases/download/openssl-{ver}/openssl-{ver}.tar.gz",
                "archive": "https://github.com/openssl/openssl/archive/refs/tags/openssl-{ver}.tar.gz"
            }),
            "sqlite": ("3450100", {  # Version 3.45.1
                "main": "https://www.sqlite.org/2024/sqlite-autoconf-{ver}.tar.gz",
                "backup": "https://www.sqlite.org/2024/sqlite-autoconf-{ver}.tar.gz"
            }),
            "bzip2": ("1.0.8", {
                "main": "https://sourceware.org/pub/bzip2/bzip2-{ver}.tar.gz",
                "backup": "https://github.com/libarchive/bzip2/archive/refs/tags/bzip2-{ver}.tar.gz"
            }),
            "libpng": ("1.6.43", {
                "main": "https://download.sourceforge.net/libpng/libpng-{ver}.tar.xz",
                "backup": "https://github.com/glennrp/libpng/archive/refs/tags/v{ver}.tar.gz"
            }),
            "libjpeg": ("9f", {
                "main": "https://www.ijg.org/files/jpegsrc.v{ver}.tar.gz",
                "backup": "https://www.ijg.org/files/jpegsrc.v{ver}.tar.gz"
            }),
            "freetype": ("2.13.2", {
                "main": "https://download.savannah.gnu.org/releases/freetype/freetype-{ver}.tar.xz",
                "backup": "https://github.com/freetype/freetype/archive/refs/tags/VER-{ver}.tar.gz"
            }),
            "libwebp": ("1.3.2", {
                "main": "https://storage.googleapis.com/downloads.webmproject.org/releases/webp/libwebp-{ver}.tar.gz",
                "backup": "https://github.com/webmproject/libwebp/archive/refs/tags/v{ver}.tar.gz"
            }),
            "curl": ("8.6.0", {
                "main": "https://curl.se/download/curl-{ver}.tar.xz",
                "backup": "https://github.com/curl/curl/releases/download/curl-{ver}/curl-{ver}.tar.xz"
            }),
            "nghttp2": ("1.60.0", {
                "main": "https://github.com/nghttp2/nghttp2/releases/download/v{ver}/nghttp2-{ver}.tar.xz",
                "backup": "https://github.com/nghttp2/nghttp2/archive/refs/tags/v{ver}.tar.gz"
            }),
            "libssh2": ("1.11.0", {
                "main": "https://www.libssh2.org/download/libssh2-{ver}.tar.gz",
                "backup": "https://github.com/libssh2/libssh2/releases/download/libssh2-{ver}/libssh2-{ver}.tar.gz"
            }),
            "xz": ("5.8.1", {  # Updated version to match downloaded file
                "main": "https://tukaani.org/xz/xz-{ver}.tar.xz",
                "backup": "https://github.com/tukaani-project/xz/releases/download/v{ver}/xz-{ver}.tar.xz"
            }),
            "libzip": ("1.10.1", {
                "main": "https://github.com/nih-at/libzip/releases/download/v{ver}/libzip-{ver}.tar.xz",
                "backup": "https://github.com/nih-at/libzip/archive/refs/tags/v{ver}.tar.gz"
            }),
            "libiconv-win": ("1.17", {
                "main": "https://ftp.gnu.org/pub/gnu/libiconv/libiconv-{ver}.tar.gz",
                "backup": "https://github.com/winlibs/libiconv/archive/refs/tags/v{ver}.tar.gz"
            }),
            "unixodbc": ("2.3.12", {
                "main": "https://github.com/lurcher/unixODBC/releases/download/{ver}/unixODBC-{ver}.tar.gz",
                "backup": "http://www.unixodbc.org/unixODBC-{ver}.tar.gz"
            }),
            "micro": ("git", {
                "main": "https://github.com/dixyes/php-src-tiny/archive/refs/heads/master.zip",
                "backup": "https://github.com/dixyes/php-src-tiny/archive/refs/heads/master.tar.gz"
            })
        }
        return versions.get(lib, ("", {}))

    def _try_download_library(self, lib: str, download_dir: Path) -> Optional[Path]:
        """Try downloading a library from various sources."""
        version, urls = self._get_library_version(lib)
        if not version:
            return None

        # Handle micro specially since it's already in downloads directory
        if lib == "micro" and (download_dir / "micro").exists():
            self.logger.info("📦 Using existing micro source files")
            return download_dir / "micro"

        # First check for exact version match
        check_patterns = [
            f"{lib}-{version}.tar.xz",
            f"{lib}-{version}.tar.gz",
            f"{lib}.tar.xz",
            f"{lib}.tar.gz"
        ]

        # Also check for any version of the library
        existing_files = list(download_dir.glob(f"{lib}-*.tar.*"))
        if not existing_files:
            existing_files = list(download_dir.glob(f"{lib}.tar.*"))

        if existing_files:
            selected_file = existing_files[0]
            self.logger.info(f"📦 Using existing download: {selected_file}")
            return selected_file

        # If no existing file found, try downloading
        for url_type, url_pattern in urls.items():
            try:
                # For libraries that need major version in URL
                major_ver = '.'.join(version.split('.')[:2])
                url = url_pattern.format(ver=version, major_ver=major_ver)
                if version == "git":
                    output_path = download_dir / \
                        f"{lib}" / "master.{url.split('.')[-1]}"
                else:
                    ext = url.split('.')[-1]
                    output_path = download_dir / f"{lib}-{version}.tar.{ext}"

                output_path.parent.mkdir(parents=True, exist_ok=True)

                if output_path.exists():
                    self.logger.info(
                        f"📦 Using existing download: {output_path}")
                    return output_path if version != "git" else output_path.parent

                if self._download_file(url, output_path):
                    if output_path.exists() and output_path.stat().st_size > 0:
                        return output_path if version != "git" else output_path.parent
                    else:
                        self.logger.warning(
                            f"⚠️ Download seemed successful but file is missing or empty: {output_path}")
            except Exception as e:
                self.logger.warning(
                    f"⚠️ Failed to download {lib} from {url_type} URL: {e}")

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

            # Skip further processing for micro as it's handled in build()
            if lib == "micro":
                continue

            if rc != 0 or not matches:
                self.logger.warning(
                    f"⚠️ spc download failed for {lib}, trying manual fallback...")

                # Handle php-src separately due to its unique versioning
                if lib == "php-src":
                    php_ver = config['php_version']
                    manual_path = self._try_download_php_src(
                        php_ver, download_dir)
                    matches = [manual_path] if manual_path else []
                else:
                    manual_path = self._try_download_library(lib, download_dir)
                    matches = [manual_path] if manual_path else []

            if matches and matches[0] and matches[0].exists():
                lib_path = matches[0]
                lib_name_str = str(lib) 
                extract_path = static_php_path / "source" / lib_name_str
                self.logger.info(f"📦 Preparing to extract {lib_name_str} from {lib_path.name}...")
                if not self.extract_tar_archive(lib_path, extract_path): # static_php_path removed
                    self.logger.error(f"❌ Failed to extract {lib_name_str}")
                    return False
            else:
                self.logger.error(f"❌ No downloaded archive found for {lib}")
                return False

        return True

    def _build_php(self, static_php_path: Path, config: dict) -> bool:
        extensions = self._get_extensions(config)
        ext_str = ",".join(sorted(set(extensions)))
        self.logger.info(
            f"🏗️ Building PHP {config['php_version']} with extensions...")
        build_cmd = f'SPC_CONCURRENCY=4 php bin/spc build "{ext_str}" --build-cli'
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
        if config.get('pgsql', False):
            extensions.extend(["pgsql", "pdo_pgsql"])
        return extensions

    def _get_libraries(self, config: dict) -> List[str]:
        libraries = [
            "php-src", "zlib", "libxml2", "openssl", "sqlite", "unixodbc",
            "micro", "libpng", "bzip2", "libssh2", "nghttp2", "curl", "xz",
            "libzip", "libiconv-win", "libjpeg", "freetype", "libwebp"
        ]
        if config.get('sqlsrv', False):
            libraries.extend(["sqlsrv", "pdo_sqlsrv"])
        if config.get('pgsql', False):
            libraries.extend(["postgresql"])
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
