#!/usr/bin/env python3
import os
import shutil
import json

import grpc
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import multiverse_pb2
import multiverse_pb2_grpc

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

GRPC_TIMEOUT_SECONDS = 2
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

DEFAULT_CONFIG = {
    "listener": {"ip": "0.0.0.0", "port": 60000},
    "pcap_parameters": {"if_name": "lo", "size_mb": 2048, "slices": 1},
}


def load_config():
    """Load the shared frontend/backend configuration, with safe UI defaults."""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as config_file:
            return json.load(config_file)
    except (OSError, json.JSONDecodeError):
        return DEFAULT_CONFIG


def listener_config(config):
    """Return the single listener shared by the backend and frontend."""
    return config["listener"]


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
        listener = listener_config(self.winfo_toplevel().config)
        self.host_var = tk.StringVar(value=str(listener["ip"]))
        self.network_var = tk.StringVar(value="ethernet")
        self.host_label = ttk.Label(self, text="IP:")
        self.host_label.grid(row=1, column=0, sticky="w", padx=(0, 6), pady=3)
        self.host_entry = ttk.Entry(self, textvariable=self.host_var, width=18)
        self.host_entry.grid(row=1, column=1, sticky="w", pady=3)

        self.port_var = tk.StringVar(value=str(listener["port"]))
        self.port_label = ttk.Label(self, text="Port:")
        self.port_label.grid(row=1, column=2, sticky="w", padx=(12, 6), pady=3)
        self.port_entry = ttk.Entry(self, textvariable=self.port_var, width=8)
        self.port_entry.grid(row=1, column=3, sticky="w", pady=3)

        ttk.Label(self, text="Interface:").grid(row=0, column=0, sticky="w", padx=(0, 6), pady=3)
        self.ethernet_button = ttk.Radiobutton(
            self, text="Ethernet", variable=self.network_var, value="ethernet"
        )
        self.ethernet_button.grid(row=0, column=1, sticky="w", pady=3)
        self.wifi_button = ttk.Radiobutton(
            self, text="Wi-Fi", variable=self.network_var, value="wifi"
        )
        self.wifi_button.grid(row=0, column=2, sticky="w", padx=(8, 12), pady=3)

        self.connect_button = make_button(self, "Connect", GREEN, GREEN_H, self.toggle_connection, width=12)
        self.connect_button.grid(row=0, column=3, padx=(0, 8), pady=3)

        self.advanced_button = make_button(self, "Advanced", GREY, "#607d8b", self.toggle_advanced, width=10)
        self.advanced_button.grid(row=0, column=4, pady=3, sticky="w")

        self.connection_label = ttk.Label(self, text="Not connected", foreground=RED, font=FONT_STATUS)
        self.connection_label.grid(row=2, column=0, columnspan=5, sticky="w", pady=(8, 0))

        self.advanced_visible = True
        self.toggle_advanced()

    def toggle_advanced(self):
        widgets = (self.host_label, self.host_entry, self.port_label, self.port_entry)
        self.advanced_visible = not self.advanced_visible
        if self.advanced_visible:
            for widget in widgets:
                widget.grid()
            self.advanced_button.config(text="Hide advanced")
        else:
            for widget in widgets:
                widget.grid_remove()
            self.advanced_button.config(text="Advanced")
            if self._connection_differs_from_json():
                messagebox.showwarning(
                    "JSON reminder",
                    "IP/port changed in the frontend. Update config.json and restart the backend to apply the listener change.",
                    parent=self.winfo_toplevel(),
                )

    def _connection_differs_from_json(self):
        listener = listener_config(self.winfo_toplevel().config)
        try:
            port = int(self.port_var.get().strip())
        except ValueError:
            return True
        return self.host_var.get().strip() != str(listener["ip"]) or port != int(listener["port"])

    def toggle_connection(self):
        app = self.winfo_toplevel()
        if getattr(app, "backend_stub", None) is None:
            host = self.host_var.get().strip() or "0.0.0.0"
            try:
                port = int(self.port_var.get().strip() or "60000")
            except ValueError:
                response = "ERROR Invalid port"
                self.connection_label.config(text="Invalid port", foreground=RED)
                app.update_command_status(response)
                return

            if self._connection_differs_from_json():
                messagebox.showwarning(
                    "JSON reminder",
                    "IP/port changed for this connection. Update config.json and restart the backend to apply the listener change.",
                    parent=app,
                )

            response = app.connect_backend(host, port)
            if response.startswith("OK"):
                self.connection_label.config(
                    text=f"Connected via {self.network_var.get().title()} to {host}:{port}",
                    foreground=GREEN,
                )
                self.connect_button.config(text="Disconnect")
                self.host_entry.config(state="disabled")
                self.port_entry.config(state="disabled")
                self.ethernet_button.config(state="disabled")
                self.wifi_button.config(state="disabled")
            else:
                self.connection_label.config(text=response, foreground=RED)
                app.update_command_status(response)
        else:
            app.disconnect_backend()
            self.connection_label.config(text="Not connected", foreground=RED)
            self.connect_button.config(text="Connect")
            self.host_entry.config(state="normal")
            self.port_entry.config(state="normal")
            self.ethernet_button.config(state="normal")
            self.wifi_button.config(state="normal")


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
        self.last_pcap_path = ""
        self.last_download_path = ""
        self.last_download_name = ""
        self.downloaded_pcap_paths = []
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

        self.download_button = make_button(pcap_frame, "DOWNLOAD", GREY, "#607d8b", self.download)
        self.download_button.grid(row=4, column=0, pady=3)
        self.download_button.config(state="disabled")

        download_progress_frame = ttk.Frame(pcap_frame)
        download_progress_frame.grid(row=4, column=1, padx=(10, 0), sticky="w")

        self.download_size_label = ttk.Label(download_progress_frame, text="", font=FONT_LABEL)
        self.download_size_label.grid(row=0, column=0, sticky="w")

        self.download_progress = ttk.Progressbar(
            download_progress_frame, orient="horizontal", mode="determinate", length=160
        )
        self.download_progress.grid(row=1, column=0, pady=(2, 0), sticky="w")

        self.download_progress_label = ttk.Label(download_progress_frame, text="", font=FONT_LABEL)
        self.download_progress_label.grid(row=2, column=0, pady=(2, 0), sticky="w")

        self.cleanup_button = make_button(pcap_frame, "CLEANUP", RED, RED_H, self.cleanup)
        self.cleanup_button.grid(row=5, column=0, pady=3)
        self.cleanup_button.config(state="disabled")

    def start(self):
        app = self.winfo_toplevel()
        response = app.send_command_to_backend("PCAP START")
        if response.startswith("OK"):
            self.pcap_state = "STARTED"
            self.pcap_status.config(text="Status: started", foreground=GREEN)
            messagebox.showinfo(
                "Capture launched",
                "Capture started (2 GiB max file size).",
                parent=app,
            )
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
        if self.pcap_state == "STARTED":
            stop_response = app.send_command_to_backend("PCAP STOP")
            if stop_response.startswith("OK"):
                self.pcap_state = "STOPPED"
                self.pcap_status.config(text="Status: stopped", foreground=RED)
                self.start_button.config(state="disabled")

        filename = filedialog.asksaveasfilename(
            title="Choose remote PCAP output file name",
            defaultextension=".pcap",
            filetypes=[("PCAP files", "*.pcap"), ("All files", "*.*")],
        )
        if not filename:
            return

        remote_name = os.path.basename(filename)
        if remote_name not in self.downloaded_pcap_paths:
            self.downloaded_pcap_paths.append(remote_name)
        response = app.send_command_to_backend(f"PCAP NAME {remote_name}")
        if response.startswith("OK"):
            self.last_pcap_path = remote_name
            self.last_download_name = remote_name
            self.pcap_state = "NAME"
            self.pcap_status.config(text=f"Status: name set ({remote_name})", foreground=GREEN)
            self.start_button.config(state="normal")
            self.download_button.config(state="normal")
            self.cleanup_button.config(state="normal")
        app.update_command_status(response)

    @staticmethod
    def _format_size(num_bytes):
        size = float(num_bytes)
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024 or unit == "GB":
                return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} {unit}"
            size /= 1024
        return f"{size:.1f} GB"

    def _reset_progress_ui(self):
        self.download_progress["value"] = 0
        self.download_progress["maximum"] = 100
        self.download_size_label.config(text="")
        self.download_progress_label.config(text="")

    def download(self):
        app = self.winfo_toplevel()
        if not self.last_pcap_path:
            app.update_command_status("ERROR No remote PCAP file is available to download")
            return

        if app.backend_stub is None:
            response = app.ensure_backend_connected()
            if not response.startswith("OK"):
                app.update_command_status(response)
                return

        # Kill the capture before pulling the file: reading a pcap tcpdump is
        # still actively writing to could hand back a truncated/corrupt file.
        if self.pcap_state == "STARTED":
            stop_response = app.send_command_to_backend("PCAP STOP")
            if stop_response.startswith("OK"):
                self.pcap_state = "STOPPED"
                self.pcap_status.config(text="Status: stopped", foreground=RED)
                self.start_button.config(state="disabled")
            app.update_command_status(stop_response)

        target = os.path.join(os.getcwd(), self.last_pcap_path)

        self.download_button.config(state="disabled")
        self._reset_progress_ui()
        self.download_progress_label.config(text="Starting download...")
        self.update_idletasks()

        received = 0
        total_size = None
        try:
            with open(target, "wb") as out_file:
                # PcapGet is a server-streaming RPC: the backend kills tcpdump
                # (belt-and-braces, mirrors the STOP above) and streams the
                # file back in 64 MB PcapChunk messages instead of one huge
                # unary reply, so the UI can show real progress as it lands.
                for chunk in app.backend_stub.PcapGet(
                    multiverse_pb2.PcapNameRequest(name=self.last_pcap_path),
                    timeout=None,
                ):
                    if total_size is None:
                        total_size = chunk.total_size
                        self.download_progress["maximum"] = max(total_size, 1)
                        self.download_size_label.config(
                            text=f"File size: {self._format_size(total_size)}"
                        )

                    out_file.write(chunk.content)
                    received += len(chunk.content)

                    self.download_progress["value"] = received
                    pct = (received / total_size * 100) if total_size else 0
                    self.download_progress_label.config(
                        text=f"{pct:.0f}%  ({self._format_size(received)} / "
                        f"{self._format_size(total_size)})"
                    )
                    self.update_idletasks()
        except grpc.RpcError as exc:
            detail = exc.details() or str(exc.code())
            if exc.code() in (grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED):
                app.disconnect_backend()
                app.connection_panel.connection_label.config(text="Not connected", foreground=RED)
                app.connection_panel.connect_button.config(text="Connect")
                app.connection_panel.host_entry.config(state="normal")
                app.connection_panel.port_entry.config(state="normal")
                app.connection_panel.ethernet_button.config(state="normal")
                app.connection_panel.wifi_button.config(state="normal")
            app.update_command_status(f"ERROR {detail}")
            self._reset_progress_ui()
            self.download_button.config(state="normal")
            return
        except OSError as exc:
            app.update_command_status(f"ERROR Could not save downloaded PCAP file: {exc}")
            self._reset_progress_ui()
            self.download_button.config(state="normal")
            return

        self.last_download_path = target
        self.last_download_name = self.last_pcap_path
        if target not in self.downloaded_pcap_paths:
            self.downloaded_pcap_paths.append(target)
        self.download_progress_label.config(text=f"Done — {self._format_size(received)}")
        app.update_command_status(f"OK Downloaded PCAP to {target}")
        self.download_button.config(state="normal")

    def cleanup(self):
        app = self.winfo_toplevel()

        remote_response = app.send_command_to_backend("PCAP DELETE-ALL")
        if not remote_response.startswith("OK"):
            app.update_command_status(remote_response)
            return

        removed_any = False
        errors = []
        for fname in os.listdir(os.getcwd()):
            if ".pcap" not in fname:
                continue
            fpath = os.path.join(os.getcwd(), fname)
            if not os.path.isfile(fpath):
                continue
            try:
                os.remove(fpath)
                removed_any = True
            except OSError as exc:
                errors.append(str(exc))

        self.downloaded_pcap_paths = []
        self.last_download_path = ""
        self.last_download_name = ""
        self.last_pcap_path = ""
        self.pcap_state = "STOPPED"
        self.pcap_status.config(text="Status: stopped", foreground=RED)
        self.start_button.config(state="disabled")
        self.download_button.config(state="disabled")
        self.cleanup_button.config(state="disabled")
        self._reset_progress_ui()

        if errors:
            app.update_command_status(
                f"ERROR Could not clean up local PCAP files: {'; '.join(errors)}"
            )
            return

        app.update_command_status(
            "OK All PCAP files cleaned up" if removed_any else remote_response
        )


