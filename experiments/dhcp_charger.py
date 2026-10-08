"""Answer DHCP requests from the JuiceBox only, handing it this Mac as its DNS server.

Every other device is ignored, so the Xfinity gateway stays the DHCP server for the
rest of the network. The charger keeps the same IP the gateway gave it. Because the
lease names this Mac as the DHCP server, the charger's renewals come back here.
"""

import socket
import struct
import time

CHARGER_MAC = bytes.fromhex("000000000000")  # your JuiceBox MAC, no colons
CHARGER_IP = "10.0.0.16"
MAC_IP = "10.0.0.113"
GATEWAY = "10.0.0.1"
NETMASK = "255.255.255.0"
LEASE = 3600
IFACE = "en1"  # Wi-Fi, the interface on the 10.0.0.x network
IP_BOUND_IF = 25  # macOS socket option

MAGIC = b"\x63\x82\x53\x63"
DISCOVER, OFFER, REQUEST, DECLINE, ACK, NAK, RELEASE, INFORM = range(1, 9)
NAMES = {1: "DISCOVER", 2: "OFFER", 3: "REQUEST", 4: "DECLINE", 5: "ACK", 6: "NAK", 7: "RELEASE", 8: "INFORM"}


def log(msg):
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}", flush=True)


def parse_options(data):
    opts, i = {}, 0
    while i < len(data):
        code = data[i]
        if code == 255:
            break
        if code == 0:
            i += 1
            continue
        length = data[i + 1]
        opts[code] = data[i + 2 : i + 2 + length]
        i += 2 + length
    return opts


def opt(code, value):
    return bytes([code, len(value)]) + value


def build_reply(req, msg_type):
    xid, flags, ciaddr, chaddr = req[4:8], req[10:12], req[12:16], req[28:44]
    header = (
        b"\x02\x01\x06\x00" + xid + b"\x00\x00" + flags + ciaddr
        + socket.inet_aton(CHARGER_IP) + socket.inet_aton(MAC_IP) + b"\x00\x00\x00\x00"
        + chaddr + b"\x00" * 192
    )
    options = (
        opt(53, bytes([msg_type]))
        + opt(54, socket.inet_aton(MAC_IP))
        + opt(51, struct.pack(">I", LEASE))
        + opt(58, struct.pack(">I", LEASE // 2))
        + opt(59, struct.pack(">I", LEASE * 7 // 8))
        + opt(1, socket.inet_aton(NETMASK))
        + opt(3, socket.inet_aton(GATEWAY))
        + opt(6, socket.inet_aton(MAC_IP))
        + opt(28, socket.inet_aton("10.0.0.255"))
        + b"\xff"
    )
    return header + MAGIC + options


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setsockopt(socket.IPPROTO_IP, IP_BOUND_IF, socket.if_nametoindex(IFACE))
    sock.bind(("0.0.0.0", 67))
    log(f"answering DHCP for {CHARGER_MAC.hex(':')} only: IP {CHARGER_IP}, DNS {MAC_IP}")
    while True:
        data, addr = sock.recvfrom(2048)
        if len(data) < 240 or data[0] != 1 or data[236:240] != MAGIC:
            continue
        if data[28:34] != CHARGER_MAC:
            continue
        opts = parse_options(data[240:])
        msg = opts.get(53, b"\x00")[0]
        server_id = opts.get(54)
        log(f"charger sent {NAMES.get(msg, msg)} (server id {socket.inet_ntoa(server_id) if server_id else '-'})")
        if msg == DISCOVER:
            reply_type = OFFER
        elif msg == REQUEST and (server_id is None or server_id == socket.inet_aton(MAC_IP)):
            reply_type = ACK
        else:
            continue  # it chose the Xfinity gateway's offer, or it's a release/decline
        reply = build_reply(data, reply_type)
        broadcast_flag = data[10] & 0x80
        if data[12:16] != b"\x00" * 4:
            dest = socket.inet_ntoa(data[12:16])  # renewing: client already has an address
        elif not broadcast_flag:
            # Unicast to the address we're handing out. Wi-Fi delivers unicast frames
            # immediately, while broadcasts wait for the next beacon, which lets the
            # gateway's offer win the race. The Mac's ARP cache already maps this IP
            # to the charger's MAC.
            dest = CHARGER_IP
        else:
            dest = "255.255.255.255"
        sock.sendto(reply, (dest, 68))
        log(f"sent {NAMES[reply_type]} to {dest}")


if __name__ == "__main__":
    main()
