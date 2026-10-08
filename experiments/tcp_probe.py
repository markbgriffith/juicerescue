"""Log which TCP ports the JuiceBox tries to connect to on this Mac, and the first bytes it sends."""

import select
import socket
import sys
import time

PORTS = [int(p) for p in sys.argv[1:]] or [80, 443, 8080, 8443, 8883, 1883, 8042, 8047, 5683]
socks = {}
for port in PORTS:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("0.0.0.0", port))
        s.listen(5)
        socks[s] = port
    except OSError as e:
        print(f"skip {port}: {e}", flush=True)
print("listening on", sorted(socks.values()), flush=True)
while True:
    ready, _, _ = select.select(list(socks), [], [], 1)
    for s in ready:
        conn, addr = s.accept()
        conn.settimeout(5)
        try:
            data = conn.recv(300)
        except socket.timeout:
            data = b"<no data in 5s>"
        print(f"{time.strftime('%H:%M:%S')} TCP {socks[s]} from {addr[0]}: {data[:120]!r}", flush=True)
        conn.close()
