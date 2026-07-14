import socket
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


class ConnectionPanel(ttk.LabelFrame):
    def __init__(self, parent):
        super().__init__(parent, text=" Backend connection ", padding=10, style="Card.TLabelframe")
        self._build_ui()

    def _build_ui(self):
        host_label = ttk.Label(self, text="IP:")
        host_label.grid(row=0, column=0, sticky="w", padx=(0, 6), pady=3)

        self.host_var = tk.StringVar(value="127.0.0.1")
        self.host_entry = ttk.Entry(self, textvariable=self.host_var, width=18)
        self.host_entry.grid(row=0, column=1, sticky="w", pady=3)

        port_label = ttk.Label(self, text="Port:")
        port_label.grid(row=0, column=2, sticky="w", padx=(12, 6), pady=3)

        self.port_var = tk.StringVar(value="1234")
        self.port_entry = ttk.Entry(self, textvariable=self.port_var, width=8)
        self.port_entry.grid(row=0, column=3, sticky="w", pady=3)

        self.connect_button = make_button(self, "Connect", GREEN, GREEN_H, self.toggle_connection, width=12)
        self.connect_button.grid(row=0, column=4, padx=(12, 0), pady=3)

        self.connection_label = ttk.Label(self, text="Not connected", foreground=RED, font=FONT_STATUS)
        self.connection_label.grid(row=1, column=0, columnspan=5, sticky="w", pady=(8, 0))

    def toggle_connection(self):
        app = self.winfo_toplevel()
        if getattr(app, "backend_socket", None) is None:
            host = self.host_var.get().strip() or "127.0.0.1"
            try:
                port = int(self.port_var.get().strip() or "1234")
            except ValueError:
                self.connection_label.config(text="Invalid port", foreground=RED)
                return

            response = app.connect_backend(host, port)
            if response.startswith("OK"):
                self.connection_label.config(text=f"Connected to {host}:{port}", foreground=GREEN)
                self.connect_button.config(text="Disconnect")
                self.host_entry.config(state="disabled")
                self.port_entry.config(state="disabled")
            else:
                self.connection_label.config(text=response, foreground=RED)
        else:
            app.disconnect_backend()
            self.connection_label.config(text="Not connected", foreground=RED)
            self.connect_button.config(text="Connect")
            self.host_entry.config(state="normal")
            self.port_entry.config(state="normal")


# pcu
class PowerPanel(ttk.LabelFrame):
    def __init__(self, parent):
        super().__init__(parent, text="  ", padding=12, style="Card.TLabelframe")

        self.pcu_state = "OFF"
        self.activation_state = "OFF"
        self.acti_state = "OFF"

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

        acti_frame = ttk.LabelFrame(self, text=" Activation line ", padding=10, style="Card.TLabelframe")
        acti_frame.grid(row=0, column=2, padx=10, pady=5, sticky="n")

        self.acti_status = ttk.Label(acti_frame, text="Status: OFF", foreground=RED, font=FONT_STATUS)
        self.acti_status.grid(row=0, column=0, pady=(0, 10))

        make_button(acti_frame, "ON", GREEN, GREEN_H, self.acti_on).grid(row=1, column=0, pady=3)
        make_button(acti_frame, "OFF", RED, RED_H, self.acti_off).grid(row=2, column=0, pady=3)

    def pcu_on(self):
        app = self.winfo_toplevel()
        response = app.send_command_to_backend("POWER 1")
        if response.startswith("OK"):
            self.pcu_state = "ON"
            self.pcu_status.config(text="Status: ON", foreground=GREEN)
        app.update_command_status(response)

    def pcu_off(self):
        app = self.winfo_toplevel()
        response = app.send_command_to_backend("POWER 0")
        if response.startswith("OK"):
            self.pcu_state = "OFF"
            self.pcu_status.config(text="Status: OFF", foreground=RED)
        app.update_command_status(response)

    def wake_up(self):
        app = self.winfo_toplevel()
        response = app.send_command_to_backend("WAKE-UP 1")
        if response.startswith("OK"):
            self.activation_state = "ON"
            self.act_status.config(text="Status: Awake", foreground=GREEN)
        app.update_command_status(response)

    def go_to_sleep(self):
        app = self.winfo_toplevel()
        response = app.send_command_to_backend("WAKE-UP 0")
        if response.startswith("OK"):
            self.activation_state = "OFF"
            self.act_status.config(text="Status: Sleep", foreground=RED)
        app.update_command_status(response)

    def acti_on(self):
        app = self.winfo_toplevel()
        response = app.send_command_to_backend("ACTI-LINE 1")
        if response.startswith("OK"):
            self.acti_state = "ON"
            self.acti_status.config(text="Status: ON", foreground=GREEN)
        app.update_command_status(response)

    def acti_off(self):
        app = self.winfo_toplevel()
        response = app.send_command_to_backend("ACTI-LINE 0")
        if response.startswith("OK"):
            self.acti_state = "OFF"
            self.acti_status.config(text="Status: OFF", foreground=RED)
        app.update_command_status(response)




