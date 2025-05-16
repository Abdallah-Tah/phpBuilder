import tkinter as tk
from tkinter import filedialog, scrolledtext
import threading
import requests


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
        tk.Label(option_frame, text="PHP Version (e.g. 8.3.21):").pack(
            anchor="w", pady=(10, 0))
        tk.Entry(option_frame, textvariable=self.php_version_var,
                 width=20).pack(anchor="w")

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
            'php_version': self.php_version_var.get().strip()
        }

        threading.Thread(
            target=self.builder.build,
            args=(config,),
            daemon=True
        ).start()

    def php_version_exists(version):
        url = f"https://www.php.net/distributions/php-{version}.tar.xz"
        try:
            resp = requests.head(url, timeout=5)
            return resp.status_code == 200
        except Exception:
            return False

    def _validate_inputs(self):
        if not self.clone_dir.get():
            self.logger.error("Please select a directory first.")
            return False
        php_version = self.php_version_var.get().strip()
        if not php_version:
            self.logger.error("Please enter a PHP version (e.g. 8.3.21)")
            return False
        if not self.php_version_exists(php_version):
            self.logger.error(
                f"PHP version {php_version} does not exist on php.net. Please enter a valid version, e.g. 8.3.7")
            return False
        return True
