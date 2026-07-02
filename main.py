import tkinter as tk
from tkinter import ttk, filedialog

BG_DARK = "#1e1e2e"
BG_PANEL = "#f4f5f7"
BG_HEADER = "#161622"
ACCENT = "#7c4dff"
GREEN = "#2e7d32"
GREEN_H = "#388e3c"
RED = "#c62828"
RED_H = "#d32f2f"
GREY = "#546e7a"
TEXT_DARK = "#212121"
FONT_TITLE = ("Segoe UI", 13, "bold")
FONT_LABEL = ("Segoe UI", 10)
FONT_STATUS = ("Segoe UI", 10, "bold")
FONT_BTN = ("Segoe UI", 9, "bold")


def make_button(parent, text, color, hover, command, width=14):
    btn = tk.Button(
        parent, text=text, command=command, width=width,
        bg=color, fg="white", activebackground=hover, activeforeground="white",
        font=FONT_BTN, relief="flat", bd=0, cursor="hand2", pady=6,
    )
    btn.bind("<Enter>", lambda e: btn.config(bg=hover))
    btn.bind("<Leave>", lambda e: btn.config(bg=color))
    return btn


# pcu
class PowerPanel(ttk.LabelFrame):
    def __init__(self, parent):
        super().__init__(parent, text="  ", padding=12, style="Card.TLabelframe")

        self.pcu_state = "OFF"
        self.activation_state = "OFF"

        self._build_ui()

    def _build_ui(self):
        pcu_frame = ttk.LabelFrame(self, text=" PCU ", padding=10, style="Card.TLabelframe")
        pcu_frame.grid(row=0, column=0, padx=10, pady=5, sticky="n")

        self.pcu_status = ttk.Label(pcu_frame, text="Status: OFF", foreground=RED, font=FONT_STATUS)
        self.pcu_status.grid(row=0, column=0, pady=(0, 10))

        make_button(pcu_frame, "ON", GREEN, GREEN_H, self.pcu_on).grid(row=1, column=0, pady=3)
        make_button(pcu_frame, "OFF", RED, RED_H, self.pcu_off).grid(row=2, column=0, pady=3)

        act_frame = ttk.LabelFrame(self, text=" Wakeup line ", padding=10, style="Card.TLabelframe")
        act_frame.grid(row=0, column=1, padx=10, pady=5, sticky="n")

        self.act_status = ttk.Label(act_frame, text="Status: Sleep", foreground=RED, font=FONT_STATUS)
        self.act_status.grid(row=0, column=0, pady=(0, 10))

        make_button(act_frame, "ON", GREEN, GREEN_H, self.wake_up).grid(row=1, column=0, pady=3)
        make_button(act_frame, "OFF", RED, RED_H, self.go_to_sleep).grid(row=2, column=0, pady=3)

    def pcu_on(self):
        self.pcu_state = "ON"
        self.pcu_status.config(text="Status: ON", foreground=GREEN)

    def pcu_off(self):
        self.pcu_state = "OFF"
        self.pcu_status.config(text="Status: OFF", foreground=RED)

    def wake_up(self):
        self.activation_state = "ON"
        self.act_status.config(text="Status: Awake", foreground=GREEN)

    def go_to_sleep(self):
        self.activation_state = "OFF"
        self.act_status.config(text="Status: Sleep", foreground=RED)


#diag
class DIAGNOSIS(ttk.LabelFrame):
    def __init__(self, parent):
        super().__init__(parent, text=" ", padding=12, style="Card.TLabelframe")

        self.diag_state = "Default"

        self._build_ui()

    def _build_ui(self):
        diag_frame = ttk.LabelFrame(self, text="Diagnosis (activation line) ", padding=10, style="Card.TLabelframe")
        diag_frame.grid(row=0, column=0, padx=10, pady=5, sticky="n")

        self.diag_status = ttk.Label(diag_frame, text="Status: default", foreground=RED, font=FONT_STATUS)
        self.diag_status.grid(row=0, column=0, pady=(0, 10))

        make_button(diag_frame, "default", GREEN, GREEN_H, self.diag_on).grid(row=1, column=0, pady=3)
        make_button(diag_frame, "forced", RED, RED_H, self.diag_off).grid(row=2, column=0, pady=3)

    def diag_on(self):
        self.diag_state = "default"
        self.diag_status.config(text="Status: default", foreground=GREEN)

    def diag_off(self):
        self.diag_state = "forced"
        self.diag_status.config(text="Status: forced", foreground=RED)


