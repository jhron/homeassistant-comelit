"""Sonda pro Comelit HSrv hub – čtení stavu klima zón a testování příkazů.

Použití (z kořene repa, .venv s aiomqtt):
  python debug/hub_climate_probe.py selftest                 # offline: parser nad tests/hub_status.json
  python debug/hub_climate_probe.py status                   # přihlásit se a vypsat klima zóny
  python debug/hub_climate_probe.py mode <obj_id> <1|2>      # act_type=13, act_params=[mode] (1=auto, 2=manual)
  python debug/hub_climate_probe.py on <obj_id>              # act_type=0,  act_params=[1]
  python debug/hub_climate_probe.py off <obj_id>             # act_type=0,  act_params=[0]
  python debug/hub_climate_probe.py raw <obj_id> <act_type> <p1[,p2]>   # libovolný příkaz

Přihlašovací údaje bere z .env v kořeni repa a nikdy je nevypisuje
(vypisují se jen názvy chybějících proměnných).
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = REPO_ROOT / ".env"

REQUIRED = (
    "COMELIT_HUB_HOST",
    "COMELIT_MQTT_PORT",
    "COMELIT_MQTT_USER",
    "COMELIT_MQTT_PASSWORD",
    "COMELIT_HUB_SERIAL",
    "COMELIT_HUB_USER",
    "COMELIT_HUB_PASSWORD",
    "COMELIT_CLIENT_NAME",
)

REQ_STATUS = 0
REQ_ACTION = 1
REQ_LOGIN = 5
REQ_ANNOUNCE = 13

AUTO_MAN_NAMES = {0: "none", 1: "AUTO", 2: "MANUAL", 3: "semi-auto", 4: "semi-man", 5: "OFF(auto)", 6: "OFF(man)"}


def load_env(path: Path) -> dict[str, str]:
    if not path.exists():
        sys.exit(f"Chybí {path} – vytvoř ho podle šablony.")
    env: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    missing = [k for k in REQUIRED if not env.get(k)]
    if missing:
        sys.exit("V .env chybí hodnoty pro: " + ", ".join(missing))
    return env


def parse_climates(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Projde status strom stejně jako hub.py a vrátí klima zóny."""
    found: list[dict[str, Any]] = []
    for item in elements:
        data = item.get("data", item)
        entity_id = data.get("id", "")
        if "GEN#PL" in entity_id:
            found.extend(parse_climates(data.get("elements", [])))
            continue
        if "DOM#CL" in entity_id and data.get("sub_type") in (16, 12):
            found.append(data)
    return found


def fmt_zone(z: dict[str, Any]) -> str:
    def num(key: str, div: float = 1.0) -> str:
        try:
            return f"{float(z.get(key, 'nan')) / div:g}"
        except (TypeError, ValueError):
            return "?"

    auto_man = int(z.get("auto_man", -1) or -1)
    return (
        f"{z.get('id', '?'):<14} {z.get('descrizione', ''):<28} "
        f"auto_man={auto_man} ({AUTO_MAN_NAMES.get(auto_man, '?'):<9}) "
        f"est_inv={z.get('est_inv', '?')} powerst={z.get('powerst', '?')} status={z.get('status', '?')} "
        f"temp={num('temperatura', 10)} target={num('soglia_attiva', 10)} "
        f"heatOut(I)={z.get('num_moduloI', '?')}/{z.get('num_uscitaI', '?')} "
        f"coolOut(E)={z.get('num_moduloE', '?')}/{z.get('num_uscitaE', '?')}"
    )


def print_zones(zones: list[dict[str, Any]], only: str | None = None) -> None:
    for z in zones:
        if only is None or z.get("id") == only:
            print("  " + fmt_zone(z))


