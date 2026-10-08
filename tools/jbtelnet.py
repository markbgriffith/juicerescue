"""Send Gecko OS commands to a JuiceBox over telnet (port 2000).

The EMWERK firmware drops follow-up commands on the same connection, so each
command opens its own connection.

    python3 tools/jbtelnet.py 10.0.0.16 list "get wlan.ssid"
"""

import socket
import sys
import time


def run(host, cmd):
    with socket.create_connection((host, 2000), timeout=5) as s:
        s.settimeout(3)
        s.recv(500)  # version banner
        s.sendall(cmd.encode() + b"\r\n")
        time.sleep(1)
        buf = b""
        try:
            while True:
                data = s.recv(4096)
                if not data:
                    break
                buf += data
        except socket.timeout:
            pass
    return buf.decode(errors="replace").replace("\r", "")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    for c in sys.argv[2:]:
        print(run(sys.argv[1], c))
