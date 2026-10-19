#!/usr/bin/env python3
"""
Laptop side: read a CSV of integers and push it to the PYNQ-Z2 over TCP/Ethernet.

Usage:
    python sender_laptop.py data.csv --ip 192.168.2.99 --port 5005
    python sender_laptop.py data.csv --skip-header

Wire format (all little-endian):
    [u32 MAGIC][u32 n_words][u32 crc32_of_payload]   <- 12-byte header
    [n_words * int32]                                  <- payload
Reply from the board:
    [u8 status (0 = OK)][u32 words_written_to_BRAM]
"""
import argparse
import socket
import struct
import sys
import zlib

import numpy as np

MAGIC = 0x42524D31  # "BRM1"


def load_csv(path, skip_header=False, dtype=np.int32):
    """Read every numeric cell of the CSV, flatten row-major to a 1-D int32 array."""
    data = np.loadtxt(path, delimiter=",", skiprows=1 if skip_header else 0, ndmin=1)
    data = data.flatten()
    info = np.iinfo(dtype)
    if data.min() < info.min or data.max() > info.max:
        sys.exit(f"CSV values out of {dtype.__name__} range")
    if not np.all(np.equal(np.mod(data, 1), 0)):
        sys.exit("CSV contains non-integers. Scale/quantise them first (e.g. fixed-point) "
                 "before sending, since the BRAM stores 32-bit words.")
    return data.astype(dtype)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--ip", default="192.168.2.99", help="PYNQ-Z2 IP (default PYNQ static IP)")
    ap.add_argument("--port", type=int, default=5005)
    ap.add_argument("--skip-header", action="store_true")
    args = ap.parse_args()

    words = load_csv(args.csv, args.skip_header)
    payload = words.astype("<i4").tobytes()
    crc = zlib.crc32(payload) & 0xFFFFFFFF
    header = struct.pack("<III", MAGIC, len(words), crc)
    print(f"Loaded {len(words)} words ({len(payload)} bytes), CRC32=0x{crc:08X}")

    with socket.create_connection((args.ip, args.port), timeout=30) as s:
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        s.sendall(header)
        s.sendall(payload)  # TCP/IP framing is handled entirely by the OS
        reply = b""
        while len(reply) < 5:
            chunk = s.recv(5 - len(reply))
            if not chunk:
                sys.exit("Board closed the connection before replying")
            reply += chunk

    status, written = struct.unpack("<BI", reply)
    if status == 0:
        print(f"OK: board wrote {written} words to BRAM and verified them")
    else:
        sys.exit(f"Board reported error code {status}")


if __name__ == "__main__":
    main()