class HubProbe:
    def __init__(self, env: dict[str, str]) -> None:
        import aiomqtt  # noqa: WPS433 – až tady, ať selftest běží i bez něj

        self._aiomqtt = aiomqtt
        self.host = env["COMELIT_HUB_HOST"]
        self.port = int(env["COMELIT_MQTT_PORT"])
        self.mqtt_user = env["COMELIT_MQTT_USER"]
        self.mqtt_password = env["COMELIT_MQTT_PASSWORD"]
        self.serial = env["COMELIT_HUB_SERIAL"]
        self.hub_user = env["COMELIT_HUB_USER"]
        self.hub_password = env["COMELIT_HUB_PASSWORD"]
        self.client_name = env["COMELIT_CLIENT_NAME"]
        self.topic_rx = f"HSrv/{self.serial}/rx/{self.client_name}"
        self.topic_tx = f"HSrv/{self.serial}/tx/{self.client_name}"

        self.seq_id = 1
        self.agent_id = 10
        self.sessiontoken = ""
        self._client: Any = None
        self._reader: asyncio.Task | None = None
        self._pending: dict[int, asyncio.Future] = {}
        self._pending_by_type: dict[int, asyncio.Future] = {}

    async def __aenter__(self) -> HubProbe:  # noqa: PYI034 – Self až od Pythonu 3.11
        self._client = self._aiomqtt.Client(
            hostname=self.host, port=self.port, username=self.mqtt_user, password=self.mqtt_password
        )
        await self._client.__aenter__()
        await self._client.subscribe(self.topic_tx)
        self._reader = asyncio.create_task(self._read_loop())
        await self._handshake()
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._reader:
            self._reader.cancel()
        if self._client:
            await self._client.__aexit__(None, None, None)

    async def _read_loop(self) -> None:
        async for message in self._client.messages:
            try:
                payload = json.loads(message.payload)
            except (TypeError, ValueError):
                continue
            seq = payload.get("seq_id")
            fut = self._pending.pop(seq, None) if seq is not None else None
            if fut is None:
                fut = self._pending_by_type.pop(payload.get("req_type"), None)
            if fut is not None and not fut.done():
                fut.set_result(payload)

    async def request(self, data: dict[str, Any], timeout: float = 15.0) -> dict[str, Any]:
        seq = self.seq_id
        self.seq_id += 1
        data = {**data, "seq_id": seq, "agent_id": self.agent_id, "sessiontoken": self.sessiontoken}
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[seq] = fut
        self._pending_by_type[data["req_type"]] = fut
        await self._client.publish(self.topic_rx, json.dumps(data))
        try:
            return await asyncio.wait_for(fut, timeout)
        finally:
            self._pending.pop(seq, None)
            if self._pending_by_type.get(data["req_type"]) is fut:
                self._pending_by_type.pop(data["req_type"], None)

    async def _handshake(self) -> None:
        announce = await self.request({"req_type": REQ_ANNOUNCE, "req_sub_type": -1, "agent_type": 0})
        self.agent_id = announce["out_data"][0]["agent_id"]
        login = await self.request(
            {
                "req_type": REQ_LOGIN,
                "req_sub_type": -1,
                "agent_type": 0,
                "user_name": self.hub_user,
                "password": self.hub_password,
            }
        )
        if login.get("req_result") == 1 or not login.get("sessiontoken"):
            sys.exit(f"Login selhal: {login.get('message', 'bez zprávy')}")
        self.sessiontoken = login["sessiontoken"]
        print(f"Přihlášeno (agent_id={self.agent_id}, token přijat).")

    async def climates(self) -> list[dict[str, Any]]:
        resp = await self.request(
            {"req_type": REQ_STATUS, "req_sub_type": -1, "obj_id": "GEN#17#13#1", "detail_level": 1}
        )
        if resp.get("req_result") not in (0, None):
            sys.exit(f"Status selhal: {resp.get('message', 'bez zprávy')}")
        elements = resp.get("out_data", [{}])[0].get("elements", [])
        return parse_climates(elements)

    async def action(self, obj_id: str, act_type: int, act_params: list[int]) -> dict[str, Any]:
        resp = await self.request(
            {
                "req_type": REQ_ACTION,
                "req_sub_type": 3,
                "obj_id": obj_id,
                "act_type": act_type,
                "act_params": act_params,
            }
        )
        print(
            f"Odesláno act_type={act_type} act_params={act_params} -> "
            f"req_result={resp.get('req_result')} message={resp.get('message', '')!r}"
        )
        return resp


async def run_command(env: dict[str, str], cmd: str, args: list[str]) -> None:
    async with HubProbe(env) as hub:
        zones = await hub.climates()
        if cmd == "status":
            print(f"Klima zóny ({len(zones)}):")
            print_zones(zones)
            return

        obj_id = args[0]
        if obj_id not in {z.get("id") for z in zones}:
            sys.exit(f"Zóna {obj_id} v hubu není. Dostupné: {[z.get('id') for z in zones]}")

        if cmd == "mode":
            act_type, params = 13, [int(args[1])]
        elif cmd == "on":
            act_type, params = 0, [1]
        elif cmd == "off":
            act_type, params = 0, [0]
        elif cmd == "raw":
            act_type, params = int(args[1]), [int(p) for p in args[2].split(",")]
        else:
            sys.exit(f"Neznámý příkaz {cmd}")

        print("PŘED:")
        print_zones(zones, only=obj_id)
        await hub.action(obj_id, act_type, params)
        for delay in (2, 3, 5):
            await asyncio.sleep(delay)
            print(f"PO +{delay}s:")
            print_zones(await hub.climates(), only=obj_id)


def selftest() -> None:
    sample = json.loads((REPO_ROOT / "tests" / "hub_status.json").read_text(encoding="utf-8"))
    zones = parse_climates(sample["out_data"][0]["elements"])
    print(f"selftest: {len(zones)} klima zón v tests/hub_status.json")
    print_zones(zones)


def main(argv: list[str]) -> None:
    if len(argv) < 2 or argv[1] not in {"selftest", "status", "mode", "on", "off", "raw"}:
        sys.exit(__doc__)
    cmd, args = argv[1], argv[2:]
    if cmd == "selftest":
        selftest()
        return
    needed = {"status": 0, "mode": 2, "on": 1, "off": 1, "raw": 3}[cmd]
    if len(args) < needed:
        sys.exit(__doc__)
    if cmd == "mode" and args[1] not in ("1", "2"):
        sys.exit("mode musí být 1 (auto) nebo 2 (manual); vypnutí dělej přes 'off'.")
    asyncio.run(run_command(load_env(ENV_FILE), cmd, args))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if sys.platform == "win32":
        # paho/aiomqtt potřebuje add_reader/add_writer, což Proactor loop na Windows neumí
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    main(sys.argv)
