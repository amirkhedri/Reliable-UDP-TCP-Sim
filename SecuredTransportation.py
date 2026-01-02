import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import time
import datetime
import random
import queue
import enum
import struct
import socket
import threading

# --- CONFIGURATION ---
THEME = {
    "bg": "#020205",        # Void Black
    "panel": "#0B1019",     # Dark Panel
    "fg": "#00FF41",        # Hacker Green
    "accent_a": "#00E5FF",  # Cyan (Client A)
    "accent_b": "#F50057",  # Pink (Client B)
    "warning": "#FFD600",   # Amber
    "danger": "#FF1744",    # Red
    "grid": "#112233",
    "disabled": "#333333"
}

# Network Configuration
SERVER_IP = '127.0.0.1'
SERVER_PORT = 12000
CLIENT_A_PORT = 12001
CLIENT_B_PORT = 12002
BUFFER_SIZE = 1024

MAX_RETRIES = 5  
TIMEOUT_DURATION = 3.0 # Seconds for socket timeout
ANIMATION_DURATION_MS = 1500 # Visual travel time
WINDOW_SIZE = 5 # GBN Window Size

# --- UTILS & PROTOCOL DEFINITIONS ---

def calculate_checksum(data_bytes):
    """
    Calculates the 16-bit one's complement of the one's complement sum 
    of all 16-bit words. Standard Internet Checksum.
    """
    if len(data_bytes) % 2 == 1:
        data_bytes += b'\0'
    
    s = 0
    for i in range(0, len(data_bytes), 2):
        w = (data_bytes[i] << 8) + (data_bytes[i + 1])
        s += w
        
    s = (s >> 16) + (s & 0xffff)
    s += (s >> 16)
    
    return ~s & 0xffff

class PacketFlags:
    SYN = 0x01
    ACK = 0x02
    FIN = 0x04
    DATA = 0x00

class Protocol(enum.Enum):
    UDP_RAW = "Raw UDP (Unreliable)"
    RDT_30 = "RDT 3.0 (Stop-and-Wait)"
    GBN = "Go-Back-N"

class RealPacket:
    """
    Binary Structure (Header 12 Bytes):
    [SeqNum (4B)] [AckNum (4B)] [Flags (2B)] [Checksum (2B)] [Payload (Variable)]
    """
    def __init__(self, seq, ack_num, flags, data, source_port=0):
        self.seq = seq
        self.ack_num = ack_num
        self.flags = flags
        self.data = data.encode('utf-8') if isinstance(data, str) else data
        self.checksum = 0
        self.source_port = source_port # Helper to identify sender visual
        
        # Calculate checksum exactly like IP/TCP
        self.checksum = calculate_checksum(self.pack(calc_mode=True))

    def pack(self, calc_mode=False):
        chk = 0 if calc_mode else self.checksum
        # ! = Network Endian (Big Endian)
        # I = unsigned int (4 bytes), H = unsigned short (2 bytes)
        header = struct.pack('!IIHH', self.seq, self.ack_num, self.flags, chk)
        return header + self.data

    @classmethod
    def unpack(cls, data_bytes):
        if len(data_bytes) < 12: return None, False
        
        header = data_bytes[:12]
        payload = data_bytes[12:]
        
        seq, ack, flags, recv_chk = struct.unpack('!IIHH', header)
        
        # Verify Integrity
        zero_chk_header = struct.pack('!IIHH', seq, ack, flags, 0)
        calc_chk = calculate_checksum(zero_chk_header + payload)
        
        is_corrupt = (calc_chk != recv_chk)
        
        pkt = cls(seq, ack, flags, payload)
        pkt.checksum = recv_chk
        return pkt, is_corrupt

    def get_type_name(self):
        names = []
        if self.flags & PacketFlags.SYN: names.append("SYN")
        if self.flags & PacketFlags.FIN: names.append("FIN")
        if self.flags & PacketFlags.ACK: names.append("ACK")
        if not names: names.append("DATA")
        return "+".join(names)

# --- STATE CLASSES ---
class ClientState:
    def __init__(self, name, port, color):
        self.name = name
        self.port = port
        self.color = color
        self.state = "CLOSED" 
        
        # RDT 3.0 Sender Variables
        self.seq = 0            # Alternating bit (0 or 1)
        self.sock = None        # The real socket
        self.waiting_ack = False
        
        # GBN Variables
        self.gbn_base = 0
        self.gbn_next_seq = 0
        self.gbn_buffer = {}    # Stores packets {seq: RealPacket}
        self.gbn_timer_start = None
        
        self.pkts_sent = 0
        self.pkts_lost = 0
        self.cwnd = 1           # Congestion Window (Bonus visual)

