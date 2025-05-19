from pathlib import Path
import shutil
import os
import glob
import ctypes
from typing import Optional
from utils.logger import Logger
from utils.exceptions import FileSystemError
from utils.path_manager import find_perl_executable


class FileOperations:
    def __init__(self, logger: Logger):
        self.logger = logger
        self.command_executor = None  # Will be set after import to avoid circular dependency

    def set_command_executor(self, executor):
        """Set command executor after instantiation to avoid circular dependency"""
        self.command_executor = executor

    def get_short_path(self, long_path: str) -> str:
        """Get Windows short path for a long path"""
        if not os.path.exists(long_path):
            self.logger.warning(
                f"Path does not exist, cannot get short path: {long_path}")
            # Attempt to return a usable default or raise an error
            # For now, returning the original path if it doesn't exist,
            # as some callers might still try to use it for creating dirs.
            return long_path
        try:
            _GetShortPathNameW = ctypes.windll.kernel32.GetShortPathNameW
            _GetShortPathNameW.argtypes = [
                ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
            _GetShortPathNameW.restype = ctypes.c_uint
            buf = ctypes.create_unicode_buffer(260)
            result = _GetShortPathNameW(long_path, buf, 260)
            if result == 0:  # Error
                error_code = ctypes.GetLastError()
                self.logger.error(
                    f"GetShortPathNameW failed for '{long_path}' with error code: {error_code}")
                return long_path  # Fallback to long path
            return buf.value
        except Exception as e:
            self.logger.error(
                f"Exception in get_short_path for '{long_path}': {e}")
            return long_path  # Fallback to long path

    def patch_perl_shim(self, base_path: Path) -> None:
        """Patch perl shim for Windows compatibility using find_perl_executable."""
        # Pass the project's base path to find_perl_executable
        # Assuming base_path for patch_perl_shim is equivalent to the project_base_path needed by find_perl_executable
        # If base_path is something like D:\python\custom-php-ext\static-php-cli,
        # and pkgroot is at D:\python\custom-php-ext\pkgroot, we need to adjust.
        # Let's assume base_path is the root of the static-php-cli checkout for now.
        # The find_perl_executable will then look for pkgroot relative to where it expects if this is not the true project root.
        # For clarity, let's try to get the actual project root if base_path is deep.
        # Assuming the script is run from project root or base_path is relative to it.
        # A more robust way would be to have PathManager initialized with project root.
        # For now, let's assume base_path.parent is the project root if base_path is static-php-cli.

        project_root_for_perl_search = base_path  # Default to base_path
        if base_path.name == 'static-php-cli':  # Heuristic: if base_path is the static-php-cli dir
            project_root_for_perl_search = base_path.parent  # Then project root is its parent

        actual_perl_path_str = find_perl_executable(
            project_base_path=project_root_for_perl_search)

        if not actual_perl_path_str:
            self.logger.error(
                "Perl executable not found using find_perl_executable. "
                "Perl setup cannot proceed. Ensure Perl is installed and accessible."
            )
            return  # Cannot proceed without perl

        self.logger.info(
            f"Using Perl executable found at: {actual_perl_path_str}")

        shim_dir = base_path
        shim_dir.mkdir(parents=True, exist_ok=True)

        # 1. Handle perl.exe: Copy the actual perl executable
        target_perl_exe_path = shim_dir / "perl.exe"
        try:
            target_perl_exe_path.parent.mkdir(parents=True, exist_ok=True)
            if target_perl_exe_path.exists():
                target_perl_exe_path.unlink(missing_ok=True)
            shutil.copy2(actual_perl_path_str, target_perl_exe_path)
            self.logger.info(
                f"Copied actual Perl executable from {actual_perl_path_str} to {target_perl_exe_path}")
        except Exception as e:
            self.logger.error(
                f"Failed to copy Perl executable from {actual_perl_path_str} to {target_perl_exe_path}: {e}")
            return

        # 2. Handle perl.bat: Create a batch file that calls the copied perl.exe
        original_perl_exe_path = Path(actual_perl_path_str)
        # Try to determine the base 'usr' directory if it's Git Perl (e.g., C:/Program Files/Git/usr)
        original_perl_usr_path = None
        if original_perl_exe_path.parent.name.lower() == 'bin' and original_perl_exe_path.parent.parent.name.lower() == 'usr':
            original_perl_usr_path = original_perl_exe_path.parent.parent

        env_setup_lines = []
        # Heuristic: if "git" is in the path of the chosen perl, it's likely Git for Windows' Perl.
        # A more specific check for Git's typical directory structure.
        if original_perl_usr_path and original_perl_usr_path.parent.name.lower() == 'git':
            self.logger.info(
                f"Perl from Git for Windows detected ({actual_perl_path_str}). Attempting to set PERL5LIB in perl.bat shim.")
            potential_lib_roots = [
                original_perl_usr_path / "lib" / "perl5",
                original_perl_usr_path / "share" / "perl5",
                # Add path for MinGW environments often used by Git for Windows Perl
                # e.g. C:/Program Files/Git/mingw64/lib/perl5
                original_perl_exe_path.parent.parent / "lib" / "perl5",
            ]
            perl_module_subdirs = ["site_perl", "vendor_perl", "core_perl"]
            candidate_lib_paths = []
            for root in potential_lib_roots:
                for subdir in perl_module_subdirs:
                    candidate_lib_paths.append(root / subdir)
        # For Strawberry Perl, the structure is different, e.g., C:\Strawberry\perl\site\lib, C:\Strawberry\perl\vendor\lib, C:\Strawberry\perl\lib
        if "strawberry" in actual_perl_path_str.lower():
            self.logger.info(
                f"Strawberry Perl detected ({actual_perl_path_str}). Attempting to set PERL5LIB in perl.bat shim.")
            strawberry_root = original_perl_exe_path.parent.parent  # C:\Strawberry\perl
            candidate_lib_paths.extend([
                strawberry_root / "site" / "lib",
                strawberry_root / "vendor" / "lib",
                strawberry_root / "lib",
            ])

            existing_lib_paths_str = [
                str(p.resolve()) for p in candidate_lib_paths if p.exists() and p.is_dir()]

            if existing_lib_paths_str:
                perl5lib_value = os.pathsep.join(existing_lib_paths_str)
                # Prepend to existing PERL5LIB to give priority, but also include original
                env_setup_lines.append(
                    f'set "SP_ORIGINAL_PERL5LIB=%PERL5LIB%"')
                env_setup_lines.append(f'set "PERL5LIB={perl5lib_value}"')
                env_setup_lines.append(
                    f'if defined SP_ORIGINAL_PERL5LIB (set "PERL5LIB=%PERL5LIB%;%SP_ORIGINAL_PERL5LIB%")')
                self.logger.info(
                    f"Perl.bat shim will attempt to set PERL5LIB to: {perl5lib_value} (and append original if exists)")
            else:
                self.logger.warning(
                    f"Could not find expected library directories for the selected Perl at {actual_perl_path_str} to set PERL5LIB.")

        bat_content_lines = ['@echo off']
        bat_content_lines.extend(env_setup_lines)
        bat_content_lines.append(f'"%~dp0perl.exe" %*')

        # Ensure lines are clean and join with CRLF
        processed_lines = [line.strip()
                           for line in bat_content_lines if line.strip()]

        if not processed_lines:
            self.logger.error(
                "Processed lines for perl.bat are empty. Using a default minimal bat content.")
            # This fallback should ideally not be reached if bat_content_lines is always populated correctly.
            bat_content = '@echo off\\r\\n"%~dp0perl.exe" %*\\r\\n'
        else:
            bat_content = '\\r\\n'.join(processed_lines)
            # Ensure it always ends with exactly one CRLF
            if not bat_content.endswith('\\r\\n'):
                bat_content += '\\r\\n'

        # As a final check, ensure no leading newlines and exactly one trailing CRLF.
        bat_content = bat_content.lstrip('\\r\\n')
        if not bat_content.endswith('\\r\\n'):
            bat_content += '\\r\\n'
        # Ensure @echo off is the first line if it got stripped
        if not bat_content.lower().startswith('@echo off'):
            bat_content = '@echo off\\r\\n' + bat_content

        target_perl_bat_path = shim_dir / "perl.bat"
        try:
            # Write in text mode. If bat_content already has the correct \\r\\n,
            # newline='' ensures Python doesn't do further \\n -> os.linesep translation.
            target_perl_bat_path.write_text(
                bat_content, encoding='utf-8', newline='')
            self.logger.info(
                f"Perl batch shim created at {target_perl_bat_path} to run {target_perl_exe_path}")
        except Exception as e:
            self.logger.error(
                f"Failed to write perl.bat shim {target_perl_bat_path}: {e}")

        # Update PATH environment variable
        # Ensure base_path is not already in PATH to avoid duplicates
        current_path_env = os.environ.get("PATH", "")
        if str(shim_dir) not in current_path_env.split(os.pathsep):
            os.environ["PATH"] = f"{shim_dir}{os.pathsep}{current_path_env}"
            self.logger.info(f"Prepended {shim_dir} to PATH for shims.")
        else:
            self.logger.info(f"{shim_dir} already in PATH.")

    def patch_functions_quote(self, base_path: Path) -> None:
        """Patch functions.php to fix quoting issues safely and idempotently"""
        fn = base_path / "src" / "globals" / "functions.php"
        if not fn.exists():
            self.logger.error("[!] Cannot patch functions.php—file not found.")
            return

        with open(fn, "r", encoding="utf-8") as f:
            lines = f.readlines()

        out = []
        patched = False
        for i, line in enumerate(lines):
            # Remove any previously broken patch lines
            if ("$cmd = '""' . str_replace('""', '\\""', $cmd) . '""';\\n" in line
                    or "$cmd = '""' . str_replace('""', '\\""', $cmd) . '""';" in line):
                continue  # skip broken or duplicate patch lines
            # Patch only inside f_passthru, before passthru($cmd, $code)
            if (
                "function f_passthru" in line
                and not any("$cmd = '""' . str_replace('""', '\\""', $cmd) . '""';" in l for l in lines[i:i+10])
            ):
                out.append(line)
                # Look ahead for passthru($cmd, $code)
                for j in range(i+1, min(i+10, len(lines))):
                    if "passthru($cmd" in lines[j] and "$cmd = '""' . str_replace('""', '\\""', $cmd) . '""';" not in lines[j-1]:
                        # Insert patch just before passthru
                        out.append(
                            "    $cmd = '""' . str_replace('""', '\\""', $cmd) . '""';\n")
                        patched = True
                        break
                continue
            out.append(line)

        if patched:
            with open(fn, "w", encoding="utf-8") as f:
                f.writelines(out)
            self.logger.info(
                "✔ Safely patched functions.php to quote all commands (idempotent)")
        else:
            self.logger.info(
                "functions.php already patched or patch not needed.")

    def extract_library(self, base_path: Path, libname: str, archive_filename_hint: Optional[str] = None) -> bool:
        """Extract a library archive with verification"""
        if not self.command_executor:
            self.logger.error(
                "Command executor not set in FileOperations. Cannot extract library.")
            return False

        downloads_dir = base_path / "downloads"
        source_dir = base_path / "source" / libname

        # Clean up existing directory
        if source_dir.exists():
            self.logger.info(f"Removing existing directory: {source_dir}")
            if not self.remove_directory_robust(source_dir):
                self.logger.error(
                    f"Failed to remove existing directory {source_dir} before extraction.")
                return False
        try:
            source_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self.logger.error(
                f"Failed to create source directory {source_dir}: {e}")
            return False

        archive_to_extract_str: Optional[str] = None

        if archive_filename_hint:
            potential_archive_path = downloads_dir / archive_filename_hint
            if potential_archive_path.is_file():
                archive_to_extract_str = str(potential_archive_path)
                self.logger.info(
                    f"Using archive hint for {libname}: {archive_to_extract_str}")
            else:
                self.logger.warning(
                    f"Archive hint '{archive_filename_hint}' for {libname} ('{potential_archive_path}') not found or not a file. Will try globbing.")

        if not archive_to_extract_str:
            self.logger.info(
                f"No valid archive hint for {libname}. Attempting glob patterns.")
            glob_patterns_priority = [
                f"{libname}.tar.gz", f"{libname}.tar.xz", f"{libname}.zip", f"{libname}.tgz",
                f"{libname}-*.tar.gz", f"{libname}-*.tar.xz", f"{libname}-*.zip", f"{libname}-*.tgz",
                f"{libname}.*.tar.gz", f"{libname}.*.tar.xz", f"{libname}.*.zip", f"{libname}.*.tgz"
            ]
            found_files = []
            for pattern in glob_patterns_priority:
                matched = list(downloads_dir.glob(pattern))
                found_files.extend(p for p in matched if p.is_file())
            if not found_files:
                matched = list(downloads_dir.glob(f"{libname}*"))
                found_files.extend(p for p in matched if p.is_file())
            if found_files:
                archive_to_extract_str = str(
                    sorted(found_files, key=lambda p: str(p.name))[0])
                self.logger.info(
                    f"Found archive for {libname} via glob: {archive_to_extract_str}")
            else:
                self.logger.error(
                    f"[!] No archive files found for {libname} via any glob pattern in {downloads_dir}.")
                return False

        archive = archive_to_extract_str

        try:
            use_7zip = self.command_executor.is_command_available("7z")
            seven_zip_path = shutil.which(
                "7z") or "C:\\Program Files\\7-Zip\\7z.exe"

            if archive.endswith(".zip"):
                if use_7zip:
                    extract_cmd = f'"{seven_zip_path}" x "{archive}" -o"{source_dir}" -y'
                    if not self.command_executor.run(extract_cmd):
                        raise RuntimeError(f"7z extraction failed: {archive}")
                else:
                    shutil.unpack_archive(str(archive), str(source_dir))
                    self.logger.info(
                        f"Successfully extracted {archive} using shutil.unpack_archive.")
                return self._post_extract_verify(source_dir, libname)

            elif archive.endswith(('.tar.xz', '.tar.gz', '.tgz', '.tar.bz2', '.tar')):
                if use_7zip:
                    extract_cmd = (
                        f'"{seven_zip_path}" x "{archive}" -so | '
                        f'"{seven_zip_path}" x -si -ttar -o"{source_dir}" -y'
                    )
                    if not self.command_executor.run(extract_cmd):
                        raise RuntimeError(
                            f"7z stream extraction failed: {archive}")
                    self.logger.info(
                        f"Successfully extracted {archive} using 7-Zip.")
                else:
                    shutil.unpack_archive(str(archive), str(source_dir))
                    self.logger.info(
                        f"Successfully extracted {archive} using shutil.unpack_archive.")
                return self._post_extract_verify(source_dir, libname)

            else:
                self.logger.warning(
                    f"Unknown archive format for {archive}. Trying shutil fallback.")
                shutil.unpack_archive(str(archive), str(source_dir))
                return self._post_extract_verify(source_dir, libname)

        except Exception as e:
            self.logger.error(f"Extraction failed for {archive}: {e}")
            if source_dir.exists():
                self.remove_directory_robust(source_dir)
            return False

    def _post_extract_verify(self, source_dir: Path, libname: str) -> bool:
        """Flatten directory and verify if CMakeLists.txt exists for build systems"""
        flattened = self._flatten_single_subdirectory(source_dir)
        cmake_file = source_dir / "CMakeLists.txt"
        if cmake_file.exists():
            self.logger.info(f"CMakeLists.txt found in {source_dir}.")
        else:
            self.logger.warning(
                f"CMakeLists.txt not found in {source_dir} after extraction of {libname}.")
        return flattened

    def _flatten_single_subdirectory(self, directory: Path) -> bool:
        """
        Checks if a directory contains exactly one subdirectory. If so,
        moves contents of that subdirectory to the parent and removes the now-empty subdirectory.
        Uses shutil for robustness.
        """
        try:
            items = list(directory.iterdir())
            if len(items) == 1 and items[0].is_dir():
                sub_dir = items[0]
                self.logger.info(
                    f"Flattening single subdirectory: {sub_dir} into {directory}")
                for item_to_move in sub_dir.iterdir():
                    shutil.move(str(item_to_move), str(
                        directory / item_to_move.name))
                sub_dir.rmdir()  # Remove now-empty subdirectory
                self.logger.info(f"Successfully flattened {sub_dir}.")
            return True
        except OSError as e:
            self.logger.error(f"Error flattening directory {directory}: {e}")
            return False
        except Exception as e:  # Catch any other unexpected errors
            self.logger.error(
                f"Unexpected error during flattening of {directory}: {e}")
            return False

    def remove_directory_robust(self, path: Path) -> bool:
        """
        Safely and robustly remove a directory and its contents.
        Tries shutil.rmtree first, then falls back to PowerShell if needed on Windows.
        """
        try:
            if path.exists():
                self.logger.info(
                    f"Attempting to remove directory with shutil.rmtree: {path}")
                shutil.rmtree(path, ignore_errors=False)
                self.logger.info(
                    f"Successfully removed directory with shutil.rmtree: {path}")
                return True
        except OSError as e:
            self.logger.warning(
                f"shutil.rmtree failed for {path}: {e}. Trying with ignore_errors=True.")
            try:
                shutil.rmtree(path, ignore_errors=True)
                if not path.exists():  # Check if it was removed
                    self.logger.info(
                        f"Successfully removed directory with shutil.rmtree (ignore_errors=True): {path}")
                    return True
                else:
                    self.logger.warning(
                        f"shutil.rmtree (ignore_errors=True) did not fully remove {path}.")
            except Exception as e_ignore:  # Catch errors even with ignore_errors=True
                self.logger.warning(
                    f"shutil.rmtree (ignore_errors=True) also failed for {path}: {e_ignore}")

            # Fallback to PowerShell on Windows if shutil.rmtree failed
            if os.name == 'nt':
                self.logger.info(
                    f"Attempting to remove directory with PowerShell: {path}")
                if self.command_executor and self.command_executor.is_command_available("powershell"):
                    # Ensure path is absolute for PowerShell command
                    abs_path_str = str(path.resolve())
                    # Using -Force and -Recurse, and ensuring the path is quoted.
                    # ErrorAction SilentlyContinue might hide issues, but rmdir can be problematic.
                    # Let's try with ErrorAction Stop first for better diagnostics.
                    ps_command = f'Remove-Item -Path "{abs_path_str}" -Recurse -Force -ErrorAction Stop'
                    if self.command_executor.run(f'powershell -NoProfile -NonInteractive -Command "{ps_command}"'):
                        if not path.exists():  # Verify removal
                            self.logger.info(
                                f"Successfully removed directory with PowerShell: {path}")
                            return True
                        else:
                            self.logger.error(
                                f"PowerShell command executed but directory still exists: {path}")
                            return False
                    else:
                        self.logger.error(
                            f"PowerShell command failed to remove directory: {path}")
                        # As a last resort, try with SilentlyContinue
                        ps_command_silent = f'Remove-Item -Path "{abs_path_str}" -Recurse -Force -ErrorAction SilentlyContinue'
                        self.command_executor.run(
                            f'powershell -NoProfile -NonInteractive -Command "{ps_command_silent}"')
                        if not path.exists():
                            self.logger.info(
                                f"Successfully removed directory with PowerShell (SilentlyContinue): {path}")
                            return True
                        else:
                            self.logger.error(
                                f"PowerShell command (SilentlyContinue) also failed to remove directory: {path}")
                            return False
                else:
                    self.logger.error(
                        "PowerShell is not available, and shutil.rmtree failed. Cannot remove directory.")
                    return False
            else:  # Not Windows, and shutil.rmtree failed
                self.logger.error(
                    f"shutil.rmtree failed on non-Windows OS for {path}. No PowerShell fallback.")
                return False
        except Exception as e:
            self.logger.error(
                f"Unexpected error removing directory {path}: {str(e)}")
            return False
        return not path.exists()  # Final check

    # Kept for compatibility if directly called elsewhere
    def remove_directory(self, path: Path) -> None:
        """Original remove_directory, now calls robust version."""
        self.logger.warning(
            f"Legacy remove_directory called for {path}. Redirecting to remove_directory_robust.")
        if not self.remove_directory_robust(path):
            self.logger.error(
                f"remove_directory_robust failed for {path} when called from legacy remove_directory.")

    def copy_directory_robust(self, src: Path, dst: Path) -> bool:
        """
        Robustly copy a directory recursively.
        Tries shutil.copytree first, then falls back to PowerShell on Windows.
        """
        try:
            if not src.exists():
                raise FileSystemError(
                    f"Source directory does not exist: {src}")

            # Create parent directory of dst if needed
            dst.parent.mkdir(parents=True, exist_ok=True)
            # If dst exists and is a file, or if it's a non-empty dir and we want to overwrite,
            # shutil.copytree might need dst to not exist or be an empty dir.
            # For simplicity, if dst exists, remove it first.
            if dst.exists():
                self.logger.info(
                    f"Destination {dst} exists. Removing before copy.")
                if not self.remove_directory_robust(dst):
                    self.logger.error(
                        f"Could not remove existing destination directory {dst}. Aborting copy.")
                    return False

            # Ensure dst exists as a directory
            dst.mkdir(parents=True, exist_ok=True)

            self.logger.info(
                f"Attempting to copy with shutil.copytree from {src} to {dst}")
            # dirs_exist_ok=True for Python 3.8+
            shutil.copytree(src, dst, dirs_exist_ok=True)
            self.logger.info(
                f"Successfully copied with shutil.copytree from {src} to {dst}")
            return True

        except shutil.Error as e:  # Specific shutil errors
            self.logger.warning(
                f"shutil.copytree failed for {src} to {dst}: {e}. Errors: {e.args}")
            # Fallback for specific errors or if dirs_exist_ok is not behaving as expected
        except Exception as e:  # General errors with shutil.copytree
            self.logger.warning(
                f"shutil.copytree failed for {src} to {dst}: {e}.")

        # Fallback to PowerShell on Windows if shutil.copytree failed
        if os.name == 'nt':
            self.logger.info(
                f"Attempting to copy directory with PowerShell from {src} to {dst}")
            if self.command_executor and self.command_executor.is_command_available("powershell"):
                # Ensure paths are absolute and correctly quoted
                abs_src_str = str(src.resolve())
                abs_dst_str = str(dst.resolve())
                # Ensure destination directory exists for Copy-Item -Recurse -Force
                # PowerShell's Copy-Item with -Recurse expects the destination to exist if copying contents.
                # If dst was removed, recreate it.
                dst.mkdir(parents=True, exist_ok=True)

                # The command `Copy-Item -Path '{src}\\*' -Destination '{dst}' -Recurse -Force`
                # copies the *contents* of src into dst.
                # If you want src itself to become a subdirectory in dst, the command is different.
                # Assuming we want to mirror src into dst (i.e., dst becomes a copy of src).
                ps_command = f'Copy-Item -Path "{abs_src_str}" -Destination "{abs_dst_str}" -Recurse -Force -ErrorAction Stop'

                if self.command_executor.run(f'powershell -NoProfile -NonInteractive -Command "{ps_command}"'):
                    self.logger.info(
                        f"Successfully copied directory with PowerShell: {src} to {dst}")
                    return True
                else:
                    self.logger.error(
                        f"PowerShell command failed to copy directory: {src} to {dst}")
                    return False
            else:
                self.logger.error(
                    "PowerShell is not available, and shutil.copytree failed. Cannot copy directory.")
                return False
        else:  # Not Windows, and shutil.copytree failed
            self.logger.error(
                f"shutil.copytree failed on non-Windows OS for {src} to {dst}. No PowerShell fallback.")
            return False
        return False

    def copy_directory(self, src: Path, dst: Path) -> bool:  # Kept for compatibility
        """Original copy_directory, now calls robust version."""
