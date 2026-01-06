import tkinter as tk
from tkinter import ttk, messagebox, font as tkfont
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import pandas as pd

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
        self.sim = None
        self.available_trials: list[int] = []

        self.hover_annotation = None
        self._last_plots: list[tuple[int, pd.DataFrame]] = []

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
        fig = Figure(figsize=(6, 4))
        self.ax = fig.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(fig, master=self.root)
        self.test_mode_label = tk.Label(
            self.root, text="The Simulator is currently in 'Test Mode'", fg="red"
        )
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.canvas.mpl_connect("motion_notify_event", self._on_hover)

        self._build_chart_controls()

        self.table_frame = tk.Frame(self.root)
        self.table_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        self.table = ttk.Treeview(self.table_frame, show="headings")
        self.table.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll = ttk.Scrollbar(self.table_frame, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.settings_bar = ttk.Frame(self.root, padding=(10, 6))
        self._build_settings_bar()
        self.settings_bar.pack(fill=tk.X, pady=(0, 8))

        controls = tk.Frame(self.root)
        controls.pack(side=tk.BOTTOM, fill=tk.X)

        tk.Button(controls, text="Run", command=self.run_simulation).pack(side=tk.LEFT)
        self.save_btn = tk.Button(controls, text="Save", command=self.save_results, state=tk.DISABLED)
        self.save_btn.pack(side=tk.LEFT)
        self.discard_btn = tk.Button(controls, text="Discard", command=self.discard_results, state=tk.DISABLED)
        self.discard_btn.pack(side=tk.LEFT)
        tk.Button(controls, text="Exit", command=self.exit_prompt).pack(side=tk.RIGHT)
        tk.Button(controls, text="Seed", command=self.open_settings).pack(side=tk.RIGHT)

    def _build_settings_bar(self):
        base_font = tkfont.nametofont("TkDefaultFont")
        label_font = base_font.copy()
        label_font.configure(size=max(label_font["size"] - 1, 9))
        section_font = base_font.copy()
        section_font.configure(size=max(section_font["size"] - 2, 9), weight="bold")

        payout_combo = ttk.Combobox(
            self.settings_bar, textvariable=self.payout, values=["3:2", "6:5"], state="readonly", width=4
        )
        dealer_combo = ttk.Combobox(
            self.settings_bar, textvariable=self.dealer, values=["H17", "S17"], state="readonly", width=4
        )

        self.das_switch_text = tk.StringVar()
        self._update_das_switch_label()
        das_toggle = self._build_switch(self.settings_bar, self.das)

        split_aces_combo = ttk.Combobox(
            self.settings_bar,
            textvariable=self.split_aces_logic,
            values=["Single", "Carnival"],
            state="readonly",
            width=8,
        )

        surrender_combo = ttk.Combobox(
            self.settings_bar,
            textvariable=self.surrender,
            values=["Early", "Late", "None"],
            state="readonly",
            width=7,
        )

        test_mode_toggle = self._build_switch(self.settings_bar, self.test_mode)

        strategy_combo = ttk.Combobox(
            self.settings_bar,
            textvariable=self.strategy_file,
            values=[self.strategy_file.get()],
            state="readonly",
            width=max(18, len(self.strategy_file.get())),
        )
        database_combo = ttk.Combobox(
            self.settings_bar,
            textvariable=self.database,
            values=[self.database.get()],
            state="readonly",
            width=max(18, len(self.database.get())),
        )

        bankroll_entry = ttk.Entry(self.settings_bar, textvariable=self.bankroll, width=12)
        trials_spin = tk.Spinbox(self.settings_bar, from_=1, to=1000, textvariable=self.trials, width=6)
        rounds_spin = tk.Spinbox(self.settings_bar, from_=1, to=100, textvariable=self.rounds_per_trial, width=6)
        hands_spin = tk.Spinbox(self.settings_bar, from_=1, to=100, textvariable=self.hands_per_round, width=6)
        bet_entry = ttk.Entry(self.settings_bar, textvariable=self.bet, width=12)
        decks_spin = tk.Spinbox(self.settings_bar, from_=1, to=12, textvariable=self.decks, width=6)
        pen_spin = tk.Spinbox(self.settings_bar, from_=0.25, to=0.95, increment=0.01, textvariable=self.penetration, width=6)

        def build_bin(parent: tk.Widget, label: str, control: tk.Widget) -> ttk.Frame:
            frame = ttk.Frame(parent, padding=(6, 2))
            ttk.Label(frame, text=label, font=label_font, anchor="center").pack(
                side=tk.TOP, fill=tk.X
            )
            control.pack(side=tk.TOP, pady=(4, 2))
            return frame

        def add_row(title: str, bins: list[ttk.Frame]):
            row_frame = ttk.Frame(self.settings_bar)
            row_frame.pack(fill=tk.X, pady=(2, 6))
            ttk.Label(row_frame, text=title, font=section_font).grid(
                row=0, column=0, sticky="nw", padx=(0, 12)
            )
            bins_frame = ttk.Frame(row_frame)
            bins_frame.grid(row=1, column=0, sticky="ew")
            for col in range(len(bins) * 2 - 1):
                bins_frame.columnconfigure(col, weight=1)

            for idx, bin_frame in enumerate(bins):
                bin_frame.grid(row=0, column=idx * 2, sticky="nsew", padx=6)
                if idx < len(bins) - 1:
                    ttk.Separator(bins_frame, orient="vertical").grid(
                        row=0, column=idx * 2 + 1, sticky="ns", padx=4, pady=4
                    )

        sim_bins = [
            build_bin(self.settings_bar, "Bankroll", bankroll_entry),
            build_bin(self.settings_bar, "Bet", bet_entry),
        ]
        sim_bins += [
            build_bin(self.settings_bar, "Trials", trials_spin),
            build_bin(self.settings_bar, "Rounds/Trial", rounds_spin),
            build_bin(self.settings_bar, "Hands/Round", hands_spin),
            build_bin(self.settings_bar, "Decks", decks_spin),
            build_bin(self.settings_bar, "Penetration", pen_spin),
        ]

        rules_bins = [
            build_bin(self.settings_bar, "Payout", payout_combo),
            build_bin(self.settings_bar, "Dealer 17 Logic", dealer_combo),
            build_bin(self.settings_bar, "Double After Split", das_toggle),
            build_bin(self.settings_bar, "Split Aces Logic", split_aces_combo),
            build_bin(self.settings_bar, "Surrender", surrender_combo),
        ]

        data_bins = [
            build_bin(self.settings_bar, "Strategy", strategy_combo),
            build_bin(self.settings_bar, "Database", database_combo),
            build_bin(self.settings_bar, "Test Mode", test_mode_toggle),
        ]

        add_row("SIMULATION SETTINGS", sim_bins)
        add_row("GAME RULES", rules_bins)
        add_row("DATA", data_bins)

    def _update_das_switch_label(self):
        self.das_switch_text.set("On" if self.das.get() else "Off")

    def _update_test_mode_label(self):
        if self.test_mode.get():
            self.test_mode_label.pack(
                side=tk.TOP, fill=tk.X, before=self.canvas.get_tk_widget()
            )
        else:
            self.test_mode_label.pack_forget()

    def _build_chart_controls(self):
        controls = ttk.Frame(self.root, padding=(10, 4))
        controls.pack(fill=tk.X)
        ttk.Label(controls, text="TRIAL VIEW", font=(None, 9, "bold")).pack(
            side=tk.LEFT, padx=(0, 8)
        )
        ttk.Label(controls, text="Enter 'all' or a list/range (e.g. 1,3-5):").pack(
            side=tk.LEFT
        )
        entry = ttk.Entry(controls, textvariable=self.trial_filter, width=20)
        entry.pack(side=tk.LEFT, padx=(6, 6))
        entry.bind("<Return>", lambda event: self.update_graph())
        ttk.Button(controls, text="Apply", command=self.update_graph).pack(side=tk.LEFT)
        ttk.Button(controls, text="Show All", command=self._show_all_trials).pack(
            side=tk.LEFT, padx=(6, 0)
        )

    def _build_switch(self, parent: tk.Widget, variable: tk.BooleanVar) -> tk.Widget:
        frame = ttk.Frame(parent)
        canvas = tk.Canvas(frame, width=48, height=26, highlightthickness=0, bg=frame.cget("background"))
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
        self.ax.set_xlabel("Total Hands Played")
        self.ax.set_ylabel("P/L")
        self.ax.axhline(0, color="gray", linewidth=0.5)
        self.ax.grid(True, axis="x", color="#a05f5f", alpha=0.25)
        self.ax.grid(True, axis="y", color="#5f748c", alpha=0.25)

        self._last_plots = []
        xmin = 0
        xmax = max(100, df["hand"].max())
        ymin = min(df["pl"].min(), -self.bankroll.get())
        ymax = max(df["pl"].max(), self.bankroll.get())

        color_cycle = self.ax._get_lines.prop_cycler
        for trial in sorted(selected_trials):
            trial_df = df[df["trial"] == trial]
            if trial_df.empty:
                continue
            color = next(color_cycle)["color"]
            self.ax.plot(trial_df["hand"], trial_df["pl"], label=f"Trial {trial}", color=color)
            self._last_plots.append((trial, trial_df[["hand", "pl"]].reset_index(drop=True)))

        self.ax.set_xlim(xmin, xmax)
        self.ax.set_ylim(ymin, ymax)
        if len(selected_trials) > 1:
            self.ax.legend()

        self.canvas.draw()

    def _clear_plot(self):
        self.ax.clear()
        if self.hover_annotation:
            self.hover_annotation.set_visible(False)
        self._last_plots = []
        self.canvas.draw()

    def _clear_table(self):
        self.table.delete(*self.table.get_children())
        self.table["columns"] = []

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
                running_count,
                true_count,
                cards_dealt
            FROM temp_results
            ORDER BY trial, round_number, hands
            """,
            self.sim.conn,
        )
        self.table.delete(*self.table.get_children())
        if df.empty:
            self.table["columns"] = []
            return

        display_names = {
            "trial": "TRIAL #",
            "round_number": "ROUND #",
            "hands": "HAND #",
            "wager": "WAGER",
            "open_bankroll": "OPEN BANKROLL",
            "close_bankroll": "CLOSE BANKROLL",
            "split_aces_logic": "SPLIT ACES LOGIC",
            "player_hand_a": "PLAYER HAND A",
            "player_hand_b": "PLAYER HAND B",
            "player_hand_c": "PLAYER HAND C",
            "player_hand_d": "PLAYER HAND D",
            "player_cards": "PLAYER HANDS",
            "dealer_cards": "DEALER HAND",
            "running_count": "RUNNING COUNT",
            "true_count": "TRUE COUNT",
            "cards_dealt": "CARDS DEALT",
        }

        self.table["columns"] = list(df.columns)
        font = tkfont.nametofont("TkDefaultFont")
        for col in df.columns:
            header_text = display_names.get(col, col.upper())
            values = [header_text] + [str(v) for v in df[col].tolist()]
            width = max(font.measure(v) for v in values) + 12
            self.table.heading(col, text=header_text)
            self.table.column(col, width=width, stretch=True, anchor=tk.W)

        for _, row in df.iterrows():
            self.table.insert("", tk.END, values=[row[col] for col in df.columns])
        self.table.update_idletasks()

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
