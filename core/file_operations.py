from pathlib import Path
import shutil
import os
import glob
import ctypes
from typing import Optional
from utils.logger import Logger
from utils.exceptions import FileSystemError


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
        """Patch perl shim for Windows compatibility"""
        # Attempt to find perl.exe in common Git installations first
        possible_perl_paths = [
            Path(os.environ.get("ProgramFiles", "C:\\Program Files")) /
            "Git" / "usr" / "bin" / "perl.exe",
            Path(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")
                 ) / "Git" / "usr" / "bin" / "perl.exe",
            Path(os.environ.get("LocalAppData", "")) / "Programs" /
            "Git" / "usr" / "bin" / "perl.exe"  # User install
        ]

        perl_exe_path_str = ""
        for p_path in possible_perl_paths:
            if p_path.exists():
                perl_exe_path_str = str(p_path)
                self.logger.info(f"Found perl.exe at: {perl_exe_path_str}")
                break

        if not perl_exe_path_str:
            # Fallback to checking PATH if not found in common Git locations
            if self.command_executor and self.command_executor.is_command_available("perl"):
                # shutil.which should give us the full path
                perl_exe_path_str = shutil.which("perl")
                if perl_exe_path_str:
                    self.logger.info(
                        f"Found perl.exe in PATH: {perl_exe_path_str}")
                else:
                    self.logger.error(
                        "Perl executable not found in common Git directories or system PATH. "
                        "Perl shim cannot be created. Ensure Git for Windows is installed correctly."
                    )
                    return  # Cannot proceed without perl
            else:  # command_executor not available or perl not in PATH
                self.logger.error(
                    "Perl executable not found in common Git directories and PATH check could not be performed. "
                    "Perl shim cannot be created. Ensure Git for Windows is installed correctly."
                )
                return

        short_perl_path = self.get_short_path(perl_exe_path_str)
        if short_perl_path == perl_exe_path_str and " " in perl_exe_path_str:
            self.logger.warning(
                f"Could not get short path for perl: {perl_exe_path_str}. Using long path. This might cause issues if it contains spaces.")

        shim = base_path / "perl.bat"
        try:
            shim.write_text(f'@"{short_perl_path}" %*\\n', encoding='utf-8')
            self.logger.info(
                f"Perl shim created at {shim} pointing to {short_perl_path}")
            # Update PATH environment variable
            # Ensure base_path is not already in PATH to avoid duplicates
            if str(base_path) not in os.environ["PATH"].split(os.pathsep):
                os.environ["PATH"] = f"{base_path}{os.pathsep}{os.environ['PATH']}"
                self.logger.info(f"Added {base_path} to PATH for perl.bat.")
            else:
                self.logger.info(f"{base_path} already in PATH.")
        except IOError as e:
            self.logger.error(f"Failed to write perl shim {shim}: {e}")
        except Exception as e:
            self.logger.error(
                f"An unexpected error occurred while creating perl shim: {e}")

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

    def extract_library(self, base_path: Path, libname: str) -> bool:
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
            # Use robust removal
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

        # Find archive with glob
        files = glob.glob(str(downloads_dir / f"{libname}*"))
        files = sorted(files, key=lambda x: (
            os.path.isdir(x), -len(x)), reverse=True)

        if not files:
            self.logger.error(
                f"[!] Archive or source folder for {libname} not found in downloads.")
            return False

        archive = files[0]
        if os.path.isdir(archive):
            # Copy directory contents using PowerShell
            if not self.command_executor.run(
                f'powershell -Command "Copy-Item -Path \'{archive}\\*\' -Destination \'{source_dir}\' -Recurse -Force"'
            ):
                return False
            self.logger.info(f"✔ Copied git-based source for {libname}")
            return True

        # Archive extraction
        try:
            use_7zip = self.command_executor.is_command_available("7z")
            seven_zip_path = "C:\\\\Program Files\\\\7-Zip\\\\7z.exe"  # Default path
            if use_7zip:
                # Attempt to get 7z path if `is_command_available` found it elsewhere
                sz_which = shutil.which("7z")
                if sz_which:
                    seven_zip_path = sz_which
                self.logger.info(
                    f"Using 7-Zip for extraction: {seven_zip_path}")

            if archive.endswith(".zip"):
                if use_7zip:
                    extract_cmd = f'"{seven_zip_path}" x "{archive}" -o"{source_dir}" -y'
                else:  # Fallback to shutil.unpack_archive
                    self.logger.info(
                        f"7-Zip not found. Attempting to extract {archive} using Python\'s shutil.unpack_archive.")
                    shutil.unpack_archive(str(archive), str(source_dir))
                    self.logger.info(
                        f"Successfully extracted {archive} using shutil.unpack_archive.")
                    # Flatten after unpack
                    return self._flatten_single_subdirectory(source_dir)
            # Added .tar.bz2 and .tar
            elif archive.endswith(('.tar.xz', '.tar.gz', '.tgz', '.tar.bz2', '.tar')):
                if use_7zip:
                    extract_cmd = (
                        f'"{seven_zip_path}" x "{archive}" -so | '
                        # Added -y for auto-yes
                        f'"{seven_zip_path}" x -si -ttar -o"{source_dir}" -y'
                    )
                else:  # Fallback to shutil.unpack_archive
                    self.logger.info(
                        f"7-Zip not found. Attempting to extract {archive} using Python\'s shutil.unpack_archive.")
                    shutil.unpack_archive(str(archive), str(source_dir))
                    self.logger.info(
                        f"Successfully extracted {archive} using shutil.unpack_archive.")
                    # Flatten after unpack
                    return self._flatten_single_subdirectory(source_dir)
            else:
                self.logger.warning(
                    f"Unknown archive format for {archive}. Attempting shutil.unpack_archive as a generic fallback.")
                try:
                    shutil.unpack_archive(str(archive), str(source_dir))
                    self.logger.info(
                        f"Successfully extracted {archive} using shutil.unpack_archive fallback.")
                    # Flatten after unpack
                    return self._flatten_single_subdirectory(source_dir)
                except Exception as e_unpack:
                    self.logger.error(
                        f"shutil.unpack_archive also failed for {archive}: {e_unpack}")
                    raise ValueError(
                        f"Unknown or unsupported archive format for {archive}")

            if use_7zip:  # Only run command_executor if 7zip was chosen
                if not self.command_executor.run(extract_cmd):
                    raise RuntimeError(
                        f"7z extraction command returned non-zero for {archive}")
                self.logger.info(
                    f"Successfully extracted {archive} using 7-Zip.")

            # Flatten any single subdirectory
            return self._flatten_single_subdirectory(source_dir)

        except Exception as e:
            self.logger.error(f"Extraction failed for {archive}: {e}")
            # Attempt to clean up partially extracted files
            if source_dir.exists():
                self.logger.info(
                    f"Cleaning up partially extracted files in {source_dir}")
                self.remove_directory_robust(source_dir)
            return False

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
                # Initially try with errors not ignored
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
