# CSV over Ethernet to FPGA Block RAM (PYNQ-Z2)

Send a CSV file from a laptop to a PYNQ-Z2 over Ethernet, store it in on-chip Block RAM in the FPGA fabric, and verify every word by reading it back.

Computer Architecture side project, Fr. C. Rodrigues Institute of Technology (FCRIT), Vashi.


![Block design](docs/images/block_design.png)

## Results

| Metric | Value |
| --- | --- |
| Data sent | 1,024 × 32-bit integers (4,096 bytes) |
| Verification | All 1,024 words read back from BRAM match the CSV; CRC32 checked on the board |
| LUTs | 1,294 (about 2.4% of xc7z020) |
| Flip-flops | 1,156 (about 1.1%) |
| Block RAM | 2 BRAM36 (about 1.4%) |
| DSP / URAM | 0 / 0 |
| PL clock | 100 MHz |
| Worst setup slack (WNS) | +2.575 ns |
| Worst hold slack (WHS) | +0.017 ns |
| Failed routes | 0 |
| Total on-chip power | 1.406 W (Vivado estimate) |

![Implementation results](docs/images/design_runs.png)

## How it works

```
Laptop (Python, data.csv)
   |  TCP over Ethernet
   v
Zynq PS (Linux, receiver_pynq.py)      <- Ethernet MAC and TCP/IP stack strip the headers
   |  AXI GP0
   v
AXI SmartConnect -> AXI BRAM Controller -> Block Memory Generator (8 KB BRAM in the PL)
```

1. `sender_laptop.py` reads the CSV, packs it as 32-bit integers and sends it over a TCP socket with a 12-byte header (magic, word count, CRC32).
2. `receiver_pynq.py` runs in JupyterLab on the PYNQ-Z2. It receives the payload, checks the CRC32, and writes the words into the BRAM through the AXI BRAM Controller.
3. It then reads the BRAM back and compares it with what it received, and replies OK or an error code to the laptop.

The Ethernet MAC and the TCP/IP stack live in the Zynq processing system and Linux, so the programmable logic only needs the BRAM and its AXI controller.

### Hardware (Vivado block design)

| Block | Role |
| --- | --- |
| ZYNQ7 Processing System | Ethernet, Linux, AXI GP0 master, 100 MHz fabric clock |
| Processor System Reset | Synchronised resets for the PL |
| AXI SmartConnect | Connects GP0 to the BRAM controller |
| AXI BRAM Controller | AXI4-Lite slave, 8 KB at `0x40000000` |
| Block Memory Generator | Single-port RAM in BRAM Controller mode |

![Address map](docs/images/address_editor.png)

## Repository layout

```
.
├── sender_laptop.py        # runs on the laptop
├── receiver_pynq.py        # runs in JupyterLab on the PYNQ-Z2
├── data.csv                # test data: 1,024 integers, 64 rows x 16 columns
├── hardware/
│   ├── design_1_wrapper.bit
│   └── design_1.hwh        # must keep the same base name as the .bit
└── docs/images/            # screenshots used in this README
```

## Running it

**Requirements:** PYNQ-Z2 with a PYNQ image, Ethernet cable, Python 3 with `numpy` on the laptop, Vivado to rebuild the design (optional).

1. **Network.** Connect the laptop and the board with an Ethernet cable. Give the laptop a static IP of `192.168.2.1`, netmask `255.255.255.0`. The board is at `192.168.2.99`. Check with `ping 192.168.2.99`.
2. **Copy to the board.** In JupyterLab (`http://192.168.2.99`, password `xilinx`), upload `design_1_wrapper.bit`, `design_1.hwh` and `receiver_pynq.py`. The `.bit` and `.hwh` must have the same base name.
3. **Start the receiver.** In a notebook cell, set `BITFILE = "design_1_wrapper.bit"` and run the contents of `receiver_pynq.py`. It prints `Listening on 0.0.0.0:5005 ...` and stays busy.
4. **Send the data** from the laptop:
   ```
   python sender_laptop.py data.csv --ip 192.168.2.99
   ```
   Add `--skip-header` if your CSV has a header row. A good run prints
   `OK: board wrote 1024 words to BRAM and verified them`.

![Sender and receiver output](docs/images/terminal_output.png)

### Verify the BRAM contents yourself

Stop the receiver cell (Kernel > Interrupt), then run this in a new cell. Do not reload the overlay, or the BRAM may be reset.

```python
import numpy as np
from pynq import MMIO

bram = MMIO(0x40000000, 0x2000)
n = 1024
from_bram = np.array(bram.array[:n], dtype=np.uint32).view(np.int32)
expected = np.loadtxt("data.csv", delimiter=",", dtype=np.int64).flatten().astype(np.int32)
print("all match:", np.array_equal(from_bram, expected))
```

![BRAM readback](docs/images/bram_readback.png)

### Limits

- The BRAM is 8 KB, so a file holds at most 2,048 values. Change the range in Vivado's Address Editor and rebuild for more.
- Values must be integers that fit in 32 bits. Scale floating-point data to fixed point first.
- Port 5005 must be reachable. Allow Python through the laptop firewall if the connection is refused.

## Rebuilding the design

1. Create a Vivado project for the PYNQ-Z2 (part `xc7z020clg400-1`) and a block design named `design_1`.
2. Add the five blocks above, run Block Automation and Connection Automation, and set the BRAM controller to 8K at `0x40000000`.
3. Validate, create the HDL wrapper and generate the bitstream.
4. Export the `.bit` and the `.hwh` (found under `<project>.gen/sources_1/bd/design_1/hw_handoff/`) with matching names.

## Future work

- Add an AXI DMA and a stream-to-BRAM block so large data moves without CPU involvement.
- Use a true dual-port BRAM so custom logic in the fabric can read and process the stored data.
- Measure and report end-to-end transfer time and throughput.

## Author

Aryan, B.E. EXTC (Honours, AIML), FCRIT, Vashi. [github.com/AryKad](https://github.com/AryKad)
