# JuiceBox local control on a Mac

Enel X shut down the JuiceBox cloud, so the JuiceNet app no longer works. This setup
puts a Mac in place of the cloud: the charger reports to the Mac, and a small web page
on the Mac shows live status and schedules charging for cheap off-peak hours.

It's built on [JuicePassProxy](https://github.com/JuiceRescue/juicepassproxy) (JPP) plus a
few small scripts in this repo.

```
JuiceBox ──Wi-Fi──▶ travel router ──Wi-Fi──▶ home network ──▶ Mac
                    (DNS = the Mac)                          ├─ dns_override.py   answers the Enel X hostname with the Mac's IP
                                                             ├─ JuicePassProxy    receives the charger's UDP data, sends commands
                                                             ├─ Mosquitto (MQTT)  message bus between the pieces
                                                             └─ charger_web.py    web page + off-peak scheduler, port 8080
```

## What you need

- A JuiceBox on Wi-Fi. Tested on a **JuiceBox 40 (2022), firmware `EMWERK-JB201-1.0.46`, Gecko OS 4.2.7, WGM160P**,
  which sends unencrypted `v09u` data.
- A Mac that stays on (Settings → Energy: prevent sleep), with [Homebrew](https://brew.sh).
- A cheap travel router whose DNS server you can set, e.g. **GL.iNet Opal (GL-SFT1200)**, about $30.
  You need one if your main router can't hand out a custom DNS server. Xfinity gateways can't, and most ISP routers can't.

## Why the travel router is needed

The charger finds its server by looking up `device-backend-udp-evos.juice.net`. That name no
longer exists, so the charger stays silent. We need it to resolve to the Mac.

Things that **don't** work on this firmware, so you can skip them:

- **`UPDATE_UDPC` / `udpc` over telnet.** The charger has no UDPC stream to rewrite, and a stream you open by hand isn't used.
- **Setting a static DNS on the charger over telnet.** The charger's software switches itself back to DHCP within about 45 seconds of every boot.
- **Answering the charger's DHCP from the Mac** (`experiments/dhcp_charger.py`). When the ISP gateway is also the Wi-Fi
  access point, its answer always arrives first.

So the DNS setting has to come from DHCP, and the travel router provides it. The charger also
tries an HTTPS connection to `device-backend-evos.juice.net`. That fails, because the name
doesn't resolve, and the charger keeps running fine anyway.

## Setup

### 1. Get the charger on Wi-Fi and find it

If it was never on Wi-Fi (many 2022 units used cellular): flip the breaker off and on, then join
the charger's `JuiceNet-XXX` network from a phone. If the setup page at `http://10.10.10.1` just
spins, use its command API directly from the phone's browser:

```
http://10.10.10.1/command/scan
http://10.10.10.1/command/set%20wlan.ssid%20YourWiFi
http://10.10.10.1/command/set%20wlan.passkey%20YourPassword
http://10.10.10.1/command/save
http://10.10.10.1/command/reboot
```

It then shows up on your network as `gecko_os-XXX`. Telnet to port 2000 to confirm the firmware:

```
python3 tools/jbtelnet.py <charger-ip> list
```

The banner shows the firmware version. The **JuiceBox ID** is the long number at the start of
each packet. JPP prints it as `juicebox_id` the first time it connects over telnet.

### 2. Install the Mac side

```sh
brew install mosquitto python@3.12
printf 'listener 1883 127.0.0.1\nallow_anonymous true\n' > /opt/homebrew/etc/mosquitto/mosquitto.conf
brew services start mosquitto

git clone https://github.com/JuiceRescue/juicepassproxy.git
/opt/homebrew/bin/python3.12 -m venv .venv
.venv/bin/pip install -r juicepassproxy/requirements.txt

./install.sh <mac-ip> <juicebox-id> [upstream-dns]
```

`install.sh` installs three launchd agents (`com.juicerescue.dns`, `.proxy` and `.web`). They
start at login and restart if they stop. Reserve the Mac's IP in your router so it never changes.

### 3. Set up the travel router

1. Power it on, join its Wi-Fi (the name and password are on the label), and open `http://192.168.8.1`.
2. **Internet → Repeater**: join your home Wi-Fi.
3. **Network → DNS**: set the mode to **Manual** with server = the Mac's IP and no second server.
   Turn **on** "Override DNS Settings for All Clients" and turn **off** "DNS Rebinding Attack Protection".
   Rebinding protection blocks private-IP answers, which is exactly what we need here.
4. Put it within Wi-Fi range of the charger. One garage wall at about 25 ft is fine.

### 4. Move the charger to the router

Over telnet (one command per connection):

```
python3 tools/jbtelnet.py <charger-ip> "set wlan.ssid GL-XXXX"
python3 tools/jbtelnet.py <charger-ip> "set wlan.passkey <router-wifi-password>"
python3 tools/jbtelnet.py <charger-ip> save
python3 tools/jbtelnet.py <charger-ip> reboot
```

Within a minute, `log/dns.out` should show the lookup and `log/juicepassproxy.log` should show
`Setting Voltage to ...` every 30 seconds.

### 5. Use it

Open `http://<mac-ip>:8080` on your phone and add it to the home screen. The page has:

- **Charge now** (default): full current whenever the car is plugged in.
- **Tonight only**: waits for the off-peak window, charges through it, then switches back to Charge now.
- **Every night**: charges only between the start and stop times, at the chosen current (6–40 A), every night.
- **Pause**: no charging.

The page only changes the charger's *online* current limit. If the Mac or router goes down, the
charger falls back to its *offline* limit after about 5 minutes. That limit is left at full current,
so the car still charges.

## Files

| File | Purpose |
|---|---|
| `dns_override.py` | Tiny DNS forwarder. Answers the Enel X UDP hostnames with the Mac's IP and forwards everything else. |
| `charger_web.py` | Web page and off-peak scheduler. Talks to JPP over MQTT. Settings are in `config/charger_web.json`. |
| `install.sh`, `launchd/` | Install the three services as launchd agents. |
| `tools/jbtelnet.py` | Send Gecko OS commands to the charger. |
| `experiments/` | Approaches that didn't work on this firmware, kept for reference (see above). `tcp_probe.py` logs which TCP ports the charger tries. |

## Troubleshooting

- **No data:** is the charger on the travel router's Wi-Fi? Does `dig @<mac-ip> device-backend-udp-evos.juice.net` return the Mac's IP?
- **`gos_app_deinit` in the log:** that's the charger's software restarting. Occasional restarts are normal. If they repeat every minute, the charger isn't getting the Mac as its DNS server.
- **JPP gives up after about 10 restarts** when the charger is silent for over an hour. launchd starts it again automatically.
- **Telnet is flaky:** the charger accepts one command per connection, so retry.
