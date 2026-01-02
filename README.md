# 🛡️ TCP-over-UDP (Reliable Data Transfer)

**Developer:** Amir Khedri  
**Course:** Computer Networks - Phase 2  
**University:** University of Isfahan  

![Python](https://img.shields.io/badge/Python-3.x-blue.svg)
![Protocol](https://img.shields.io/badge/Style-TCP%20%2F%20Sliding%20Window-orange.svg)
![Mode](https://img.shields.io/badge/Mode-Raw%20UDP%20Support-yellow.svg)

## 📖 Project Overview
This project implements a full **TCP-style Reliable Data Transfer (RDT)** protocol on top of UDP. It simulates the core features of TCP—including connection establishment, reliability, and flow control—while allowing the user to switch to a **Raw UDP** mode for unreliable transmission.

The application features a real-time **GUI Network Emulator** that visualizes packets traveling between clients and servers, complete with simulated packet loss and corruption.

## ✨ Key Features

### 🔧 TCP-Like Implementation
* **3-Way Handshake:** Establishes connections using `SYN` → `SYN-ACK` → `ACK` packets.
* **Connection Teardown:** Gracefully closes connections using `FIN` flags.
* **Packet Structure:** Uses a binary header with **Sequence Numbers**, **Acknowledgement Numbers**, and **Flags** (SYN, FIN, ACK).
* **Reliability Algorithms:**
    * **Stop-and-Wait (RDT 3.0):** Alternating bit protocol for basic reliability.
    * **Go-Back-N (GBN):** Sliding window protocol with cumulative ACKs and a single timer.
    * **Congestion Window (CWND):** Visualizes the growth of the congestion window during transmission.

### ⚡ Raw UDP Mode
* **Unreliable Transport:** Includes a `UDP_RAW` mode that bypasses all reliability checks.
* **Fire-and-Forget:** Sends packets without handshakes or ACKs, demonstrating the difference between reliable (TCP) and unreliable (UDP) streams.

### 🧪 Error Simulation (The "Unreliable Channel")
The code intercepts packets before sending them to the real socket to simulate network faults:
* **Packet Loss:** Randomly drops packets to test retransmission logic.
* **Bit Corruption:** Flips bits in the payload, detected via **Internet Checksum**.
* **Delay & Duplication:** Simulates lag and duplicate packets.

## 🛠️ Usage

### Running the Simulator
1.  Run the application:
    ```bash
    python SecuredTransportation.py
    ```

### Testing TCP Features
1.  **Select Protocol:** Choose `RDT 3.0` or `Go-Back-N`.
2.  **Handshake:** Click **"ESTABLISH CONNECTION"** to see the SYN/ACK flow.
3.  **Send Data:** Type a payload and send. Watch the Sequence numbers increment.

### Testing Raw UDP
1.  **Select Protocol:** Choose `UDP_RAW`.
2.  **Send Data:** You can send immediately (no handshake required). Packets may be lost without notification.

## 🏗️ Architecture

```mermaid
graph TD
    %% --- Styles ---
    classDef client fill:#38BDF8,stroke:#0f172a,stroke-width:2px,color:black;
    classDef logic fill:#10B981,stroke:#047857,stroke-width:2px,color:white;
    classDef raw fill:#EF4444,stroke:#b91c1c,stroke-width:2px,color:white;

    User(("👤 User Input")) --> GUI["🖥️ Simulator GUI"]
    
    subgraph "Transport Logic"
        GUI --> Selector{"Protocol?"}
        
        Selector -- "RDT/TCP-Like" --> Handshake["🤝 3-Way Handshake"]
        Handshake --> Reliability["🛡️ GBN / Stop-Wait"]
        Reliability --> Checksum["🧮 Add Checksum"]
        
        Selector -- "Raw UDP" --> Raw["⚡ Raw Passthrough"]:::raw
    end
    
    Checksum --> Channel["⚠️ Error Sim (Loss/Corrupt)"]
    Raw --> Channel
    
    Channel --> Socket["🔌 Real UDP Socket"]:::client