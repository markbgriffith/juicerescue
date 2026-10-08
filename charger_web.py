"""JuiceBox control page: live status, charge modes, and an off-peak schedule.

Reads charger state from JuicePassProxy over MQTT and sets the charging current by
publishing to the proxy's "Max Current (Online/Wanted)" command topic. Only the
online limit is changed: if this Mac stops talking to the charger, it falls back
to its offline limit (left at full current) so the car still charges.

Serves http://<this Mac>:8080
"""

import json
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import paho.mqtt.client as mqtt

HERE = Path(__file__).resolve().parent
SETTINGS_FILE = HERE / "config" / "charger_web.json"
PORT = 8080
STATE_TOPIC = "hmd/+/JuiceBox/+/state"
CURRENT_CMD = "hmd/number/JuiceBox/Max-Current-Online-Wanted-/command"
MAX_AMPS = 40
MIN_AMPS = 6  # J1772 chargers can't advertise less than 6 A; 0 means pause
RESEND_SECONDS = 300

DEFAULTS = {"mode": "scheduled", "start": "00:00", "end": "06:00", "amps": MAX_AMPS}

lock = threading.Lock()
state = {}  # entity name -> value, from MQTT
last_seen = 0.0
last_sent = {"amps": None, "at": 0.0}


def load_settings():
    try:
        return {**DEFAULTS, **json.loads(SETTINGS_FILE.read_text())}
    except (OSError, ValueError):
        return dict(DEFAULTS)


settings = load_settings()


def save_settings():
    SETTINGS_FILE.parent.mkdir(exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(settings, indent=2))


def in_window(now, start, end):
    t = now.strftime("%H:%M")
    if start == end:
        return True
    if start < end:
        return start <= t < end
    return t >= start or t < end  # window crosses midnight


def desired_amps(now=None):
    now = now or datetime.now()
    mode = settings["mode"]
    if mode == "now":
        return MAX_AMPS
    if mode == "pause":
        return 0
    return settings["amps"] if in_window(now, settings["start"], settings["end"]) else 0


def on_message(client, userdata, msg):
    global last_seen
    name = msg.topic.split("/")[3]
    with lock:
        state[name] = msg.payload.decode(errors="replace")
        if name in ("Voltage", "Status"):
            last_seen = time.time()


def scheduler(client):
    while True:
        amps = desired_amps()
        with lock:
            due = amps != last_sent["amps"] or time.time() - last_sent["at"] > RESEND_SECONDS
        if due:
            client.publish(CURRENT_CMD, str(amps), retain=False)
            with lock:
                last_sent.update(amps=amps, at=time.time())
            print(f"{datetime.now():%Y-%m-%d %H:%M:%S} set charging limit to {amps} A ({settings['mode']})", flush=True)
        time.sleep(20)


def num(name, default=0.0):
    try:
        return float(state.get(name, default))
    except ValueError:
        return default


def api_state():
    with lock:
        return {
            "status": state.get("Status", "Unknown"),
            "power_kw": round(num("Power") / 1000, 2),
            "current": num("Current"),
            "voltage": num("Voltage"),
            "session_kwh": round(num("Energy--Session-") / 1000, 2),
            "temperature": num("Temperature"),
            "limit": num("Max-Current-Online-Wanted-", -1),
            "seconds_since_update": round(time.time() - last_seen) if last_seen else None,
            "settings": settings,
            "target_amps": desired_amps(),
            "in_window": in_window(datetime.now(), settings["start"], settings["end"]),
        }


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/":
            self._send(200, PAGE, "text/html; charset=utf-8")
        elif self.path == "/api/state":
            self._send(200, json.dumps(api_state()))
        else:
            self._send(404, '{"error": "not found"}')

    def do_POST(self):
        if self.path != "/api/settings":
            return self._send(404, '{"error": "not found"}')
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            new = dict(settings)
            if "mode" in body:
                if body["mode"] not in ("scheduled", "now", "pause"):
                    raise ValueError("bad mode")
                new["mode"] = body["mode"]
            for key in ("start", "end"):
                if key in body:
                    datetime.strptime(body[key], "%H:%M")
                    new[key] = body[key]
            if "amps" in body:
                new["amps"] = max(MIN_AMPS, min(MAX_AMPS, int(body["amps"])))
        except (ValueError, TypeError) as e:
            return self._send(400, json.dumps({"error": str(e)}))
        settings.update(new)
        save_settings()
        with lock:
            last_sent["amps"] = None  # apply on the next scheduler tick
        self._send(200, json.dumps(api_state()))

    def log_message(self, *args):
        pass


