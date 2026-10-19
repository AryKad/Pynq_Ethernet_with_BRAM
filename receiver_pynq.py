"""
PYNQ-Z2 side (run in a JupyterLab cell or as a notebook script).

Flow:  Ethernet -> TCP socket (OS strips Ethernet/IP/TCP headers) -> numpy buffer
       -> AXI DMA (MM2S) -> PL -> BRAM  (via AXI BRAM controller / Block Memory Generator)
       -> optional read-back through the PS and CRC check.

Copy to the board together with:
    bram_bd_wrapper.bit
    bram_bd_wrapper.hwh   <-- REQUIRED, same base name as the .bit (Vivado: File > Export > Export Block Design,
                              or <project>.gen/sources_1/bd/bram_bd/hw_handoff/bram_bd.hwh)
"""
import socket
import struct
import zlib

import numpy as np
from pynq import Overlay, allocate, MMIO

# ----------------------------- CONFIGURATION -----------------------------
BITFILE = "bram_bd.bit"        # exported .bit; the .hwh must sit next to it with the same base name
DMA_NAME = "axi_dma_0"          # check with: ol.ip_dict.keys()
BRAM_BASE = 0x40000000          # base address of the AXI BRAM controller (Vivado Address Editor)
BRAM_SIZE = 8 * 1024            # bytes mapped to the BRAM controller (Address Editor "Range")
USE_DMA = False                 # False -> bypass DMA and write BRAM directly from the PS via AXI-Lite/GP
DMA_CHUNK_WORDS = 2048          # words per DMA transfer; keep <= (2**buffer_length_width - 1) / 4
HOST, PORT = "0.0.0.0", 5005
MAGIC = 0x42524D31
# --------------------------------------------------------------------------

ERR_OK, ERR_MAGIC, ERR_SIZE, ERR_CRC, ERR_VERIFY = 0, 1, 2, 3, 4


def recv_exact_into(conn, view):
    """Fill the memoryview completely from the socket."""
    got = 0
    while got < len(view):
        n = conn.recv_into(view[got:], len(view) - got)
        if n == 0:
            raise ConnectionError("sender closed early")
        got += n


def recv_exact(conn, n):
    buf = bytearray(n)
    recv_exact_into(conn, memoryview(buf))
    return bytes(buf)


def write_bram_via_dma(dma, words):
    """Push `words` (uint32 array) into the PL with the AXI DMA, in chunks."""
    buf = allocate(shape=(DMA_CHUNK_WORDS,), dtype=np.uint32)
    try:
        for i in range(0, len(words), DMA_CHUNK_WORDS):
            chunk = words[i:i + DMA_CHUNK_WORDS]
            buf[:len(chunk)] = chunk
            # last chunk may be shorter: transfer only what's valid
            dma.sendchannel.transfer(buf[:len(chunk)] if len(chunk) != DMA_CHUNK_WORDS else buf)
            dma.sendchannel.wait()
    finally:
        buf.freebuffer()


def serve():
    ol = Overlay(BITFILE)
    print("IPs in design:", list(ol.ip_dict.keys()))
    dma = getattr(ol, DMA_NAME) if USE_DMA else None
    bram = MMIO(BRAM_BASE, BRAM_SIZE)           # PS-side window for clear + read-back
    bram_words = BRAM_SIZE // 4

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, PORT))
    srv.listen(1)
    print(f"Listening on {HOST}:{PORT} ...")

    try:
        while True:
            conn, addr = srv.accept()
            print("Connection from", addr)
            status, written = ERR_OK, 0
            try:
                with conn:
                    magic, n_words, crc = struct.unpack("<III", recv_exact(conn, 12))
                    if magic != MAGIC:
                        status = ERR_MAGIC
                    elif n_words == 0 or n_words > bram_words:
                        status = ERR_SIZE
                        print(f"Rejected: {n_words} words, BRAM holds {bram_words}")
                    else:
                        payload = bytearray(n_words * 4)
                        recv_exact_into(conn, memoryview(payload))
                        if (zlib.crc32(payload) & 0xFFFFFFFF) != crc:
                            status = ERR_CRC
                        else:
                            words = np.frombuffer(payload, dtype="<u4").copy()

                            # clear BRAM so stale data can't fake a pass
                            bram.array[:bram_words] = 0

                            if USE_DMA:
                                write_bram_via_dma(dma, words)
                            else:
                                bram.array[:n_words] = words   # direct PS write via AXI BRAM controller

                            # read back through the PS and verify
                            back = np.array(bram.array[:n_words], dtype=np.uint32)
                            if np.array_equal(back, words):
                                written = n_words
                                print(f"Wrote + verified {n_words} words")
                            else:
                                bad = np.flatnonzero(back != words)
                                print(f"Verify FAILED at {len(bad)} words, first idx {bad[0]}: "
                                      f"sent 0x{words[bad[0]]:08X} got 0x{back[bad[0]]:08X}")
                                status = ERR_VERIFY
                    conn.sendall(struct.pack("<BI", status, written))
            except Exception as e:
                print("Error:", e)
    except KeyboardInterrupt:
        print("Stopped")
    finally:
        srv.close()


serve()
