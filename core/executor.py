from pathlib import Path
import subprocess
from typing import Optional, Tuple, List
from utils.logger import Logger


class CommandExecutor:
    def __init__(self, logger: Logger):
        self.logger = logger

    def is_command_available(self, command: str) -> bool:
        """Check if a command is available in PATH"""
        try:
            result = subprocess.run(
                ["where", command],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            return result.returncode == 0
        except Exception as e:
            self.logger.error(f"Error checking command {command}: {e}")
            return False

    def run(self, command: str, cwd: Optional[Path] = None) -> bool:
        """Run a command and return True if successful"""
        self.logger.info(f"📎 Running command: {command}")
        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            if result.stdout:
                self.logger.info(result.stdout)
            if result.stderr:
                self.logger.error(result.stderr)
            return result.returncode == 0
        except Exception as e:
            self.logger.error(f"Command execution failed: {e}")
            return False

    def run_with_output(self, command: str, cwd: Optional[Path] = None) -> Tuple[int, List[str], List[str]]:
        """Run a command and return (returncode, stdout_lines, stderr_lines)"""
        self.logger.info(f"📎 Running command: {command}")
        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            stdout_lines = result.stdout.splitlines() if result.stdout else []
            stderr_lines = result.stderr.splitlines() if result.stderr else []
            return result.returncode, stdout_lines, stderr_lines
        except Exception as e:
            self.logger.error(f"Command execution failed: {e}")
            return 1, [], [str(e)]
