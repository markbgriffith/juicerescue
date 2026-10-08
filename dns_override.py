"""Tiny DNS forwarder for the JuiceBox.

Answers Enel X / JuiceNet hostnames with this Mac's IP (so the charger sends its
UDP telemetry to JuicePassProxy) and forwards every other query upstream.
Logs every query so we can see what the charger looks up.
"""

import socket
import struct
import sys
import time

LISTEN = ("0.0.0.0", 53)
PROXY_IP = sys.argv[1] if len(sys.argv) > 1 else "10.0.0.113"
UPSTREAM = (sys.argv[2] if len(sys.argv) > 2 else "1.1.1.1", 53)
# Only the UDP telemetry hosts. device-backend-evos.juice.net (HTTPS, cert-checked)
# is left to resolve upstream (NXDOMAIN): pointing it here makes the charger's TLS
# handshake fail, after which it shuts its app down (gos_app_deinit).
OVERRIDE = ("device-backend-udp-evos.juice.net", "juicenet-udp", "enelx.com", "emotorwerks", "voltie")


def qname(pkt):
    labels, i = [], 12
    while pkt[i]:
        n = pkt[i]
        labels.append(pkt[i + 1 : i + 1 + n].decode(errors="replace"))
        i += n + 1
    return ".".join(labels).lower(), i + 1


def a_reply(pkt, end, ip):
    qtype = struct.unpack(">H", pkt[end : end + 2])[0]
    header = pkt[:2] + b"\x81\x80" + pkt[4:6] + (b"\x00\x01" if qtype == 1 else b"\x00\x00") + b"\x00\x00\x00\x00"
    out = header + pkt[12 : end + 4]
    if qtype == 1:
        out += b"\xc0\x0c\x00\x01\x00\x01" + struct.pack(">I", 60) + b"\x00\x04" + socket.inet_aton(ip)
    return out


def main():
    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    srv.bind(LISTEN)
    print(f"DNS override listening on {LISTEN}, overriding {OVERRIDE} -> {PROXY_IP}", flush=True)
    while True:
        pkt, addr = srv.recvfrom(2048)
        try:
            name, end = qname(pkt)
        except Exception:
            continue
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        if any(o in name for o in OVERRIDE):
            print(f"{ts} {addr[0]} {name} -> OVERRIDE {PROXY_IP}", flush=True)
            srv.sendto(a_reply(pkt, end, PROXY_IP), addr)
            continue
        print(f"{ts} {addr[0]} {name} -> upstream", flush=True)
        up = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        up.settimeout(3)
        try:
            up.sendto(pkt, UPSTREAM)
            srv.sendto(up.recv(2048), addr)
        except socket.timeout:
            pass
        finally:
            up.close()


if __name__ == "__main__":
    main()