class ServerState:
    def __init__(self):
        # Maps Port -> ExpectedSequenceNumber
        self.client_expected_seq = {
            CLIENT_A_PORT: 0,
            CLIENT_B_PORT: 0
        }
        self.sock = None

# --- MAIN APPLICATION ---
class UltimateNetSim:
    def __init__(self, root):
        self.root = root
        self.root.title("RDT 3.0 / GBN / Real Socket Emulator")
        self.root.geometry("1450x950")
        self.root.configure(bg=THEME['bg'])
        
        # State Lock for Thread Safety (Fixes Race Conditions)
        self.state_lock = threading.Lock()

        # -- REAL NETWORKING SETUP --
        self.clients = {
            "Client A": ClientState("Client A", CLIENT_A_PORT, THEME['accent_a']),
            "Client B": ClientState("Client B", CLIENT_B_PORT, THEME['accent_b'])
        }
        self.server_state = ServerState()
        self.running = True
        
        self.setup_sockets()
        
        # UI State
        self.active_client_name = "Client A"
        self.anim_queue = queue.Queue()
        
        # Sim Variables (Error Injection)
        self.protocol_var = tk.StringVar(value=Protocol.RDT_30.value)
        self.p_loss = tk.DoubleVar(value=0.0)
        self.p_corrupt = tk.DoubleVar(value=0.0)
        self.p_delay = tk.DoubleVar(value=0.0)
        self.p_dupe = tk.DoubleVar(value=0.0)
        
        self.setup_ui()
        self.start_loops()
        
        # Start GBN Background Monitor
        self.gbn_monitor_thread = threading.Thread(target=self.gbn_monitor_loop, daemon=True)
        self.gbn_monitor_thread.start()

    def setup_sockets(self):
        """Binds real UDP sockets to localhost ports"""
        try:
            # Server Socket
            self.server_state.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.server_state.sock.bind((SERVER_IP, SERVER_PORT))
            self.server_state.sock.setblocking(False) # Non-blocking for UI thread safety

            # Client Sockets
            for cli in self.clients.values():
                cli.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                cli.sock.bind((SERVER_IP, cli.port))
                cli.sock.settimeout(TIMEOUT_DURATION)
                
            # Start Receiver Threads
            self.server_thread = threading.Thread(target=self.server_listen_loop, daemon=True)
            self.server_thread.start()
            
            # We need client listeners mainly for ACKs
            self.client_threads = {}
            for name in self.clients:
                t = threading.Thread(target=self.client_listen_loop, args=(name,), daemon=True)
                t.start()
                self.client_threads[name] = t
                
            print("Real Sockets Bound Successfully.")
            
        except Exception as e:
            messagebox.showerror("Socket Error", f"Failed to bind ports: {e}\nEnsure ports 12000-12002 are free.")
            self.running = False

    def get_active_client(self):
        return self.clients[self.active_client_name]

    # --- UI CONSTRUCTION (PRESERVED) ---
    def setup_ui(self):
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("TFrame", background=THEME['bg'])
        style.configure("Panel.TFrame", background=THEME['panel'])
        style.configure("TLabel", background=THEME['bg'], foreground="white", font=("Consolas", 10))
        style.configure("Header.TLabel", background=THEME['bg'], foreground=THEME['accent_a'], font=("Impact", 24))
        
        # Header
        head = ttk.Frame(self.root)
        head.pack(fill="x", padx=20, pady=15)
        ttk.Label(head, text="NETWORK EMULATOR PRO", style="Header.TLabel").pack(side="left")
        ttk.Label(head, text="REAL UDP / RDT 3.0 / GBN", style="Header.TLabel").pack(side="right")

        # Main Body
        main = ttk.Frame(self.root)
        main.pack(fill="both", expand=True, padx=10, pady=5)

        # -- LEFT PANEL --
        left = ttk.Frame(main, width=320, style="Panel.TFrame")
        left.pack(side="left", fill="y", padx=5)
        self.build_controls(left)

        # -- CENTER PANEL --
        center = ttk.Frame(main)
        center.pack(side="left", fill="both", expand=True, padx=5)
        
        self.canvas = tk.Canvas(center, bg="#000000", height=500, highlightthickness=2, highlightbackground=THEME['fg'])
        self.canvas.pack(fill="x", pady=5)
        self.draw_topology()

        graph_frame = ttk.LabelFrame(center, text=" STATS & CWND ", style="Panel.TFrame")
        graph_frame.pack(fill="both", expand=True, pady=5)
        
        self.cwnd_canvas = tk.Canvas(graph_frame, bg="black", height=150)
        self.cwnd_canvas.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        self.cwnd_history = []
        
        self.stats_text = tk.Text(graph_frame, bg="black", fg=THEME['fg'], width=40, font=("Consolas", 10))
        self.stats_text.pack(side="right", fill="y", padx=5, pady=5)

        # -- RIGHT PANEL --
        right = ttk.Frame(main, width=320, style="Panel.TFrame")
        right.pack(side="left", fill="y", padx=5)
        
        ttk.Label(right, text="LIVE PACKET LOGS", font=("Consolas", 12, "bold"), background=THEME['panel']).pack(pady=5)
        self.log_area = scrolledtext.ScrolledText(right, bg="#000", fg=THEME['fg'], font=("Consolas", 9))
        self.log_area.pack(fill="both", expand=True, padx=5, pady=5)
        
        self.log_area.tag_config("INFO", foreground="white")
        self.log_area.tag_config("SUCCESS", foreground=THEME['fg'])
        self.log_area.tag_config("WARN", foreground=THEME['warning'])
        self.log_area.tag_config("ERROR", foreground=THEME['danger'])
        self.log_area.tag_config("Client A", foreground=THEME['accent_a'])
        self.log_area.tag_config("Client B", foreground=THEME['accent_b'])

    def build_controls(self, parent):
        p = ttk.Frame(parent, style="Panel.TFrame", padding=15)
        p.pack(fill="both", expand=True)

        # Client Switch
        ttk.Label(p, text="ACTIVE CLIENT SOURCE:", background=THEME['panel'], foreground="#888").pack(anchor="w")
        self.client_switch = ttk.Combobox(p, values=["Client A", "Client B"], state="readonly", font=("Consolas", 11, "bold"))
        self.client_switch.set("Client A")
        self.client_switch.pack(fill="x", pady=5)
        self.client_switch.bind("<<ComboboxSelected>>", self.on_client_switch)
        self.lbl_status = ttk.Label(p, text="STATUS: CLOSED", background=THEME['panel'], font=("Consolas", 10, "bold"), foreground=THEME['danger'])
        self.lbl_status.pack(anchor="w", pady=(0, 15))

        # Protocol
        ttk.Label(p, text="PROTOCOL LAYER:", background=THEME['panel'], foreground="#888").pack(anchor="w")
        pm = ttk.OptionMenu(p, self.protocol_var, Protocol.RDT_30.value, *[x.value for x in Protocol], command=self.on_proto_change)
        pm.pack(fill="x", pady=5)

        # Connection
        self.btn_connect = tk.Button(p, text="ESTABLISH CONNECTION", bg=THEME['panel'], fg="white", command=lambda: self.run_async(self.handshake))
        self.btn_connect.pack(fill="x", pady=2)
        self.btn_close = tk.Button(p, text="TERMINATE CONNECTION", bg=THEME['panel'], fg="white", command=lambda: self.run_async(self.teardown))
        self.btn_close.pack(fill="x", pady=2)

        # Data
        ttk.Label(p, text="DATA PAYLOAD:", background=THEME['panel'], foreground="#888").pack(anchor="w", pady=(15, 0))
        self.entry_data = ttk.Entry(p)
        self.entry_data.insert(0, "Sensitive_Data_01")
        self.entry_data.pack(fill="x", pady=5)
        
        self.btn_send = tk.Button(p, text="SEND PACKET", bg=THEME['fg'], fg="black", font=("Impact", 12), command=lambda: self.run_async(self.send_data_logic))
        self.btn_send.pack(fill="x", pady=10)

        # Errors
        err = ttk.LabelFrame(p, text=" UNRELIABLE CHANNEL ", style="Panel.TFrame")
        err.pack(fill="x", pady=20)
        
        def slider(frame, txt, var):
            f = ttk.Frame(frame, style="Panel.TFrame")
            f.pack(fill="x", pady=2)
            ttk.Label(f, text=txt, width=12, background=THEME['panel']).pack(side="left")
            tk.Scale(f, from_=0.0, to=1.0, resolution=0.1, orient="horizontal", variable=var, bg=THEME['panel'], fg="white", highlightthickness=0).pack(side="left", fill="x", expand=True)
        
        slider(err, "P(Drop):", self.p_loss)
        slider(err, "P(Corrupt):", self.p_corrupt)
        slider(err, "P(Delay):", self.p_delay)
        slider(err, "P(Dupe):", self.p_dupe)

    def draw_topology(self):
        w, h = 1000, 500
        # Grid
        for i in range(0, w, 50): self.canvas.create_line(i, 0, i, h, fill="#112233")
        for i in range(0, h, 50): self.canvas.create_line(0, i, w, i, fill="#112233")
        
        # Nodes
        self.canvas.create_oval(50, 100, 150, 200, outline=THEME['accent_a'], width=3, fill=THEME['panel'])
        self.canvas.create_text(100, 150, text="CLIENT A\n:12001", fill="white", font=("Impact", 12), justify="center")
        
        self.canvas.create_oval(50, 300, 150, 400, outline=THEME['accent_b'], width=3, fill=THEME['panel'])
        self.canvas.create_text(100, 350, text="CLIENT B\n:12002", fill="white", font=("Impact", 12), justify="center")
        
        self.canvas.create_oval(600, 200, 700, 300, outline=THEME['fg'], width=3, fill=THEME['panel'])
        self.canvas.create_text(650, 250, text="SERVER\n:12000", fill="white", font=("Impact", 12), justify="center")

        # Links
        self.canvas.create_line(150, 150, 600, 250, fill=THEME['accent_a'], dash=(4, 2), width=2)
        self.canvas.create_line(150, 350, 600, 250, fill=THEME['accent_b'], dash=(4, 2), width=2)

    # --- THREADING HELPERS ---
    def run_async(self, func, *args):
        """Runs a function in a separate thread to prevent UI freezing."""
        t = threading.Thread(target=func, args=args, daemon=True)
        t.start()

    def on_client_switch(self, event):
        self.active_client_name = self.client_switch.get()
        self.update_ui_state()
        self.log("INFO", f"Active Control: {self.active_client_name}")

    def on_proto_change(self, val):
        self.log("INFO", f"Protocol Switched to {val}")
        # Reset server expectation on protocol switch to avoid sync issues
        with self.state_lock:
            for k in self.server_state.client_expected_seq:
                self.server_state.client_expected_seq[k] = 0
            # Reset client GBN vars
            for cli in self.clients.values():
                cli.seq = 0
                cli.gbn_base = 0
                cli.gbn_next_seq = 0
                cli.gbn_buffer.clear()
                cli.gbn_timer_start = None

    def update_ui_state(self):
        cli = self.get_active_client()
        color = THEME['fg'] if cli.state == "ESTABLISHED" else THEME['danger']
        self.lbl_status.config(text=f"STATUS: {cli.state}", foreground=color)
        
        # Only block Send button for RDT 3.0 Stop-and-Wait
        if self.protocol_var.get() == Protocol.RDT_30.value and cli.waiting_ack:
            self.btn_send.config(state="disabled", text="WAITING FOR ACK...", bg=THEME['disabled'])
        else:
            self.btn_send.config(state="normal", text="SEND PACKET", bg=THEME['fg'])

    def log(self, tag, msg, color=None):
        def _log():
            ts = datetime.datetime.now().strftime("%H:%M:%S")
            self.log_area.insert("end", f"[{ts}] ", "INFO")
            self.log_area.insert("end", f"[{tag}] ", color if color else tag)
            self.log_area.insert("end", f"{msg}\n", "INFO")
            self.log_area.see("end")
        self.root.after(0, _log)

    # --- THE "UNRELIABLE" CHANNEL (Middleware) ---
    def udt_send(self, packet_obj, sock, dest_addr):
        """
        Unreliable Data Transfer:
        Simulates Drop, Corruption, Delay, Duplication BEFORE sending to real socket.
        """
        raw_bytes = packet_obj.pack()
        status = "OK"
        
        # 1. DROP
        if random.random() < self.p_loss.get():
            self.trigger_animation(packet_obj, "LOSS")
            self.log("CHANNEL", f"Packet #{packet_obj.seq} Dropped by Network.", "ERROR")
            return # Don't send

        # 2. DELAY
        delay = 0
        if random.random() < self.p_delay.get():
            delay = random.uniform(0.5, 2.0)
            status = "DELAY"
            time.sleep(delay)

        # 3. CORRUPT (Bit Flip)
        if random.random() < self.p_corrupt.get():
            status = "CORRUPT"
            # Corrupt the 10th byte (part of flags/checksum)
            arr = bytearray(raw_bytes)
            if len(arr) > 10:
                arr[10] ^= 0xFF 
            raw_bytes = bytes(arr)
            self.log("CHANNEL", f"Packet #{packet_obj.seq} Corrupted.", "ERROR")

        # 4. DUPLICATE
        if random.random() < self.p_dupe.get():
            self.log("CHANNEL", f"Packet #{packet_obj.seq} Duplicated.", "WARN")
            sock.sendto(raw_bytes, dest_addr)

        # Send Real
        self.trigger_animation(packet_obj, status)
        
        # Sync socket send with animation duration for visual consistency
        time.sleep(ANIMATION_DURATION_MS / 1000.0) 
        
        sock.sendto(raw_bytes, dest_addr)

    # --- CLIENT SIDE LOGIC (RDT SENDER) ---
    def handshake(self):
        cli = self.get_active_client()
        if cli.state != "CLOSED": return

        self.log(cli.name, "Initiating 3-Way Handshake...", THEME['accent_a'])
        cli.state = "SYN_SENT"
        self.root.after(0, self.update_ui_state)
        
        # Send SYN
        pkt = RealPacket(0, 0, PacketFlags.SYN, "", cli.port)
        self.udt_send(pkt, cli.sock, (SERVER_IP, SERVER_PORT))

    def teardown(self):
        cli = self.get_active_client()
        if cli.state != "ESTABLISHED": return
        
        self.log(cli.name, "Requesting Teardown...", THEME['danger'])
        cli.state = "FIN_WAIT"
        self.root.after(0, self.update_ui_state)
        
        # Send FIN
        pkt = RealPacket(cli.seq, 0, PacketFlags.FIN, "", cli.port)
        self.udt_send(pkt, cli.sock, (SERVER_IP, SERVER_PORT))

    def send_data_logic(self):
        """
        Main Sender Logic.
        Handles both RDT 3.0 (Stop-and-Wait) and GBN.
        """
        cli = self.get_active_client()
        # Note: Raw UDP does not require ESTABLISHED state.
        if self.protocol_var.get() != Protocol.UDP_RAW.value and cli.state != "ESTABLISHED":
             messagebox.showerror("Protocol Error", "Connection not established! Handshake required.")
             return

        data = self.entry_data.get()
        protocol = self.protocol_var.get()

        # --- GBN LOGIC ---
        if protocol == Protocol.GBN.value:
            packet_to_send = None
            seq_to_send = 0
            
            # --- CRITICAL SECTION: State Update ---
            # We must lock the state modification so that rapid clicks don't 
            # read the same 'next_seq' before it is incremented.
            with self.state_lock:
                if cli.gbn_next_seq < cli.gbn_base + WINDOW_SIZE:
                    # Create and Buffer
                    seq_to_send = cli.gbn_next_seq
                    pkt = RealPacket(seq_to_send, 0, PacketFlags.DATA, data, cli.port)
                    cli.gbn_buffer[seq_to_send] = pkt
                    
                    # Update State
                    cli.gbn_next_seq += 1
                    cli.pkts_sent += 1
                    
                    if cli.gbn_base == seq_to_send:
                        cli.gbn_timer_start = time.time()
                    
                    packet_to_send = pkt
                else:
                    self.log(cli.name, "[GBN] Window Full. Cannot send.", "WARN")
                    return
            
            # --- NETWORK SECTION ---
            # Send outside the lock to allow UI responsivenes and concurrency
            if packet_to_send:
                self.log(cli.name, f"[GBN] Sending Packet #{seq_to_send}", THEME['accent_a'])
                self.udt_send(packet_to_send, cli.sock, (SERVER_IP, SERVER_PORT))
            
            return

        # --- RDT 3.0 LOGIC (STOP-AND-WAIT) ---
        elif protocol == Protocol.RDT_30.value:
            cli.waiting_ack = True
            self.root.after(0, self.update_ui_state)
            
            pkt = RealPacket(cli.seq, 0, PacketFlags.DATA, data, cli.port)
            
            # Retry Loop
            retries = 0
            while retries < MAX_RETRIES:
                # 1. UDT Send
                self.udt_send(pkt, cli.sock, (SERVER_IP, SERVER_PORT))
                with self.state_lock:
                    cli.pkts_sent += 1
                
                # 2. Wait for ACK (Blocking with Timeout)
                try:
                    ack_received = self.wait_for_ack(cli, pkt.seq)
                    
                    if ack_received:
                        self.log(cli.name, f"Received Valid ACK {cli.seq}", "SUCCESS")
                        with self.state_lock:
                            cli.seq = 1 - cli.seq # Toggle
                            cli.cwnd = min(cli.cwnd + 1, 10) 
                        cli.waiting_ack = False
                        self.root.after(0, self.update_ui_state)
                        return # Success
                    else:
                        self.log(cli.name, f"ACK Error/Corruption. Retrying...", "WARN")
                        
                except TimeoutError:
                    self.log(cli.name, f"Timeout waiting for ACK {cli.seq}", "ERROR")
                
                retries += 1
                cli.pkts_lost += 1
                self.log(cli.name, f"Retransmitting ({retries}/{MAX_RETRIES})...", "warning")
                time.sleep(1) # Backoff

            self.log(cli.name, "Max Retries Reached. Aborting.", "ERROR")
            cli.waiting_ack = False
            cli.cwnd = 1
            self.root.after(0, self.update_ui_state)

        # --- RAW UDP LOGIC (NEW) ---
        else: # Protocol.UDP_RAW
             # Raw UDP: No reliability, no windows, no ACKs. Fire and forget.
             # We use seq 0 just as a placeholder (or you could use a counter)
             pkt = RealPacket(cli.pkts_sent, 0, PacketFlags.DATA, data, cli.port)
             self.log(cli.name, f"[UDP] Sending Packet #{cli.pkts_sent} (Unreliable)", THEME['accent_a'])
             
             self.udt_send(pkt, cli.sock, (SERVER_IP, SERVER_PORT))
             
             with self.state_lock:
                 cli.pkts_sent += 1

    def wait_for_ack(self, cli, expected_ack):
        """
        Waits for a signal from the Client Listener thread.
        This is a simplistic sync for Stop-and-Wait.
        """
        start_time = time.time()
        while time.time() - start_time < (TIMEOUT_DURATION + 2): # +2 for animation buffer
            # Check the shared state last received
            if hasattr(cli, 'last_ack_pkt'):
                ack_pkt = cli.last_ack_pkt
                if ack_pkt and ack_pkt.ack_num == expected_ack and (ack_pkt.flags & PacketFlags.ACK):
                    cli.last_ack_pkt = None # Consume
                    return True
            time.sleep(0.1)
        return False

    def gbn_monitor_loop(self):
        """
        Background Thread to handle GBN Timeouts.
        """
        while self.running:
            if self.protocol_var.get() == Protocol.GBN.value:
                # Iterate over a copy of values or keys to avoid runtime dict size change errors
                # But here we iterate over fixed keys
                for cli in self.clients.values():
                    # Read state with Lock for safety
                    needs_retransmit = False
                    packets_to_resend = []
                    
                    with self.state_lock:
                        if cli.state == "ESTABLISHED" and cli.gbn_base < cli.gbn_next_seq:
                            if cli.gbn_timer_start and (time.time() - cli.gbn_timer_start > TIMEOUT_DURATION):
                                needs_retransmit = True
                                # Restart Timer
                                cli.gbn_timer_start = time.time()
                                # Collect packets
                                for seq in range(cli.gbn_base, cli.gbn_next_seq):
                                    if seq in cli.gbn_buffer:
                                        packets_to_resend.append(cli.gbn_buffer[seq])

                    if needs_retransmit:
                        base = packets_to_resend[0].seq if packets_to_resend else -1
                        last = packets_to_resend[-1].seq if packets_to_resend else -1
                        self.log(cli.name, f"[GBN] Timeout! Retransmitting window {base} to {last}", "danger")
                        
                        for pkt in packets_to_resend:
                            # Launch separate threads so we don't block the monitor loop
                            threading.Thread(target=self.udt_send, args=(pkt, cli.sock, (SERVER_IP, SERVER_PORT)), daemon=True).start()
                            with self.state_lock:
                                cli.pkts_lost += 1
            time.sleep(0.5)

    # --- RECEIVER LOOPS (DAEMONS) ---
    
    def server_listen_loop(self):
        """Real Socket Receiver for Server"""
        while self.running:
            try:
                data, addr = self.server_state.sock.recvfrom(BUFFER_SIZE)
                # Identify Client based on port
                client_id = "Client A" if addr[1] == CLIENT_A_PORT else "Client B"
                
                # Unpack and Verify Checksum
                pkt, is_corrupt = RealPacket.unpack(data)
                
                if not pkt: continue # Junk data

                expected_seq = self.server_state.client_expected_seq[addr[1]]
                response_pkt = None
                
                current_proto = self.protocol_var.get()

                # 1. Corrupt Check
                if is_corrupt:
                    self.log("SERVER", f"Corrupt Packet from {client_id}. Re-ACKing.", "ERROR")
                    # Send ACK for PREVIOUS sequence (Last correctly received)
                    ack_target = expected_seq if current_proto == Protocol.RDT_30.value else (expected_seq - 1)
                    if current_proto == Protocol.RDT_30.value: ack_target = 1 - expected_seq
                    
                    # For Raw UDP, we probably just ignore corrupts or log them
                    if current_proto == Protocol.UDP_RAW.value:
                        continue
                    
                    response_pkt = RealPacket(0, ack_target, PacketFlags.ACK, "", 0)
                
                # 2. Control Messages
                elif pkt.flags & PacketFlags.SYN:
                    self.log("SERVER", f"SYN received from {client_id}", "INFO")
                    response_pkt = RealPacket(0, 0, PacketFlags.SYN | PacketFlags.ACK, "", 0)
                    with self.state_lock:
                        self.server_state.client_expected_seq[addr[1]] = 0
                    
                elif pkt.flags & PacketFlags.FIN:
                    self.log("SERVER", f"FIN received from {client_id}", "WARN")
                    response_pkt = RealPacket(0, 0, PacketFlags.FIN | PacketFlags.ACK, "", 0)
                
                # 3. DATA Processing
                elif pkt.flags == PacketFlags.DATA: # Ensure no control flags
                    
                    # --- RAW UDP HANDLER ---
                    if current_proto == Protocol.UDP_RAW.value:
                         self.log("SERVER", f"UDP Packet from {client_id}: {pkt.data.decode()}", "SUCCESS")
                         # Do NOT send ACK.
                         continue

                    # --- RDT/GBN HANDLER ---
                    if pkt.seq == expected_seq:
                        self.log("SERVER", f"Data Accepted from {client_id} (Seq {pkt.seq}): {pkt.data.decode()}", "SUCCESS")
                        
                        # Send ACK
                        # For RDT 3.0: ACK the specific sequence
                        # For GBN: Cumulative ACK (ACK matches seq received)
                        response_pkt = RealPacket(0, pkt.seq, PacketFlags.ACK, "", 0)
                        
                        # Update Expected
                        with self.state_lock:
                            if current_proto == Protocol.RDT_30.value:
                                self.server_state.client_expected_seq[addr[1]] = 1 - expected_seq
                            else:
                                self.server_state.client_expected_seq[addr[1]] = expected_seq + 1
                            
                    else:
                        self.log("SERVER", f"Out-of-Order Seq {pkt.seq} (Expected {expected_seq}). Re-ACKing.", "WARN")
                        # GBN: Re-send ACK for largest correctly received packet
                        # RDT: Re-send ACK for duplicate
                        ack_target = pkt.seq if current_proto == Protocol.RDT_30.value else (expected_seq - 1)
                        response_pkt = RealPacket(0, ack_target, PacketFlags.ACK, "", 0)

                # Send Response
                if response_pkt:
                    # Animate Server -> Client
                    self.trigger_animation(response_pkt, "OK", reverse=True, dest_client=client_id)
                    time.sleep(ANIMATION_DURATION_MS / 1000.0)
                    self.server_state.sock.sendto(response_pkt.pack(), addr)
                    
            except BlockingIOError:
                time.sleep(0.1) # No data
            except Exception as e:
                print(f"Server Error: {e}")

    def client_listen_loop(self, client_name):
        """Real Socket Receiver for Clients (Handling ACKs)"""
        cli = self.clients[client_name]
        while self.running:
            try:
                data, addr = cli.sock.recvfrom(BUFFER_SIZE)
                pkt, is_corrupt = RealPacket.unpack(data)
                
                if not pkt: continue
                if is_corrupt: 
                    self.log(client_name, "Received Corrupt ACK. Ignoring.", "ERROR")
                    continue

                # Handshake Logic
                if (pkt.flags & PacketFlags.SYN) and (pkt.flags & PacketFlags.ACK):
                    cli.state = "ESTABLISHED"
                    self.log(client_name, "Connection Established (SYN-ACK).", "SUCCESS")
                    self.root.after(0, self.update_ui_state)
                    continue
                    
                if (pkt.flags & PacketFlags.FIN) and (pkt.flags & PacketFlags.ACK):
                    cli.state = "CLOSED"
                    self.log(client_name, "Connection Closed (FIN-ACK).", "danger")
                    self.root.after(0, self.update_ui_state)
                    continue

                # Data Logic - Store for Sender Thread to read
                cli.last_ack_pkt = pkt
                
                # --- GBN ACK PROCESSING ---
                if self.protocol_var.get() == Protocol.GBN.value and (pkt.flags & PacketFlags.ACK):
                    # Cumulative ACK: If we receive ACK N, it means everything up to N is handled.
                    # Current impl sends ACK N to confirm N.
                    ack_seq = pkt.ack_num
                    
                    with self.state_lock:
                        if ack_seq >= cli.gbn_base:
                            # Verify valid range to avoid weird jumps
                            if ack_seq < cli.gbn_next_seq:
                                self.log(client_name, f"[GBN] Received ACK {ack_seq}. Window Slides.", "SUCCESS")
                                # Slide window
                                cli.gbn_base = ack_seq + 1
                                
                                # Stop timer if no more unacked packets
                                if cli.gbn_base == cli.gbn_next_seq:
                                    cli.gbn_timer_start = None
                                else:
                                    # Restart timer for the remaining oldest packet
                                    cli.gbn_timer_start = time.time()
                
            except socket.timeout:
                pass # Normal behavior
            except Exception as e:
                pass

    # --- ANIMATION CORE ---
    def trigger_animation(self, pkt_obj, status, reverse=False, dest_client=None):
        """Queues animation on the Main Thread"""
        self.root.after(0, lambda: self._animate_start(pkt_obj, status, reverse, dest_client))

    def _animate_start(self, pkt_obj, status, reverse, dest_client):
        # Determine source/dest coordinates
        client_name = dest_client if dest_client else ("Client A" if pkt_obj.source_port == CLIENT_A_PORT else "Client B")
        
        c_coords = (150, 150) if client_name == "Client A" else (150, 350)
        s_coords = (600, 250)
        
        start = s_coords if reverse else c_coords
        end = c_coords if reverse else s_coords
        
        # Color
        color = THEME['accent_a'] if client_name == "Client A" else THEME['accent_b']
        if status == "CORRUPT": color = THEME['danger']
        if pkt_obj.flags & PacketFlags.ACK: color = THEME['warning']
        
        # Draw Object
        size = 15
        obj = self.canvas.create_oval(start[0]-size, start[1]-size, start[0]+size, start[1]+size, fill=color, outline="white")
        
        label_txt = pkt_obj.get_type_name()
        if pkt_obj.flags == PacketFlags.DATA: label_txt += f" #{pkt_obj.seq}"
        if pkt_obj.flags & PacketFlags.ACK: label_txt += f" #{pkt_obj.ack_num}"
        if status == "DELAY": label_txt += " (D)"
        
        txt = self.canvas.create_text(start[0], start[1]-30, text=label_txt, fill="white", font=("Arial", 8))
        
        steps = 60
        dx = (end[0] - start[0]) / steps
        dy = (end[1] - start[1]) / steps
        refresh_rate = int(ANIMATION_DURATION_MS / steps)

        def move(step):
            if step >= steps:
                self.canvas.delete(obj)
                self.canvas.delete(txt)
                return

            # Visual Drop
            if status == "LOSS" and step == int(steps/2):
                self.canvas.delete(obj)
                self.canvas.delete(txt)
                return 

            self.canvas.move(obj, dx, dy)
            self.canvas.move(txt, dx, dy)
            self.root.after(refresh_rate, lambda: move(step+1))
        
        move(0)

    # --- STATS LOOP ---
    def start_loops(self):
        self.update_stats()
        self.update_graphs()
        
    def update_stats(self):
        cli = self.get_active_client()
        
        # Determine seq display based on protocol
        curr_seq = cli.seq if self.protocol_var.get() == Protocol.RDT_30.value else cli.gbn_next_seq
        if self.protocol_var.get() == Protocol.UDP_RAW.value:
            curr_seq = cli.pkts_sent

        txt = f"""
        ACTIVE SOCKET: {cli.port} -> {SERVER_PORT}
        STATE: {cli.state}
        NEXT SEQ: {curr_seq}
        CWND (Sim): {cli.cwnd}
        
        Total Sent: {cli.pkts_sent}
        Total Lost: {cli.pkts_lost}
        """
        if self.protocol_var.get() == Protocol.GBN.value:
            txt += f"GBN Base: {cli.gbn_base}\n"
            
        self.stats_text.delete("1.0", "end")
        self.stats_text.insert("end", txt)
        self.root.after(200, self.update_stats)

    def update_graphs(self):
        cli = self.get_active_client()
        self.cwnd_history.append(cli.cwnd)
        if len(self.cwnd_history) > 60: self.cwnd_history.pop(0)
        
        self.cwnd_canvas.delete("all")
        w = self.cwnd_canvas.winfo_width()
        h = self.cwnd_canvas.winfo_height()
        if w < 10: w = 200
        
        if len(self.cwnd_history) > 1:
            points = []
            dx = w / 60
            for i, val in enumerate(self.cwnd_history):
                x = i * dx
                y = h - (val * (h/12))
                points.extend([x, y])
            
            color = THEME['accent_a'] if cli.name == "Client A" else THEME['accent_b']
            self.cwnd_canvas.create_line(points, fill=color, width=2)
            self.cwnd_canvas.create_text(10, 10, text=f"Congestion Window: {cli.cwnd}", fill="white", anchor="nw")
            
        self.root.after(100, self.update_graphs)

if __name__ == "__main__":
    root = tk.Tk()
    app = UltimateNetSim(root)
    
    # Clean exit
    def on_closing():
        app.running = False
        root.destroy()
        import sys
        sys.exit(0)
        
    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()