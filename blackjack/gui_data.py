import tkinter as tk
from tkinter import ttk, font as tkfont
import pandas as pd


class DataWindow:
    def __init__(self, parent: tk.Tk, dataframe: pd.DataFrame, on_close=None):
        self.parent = parent
        self.on_close = on_close
        self.win = tk.Toplevel(parent)
        self.win.title("Simulation Data")
        self.win.geometry("700x500")
        self.win.protocol("WM_DELETE_WINDOW", self.close)

        container = ttk.Frame(self.win, padding=10)
        container.pack(fill=tk.BOTH, expand=True)
        container.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)

        self.table = ttk.Treeview(container, show="headings", height=20)
        self.table.grid(row=0, column=0, sticky="nsew")

        v_scroll = ttk.Scrollbar(container, orient="vertical", command=self.table.yview)
        h_scroll = ttk.Scrollbar(container, orient="horizontal", command=self.table.xview)
        self.table.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)
        v_scroll.grid(row=0, column=1, sticky="ns")
        h_scroll.grid(row=1, column=0, sticky="ew")

        self.update_dataframe(dataframe)

    def is_open(self) -> bool:
        return bool(self.win and self.win.winfo_exists())

    def close(self):
        if self.win and self.win.winfo_exists():
            self.win.destroy()
        if self.on_close:
            self.on_close()

    def update_dataframe(self, dataframe: pd.DataFrame):
        if dataframe is None:
            dataframe = pd.DataFrame()
        self.table.delete(*self.table.get_children())
        if dataframe.empty:
            self.table["columns"] = []
            return

        columns = list(dataframe.columns)
        self.table["columns"] = columns
        font = tkfont.nametofont("TkDefaultFont")
        for col in columns:
            header = col.replace("_", " ").upper()
            values = [header] + [str(v) for v in dataframe[col].tolist()]
            width = max(font.measure(v) for v in values) + 16
            self.table.heading(col, text=header)
            self.table.column(col, width=width, stretch=True, anchor=tk.W)

        for _, row in dataframe.iterrows():
            self.table.insert("", tk.END, values=[row[col] for col in columns])
