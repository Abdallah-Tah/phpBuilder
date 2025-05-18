import tkinter as tk
from tkinter import filedialog, scrolledtext
from tkinter import ttk
import threading
import requests
import re
from utils.path_manager import find_7zip_executable


class BuilderFrame(tk.Frame):
    def __init__(self, parent, builder, logger):
        super().__init__(parent)
        self.builder = builder
        self.logger = logger

        self.clone_dir = tk.StringVar()
        self.var_mysql = tk.BooleanVar()
        self.var_sqlsrv = tk.BooleanVar()
        self.php_version_var = tk.StringVar()

        self._init_ui()

    def _init_ui(self):
        # Directory selection
        tk.Label(self, text="Select Clone Directory:").pack(pady=(10, 0))
        dir_frame = tk.Frame(self)
        dir_frame.pack(padx=10, pady=5, fill="x")
        tk.Entry(dir_frame, textvariable=self.clone_dir, width=60).pack(
            side="left", padx=(0, 5), fill="x", expand=True)
        tk.Button(dir_frame, text="Browse",
                  command=self._select_directory).pack(side="right")

        # Options
        option_frame = tk.Frame(self)
        option_frame.pack(padx=10, pady=5, fill="x")
        tk.Checkbutton(option_frame, text="Include MySQL (pdo_mysql, mysqli)",
                       variable=self.var_mysql).pack(anchor="w")
        tk.Checkbutton(option_frame, text="Include SQLSRV (sqlsrv, pdo_sqlsrv)",
                       variable=self.var_sqlsrv).pack(anchor="w")
        tk.Label(option_frame, text="PHP Version:").pack(
            anchor="w", pady=(10, 0))
        self.php_versions = self.fetch_php_versions()
        if self.php_versions:
            self.php_version_var.set(self.php_versions[0])
        self.php_version_dropdown = ttk.Combobox(
            option_frame, textvariable=self.php_version_var, values=self.php_versions, width=20, state="readonly")
        self.php_version_dropdown.pack(anchor="w")

        # Build button
        tk.Button(self, text="Start Build", command=self._start_build,
                  bg="green", fg="white").pack(pady=10)

        # Output area
        self.output = scrolledtext.ScrolledText(self, height=25, width=100)
        self.output.pack(padx=10, pady=(0, 10), fill="both", expand=True)
        self.logger.set_output(self.output)

    def _select_directory(self):
        folder = filedialog.askdirectory()
        if folder:
            self.clone_dir.set(folder)

    def _start_build(self):
        if not self._validate_inputs():
            return

        config = {
            'clone_dir': self.clone_dir.get(),
            'mysql': self.var_mysql.get(),
            'sqlsrv': self.var_sqlsrv.get(),
            'php_version': self.php_version_var.get().strip(),
            'seven_zip_exe': self.seven_zip_exe  # Pass the found 7-Zip path to the builder
        }

        threading.Thread(
            target=self.builder.build,
            args=(config,),
            daemon=True
        ).start()

    def fetch_php_versions(self):
        # Fallback to hardcoded versions if fetching fails or returns empty
        try:
            resp = requests.get("https://www.php.net/downloads", timeout=10)
            versions = re.findall(
                r'php-(\\d+\\.\\d+\\.\\d+)\\.tar\\.xz', resp.text)
            versions = sorted(set(versions), key=lambda v: list(
                map(int, v.split('.'))), reverse=True)
            if versions:
                return versions
        except Exception:
            pass
        # Default/fallback versions (update as needed)
        return [
            "8.4.0", "8.3.4", "8.3.3", "8.3.2", "8.3.1", "8.3.0"
        ]

    def _validate_inputs(self):
        if not self.clone_dir.get():
            self.logger.error("Please select a directory first.")
            return False
        php_version = self.php_version_var.get().strip()
        if not php_version:
            self.logger.error("Please select a PHP version from the dropdown.")
            return False
        if php_version not in self.php_versions:
            self.logger.error(
                f"PHP version {php_version} is not available for download. Please select a valid version.")
            return False

        self.seven_zip_exe = find_7zip_executable()
        if not self.seven_zip_exe:
            self.logger.error(
                "7-Zip (7z.exe) not found. Please install 7-Zip and ensure it is in your PATH, or installed in a standard location (e.g., C:\\Program Files\\7-Zip).")
            return False
        else:
            self.logger.info(f"Found 7-Zip: {self.seven_zip_exe}")

        return True
