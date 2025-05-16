import tkinter as tk


class Logger:
    def __init__(self):
        self.output = None

    def set_output(self, output_widget):
        self.output = output_widget

    def debug(self, message):
        if self.output:
            self._log(f"[DEBUG] {message}", color="gray")

    def info(self, message):
        if self.output:
            self._log(message)

    def warning(self, message):
        if self.output:
            self._log(f"[WARNING] {message}", color="orange")

    def error(self, message):
        if self.output:
            self._log(f"[!] {message}", error=True)

    def _log(self, text, error=False, color=None):
        if not self.output:
            return

        self.output.insert(tk.END, text + "\n")

        # Get the last line's position
        last_line = self.output.get("end-2c linestart", "end-1c")
        line_start = f"end-{len(last_line)+1}c linestart"
        line_end = f"end-1c"

        # Apply appropriate color tag
        if error:
            self.output.tag_add("error", line_start, line_end)
            self.output.tag_config("error", foreground="red")
        elif color:
            tag_name = f"color_{color}"
            self.output.tag_add(tag_name, line_start, line_end)
            self.output.tag_config(tag_name, foreground=color)

        self.output.see(tk.END)
        self.output.update()
