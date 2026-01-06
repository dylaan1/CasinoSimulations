import tkinter as tk
from tkinter import ttk, messagebox, font as tkfont
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import pandas as pd

from .gui_data import DataWindow
from .settings import SimulationSettings
from .simulator import Simulator


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
        self.available_trials: list[int] = []

        self.hover_annotation = None
        self._last_plots: list[tuple[int, pd.DataFrame]] = []
        self.results_df = pd.DataFrame()
        self.data_window: DataWindow | None = None

        # simulation setting variables
        self.bankroll = tk.DoubleVar(value=1000)
        self.trials = tk.IntVar(value=1)
        self.rounds_per_trial = tk.IntVar(value=1)
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
        self.seed = tk.StringVar()
        self.test_mode = tk.BooleanVar()
        self.das.trace_add("write", lambda *args: self._update_das_switch_label())
        self.test_mode.trace_add("write", lambda *args: self._update_test_mode_label())

        self.trial_filter = tk.StringVar(value="all")

        self._build_widgets()
        self._update_test_mode_label()

    def _build_widgets(self):
        self.top_panel = tk.Frame(self.root)
        self.top_panel.grid(row=0, column=0, sticky="nsew")
        self.top_panel.rowconfigure(2, weight=1)
        self.top_panel.columnconfigure(0, weight=1)

        fig = Figure(figsize=(6, 4))
        self.ax = fig.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(fig, master=self.top_panel)
        self.test_mode_label = tk.Label(
            self.top_panel, text="The Simulator is currently in 'Test Mode'", fg="red"
        )

        self._build_chart_controls(self.top_panel)

        chart_frame = tk.Frame(self.top_panel, padx=10, pady=6)
        chart_frame.grid(row=2, column=0, sticky="nsew")
        chart_frame.rowconfigure(0, weight=1)
        chart_frame.columnconfigure(0, weight=1)
        self.canvas.get_tk_widget().pack(in_=chart_frame, fill=tk.BOTH, expand=True)
        self.canvas.mpl_connect("motion_notify_event", self._on_hover)

        chart_footer = tk.Frame(self.top_panel, padx=10, pady=(0, 6))
        chart_footer.grid(row=3, column=0, sticky="ew")
        chart_footer.columnconfigure(0, weight=1)
        self.view_data_btn = ttk.Button(
            chart_footer,
            text="View Data",
            command=self.open_data_window,
            state=tk.DISABLED,
        )
        self.view_data_btn.grid(row=0, column=1, sticky="e")

        self.bottom_panel = tk.Frame(self.root, padx=10, pady=10)
        self.bottom_panel.grid(row=1, column=0, sticky="nsew")
        self.bottom_panel.rowconfigure(0, weight=1)
        self.bottom_panel.columnconfigure(0, weight=1)

        self.settings_bar = ttk.Frame(self.bottom_panel, padding=(10, 6))
        self._build_settings_bar()
        self.settings_bar.pack(anchor="center", pady=(0, 8))

        footer = tk.Frame(self.bottom_panel)
        footer.pack(fill=tk.X)
        ttk.Button(footer, text="Seed", command=self.open_settings).pack(side=tk.LEFT)
        tk.Button(
            footer,
            text="Exit",
            command=self.exit_prompt,
            bg="red",
            fg="white",
            activebackground="red",
            activeforeground="white",
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
            ("Trials", lambda parent: tk.Spinbox(parent, from_=1, to=1000, textvariable=self.trials, width=6)),
            (
                "Rounds/Trial",
                lambda parent: tk.Spinbox(parent, from_=1, to=100, textvariable=self.rounds_per_trial, width=6),
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

        ttk.Label(controls, text="TRIAL VIEW", font=(None, 9, "bold")).grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )
        ttk.Label(
            controls, text="Enter 'all' or a list/range (e.g. 1,3-5):"
        ).grid(row=0, column=1, sticky="w")
        entry = ttk.Entry(controls, textvariable=self.trial_filter, width=20)
        entry.grid(row=0, column=2, sticky="w", padx=(6, 6))
        entry.bind("<Return>", lambda event: self.update_graph())
        ttk.Button(controls, text="Apply", command=self.update_graph).grid(
            row=0, column=3, padx=(0, 6)
        )
        ttk.Button(controls, text="Show All", command=self._show_all_trials).grid(
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
            trials=self.trials.get(),
            rounds_per_trial=self.rounds_per_trial.get(),
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
            seed=int(self.seed.get()) if self.seed.get() else None,
            test_mode=self.test_mode.get(),
        )

    def open_settings(self):
        if hasattr(self, "settings_win") and self.settings_win.winfo_exists():
            self.settings_win.lift()
            return
        self.settings_win = tk.Toplevel(self.root)
        self.settings_win.title("Seed")
        frame = ttk.Frame(self.settings_win, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Seed").grid(row=0, column=0, sticky="e", padx=(0, 6))
        ttk.Entry(frame, textvariable=self.seed, width=20).grid(row=0, column=1, sticky="w")
        ttk.Button(frame, text="Close", command=self.settings_win.destroy).grid(
            row=1, column=0, columnspan=2, pady=(10, 0)
        )

    def run_simulation(self):
        if self.sim:
            self.sim.close()
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
        self.available_trials = list(range(1, self.trials.get() + 1))
        self.trial_filter.set("all")
        self.update_graph()
        self.update_table()
        if not self.sim.results_available:
            messagebox.showwarning(
                "No Results", "No hands were played. Check bankroll and bet settings."
            )
            self._clear_plot()
            self._clear_table()
            self.available_trials = []
            self.trial_filter.set("all")
            self.save_btn.config(state=tk.DISABLED)
            self.discard_btn.config(state=tk.DISABLED)
            return
        if self.test_mode.get():
            self.save_btn.config(state=tk.DISABLED)
        else:
            self.save_btn.config(state=tk.NORMAL)
        self.discard_btn.config(state=tk.NORMAL)

    def update_graph(self):
        if not self.sim:
            self._clear_plot()
            return
        df = pd.read_sql_query(
            "SELECT trial, hand, bankroll FROM temp_bankroll ORDER BY trial, hand",
            self.sim.conn,
        )
        if df.empty:
            self._clear_plot()
            return

        selected_trials = self._parse_trial_selection()
        if not selected_trials:
            messagebox.showwarning("Invalid Selection", "No valid trials were selected.")
            self._show_all_trials()
            return

        df = df[df["trial"].isin(selected_trials)].copy()
        if df.empty:
            self._clear_plot()
            return

        df["pl"] = df["bankroll"] - self.bankroll.get()

        self.ax.clear()
        self.ax.set_xlabel("# of Hands Played")
        self.ax.set_ylabel("P/L ($)")
        self.ax.set_title("Total Profit/Loss", fontname="Verdana", fontsize=18, fontweight="bold")
        self.ax.axhline(0, color="gray", linewidth=0.5)
        self.ax.grid(True, axis="x", color="#a05f5f", alpha=0.25)
        self.ax.grid(True, axis="y", color="#5f748c", alpha=0.25)

        self._last_plots = []
        xmin = 0
        xmax = max(100, df["hand"].max())
        ymin = min(df["pl"].min(), -self.bankroll.get())
        ymax = max(df["pl"].max(), self.bankroll.get())

        for trial in sorted(selected_trials):
            trial_df = df[df["trial"] == trial]
            if trial_df.empty:
                continue
            color = self.ax._get_lines.get_next_color()
            self.ax.plot(trial_df["hand"], trial_df["pl"], label=f"Trial {trial}", color=color)
            self._last_plots.append((trial, trial_df[["hand", "pl"]].reset_index(drop=True)))

        self.ax.set_xlim(xmin, xmax)
        self.ax.set_ylim(ymin, ymax)
        if len(selected_trials) > 1:
            self.ax.legend()

        summary_trial = max(selected_trials)
        summary_df = df[df["trial"] == summary_trial]
        if not summary_df.empty:
            hands_played = int(summary_df["hand"].max())
            ending_bankroll = float(summary_df["bankroll"].iloc[-1])
            final_pl = float(summary_df["pl"].iloc[-1])
            summary_text = (
                f"Trial: {summary_trial}\n"
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

        self.canvas.draw()

    def _clear_plot(self):
        self.ax.clear()
        if self.hover_annotation:
            self.hover_annotation.set_visible(False)
        self._last_plots = []
        self.canvas.draw()

    def _clear_table(self):
        self.results_df = pd.DataFrame()
        self.view_data_btn.state(["disabled"])
        if self.data_window and self.data_window.is_open():
            self.data_window.close()

    def open_data_window(self):
        if self.results_df.empty:
            return
        if self.data_window and self.data_window.is_open():
            self.data_window.update_dataframe(self.results_df)
            self.data_window.win.lift()
            return
        self.data_window = DataWindow(
            self.root, self.results_df, on_close=lambda: setattr(self, "data_window", None)
        )

    def _parse_trial_selection(self) -> list[int]:
        raw = self.trial_filter.get().strip().lower()
        if not raw or raw == "all":
            return self.available_trials

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

        return [t for t in sorted(selected) if t in self.available_trials]

    def _show_all_trials(self):
        self.trial_filter.set("all")
        self.update_graph()

    def _on_hover(self, event):
        if not hasattr(self, "_last_plots") or not self._last_plots or event.inaxes != self.ax:
            if self.hover_annotation:
                self.hover_annotation.set_visible(False)
                self.canvas.draw_idle()
            return

        if event.xdata is None:
            return

        closest = None
        for trial, data in self._last_plots:
            idx = (data["hand"] - event.xdata).abs().idxmin()
            point = data.loc[idx]
            if closest is None or abs(point["hand"] - event.xdata) < abs(closest[1]["hand"] - event.xdata):
                closest = (trial, point)

        if not closest:
            return

        trial, point = closest
        text = f"Trial {trial}: Hand {int(point['hand'])}, P/L {point['pl']:.2f}"

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

        self.canvas.draw_idle()

    def update_table(self):
        if not self.sim:
            self._clear_table()
            return
        df = pd.read_sql_query(
            """
            SELECT
                trial,
                round_number,
                hands,
                wager,
                open_bankroll,
                close_bankroll,
                split_aces_logic,
                player_hand_a,
                player_hand_b,
                player_hand_c,
                player_hand_d,
                player_cards,
                dealer_cards,
                cards_dealt,
                running_count,
                true_count
            FROM temp_results
            ORDER BY trial, round_number, hands
            """,
            self.sim.conn,
        )

        if df.empty:
            self._clear_table()
            return

        ordered_cols = [
            "trial",
            "round_number",
            "hands",
            "wager",
            "open_bankroll",
            "close_bankroll",
            "split_aces_logic",
            "player_hand_a",
            "player_hand_b",
            "player_hand_c",
            "player_hand_d",
            "player_cards",
            "dealer_cards",
            "cards_dealt",
            "running_count",
            "true_count",
        ]
        self.results_df = df[ordered_cols]
        self.view_data_btn.state(["!disabled"])
        if self.data_window and self.data_window.is_open():
            self.data_window.update_dataframe(self.results_df)

    def save_results(self):
        if self.sim:
            self.sim.save_results()
            self.sim.close()
            self.sim = None
            messagebox.showinfo("Saved", "Results saved")
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
            self.available_trials = []
            self.trial_filter.set("all")

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
