import tkinter as tk
from tkinter import ttk, messagebox, font as tkfont
from matplotlib.figure import Figure
import pandas as pd
import sqlite3

from .gui_chart import ChartWindow
from .sys_settings import SimulationSettings
from .sys_simulator import Simulator


class SimulatorGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("CasinoSimulations™ Blackjack")
        self.root.update_idletasks()
        try:
            self.root.state("zoomed")
        except tk.TclError:
            width = self.root.winfo_screenwidth()
            height = self.root.winfo_screenheight()
            self.root.geometry(f"{width}x{height}")
        self.root.rowconfigure(0, weight=3)
        self.root.rowconfigure(1, weight=2)
        self.root.columnconfigure(0, weight=1)
        self.sim = None
        self.available_rounds: list[int] = []

        self.hover_annotation = None
        self._last_plots: list[tuple[int, pd.DataFrame]] = []
        self.results_df = pd.DataFrame()
        self.chart_window: ChartWindow | None = None
        self.loaded_seed_id: str | None = None
        self.loaded_bankroll_df = pd.DataFrame()
        self.loaded_starting_bankroll: float | None = None
        self.loaded_results_df = pd.DataFrame()

        # simulation setting variables
        self.bankroll = tk.DoubleVar(value=1000)
        self.rounds = tk.IntVar(value=1)
        self.hands_per_round = tk.IntVar(value=6)
        self.bet = tk.DoubleVar(value=10)
        self.decks = tk.IntVar(value=6)
        self.payout = tk.StringVar(value="3:2")
        self.dealer = tk.StringVar(value="H17")
        self.das = tk.BooleanVar()
        self.split_aces_logic = tk.StringVar(value="Single")
        self.surrender = tk.StringVar(value="Late")
        self.das_switch_text = tk.StringVar()
        self.strategy_file = tk.StringVar(value="BJ_basicStrategy.json")
        self.database = tk.StringVar(value="simulation.db")
        self.penetration = tk.DoubleVar(value=0.75)
        self.seed_id = tk.StringVar()
        self.test_mode = tk.BooleanVar()
        self.das.trace_add("write", lambda *args: self._update_das_switch_label())
        self.test_mode.trace_add("write", lambda *args: self._update_test_mode_label())

        self.round_filter = tk.StringVar(value="all")

        self._build_widgets()
        self._update_test_mode_label()

    def _build_widgets(self):
        self.top_panel = tk.Frame(self.root)
        self.top_panel.grid(row=0, column=0, sticky="nsew")
        self.top_panel.rowconfigure(2, weight=1)
        self.top_panel.columnconfigure(0, weight=1)

        self.figure = Figure(figsize=(7.5, 4.5), dpi=100, constrained_layout=True)
        self.ax = self.figure.add_subplot(111)
        self.test_mode_label = tk.Label(
            self.top_panel, text="The Simulator is currently in 'Test Mode'", fg="red"
        )

        self._build_chart_controls(self.top_panel)

        data_frame = ttk.Frame(self.top_panel, padding=(20, 10))
        data_frame.grid(row=2, column=0, sticky="nsew", padx=10, pady=6)
        data_frame.rowconfigure(0, weight=1)
        data_frame.columnconfigure(0, weight=1)
        self._build_data_table(data_frame)

        data_footer = tk.Frame(self.top_panel, padx=10)
        data_footer.grid(row=3, column=0, sticky="ew", pady=(0, 6))
        data_footer.columnconfigure(0, weight=1)
        self.view_chart_btn = ttk.Button(
            data_footer,
            text="View Chart",
            command=self.open_chart_window,
            state=tk.DISABLED,
        )
        self.view_chart_btn.grid(row=0, column=1, sticky="e")

        self.bottom_panel = tk.Frame(self.root, padx=10, pady=10)
        self.bottom_panel.grid(row=1, column=0, sticky="nsew")
        self.bottom_panel.rowconfigure(0, weight=1)
        self.bottom_panel.columnconfigure(0, weight=1)

        self.settings_bar = ttk.Frame(self.bottom_panel, padding=(10, 6))
        self._build_settings_bar()
        self.settings_bar.pack(anchor="center", pady=(0, 8))

        footer = ttk.Frame(self.bottom_panel, padding=(10, 8))
        footer.pack(fill=tk.X, pady=(6, 0))
        seed_frame = ttk.Frame(footer)
        seed_frame.pack(side=tk.LEFT)
        ttk.Label(seed_frame, text="Seed").pack(side=tk.LEFT, padx=(0, 6))
        seed_entry = ttk.Entry(seed_frame, textvariable=self.seed_id, width=18)
        seed_entry.pack(side=tk.LEFT)
        ttk.Button(
            seed_frame,
            text="Choose Seed",
            command=self.open_seed_manager,
            padding=(10, 4),
        ).pack(side=tk.LEFT, padx=(6, 0))
        tk.Button(
            footer,
            text="Exit",
            command=self.exit_prompt,
            bg="red",
            fg="black",
            activebackground="red",
            activeforeground="black",
            padx=10,
            pady=2,
        ).pack(side=tk.RIGHT)

    def _build_settings_bar(self):
        base_font = tkfont.nametofont("TkDefaultFont")
        label_font = base_font.copy()
        label_font.configure(size=max(label_font["size"] - 1, 9))
        section_font = base_font.copy()
        section_font.configure(size=max(section_font["size"] - 2, 9), weight="bold")

        self._update_das_switch_label()

        def build_bin(parent: tk.Widget, label: str, control_factory) -> ttk.Frame:
            frame = ttk.Frame(parent, padding=(6, 2))
            ttk.Label(frame, text=label, font=label_font, anchor="center").pack(
                side=tk.TOP, fill=tk.X
            )
            control = control_factory(frame)
            control.pack(side=tk.TOP, pady=(4, 2))
            return frame

        def add_row(title: str, bin_specs: list[tuple[str, callable]]):
            row_frame = ttk.Frame(self.settings_bar)
            row_frame.pack(anchor="center", pady=(2, 6))
            ttk.Label(row_frame, text=title, font=section_font).grid(
                row=0, column=0, sticky="nw", padx=(0, 12)
            )
            bins_frame = ttk.Frame(row_frame)
            bins_frame.grid(row=1, column=0, sticky="ew")
            for col in range(len(bin_specs) * 2 - 1):
                bins_frame.columnconfigure(col, weight=1)

            for idx, (label, factory) in enumerate(bin_specs):
                bin_frame = build_bin(bins_frame, label, factory)
                bin_frame.grid(row=0, column=idx * 2, sticky="nsew", padx=6)
                if idx < len(bin_specs) - 1:
                    ttk.Separator(bins_frame, orient="vertical").grid(
                        row=0, column=idx * 2 + 1, sticky="ns", padx=4, pady=4
                    )

        sim_bins = [
            ("Bankroll", lambda parent: ttk.Entry(parent, textvariable=self.bankroll, width=12)),
            ("Bet", lambda parent: ttk.Entry(parent, textvariable=self.bet, width=12)),
            (
                "Rounds",
                lambda parent: tk.Spinbox(parent, from_=1, to=1000, textvariable=self.rounds, width=6),
            ),
            (
                "Hands/Round",
                lambda parent: tk.Spinbox(parent, from_=1, to=100, textvariable=self.hands_per_round, width=6),
            ),
            ("Decks", lambda parent: tk.Spinbox(parent, from_=1, to=12, textvariable=self.decks, width=6)),
            (
                "Penetration",
                lambda parent: tk.Spinbox(
                    parent,
                    from_=0.25,
                    to=0.95,
                    increment=0.01,
                    textvariable=self.penetration,
                    width=6,
                ),
            ),
        ]

        rules_bins = [
            (
                "Payout",
                lambda parent: ttk.Combobox(
                    parent, textvariable=self.payout, values=["3:2", "6:5"], state="readonly", width=4
                ),
            ),
            (
                "Dealer 17 Logic",
                lambda parent: ttk.Combobox(
                    parent, textvariable=self.dealer, values=["H17", "S17"], state="readonly", width=4
                ),
            ),
            (
                "Double After Split",
                lambda parent: self._build_switch(parent, self.das),
            ),
            (
                "Split Aces Logic",
                lambda parent: ttk.Combobox(
                    parent,
                    textvariable=self.split_aces_logic,
                    values=["Single", "Carnival"],
                    state="readonly",
                    width=8,
                ),
            ),
            (
                "Surrender",
                lambda parent: ttk.Combobox(
                    parent,
                    textvariable=self.surrender,
                    values=["Early", "Late", "None"],
                    state="readonly",
                    width=7,
                ),
            ),
        ]

        data_bins = [
            (
                "Strategy",
                lambda parent: ttk.Combobox(
                    parent,
                    textvariable=self.strategy_file,
                    values=[self.strategy_file.get()],
                    state="readonly",
                    width=max(18, len(self.strategy_file.get())),
                ),
            ),
            (
                "Database",
                lambda parent: ttk.Combobox(
                    parent,
                    textvariable=self.database,
                    values=[self.database.get()],
                    state="readonly",
                    width=max(18, len(self.database.get())),
                ),
            ),
            ("Test Mode", lambda parent: self._build_switch(parent, self.test_mode)),
        ]

        add_row("SIMULATION SETTINGS", sim_bins)
        add_row("GAME RULES", rules_bins)
        add_row("DATA", data_bins)

    def _update_das_switch_label(self):
        self.das_switch_text.set("On" if self.das.get() else "Off")

    def _update_test_mode_label(self):
        if self.test_mode.get():
            self.test_mode_label.grid(
                row=0,
                column=0,
                sticky="ew",
                in_=self.top_panel,
                pady=(4, 0),
                padx=10,
            )
        else:
            self.test_mode_label.grid_forget()

    def _build_chart_controls(self, parent: tk.Widget):
        controls = ttk.Frame(parent, padding=(10, 4))
        controls.grid(row=1, column=0, sticky="ew")
        for idx in range(8):
            controls.columnconfigure(idx, weight=0)
        controls.columnconfigure(2, weight=1)

        ttk.Label(controls, text="ROUND VIEW", font=(None, 9, "bold")).grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )
        ttk.Label(
            controls, text="Enter 'all' or a list/range (e.g. 1,3-5):"
        ).grid(row=0, column=1, sticky="w")
        entry = ttk.Entry(controls, textvariable=self.round_filter, width=20)
        entry.grid(row=0, column=2, sticky="w", padx=(6, 6))
        entry.bind("<Return>", lambda event: self.update_graph())
        ttk.Button(controls, text="Apply", command=self.update_graph).grid(
            row=0, column=3, padx=(0, 6)
        )
        ttk.Button(controls, text="Show All", command=self._show_all_rounds).grid(
            row=0, column=4, padx=(0, 12)
        )
        self.run_btn = ttk.Button(controls, text="Run", command=self.run_simulation)
        self.run_btn.grid(row=0, column=5, padx=(0, 6))
        self.save_btn = ttk.Button(
            controls, text="Save", command=self.save_results, state=tk.DISABLED
        )
        self.save_btn.grid(row=0, column=6, padx=(0, 6))
        self.discard_btn = ttk.Button(
            controls, text="Discard", command=self.discard_results, state=tk.DISABLED
        )
        self.discard_btn.grid(row=0, column=7)

    def _build_data_table(self, parent: tk.Widget):
        style = ttk.Style(parent)
        style.configure(
            "Data.Treeview",
            rowheight=24,
            borderwidth=1,
            relief="solid",
            background="white",
            fieldbackground="white",
            bordercolor="#c7c7c7",
            lightcolor="#c7c7c7",
            darkcolor="#c7c7c7",
        )
        style.configure(
            "Data.Treeview.Heading",
            font=(None, 9, "bold"),
            borderwidth=1,
            relief="solid",
        )
        style.map(
            "Data.Treeview",
            background=[("selected", "#dbe6f5")],
            foreground=[("selected", "#000000")],
        )

        table_frame = ttk.Frame(parent)
        table_frame.grid(row=0, column=0, sticky="nsew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

        self.data_tree = ttk.Treeview(
            table_frame,
            show="headings",
            style="Data.Treeview",
            selectmode="browse",
        )
        self.data_tree.grid(row=0, column=0, sticky="nsew")
        v_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.data_tree.yview)
        v_scroll.grid(row=0, column=1, sticky="ns")
        self.data_tree.configure(yscrollcommand=v_scroll.set)
        self.data_tree.tag_configure("odd_row", background="white")
        self.data_tree.tag_configure("even_row", background="#f6f6f6")

    def _populate_data_table(self, dataframe: pd.DataFrame):
        self.data_tree.delete(*self.data_tree.get_children())
        if dataframe.empty:
            return

        columns = list(dataframe.columns)
        self.data_tree["columns"] = columns

        font = tkfont.nametofont("TkDefaultFont")
        widths = []
        for col in columns:
            max_text = max([str(col)] + [str(v) for v in dataframe[col].tolist()], key=len)
            widths.append(font.measure(max_text) + 24)

        self.data_tree.update_idletasks()
        available_width = max(self.data_tree.winfo_width(), self.root.winfo_width()) - 40
        if available_width <= 0:
            available_width = int(self.root.winfo_screenwidth() * 0.9)

        total_width = sum(widths)
        min_width = 60
        if total_width > available_width:
            scale = available_width / total_width
            widths = [max(min_width, int(width * scale)) for width in widths]

        for col, width in zip(columns, widths):
            self.data_tree.heading(col, text=col, anchor=tk.E)
            self.data_tree.column(col, anchor=tk.E, width=width, minwidth=min_width, stretch=True)

        for idx, (_, row) in enumerate(dataframe.iterrows()):
            values = ["" if pd.isna(row[col]) else row[col] for col in columns]
            tag = "even_row" if idx % 2 == 0 else "odd_row"
            self.data_tree.insert("", tk.END, values=values, tags=(tag,))

    def _build_switch(self, parent: tk.Widget, variable: tk.BooleanVar) -> tk.Widget:
        base_bg = parent.winfo_toplevel().cget("bg")
        frame = tk.Frame(parent, bg=base_bg, highlightthickness=0, bd=0)
        canvas = tk.Canvas(
            frame,
            width=48,
            height=26,
            highlightthickness=0,
            bg=base_bg,
            bd=0,
            relief=tk.FLAT,
        )
        canvas.pack()

        def redraw(*_):
            canvas.delete("all")
            is_on = variable.get()
            bg_color = "#4cd964" if is_on else "#d5d5d5"
            knob_x = 26 if is_on else 10
            canvas.create_rectangle(2, 8, 46, 18, outline="", fill=bg_color, width=0)
            canvas.create_oval(knob_x - 10, 6, knob_x + 10, 26, fill="white", outline="#aaaaaa")

        def toggle(event=None):
            variable.set(not variable.get())
            redraw()

        canvas.bind("<Button-1>", toggle)
        variable.trace_add("write", redraw)
        redraw()
        return frame

    def _gather_settings(self) -> SimulationSettings:
        return SimulationSettings(
            rounds=self.rounds.get(),
            hands_per_round=self.hands_per_round.get(),
            bankroll=float(self.bankroll.get()),
            blackjack_payout=1.5 if self.payout.get() == "3:2" else 1.2,
            double_after_split=self.das.get(),
            split_aces_logic=self.split_aces_logic.get(),
            surrender=self.surrender.get(),
            bet_amount=float(self.bet.get()),
            num_decks=self.decks.get(),
            hit_soft_17=self.dealer.get() == "H17",
            penetration=float(self.penetration.get()),
            strategy_file=self.strategy_file.get(),
            database=self.database.get(),
            test_mode=self.test_mode.get(),
        )

    def open_seed_manager(self):
        if hasattr(self, "seed_win") and self.seed_win.winfo_exists():
            self.seed_win.lift()
            return
        self.seed_win = tk.Toplevel(self.root)
        self.seed_win.title("Seeds")
        frame = ttk.Frame(self.seed_win, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.columnconfigure(0, weight=1)

        ttk.Label(frame, text="Seed ID").grid(row=0, column=0, sticky="w", pady=(0, 6))
        ttk.Entry(frame, textvariable=self.seed_id, width=18).grid(
            row=0, column=1, sticky="w", pady=(0, 6)
        )

        self.seed_tree = ttk.Treeview(
            frame,
            columns=("seed_id", "created_at", "rounds", "hands", "pl", "favorite"),
            show="headings",
            height=8,
        )
        for col, heading, width in [
            ("seed_id", "Seed ID", 90),
            ("created_at", "Saved At", 150),
            ("rounds", "Rounds", 70),
            ("hands", "Hands", 70),
            ("pl", "Total P/L", 90),
            ("favorite", "Favorite", 70),
        ]:
            self.seed_tree.heading(col, text=heading)
            self.seed_tree.column(col, width=width, anchor=tk.W)
        self.seed_tree.grid(row=1, column=0, columnspan=2, sticky="nsew")
        frame.rowconfigure(1, weight=1)

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(btn_frame, text="Run Seed", command=self.run_seed).pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="Toggle Favorite", command=self.toggle_seed_favorite).pack(
            side=tk.LEFT, padx=(6, 0)
        )
        ttk.Button(btn_frame, text="Close", command=self.seed_win.destroy).pack(
            side=tk.RIGHT
        )

        self.seed_tree.bind("<Double-1>", lambda *_: self._select_seed_from_tree())
        self._refresh_seed_tree()

    def run_simulation(self):
        if self.sim:
            self.sim.close()
        self.loaded_seed_id = None
        self.loaded_bankroll_df = pd.DataFrame()
        self.loaded_starting_bankroll = None
        self.loaded_results_df = pd.DataFrame()
        settings = self._gather_settings()
        self.sim = Simulator(settings)
        try:
            self.sim.run()
        except Exception as exc:  # noqa: BLE001 - surface runtime issues to the user
            if self.sim:
                self.sim.close()
                self.sim = None
            messagebox.showerror(
                "Simulation Error",
                "An error occurred while launching or running the simulation.\n"
                f"Details: {exc}",
            )
            return
        self.available_rounds = list(range(1, self.rounds.get() + 1))
        self.round_filter.set("all")
        self.update_graph()
        self.update_table()
        if not self.sim.results_available:
            messagebox.showwarning(
                "No Results", "No hands were played. Check bankroll and bet settings."
            )
            self._clear_plot()
            self._clear_table()
            self.available_rounds = []
            self.round_filter.set("all")
            self.save_btn.config(state=tk.DISABLED)
            self.discard_btn.config(state=tk.DISABLED)
            return
        if self.test_mode.get():
            self.save_btn.config(state=tk.DISABLED)
        else:
            self.save_btn.config(state=tk.NORMAL)
        self.discard_btn.config(state=tk.NORMAL)

    def update_graph(self):
        if self.sim:
            df = pd.read_sql_query(
                """
                SELECT round_number, hand, bankroll
                FROM temp_bankroll
                ORDER BY round_number, hand
                """,
                self.sim.conn,
            )
            starting_bankroll = self.bankroll.get()
        elif not self.loaded_bankroll_df.empty:
            df = self.loaded_bankroll_df.copy()
            starting_bankroll = self.loaded_starting_bankroll or 0.0
        else:
            self._clear_plot()
            return

        if df.empty:
            self._clear_plot()
            return

        selected_rounds = self._parse_round_selection()
        if not selected_rounds:
            messagebox.showwarning("Invalid Selection", "No valid rounds were selected.")
            self._show_all_rounds()
            return

        df = df[df["round_number"].isin(selected_rounds)].copy()
        if df.empty:
            self._clear_plot()
            return

        self._plot_bankroll(df, starting_bankroll, selected_rounds)

    def _plot_bankroll(
        self, df: pd.DataFrame, starting_bankroll: float, selected_rounds: list[int]
    ):
        df["pl"] = df["bankroll"] - starting_bankroll

        self.ax.clear()
        self.ax.set_xlabel("Hand #")
        self.ax.set_ylabel("P/L ($)")
        self.ax.set_title("Total Profit/Loss", fontname="Verdana", fontsize=18, fontweight="bold")
        self.ax.axhline(0, color="gray", linewidth=0.5)
        self.ax.grid(True, axis="x", color="#a05f5f", alpha=0.25)
        self.ax.grid(True, axis="y", color="#5f748c", alpha=0.25)

        self._last_plots = []
        xmin = 0
        xmax = max(100, df["hand"].max())
        ymin = min(df["pl"].min(), -starting_bankroll)
        ymax = max(df["pl"].max(), starting_bankroll)

        for round_number in sorted(selected_rounds):
            round_df = df[df["round_number"] == round_number]
            if round_df.empty:
                continue
            color = self.ax._get_lines.get_next_color()
            self.ax.plot(
                round_df["hand"],
                round_df["pl"],
                label=f"Round {round_number}",
                color=color,
            )
            self._last_plots.append(
                (round_number, round_df[["hand", "pl"]].reset_index(drop=True))
            )

        self.ax.set_xlim(xmin, xmax)
        self.ax.set_ylim(ymin, ymax)
        if len(selected_rounds) > 1:
            self.ax.legend()

        summary_round = max(selected_rounds)
        summary_df = df[df["round_number"] == summary_round]
        if not summary_df.empty:
            hands_played = int(summary_df["hand"].max())
            ending_bankroll = float(summary_df["bankroll"].iloc[-1])
            final_pl = float(summary_df["pl"].iloc[-1])
            summary_text = (
                f"Round: {summary_round}\n"
                f"Hands Played: {hands_played}\n"
                f"Ending Bankroll: ${ending_bankroll:,.2f}\n"
                f"Final P/L: ${final_pl:,.2f}"
            )
            self.ax.text(
                0.02,
                0.98,
                summary_text,
                transform=self.ax.transAxes,
                fontsize=12,
                fontfamily="Verdana",
                verticalalignment="top",
                bbox=dict(boxstyle="round", facecolor="white", alpha=0.85),
            )

        self._draw_chart_idle()

    def _clear_plot(self):
        self.ax.clear()
        if self.hover_annotation:
            self.hover_annotation.set_visible(False)
        self._last_plots = []
        self._draw_chart()

    def _clear_table(self):
        self.results_df = pd.DataFrame()
        self.view_chart_btn.state(["disabled"])
        self.data_tree.delete(*self.data_tree.get_children())
        self.loaded_seed_id = None
        self.loaded_bankroll_df = pd.DataFrame()
        self.loaded_starting_bankroll = None

    def open_chart_window(self):
        if self.chart_window and self.chart_window.is_open():
            self.chart_window.win.lift()
            self.chart_window.draw_idle()
            return
        self.chart_window = ChartWindow(
            self.root,
            self.figure,
            on_close=lambda: setattr(self, "chart_window", None),
            on_hover=self._on_hover,
        )
        self._draw_chart_idle()

    def _parse_round_selection(self) -> list[int]:
        raw = self.round_filter.get().strip().lower()
        if not raw or raw == "all":
            return self.available_rounds

        selected: set[int] = set()
        for part in raw.replace(" ", "").split(","):
            if not part:
                continue
            if "-" in part:
                try:
                    start, end = part.split("-", 1)
                    start_val, end_val = int(start), int(end)
                    if start_val > end_val:
                        start_val, end_val = end_val, start_val
                    selected.update(range(start_val, end_val + 1))
                except ValueError:
                    continue
            else:
                try:
                    selected.add(int(part))
                except ValueError:
                    continue

        return [t for t in sorted(selected) if t in self.available_rounds]

    def _show_all_rounds(self):
        self.round_filter.set("all")
        self.update_graph()

    def _on_hover(self, event):
        if not hasattr(self, "_last_plots") or not self._last_plots or event.inaxes != self.ax:
            if self.hover_annotation:
                self.hover_annotation.set_visible(False)
                self._draw_chart_idle()
            return

        if event.xdata is None:
            return

        closest = None
        for round_number, data in self._last_plots:
            idx = (data["hand"] - event.xdata).abs().idxmin()
            point = data.loc[idx]
            if closest is None or abs(point["hand"] - event.xdata) < abs(closest[1]["hand"] - event.xdata):
                closest = (round_number, point)

        if not closest:
            return

        round_number, point = closest
        text = f"Round {round_number}: Hand {int(point['hand'])}, P/L {point['pl']:.2f}"

        if not self.hover_annotation:
            self.hover_annotation = self.ax.annotate(
                text,
                xy=(point["hand"], point["pl"]),
                xytext=(12, 12),
                textcoords="offset points",
                bbox=dict(boxstyle="round", fc="w", ec="#888", alpha=0.9),
            )
        else:
            self.hover_annotation.xy = (point["hand"], point["pl"])
            self.hover_annotation.set_text(text)
            self.hover_annotation.set_visible(True)

        self._draw_chart_idle()

    def _draw_chart(self):
        if self.chart_window and self.chart_window.is_open():
            self.chart_window.draw()

    def _draw_chart_idle(self):
        if self.chart_window and self.chart_window.is_open():
            self.chart_window.draw_idle()

    def update_table(self):
        if self.sim:
            df = pd.read_sql_query(
                """
                SELECT
                    round_number,
                    hands,
                    wager,
                    open_bankroll,
                    close_bankroll,
                    player_hand_a,
                    player_hand_b,
                    player_hand_c,
                    player_hand_d,
                    dealer_cards,
                    cards_dealt,
                    running_count,
                    true_count
                FROM temp_results
                ORDER BY round_number, hands
                """,
                self.sim.conn,
            )
        elif not self.loaded_results_df.empty:
            df = self.loaded_results_df.copy()
        else:
            self._clear_table()
            return

        if df.empty:
            self._clear_table()
            return

        df["true_count"] = df["true_count"].round(1)
        df.rename(
            columns={
                "round_number": "Round #",
                "hands": "Hand #",
                "wager": "Wager",
                "open_bankroll": "Open Bankroll",
                "close_bankroll": "Close Bankroll",
                "player_hand_a": "Player Hand A",
                "player_hand_b": "Player Hand B",
                "player_hand_c": "Player Hand C",
                "player_hand_d": "Player Hand D",
                "dealer_cards": "Dealer Cards",
                "cards_dealt": "Cards Dealt",
                "running_count": "Running Count",
                "true_count": "True Count",
            },
            inplace=True,
        )
        df["True Count"] = df["True Count"].map(lambda val: f"{val:.1f}")
        column_order = [
            "Round #",
            "Hand #",
            "Wager",
            "Running Count",
            "True Count",
            "Cards Dealt",
            "Open Bankroll",
            "Close Bankroll",
            "Dealer Cards",
            "Player Hand A",
            "Player Hand B",
            "Player Hand C",
            "Player Hand D",
        ]
        self.results_df = df[column_order]
        self.view_chart_btn.state(["!disabled"])
        self._populate_data_table(self.results_df)

    def _refresh_seed_tree(self):
        if not hasattr(self, "seed_tree"):
            return
        for item in self.seed_tree.get_children():
            self.seed_tree.delete(item)
        for seed in self._fetch_saved_seeds():
            favorite = "★" if seed["favorite"] else ""
            self.seed_tree.insert(
                "",
                tk.END,
                values=(
                    seed["seed_id"],
                    seed["created_at"],
                    seed["total_rounds"],
                    seed["total_hands"],
                    f"${seed['total_pl']:,.2f}",
                    favorite,
                ),
            )

    def _fetch_saved_seeds(self):
        db_path = self.database.get()
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        self._ensure_seed_tables(conn)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT seed_id, created_at, total_rounds, total_hands, total_pl, favorite
            FROM saved_seeds
            ORDER BY created_at DESC
            """
        )
        rows = [dict(row) for row in cur.fetchall()]
        conn.close()
        return rows

    def _select_seed_from_tree(self):
        selection = self.seed_tree.selection()
        if not selection:
            return
        values = self.seed_tree.item(selection[0], "values")
        if values:
            self.seed_id.set(values[0])

    def toggle_seed_favorite(self):
        selection = self.seed_tree.selection()
        if not selection:
            messagebox.showwarning("No Selection", "Select a seed to toggle favorite.")
            return
        seed_id = self.seed_tree.item(selection[0], "values")[0]
        db_path = self.database.get()
        conn = sqlite3.connect(db_path)
        self._ensure_seed_tables(conn)
        cur = conn.cursor()
        cur.execute(
            "UPDATE saved_seeds SET favorite = CASE favorite WHEN 1 THEN 0 ELSE 1 END WHERE seed_id = ?",
            (seed_id,),
        )
        conn.commit()
        conn.close()
        self._refresh_seed_tree()

    def run_seed(self):
        seed_id = self.seed_id.get().strip()
        if not seed_id:
            messagebox.showwarning("No Seed", "Enter a seed ID to run.")
            return
        self.load_seed(seed_id)
        if hasattr(self, "seed_win") and self.seed_win.winfo_exists():
            self.seed_win.destroy()

    def load_seed(self, seed_id: str):
        db_path = self.database.get()
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        self._ensure_seed_tables(conn)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT seed_id, starting_bankroll
            FROM saved_seeds
            WHERE seed_id = ?
            """,
            (seed_id,),
        )
        seed_row = cur.fetchone()
        if not seed_row:
            conn.close()
            messagebox.showwarning("Missing Seed", "Seed ID not found in saved seeds.")
            return

        bankroll_df = pd.read_sql_query(
            """
            SELECT round_number, hand, bankroll
            FROM saved_seed_bankroll
            WHERE seed_id = ?
            ORDER BY round_number, hand
            """,
            conn,
            params=(seed_id,),
        )
        results_df = pd.read_sql_query(
            """
            SELECT
                round_number,
                hand AS hands,
                wager,
                open_bankroll,
                close_bankroll,
                player_hand_a,
                player_hand_b,
                player_hand_c,
                player_hand_d,
                dealer_cards,
                cards_dealt,
                running_count,
                true_count
            FROM saved_seed_results
            WHERE seed_id = ?
            ORDER BY round_number, hand
            """,
            conn,
            params=(seed_id,),
        )
        conn.close()

        if bankroll_df.empty or results_df.empty:
            messagebox.showwarning("No Data", "No saved data found for this seed.")
            return

        if self.sim:
            self.sim.close()
            self.sim = None
        self.loaded_seed_id = seed_id
        self.loaded_bankroll_df = bankroll_df
        self.loaded_starting_bankroll = float(seed_row["starting_bankroll"])
        self.loaded_results_df = results_df

        self.available_rounds = sorted(bankroll_df["round_number"].unique().tolist())
        self.round_filter.set("all")
        self.update_graph()
        self.update_table()
        self.save_btn.config(state=tk.DISABLED)
        self.discard_btn.config(state=tk.DISABLED)

    def _ensure_seed_tables(self, conn: sqlite3.Connection):
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS saved_seeds (
                seed_id TEXT PRIMARY KEY,
                created_at TEXT,
                total_rounds INTEGER,
                total_hands INTEGER,
                total_pl REAL,
                starting_bankroll REAL,
                favorite INTEGER DEFAULT 0
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS saved_seed_results (
                seed_id TEXT,
                round_number INTEGER,
                hand INTEGER,
                wager REAL,
                open_bankroll REAL,
                close_bankroll REAL,
                player_hand_a TEXT,
                player_hand_b TEXT,
                player_hand_c TEXT,
                player_hand_d TEXT,
                dealer_cards TEXT,
                cards_dealt INTEGER,
                running_count INTEGER,
                true_count REAL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS saved_seed_bankroll (
                seed_id TEXT,
                round_number INTEGER,
                hand INTEGER,
                bankroll REAL
            )
            """
        )
        conn.commit()

    def save_results(self):
        if self.sim:
            seed_id = self.sim.save_results()
            self.sim.close()
            self.sim = None
            self.seed_id.set(seed_id)
            self._refresh_seed_tree()
            messagebox.showinfo("Saved", f"Results saved to Seed {seed_id}")
            self.save_btn.config(state=tk.DISABLED)
            self.discard_btn.config(state=tk.DISABLED)
            self.update_table()

    def discard_results(self):
        if self.sim:
            self.sim.discard_results()
            self.sim.close()
            self.sim = None
            messagebox.showinfo("Discarded", "Results discarded")
            self.save_btn.config(state=tk.DISABLED)
            self.discard_btn.config(state=tk.DISABLED)
            self.update_table()
            self._clear_plot()
            self.available_rounds = []
            self.round_filter.set("all")

    def has_unsaved_data(self) -> bool:
        if not self.sim:
            return False
        cur = self.sim.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM temp_results")
        return cur.fetchone()[0] > 0

    def exit_prompt(self):
        if self.has_unsaved_data():
            win = tk.Toplevel(self.root)
            win.title("Exit")
            tk.Label(win, text="Save data to permanent tables before exiting?").pack(padx=10, pady=10)
            btn_frame = tk.Frame(win)
            btn_frame.pack(pady=5)
            tk.Button(btn_frame, text="Save", command=lambda: self._exit_and_save(win)).pack(side=tk.LEFT, padx=5)
            tk.Button(btn_frame, text="Don't Save", command=lambda: self._exit_without_save(win)).pack(side=tk.LEFT, padx=5)
        else:
            self._exit_without_save()

    def _exit_and_save(self, win=None):
        if win:
            win.destroy()
        if self.sim:
            self.save_results()
        self.root.destroy()

    def _exit_without_save(self, win=None):
        if win:
            win.destroy()
        if self.sim:
            self.sim.close()
        self.root.destroy()

    def run(self):
        self.root.mainloop()