PAGE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>JuiceBox</title>
<style>
:root{--bg:#f4f5f7;--card:#fff;--text:#16181d;--muted:#667085;--line:#e4e7ec;--accent:#1f7a4d;--accent-soft:#e3f3ea;--warn:#b54708;--warn-soft:#fef0c7}
@media (prefers-color-scheme:dark){:root{--bg:#0f1115;--card:#181b21;--text:#eceef2;--muted:#98a2b3;--line:#2a2f37;--accent:#4cc38a;--accent-soft:#16301f;--warn:#fdb022;--warn-soft:#3a2a0b}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:16px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
main{max-width:480px;margin:0 auto;padding:16px}
h1{font-size:22px;margin:4px 0 14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px;margin-bottom:14px}
.status{display:flex;justify-content:space-between;align-items:baseline}
.status b{font-size:24px}.muted{color:var(--muted);font-size:14px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:14px}
.grid div{background:var(--bg);border-radius:10px;padding:10px}.grid span{display:block;font-size:13px;color:var(--muted)}.grid b{font-size:20px;font-variant-numeric:tabular-nums}
.modes{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}
.modes button{padding:12px 4px;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--text);font-size:15px;font-weight:600}
.modes button.on{background:var(--accent);border-color:var(--accent);color:#fff}
label{display:flex;justify-content:space-between;align-items:center;margin:12px 0;gap:12px}
input[type=time]{font-size:16px;padding:6px 8px;border-radius:8px;border:1px solid var(--line);background:var(--bg);color:var(--text)}
input[type=range]{flex:1;accent-color:var(--accent)}
.save{width:100%;padding:12px;border:0;border-radius:10px;background:var(--accent);color:#fff;font-size:16px;font-weight:600}
.banner{padding:10px 12px;border-radius:10px;font-size:14px;margin-top:12px;background:var(--accent-soft)}
.banner.warn{background:var(--warn-soft);color:var(--warn)}
</style></head><body><main>
<h1>JuiceBox</h1>
<section class="card">
  <div class="status"><b id="status">…</b><span class="muted" id="seen"></span></div>
  <div class="grid">
    <div><span>Power</span><b id="power">–</b></div>
    <div><span>Current</span><b id="current">–</b></div>
    <div><span>This session</span><b id="session">–</b></div>
    <div><span>Charging limit</span><b id="limit">–</b></div>
  </div>
  <div class="banner" id="plan"></div>
</section>
<section class="card">
  <div class="modes">
    <button data-mode="scheduled">Scheduled</button>
    <button data-mode="now">Charge now</button>
    <button data-mode="pause">Pause</button>
  </div>
</section>
<section class="card">
  <b>Off-peak schedule</b>
  <label>Start charging <input type="time" id="start"></label>
  <label>Stop charging <input type="time" id="end"></label>
  <label>Current <input type="range" id="amps" min="6" max="40" step="1"><b id="ampsv"></b></label>
  <button class="save" id="save">Save schedule</button>
</section>
<p class="muted">If this Mac is off, the charger falls back to charging at full current whenever plugged in.</p>
</main>
<script>
const $=id=>document.getElementById(id);let editing=false;
function fmt12(t){const[h,m]=t.split(':').map(Number);return((h%12)||12)+':'+String(m).padStart(2,'0')+(h<12?' am':' pm')}
function render(s){
  $('status').textContent=s.status;
  $('seen').textContent=s.seconds_since_update==null?'waiting for charger':(s.seconds_since_update<90?'live':'last update '+Math.round(s.seconds_since_update/60)+' min ago');
  $('power').textContent=s.power_kw.toFixed(2)+' kW';
  $('current').textContent=s.current.toFixed(0)+' A';
  $('session').textContent=s.session_kwh.toFixed(2)+' kWh';
  $('limit').textContent=s.limit<0?'–':(s.limit==0?'Paused':s.limit.toFixed(0)+' A');
  document.querySelectorAll('.modes button').forEach(b=>b.classList.toggle('on',b.dataset.mode==s.settings.mode));
  const st=s.settings,p=$('plan');p.classList.remove('warn');
  if(st.mode=='now')p.textContent='Charging at full current until you switch back to Scheduled.';
  else if(st.mode=='pause'){p.textContent='Paused. The car will not charge.';p.classList.add('warn')}
  else p.textContent=s.in_window?`Off-peak now: charging at ${st.amps} A until ${fmt12(st.end)}.`:`Waiting for off-peak: charging starts at ${fmt12(st.start)}.`;
  if(s.seconds_since_update!=null&&s.seconds_since_update>180){p.textContent='No data from the charger for a few minutes. Check the router and the Mac.';p.classList.add('warn')}
  if(!editing){$('start').value=st.start;$('end').value=st.end;$('amps').value=st.amps;$('ampsv').textContent=st.amps+' A'}
}
async function refresh(){try{render(await (await fetch('/api/state')).json())}catch(e){$('seen').textContent='Mac not reachable'}}
async function post(body){render(await (await fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})).json())}
document.querySelectorAll('.modes button').forEach(b=>b.onclick=()=>post({mode:b.dataset.mode}));
['start','end','amps'].forEach(id=>$(id).addEventListener('input',()=>{editing=true;$('ampsv').textContent=$('amps').value+' A'}));
$('save').onclick=async()=>{editing=false;await post({start:$('start').value,end:$('end').value,amps:+$('amps').value});$('save').textContent='Saved';setTimeout(()=>$('save').textContent='Save schedule',1500)};
refresh();setInterval(refresh,5000);
</script></body></html>"""


def main():
    client = mqtt.Client(client_id="juicerescue-web")
    client.on_connect = lambda c, u, f, rc: c.subscribe(STATE_TOPIC)
    client.on_message = on_message
    client.connect("127.0.0.1", 1883)
    client.loop_start()
    threading.Thread(target=scheduler, args=(client,), daemon=True).start()
    print(f"JuiceBox page on http://0.0.0.0:{PORT}  settings={settings}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