# trame
class Trame(ttk.LabelFrame):
    def __init__(self, parent):
        super().__init__(parent, text=" Trame ", padding=12, style="Card.TLabelframe")

        self.running = False
        self.after_id = None
        self.frame_index = 0

        self._build_ui()

    def _build_ui(self):
        # boutons controle
        ctrl_row = ttk.Frame(self, style="Card.TFrame")
        ctrl_row.grid(row=0, column=0, columnspan=3, pady=(0, 10))

        make_button(ctrl_row, "Lancer", GREEN, GREEN_H, self.lancer, width=12).grid(row=0, column=0, padx=6)
        make_button(ctrl_row, "Arrêter", RED, RED_H, self.arreter, width=12).grid(row=0, column=1, padx=6)
        make_button(ctrl_row, "Sauvegarder", GREY, "#607d8b", self.sauvegarder, width=12).grid(row=0, column=2, padx=6)

        self.status_label = ttk.Label(
            ctrl_row, text="Status: arrêté", foreground=RED, font=FONT_STATUS, background=BG_PANEL
        )
        self.status_label.grid(row=0, column=3, padx=(16, 0))




    def lancer(self):
        if self.running:
            return
        self.running = True
        self.status_label.config(text="Status: en cours", foreground=GREEN)
        self.frame_index = 0

    def arreter(self):
        self.running = False
        if self.after_id is not None:
            self.after_cancel(self.after_id)
            self.after_id = None
        self.status_label.config(text="Status: arrêté", foreground=RED)

    def sauvegarder(self):
        path = filedialog.asksaveasfilename(
            title="Sauvegarder le log des trames",
            defaultextension=".*"
        )
        if not path:
            return
        try:
            content = self.log_text.get("1.0", "end-1c")
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
        except OSError as exc:
            self._log_frame(f"Erreur sauvegarde: {exc}")




class Multiverse(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Multiverse")
        self.geometry("1000x780")
        self.configure(bg=BG_DARK)
        self.minsize(880, 700)

        self._setup_style()

        header = tk.Frame(self, bg=BG_HEADER, height=54)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(
            header, text="MULTIVERSE", bg=BG_HEADER, fg="white",
            font=("Segoe UI", 16, "bold"),
        ).pack(side="left", padx=20)


        content = tk.Frame(self, bg=BG_DARK)
        content.pack(fill="both", expand=True, padx=16, pady=16)

        PowerPanel(content).pack(fill="x", pady=(0, 12))
        DIAGNOSIS(content).pack(fill="x", pady=(0, 12))
        Trame(content).pack(fill="both", expand=True, pady=(0, 4))

    def _setup_style(self):
        style = ttk.Style(self)
        style.theme_use("clam")

        style.configure("TLabelframe", background=BG_PANEL, borderwidth=1, relief="flat")
        style.configure(
            "TLabelframe.Label", background=BG_PANEL, foreground=TEXT_DARK,
            font=FONT_TITLE,
        )
        style.configure("Card.TLabelframe", background=BG_PANEL)
        style.configure("Card.TLabelframe.Label", background=BG_PANEL, font=FONT_TITLE)
        style.configure("Card.TFrame", background=BG_PANEL)
        style.configure("TLabel", background=BG_PANEL, font=FONT_LABEL)
        style.configure("TEntry", padding=4)
        style.configure("TScrollbar", background=BG_PANEL)


if __name__ == "__main__":
    app = Multiverse()
    app.mainloop()