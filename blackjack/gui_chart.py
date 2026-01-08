import tkinter as tk
from tkinter import ttk, font as tkfont
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure


class ChartWindow:
    def __init__(
        self,
        parent: tk.Tk,
        figure: Figure,
        on_close=None,
        on_hover=None,
        round_var: tk.StringVar | None = None,
        on_apply=None,
        on_show_all=None,
    ):
        self.win = tk.Toplevel(parent)
        self.win.title("Chart")
        self._on_close = on_close
        self._on_apply = on_apply
        self._on_show_all = on_show_all
        self.round_var = round_var or tk.StringVar(value="all")
        self._round_values: list[str] = ["all"]
        self.win.protocol("WM_DELETE_WINDOW", self.close)

        container = ttk.Frame(self.win, padding=(10, 10))
        container.grid(row=0, column=0, sticky="nsew")
        self.win.columnconfigure(0, weight=1)
        self.win.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)

        self.canvas = FigureCanvasTkAgg(figure, master=container)
        self.canvas.draw()
        self.canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")
        if on_hover:
            self.canvas.mpl_connect("motion_notify_event", on_hover)

        controls = ttk.Frame(container, padding=(0, 8))
        controls.grid(row=1, column=0, sticky="ew")
        controls.columnconfigure(0, weight=1)

        control_inner = ttk.Frame(controls)
        control_inner.grid(row=0, column=0)

        label_font = tkfont.Font(family="Verdana", size=11, weight="bold")
        ttk.Label(control_inner, text="ROUND VIEW", font=label_font).grid(
            row=0, column=0, padx=(0, 8)
        )
        self.round_combo = ttk.Spinbox(
            control_inner,
            textvariable=self.round_var,
            values=self._round_values,
            width=8,
            command=self.apply_round_filter,
        )
        self.round_combo.grid(row=0, column=1, padx=(0, 8))
        self.round_combo.bind("<Return>", lambda *_: self.apply_round_filter())
        ttk.Button(control_inner, text="Show All", command=self.show_all).grid(
            row=0, column=2
        )

    def set_round_values(self, rounds: list[int]):
        self._round_values = ["all"] + [str(r) for r in sorted(rounds)]
        self.round_combo["values"] = self._round_values
        if self.round_var.get() not in self._round_values:
            self.round_var.set("all")

    def apply_round_filter(self):
        if self._on_apply:
            self._on_apply()

    def show_all(self):
        self.round_var.set("all")
        if self._on_show_all:
            self._on_show_all()

    def draw(self):
        self.canvas.draw()

    def draw_idle(self):
        self.canvas.draw_idle()

    def is_open(self) -> bool:
        return bool(self.win.winfo_exists())

    def close(self):
        if self._on_close:
            self._on_close()
        if self.win.winfo_exists():
            self.win.destroy()