class PcapPanel(ttk.LabelFrame):
    def __init__(self, parent):
        super().__init__(parent, text="  ", padding=12, style="Card.TLabelframe")

        self.pcap_state = "STOPPED"
        self._build_ui()

    def _build_ui(self):
        pcap_frame = ttk.LabelFrame(self, text=" PCAP Control ", padding=10, style="Card.TLabelframe")
        pcap_frame.grid(row=0, column=0, padx=10, pady=5, sticky="n")

        self.pcap_status = ttk.Label(pcap_frame, text="Status: stopped", foreground=RED, font=FONT_STATUS)
        self.pcap_status.grid(row=0, column=0, pady=(0, 10))

        self.start_button = make_button(pcap_frame, "START", GREEN, GREEN_H, self.start)
        self.start_button.grid(row=1, column=0, pady=3)
        self.start_button.config(state="disabled")
        make_button(pcap_frame, "STOP", RED, RED_H, self.stop).grid(row=2, column=0, pady=3)
        make_button(pcap_frame, "NAME", GREY, "#607d8b", self.name).grid(row=3, column=0, pady=3)

    def start(self):
        app = self.winfo_toplevel()
        response = app.send_command_to_backend("PCAP START")
        if response.startswith("OK"):
            self.pcap_state = "STARTED"
            self.pcap_status.config(text="Status: started", foreground=GREEN)
        app.update_command_status(response)

    def stop(self):
        app = self.winfo_toplevel()
        response = app.send_command_to_backend("PCAP STOP")
        if response.startswith("OK"):
            self.pcap_state = "STOPPED"
            self.pcap_status.config(text="Status: stopped", foreground=RED)
            self.start_button.config(state="disabled")
        app.update_command_status(response)

    def name(self):
        app = self.winfo_toplevel()
        filename = filedialog.asksaveasfilename(
            title="Choose PCAP output file",
            defaultextension=".pcap",
            filetypes=[("PCAP files", "*.pcap"), ("All files", "*.*")],
        )
        if not filename:
            return  # user cancelled

        response = app.send_command_to_backend(f"PCAP NAME {filename}")
        if response.startswith("OK"):
            self.pcap_state = "NAME"
            self.pcap_status.config(text=f"Status: name set ({filename})", foreground=GREEN)
            self.start_button.config(state="normal")
        app.update_command_status(response)


class Multiverse(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Multiverse")
        self.geometry("1000x780")
        self.configure(bg=BG_DARK)
        self.minsize(880, 700)

        self.backend_socket = None
        self.backend_host = "127.0.0.1"
        self.backend_port = 1234

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

        self.connection_panel = ConnectionPanel(content)
        self.connection_panel.pack(fill="x", pady=(0, 12))
        PowerPanel(content).pack(fill="x", pady=(0, 12))
        PcapPanel(content).pack(fill="x", pady=(0, 12))

        self.response_label = tk.Label(
            self, text="Backend: idle", bg=BG_DARK, fg="white", font=FONT_LABEL
        )
        self.response_label.pack(fill="x", padx=16, pady=(0, 8))

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

    def connect_backend(self, host: str, port: int) -> str:
        try:
            sock = socket.create_connection((host, port), timeout=2)
            self.backend_socket = sock
            self.backend_host = host
            self.backend_port = port
            return f"OK Connected to {host}:{port}"
        except OSError as exc:
            self.backend_socket = None
            return f"ERROR {exc}"

    def disconnect_backend(self):
        if self.backend_socket is not None:
            try:
                self.backend_socket.close()
            except OSError:
                pass
            self.backend_socket = None

    def ensure_backend_connected(self) -> str:
        if self.backend_socket is not None:
            return "OK Already connected"

        host = self.connection_panel.host_var.get().strip() or self.backend_host
        port_string = self.connection_panel.port_var.get().strip() or str(self.backend_port)
        try:
            port = int(port_string)
        except ValueError:
            return "ERROR Invalid port"

        response = self.connect_backend(host, port)
        if response.startswith("OK"):
            self.connection_panel.connection_label.config(text=f"Connected to {host}:{port}", foreground=GREEN)
            self.connection_panel.connect_button.config(text="Disconnect")
            self.connection_panel.host_entry.config(state="disabled")
            self.connection_panel.port_entry.config(state="disabled")
        return response

    def send_command_to_backend(self, command: str) -> str:
        if self.backend_socket is None:
            response = self.ensure_backend_connected()
            if not response.startswith("OK"):
                return response

        try:
            self.backend_socket.sendall((command.strip() + "\n").encode("utf-8"))
            response = self.backend_socket.recv(1024).decode("utf-8", errors="replace").strip()
            return response or "No response from backend"
        except OSError as exc:
            self.disconnect_backend()
            self.connection_panel.connection_label.config(text="Not connected", foreground=RED)
            self.connection_panel.connect_button.config(text="Connect")
            self.connection_panel.host_entry.config(state="normal")
            self.connection_panel.port_entry.config(state="normal")
            return f"ERROR {exc}"

    def update_command_status(self, response: str):
        self.response_label.config(text=f"Backend: {response}")


if __name__ == "__main__":
    app = Multiverse()
    app.mainloop()