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

        self.table = tk.Text(container, wrap="none", height=20)
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
        self.table.configure(state=tk.NORMAL)
        self.table.delete("1.0", tk.END)
        if dataframe.empty:
            self.table.configure(state=tk.DISABLED)
            return

        columns = list(dataframe.columns)
        font = tkfont.nametofont("TkFixedFont")
        self.table.configure(font=font)

        col_widths = {}
        for col in columns:
            values = [str(col)] + [str(v) for v in dataframe[col].tolist()]
            col_widths[col] = max(len(v) for v in values) + 2

        header_line = ""
        col_positions = []
        for col in columns:
            start = len(header_line)
            header_line += str(col).ljust(col_widths[col])
            col_positions.append((col, start))
        header_line = header_line.rstrip()
        self.table.insert(tk.END, header_line + "\n")
        self.table.insert(tk.END, "-" * len(header_line) + "\n")

        self.table.tag_configure("dealer_up", foreground="red")
        self.table.tag_configure("player_initial", foreground="blue")

        line_number = 3
        for _, row in dataframe.iterrows():
            line = ""
            for col in columns:
                cell = "" if pd.isna(row[col]) else str(row[col])
                line += cell.ljust(col_widths[col])
            line = line.rstrip()
            self.table.insert(tk.END, line + "\n")

            for col, start in col_positions:
                cell = "" if pd.isna(row[col]) else str(row[col])
                if not cell:
                    continue
                if col == "Dealer Cards":
                    up_card = self._extract_cards(cell, 1)
                    if up_card:
                        offset = cell.find(up_card[0])
                        if offset >= 0:
                            self._tag_range(
                                line_number, start + offset, len(up_card[0]), "dealer_up"
                            )
                if col.startswith("Player Hand"):
                    cards = self._extract_cards(cell, 2)
                    for card in cards:
                        offset = cell.find(card)
                        if offset >= 0:
                            self._tag_range(
                                line_number, start + offset, len(card), "player_initial"
                            )
            line_number += 1

        self.table.configure(state=tk.DISABLED)

    def _extract_cards(self, text: str, count: int) -> list[str]:
        card_section = text.split("|", 1)[0].strip()
        cards = [c.strip() for c in card_section.split(",") if c.strip()]
        return cards[:count]

    def _tag_range(self, line_number: int, col_start: int, length: int, tag: str) -> None:
        start_index = f"{line_number}.{col_start}"
        end_index = f"{line_number}.{col_start + length}"
        self.table.tag_add(tag, start_index, end_index)
