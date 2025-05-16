import os
import subprocess
import shutil  # Add this import
from pathlib import Path
from typing import Tuple, List, Optional
from utils.logger import Logger
from utils.exceptions import CommandError


class CommandExecutor:
    def __init__(self, logger: Logger):
        self.logger = logger

    def is_command_available(self, command_name: str) -> bool:
        """Check if a command is available in the system's PATH."""
        found_path = shutil.which(command_name)
        if found_path:
            self.logger.debug(
                f"Command '{command_name}' found in PATH: {found_path}")
            return True
        else:
            self.logger.warning(
                f"Command '{command_name}' not found in PATH via shutil.which.")
            # Fallback: try running command --version
            try:
                result = subprocess.run(
                    [command_name, "--version"],
                    capture_output=True,
                    text=True,
                    check=False,  # Don't raise exception on non-zero exit
                    timeout=5  # Add a timeout for the check
                )
                if result.returncode == 0:
                    self.logger.debug(
                        f"Command '{command_name}' confirmed with --version (fallback check). Output: {result.stdout.strip()}"
                    )
                    return True
                else:
                    self.logger.warning(
                        f"Fallback check: '{command_name} --version' failed. RC: {result.returncode}. Stderr: {result.stderr.strip()}"
                    )
                    return False
            except FileNotFoundError:
                self.logger.warning(
                    f"Fallback check: Command '{command_name}' not found (FileNotFoundError)."
                )
                return False
            except subprocess.TimeoutExpired:
                self.logger.warning(
                    f"Fallback check: Command '{command_name} --version' timed out."
                )
                return False
            except Exception as e:
                self.logger.warning(
                    f"Fallback check: Error running '{command_name} --version': {e}"
                )
                return False

    def run(self, command: str, cwd: Optional[Path] = None, env: Optional[dict] = None) -> bool:
        """Run a command and return True if successful"""
        try:
            self.logger.debug(f"Running command: {command}")
            result = subprocess.run(
                command,
                shell=True,
                cwd=str(cwd) if cwd else None,
                env=env,
                check=False,
                capture_output=True,
                text=True
            )

            # Log output
            if result.stdout:
                self.logger.debug(result.stdout)
            if result.stderr:
                self.logger.error(result.stderr)

            if result.returncode != 0:
                self.logger.error(
                    f"Command failed with exit code {result.returncode}")
                return False

            return True

        except Exception as e:
            self.logger.error(f"Failed to execute command: {str(e)}")
            return False

    def run_with_output(self, command: str, cwd: Optional[Path] = None, env: Optional[dict] = None) -> Tuple[int, List[str], List[str]]:
        """Run a command and return (exit_code, stdout_lines, stderr_lines)"""
        try:
            self.logger.debug(f"Running command: {command}")
            result = subprocess.run(
                command,
                shell=True,
                cwd=str(cwd) if cwd else None,
                env=env,
                check=False,
                capture_output=True,
                text=True
            )

            stdout_lines = result.stdout.splitlines() if result.stdout else []
            stderr_lines = result.stderr.splitlines() if result.stderr else []

            # Log output
            if stdout_lines:
                self.logger.debug("\n".join(stdout_lines))
            if stderr_lines:
                self.logger.error("\n".join(stderr_lines))

            return result.returncode, stdout_lines, stderr_lines

        except Exception as e:
            self.logger.error(f"Failed to execute command: {str(e)}")
            return 1, [], [str(e)]

    def run_php(self, script: str, cwd: Optional[Path] = None, env: Optional[dict] = None) -> bool:
        """Run a PHP script with error handling"""
        try:
            # Find PHP executable
            php_exe = self._find_php_executable()
            if not php_exe:
                raise CommandError("PHP executable not found")

            # Execute PHP script
            command = f'"{php_exe}" -r "{script}"'
            return self.run(command, cwd, env)

        except Exception as e:
            self.logger.error(f"Failed to execute PHP script: {str(e)}")
            return False

    def _find_php_executable(self) -> Optional[str]:
        """Find PHP executable in the system"""
        try:
            result = subprocess.run(
                ["where", "php"] if os.name == "nt" else ["which", "php"],
                capture_output=True,
                text=True,
                check=False
            )
            if result.returncode == 0:
                return result.stdout.splitlines()[0]
        except Exception:
            pass

        # Try common locations
        common_paths = [
            Path("php"),  # In PATH
            Path("C:/php/php.exe"),  # Windows common location
            Path("/usr/bin/php"),  # Linux/Unix common location
            Path("/usr/local/bin/php")  # macOS common location
        ]

        for path in common_paths:
            try:
                if path.exists() or subprocess.run([str(path), "-v"], capture_output=True).returncode == 0:
                    return str(path)
            except Exception:
                continue

        return None