class Multiverse(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Multiverse")
        self.geometry("1000x780")
        self.configure(bg=BG_DARK)
        self.minsize(880, 700)

        
        self.backend_channel = None
        self.backend_stub = None
        self.backend_host = "0.0.0.0"
        self.backend_port = 60000
        self.config = load_config()

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
        target = f"{host}:{port}"
        try:
            channel = grpc.insecure_channel(target)
            grpc.channel_ready_future(channel).result(timeout=2)
        except grpc.FutureTimeoutError:
            return f"ERROR Could not reach {target}"
        except Exception as exc:  
            return f"ERROR {exc}"

        self.backend_channel = channel
        self.backend_stub = multiverse_pb2_grpc.MultiverseStub(channel)
        self.backend_host = host
        self.backend_port = port
        return f"OK Connected to {host}:{port}"

    def disconnect_backend(self):
        if self.backend_channel is not None:
            try:
                self.backend_channel.close()
            except Exception:  
                pass
            self.backend_channel = None
            self.backend_stub = None

    def ensure_backend_connected(self) -> str:
        if self.backend_stub is not None:
            return "OK Already connected"

        host = self.connection_panel.host_var.get().strip() or self.backend_host
        port_string = self.connection_panel.port_var.get().strip() or str(self.backend_port)
        try:
            port = int(port_string)
        except ValueError:
            return "ERROR Invalid port"

        response = self.connect_backend(host, port)
        if response.startswith("OK"):
            self.connection_panel.connection_label.config(
                text=(
                    f"Connected via {self.connection_panel.network_var.get().title()} "
                    f"to {host}:{port}"
                ),
                foreground=GREEN,
            )
            self.connection_panel.connect_button.config(text="Disconnect")
            self.connection_panel.host_entry.config(state="disabled")
            self.connection_panel.port_entry.config(state="disabled")
            self.connection_panel.ethernet_button.config(state="disabled")
            self.connection_panel.wifi_button.config(state="disabled")
        return response

    def send_command_to_backend(self, command: str) -> str:
       
        if self.backend_stub is None:
            response = self.ensure_backend_connected()
            if not response.startswith("OK"):
                return response

        try:
            parts = command.strip().split(" ", 1)
            cmd = parts[0]
            arg = parts[1] if len(parts) > 1 else ""

            if cmd == "POWER":
                reply = self.backend_stub.SetPower(
                    multiverse_pb2.PowerRequest(on=(arg == "1")),
                    timeout=GRPC_TIMEOUT_SECONDS,
                )
            elif cmd == "WAKE-UP":
                reply = self.backend_stub.SetWakeUp(
                    multiverse_pb2.WakeUpRequest(on=(arg == "1")),
                    timeout=GRPC_TIMEOUT_SECONDS,
                )
            elif cmd == "ACTI-LINE":
                reply = self.backend_stub.SetActiLine(
                    multiverse_pb2.ActiLineRequest(on=(arg == "1")),
                    timeout=GRPC_TIMEOUT_SECONDS,
                )
            elif cmd == "PCAP":
                sub_parts = arg.split(" ", 1)
                sub = sub_parts[0]
                sub_arg = sub_parts[1] if len(sub_parts) > 1 else ""
                if sub == "START":
                    reply = self.backend_stub.PcapStart(
                        multiverse_pb2.Empty(), timeout=GRPC_TIMEOUT_SECONDS
                    )
                elif sub == "STOP":
                    reply = self.backend_stub.PcapStop(
                        multiverse_pb2.Empty(), timeout=GRPC_TIMEOUT_SECONDS
                    )
                elif sub == "NAME":
                    reply = self.backend_stub.PcapSetName(
                        multiverse_pb2.PcapNameRequest(name=sub_arg),
                        timeout=GRPC_TIMEOUT_SECONDS,
                    )
                elif sub == "DELETE":
                    reply = self.backend_stub.PcapDelete(
                        multiverse_pb2.PcapNameRequest(name=sub_arg),
                        timeout=GRPC_TIMEOUT_SECONDS,
                    )
                elif sub == "DELETE-ALL":
                    reply = self.backend_stub.PcapDeleteAll(
                        multiverse_pb2.Empty(), timeout=GRPC_TIMEOUT_SECONDS
                    )
                else:
                    return "ERROR Unknown PCAP subcommand"
            else:
                return "ERROR Unknown command"

            return reply.message

        except grpc.RpcError as exc:
            self.disconnect_backend()
            self.connection_panel.connection_label.config(text="Not connected", foreground=RED)
            self.connection_panel.connect_button.config(text="Connect")
            self.connection_panel.host_entry.config(state="normal")
            self.connection_panel.port_entry.config(state="normal")
            self.connection_panel.ethernet_button.config(state="normal")
            self.connection_panel.wifi_button.config(state="normal")
            detail = exc.details() or str(exc.code())
            return f"ERROR {detail}"

    def update_command_status(self, response: str):
        self.response_label.config(text=f"Backend: {response}")
        if response.startswith(("ERROR", "ERR")):
            detail = response.removeprefix("ERROR").removeprefix("ERR").strip()
            detail = detail or "An unknown error occurred."
            messagebox.showerror("Operation failed", detail, parent=self)


if __name__ == "__main__":
    app = Multiverse()
    app.mainloop()