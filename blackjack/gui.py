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

        self.settings_bar = ttk.Frame(self.root, padding=(10, 6))
        self._build_settings_bar()
        self.settings_bar.pack(fill=tk.X)

        self.table_frame = tk.Frame(self.root)
        self.table_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        self.table = ttk.Treeview(self.table_frame, show="headings")
        self.table.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll = ttk.Scrollbar(self.table_frame, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        controls = tk.Frame(self.root)
        controls.pack(side=tk.BOTTOM, fill=tk.X)

        tk.Button(controls, text="Run", command=self.run_simulation).pack(side=tk.LEFT)
        self.save_btn = tk.Button(controls, text="Save", command=self.save_results, state=tk.DISABLED)
        self.save_btn.pack(side=tk.LEFT)
        self.discard_btn = tk.Button(controls, text="Discard", command=self.discard_results, state=tk.DISABLED)
        self.discard_btn.pack(side=tk.LEFT)

        tk.Label(controls, text="Plot Trial").pack(side=tk.LEFT)
        self.plot_trial = tk.IntVar(value=1)
        self.plot_trial_spin = tk.Spinbox(
            controls,
            from_=1,
            to=1,
            textvariable=self.plot_trial,
            command=self.update_graph,
            width=5,
        )
        self.plot_trial_spin.pack(side=tk.LEFT)

        tk.Button(controls, text="Exit", command=self.exit_prompt).pack(side=tk.RIGHT)
        tk.Button(controls, text="Seed", command=self.open_settings).pack(side=tk.RIGHT)

    def _build_settings_bar(self):
        label_font = tkfont.nametofont("TkDefaultFont").copy()
        label_font.configure(size=max(label_font["size"] - 1, 9))

        content = ttk.Frame(self.settings_bar)
        content.pack(fill=tk.X)

        def add_row(row: int, col: int, text: str, widget: tk.Widget):
            ttk.Label(content, text=text, font=label_font).grid(
                row=row, column=col * 2, sticky="e", padx=(0, 4), pady=4
            )
            widget.grid(row=row, column=col * 2 + 1, sticky="w", padx=(0, 12), pady=4)

        bankroll_entry = ttk.Entry(content, textvariable=self.bankroll, width=10)
        trials_spin = tk.Spinbox(content, from_=1, to=1000, textvariable=self.trials, width=6)
        rounds_spin = tk.Spinbox(content, from_=1, to=100, textvariable=self.rounds_per_trial, width=6)
        hands_spin = tk.Spinbox(content, from_=1, to=100, textvariable=self.hands_per_round, width=6)
        bet_entry = ttk.Entry(content, textvariable=self.bet, width=10)
        decks_spin = tk.Spinbox(content, from_=1, to=12, textvariable=self.decks, width=6)
        pen_spin = tk.Spinbox(content, from_=0.25, to=0.95, increment=0.01, textvariable=self.penetration, width=6)

        payout_combo = ttk.Combobox(
            content, textvariable=self.payout, values=["3:2", "6:5"], state="readonly", width=5
        )
        dealer_combo = ttk.Combobox(
            content, textvariable=self.dealer, values=["H17", "S17"], state="readonly", width=5
        )

        self.das_switch_text = tk.StringVar()
        self._update_das_switch_label()
        das_toggle = tk.Checkbutton(
            content,
            textvariable=self.das_switch_text,
            variable=self.das,
            indicatoron=False,
            width=6,
        )

        split_aces_combo = ttk.Combobox(
            content,
            textvariable=self.split_aces_logic,
            values=["Single", "Carnival"],
            state="readonly",
            width=10,
        )

        surrender_combo = ttk.Combobox(
            content,
            textvariable=self.surrender,
            values=["Early", "Late", "None"],
            state="readonly",
            width=8,
        )

        test_mode_check = ttk.Checkbutton(content, text="Test Mode", variable=self.test_mode)

        strategy_combo = ttk.Combobox(
            content,
            textvariable=self.strategy_file,
            values=[self.strategy_file.get()],
            state="readonly",
            width=max(15, len(self.strategy_file.get())),
        )
        database_combo = ttk.Combobox(
            content,
            textvariable=self.database,
            values=[self.database.get()],
            state="readonly",
            width=max(15, len(self.database.get())),
        )

        add_row(0, 0, "Bankroll", bankroll_entry)
        add_row(0, 1, "Bet", bet_entry)
        add_row(0, 2, "Trials", trials_spin)
        add_row(0, 3, "Rounds/Trial", rounds_spin)
        add_row(0, 4, "Hands/Round", hands_spin)
        add_row(0, 5, "Decks", decks_spin)
        add_row(0, 6, "Penetration", pen_spin)

        add_row(1, 0, "Payout", payout_combo)
        add_row(1, 1, "Dealer 17 Logic", dealer_combo)
        add_row(1, 2, "Double After Split", das_toggle)
        add_row(1, 3, "Split Aces Logic", split_aces_combo)
        add_row(1, 4, "Surrender", surrender_combo)
        add_row(1, 5, "Test Mode", test_mode_check)

        add_row(2, 0, "Strategy", strategy_combo)
        add_row(2, 2, "Database", database_combo)

        for i in range(14):
            content.columnconfigure(i, weight=1)

    def _update_das_switch_label(self):
        self.das_switch_text.set("On" if self.das.get() else "Off")

    def _update_test_mode_label(self):
        if self.test_mode.get():
            self.test_mode_label.pack(
                side=tk.TOP, fill=tk.X, before=self.canvas.get_tk_widget()
            )
        else:
            self.test_mode_label.pack_forget()

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
        self.sim.run()
        self.plot_trial_spin.config(to=self.trials.get())
        self.plot_trial.set(1)
        self.update_graph()
        self.update_table()
        if not self.sim.results_available:
            messagebox.showwarning(
                "No Results", "No hands were played. Check bankroll and bet settings."
            )
            self._clear_plot()
            self._clear_table()
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
        trial = self.plot_trial.get()
        df = pd.read_sql_query(
            "SELECT hand, bankroll FROM temp_bankroll WHERE trial=? ORDER BY hand",
            self.sim.conn,
            params=(trial,),
        )
        if df.empty:
            self._clear_plot()
            return

        df["pl"] = df["bankroll"] - self.bankroll.get()
        xmin = 0
        xmax = max(100, df["hand"].max())
        ymin = -self.bankroll.get()
        ymax = self.bankroll.get() * 2

        self.ax.clear()
        self.ax.set_xlabel("Total Hands Played")
        self.ax.set_ylabel("P/L")
        self.ax.set_xlim(xmin, xmax)
        self.ax.set_ylim(ymin, ymax)
        # Draw a horizontal line at y=0 so it's visually centered
        self.ax.axhline(0, color="gray", linewidth=0.5)
        self.ax.plot(df["hand"], df["pl"], color="blue")
        self.canvas.draw()

    def _clear_plot(self):
        self.ax.clear()
        self.canvas.draw()

    def _clear_table(self):
        self.table.delete(*self.table.get_children())
        self.table["columns"] = []

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
                player_cards,
                dealer_cards
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
            "player_cards": "PLAYER HAND",
            "dealer_cards": "DEALER HAND",
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
