import tkinter as tk
from gui.components import BuilderFrame
from core.builder import PHPBuilder
from utils.logger import Logger


class StaticPHPBuilderApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Static PHP Builder")
        self.logger = Logger()
        self.builder = PHPBuilder(self.logger)
        self.main_frame = BuilderFrame(self.root, self.builder, self.logger)
        self.main_frame.pack(fill="both", expand=True)

    def run(self):
        self.root.mainloop()
