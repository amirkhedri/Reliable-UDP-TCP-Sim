# 🛡️ Reliable Data Transfer (RDT) Protocol

**Developer:** Amir Khedri  
**Course:** Computer Networks - Phase 2  
**University:** University of Isfahan  

![Python](https://img.shields.io/badge/Python-3.x-blue.svg)
![Transport](https://img.shields.io/badge/Transport-Real%20UDP%20Sockets-red.svg)
![Protocol](https://img.shields.io/badge/Reliability-RDT%203.0%20%2F%20GBN-green.svg)

## 📖 Project Overview
This project is a **full implementation** of a Reliable Data Transfer (RDT) protocol running over **Real UDP Sockets**. It transforms the naturally unreliable, connectionless UDP protocol into a reliable, connection-oriented service similar to TCP.

Unlike a pure simulation, this application binds to actual OS ports (`127.0.0.1:12000+`) and transmits binary packets. To demonstrate reliability, it includes an **Error Injection Layer** that intentionally drops, corrupts, or delays these real packets before they leave the socket.

## ✨ Key Features

### 🔧 Real Protocol Implementation
* **Binary Packet Structure:** Uses `struct` to pack headers with Sequence Numbers, ACK Numbers, Flags, and Checksums.
* **Socket Programming:** Direct use of `socket.SOCK_DGRAM` for transmission.
* **TCP-Style Handshake:** Establishes connections using `SYN` ↔ `SYN-ACK` ↔ `ACK`.
* **Flow Control Algorithms:**
    * **RDT 3.0 (Stop-and-Wait):** Blocks until acknowledgment is received.
    * **Go-Back-N (GBN):** Sliding window protocol with cumulative ACKs and timer management.

### 🛡️ Error Handling & Recovery
The protocol handles the inherent unreliability of UDP through:
* **Checksums:** Detects bit errors/corruption in the payload.
* **Sequence Numbers:** Detects duplicate or out-of-order packets.
* **Retransmission Timers:** Automatically resends lost packets if no ACK is received.
* **Drop/Delay Simulation:** A middleware layer randomly drops or delays outgoing packets to force the protocol to recover.

## 🛠️ Usage
   
### Running the Application
1.Clone the repo:
   ```bash

     git clone  https://github.com/amirkhedri/Reliable-UDP-TCP-Sim
   ```

2.  Run the main script:
    ```bash
    python SecuredTransportation.py
    ```

### How to Test Reliability
1.  **Setup:** Select `Client A` and click **"ESTABLISH CONNECTION"**.
2.  **Inject Errors:** Move the **P(Drop)** slider to `0.4` (40% packet loss).
3.  **Send Data:** Type a message and send.
4.  **Observe:** Check the logs. You will see the packet get "Dropped," followed by a "Timeout," and finally a successful **"Retransmission"**.

## 🏗️ Architecture & Implementation Logic

```mermaid
graph TD
    User["👤 User Input"] -->|1. Connect| Handshake["🤝 3-Way Handshake"]
    User -->|2. Send Data| GBN["💾 GBN Sliding Window"]
    
    Handshake --> Packetizer["📦 Packetizer (Struct)"]
    GBN --> Packetizer
    
    Packetizer --> Checksum["🧮 Calc Checksum"]
    Checksum --> ErrorSim{"🎲 Error Injection"}
    
    ErrorSim -- "Drop Packet" --> Log["❌ Log: Packet Lost"]
    ErrorSim -- "Pass" --> RealSock["🔌 Real UDP Socket"]
    
    RealSock -->|Binary Stream| Network["☁️ Internet / Localhost"]
    
    %% Retransmission Loop
    GBN -.->|Timeout?| Retransmit["QC Retransmit Window"]
    Retransmit --> Checksum

    %% Receiver Side
    Network --> RecvSock["🔌 UDP Socket"]
    RecvSock --> Validate{"✅ Checksum Valid?"}
    
    Validate -- "No" --> Drop["🗑️ Drop (Corrupt)"]
    Validate -- "Yes" --> SeqCheck{"🔢 Seq Expected?"}
    
    SeqCheck -- "Gap/Dupe" --> ReACK["⚠️ Resend Last ACK"]
    SeqCheck -- "Order OK" --> Deliver["🔓 Extract Data"]
    
    Deliver -->|3. Receive| App["👤 Receiver App"]
    Deliver -.->|ACK N| RealSock
