import tkinter as tk
from tkinter import ttk

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure


class ChartWindow:
    def __init__(
        self,
        parent: tk.Tk,
        figure: Figure,
        on_close=None,
        on_hover=None,
    ):
        self.parent = parent
        self.on_close = on_close
        self.win = tk.Toplevel(parent)
        self.win.title("Simulation Chart")
        self.win.geometry("900x600")
        self.win.protocol("WM_DELETE_WINDOW", self.close)

        container = ttk.Frame(self.win, padding=10)
        container.pack(fill=tk.BOTH, expand=True)
        container.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)

        self.canvas = FigureCanvasTkAgg(figure, master=container)
        self.canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")
        if on_hover:
            self.canvas.mpl_connect("motion_notify_event", on_hover)

    def is_open(self) -> bool:
        return bool(self.win and self.win.winfo_exists())

    def close(self):
        if self.win and self.win.winfo_exists():
            self.win.destroy()
        if self.on_close:
            self.on_close()

    def draw(self):
        self.canvas.draw()

    def draw_idle(self):
        self.canvas.draw_idle()
