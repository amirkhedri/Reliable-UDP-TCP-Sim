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
1.  Run the main script:
    ```bash
    python SecuredTransportation.py
    ```

### How to Test Reliability
1.  **Setup:** Select `Client A` and click **"ESTABLISH CONNECTION"**.
2.  **Inject Errors:** Move the **P(Drop)** slider to `0.4` (40% packet loss).
3.  **Send Data:** Type a message and send.
4.  **Observe:** Check the logs. You will see the packet get "Dropped," followed by a "Timeout," and finally a successful **"Retransmission"**.

## 🏗️ Architecture

```mermaid
graph TD
    User["👤 User Data / GUI"] -->|1. Data| Packetizer["📦 Packetizer"]
    Packetizer -->|2. Buffer| Buffer["💾 Window Buffer"]
    
    Buffer --> Checksum["🧮 Calc Checksum"]
    Checksum --> ErrorInjector{"🎲 Error Injection?"}
    
    ErrorInjector -- "Drop/Delay" --> Log["📝 Log Error"]
    ErrorInjector -- "Pass" --> Socket["🔌 Python UDP Socket"]
    
    Socket <-->|3. Real Bytes Unreliable| Internet["☁️ Localhost / Network"]
    
    Internet --> RecvSock["🔌 UDP Socket"]
    RecvSock --> Validator{"✅ Validate?"}
    
    Validator -- "Corrupt/Gap" --> Discard["🗑️ Discard & Re-ACK"]
    Validator -- "Valid" --> Process["🔓 Extract Payload"]
    Process -->|4. Deliver| User