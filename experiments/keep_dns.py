"""Keep the JuiceBox pointed at this Mac for DNS.

A full power cycle resets the charger to DHCP (Comcast DNS), where the dead
Enel X hostnames don't resolve and the charger never talks to JuicePassProxy.
This polls the charger over telnet; when it finds DHCP back on, it re-applies
the static settings, saves, and restarts the Wi-Fi module.
"""

import socket
import sys
import time

HOST = "10.0.0.16"
MAC_IP = "10.0.0.113"
SETTINGS = [
    f"set wlan.static.ip {HOST}",
    "set wlan.static.netmask 255.255.255.0",
    "set wlan.static.gateway 10.0.0.1",
    f"set wlan.static.dns {MAC_IP}",
    "set wlan.dhcp.enabled 0",
]
POLL = 5


def log(msg):
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}", flush=True)


def command(cmd, expect, tries=5):
    """Send one command per connection (the charger drops follow-ups)."""
    for _ in range(tries):
        try:
            with socket.create_connection((HOST, 2000), timeout=5) as s:
                s.settimeout(3)
                s.recv(500)
                s.sendall(cmd.encode() + b"\r\n")
                time.sleep(1)
                reply = s.recv(1000).decode(errors="replace")
            if expect is None or expect in reply:
                return reply
        except OSError:
            pass
        time.sleep(2)
    return None


def dhcp_enabled():
    reply = command("get wlan.dhcp.enabled", None, tries=2)
    if reply is None:
        return None
    lines = [l.strip() for l in reply.splitlines() if l.strip() and not l.startswith(("get", ">"))]
    return lines[0] == "1" if lines else None


def main():
    once = "--once" in sys.argv
    log("watching charger network settings")
    while True:
        state = dhcp_enabled()
        if state:
            log("charger is back on DHCP; re-applying Mac DNS")
            ok = all(command(c, "Set OK") for c in SETTINGS)
            ok = ok and command("save", "Success") is not None
            ok = ok and command("reboot", "Success") is not None
            log("re-applied and restarted Wi-Fi module" if ok else "re-apply FAILED; will retry")
            time.sleep(60 if ok else POLL)
            if ok and once:
                return
            continue
        time.sleep(POLL)


if __name__ == "__main__":
    main()
