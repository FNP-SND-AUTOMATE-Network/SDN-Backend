"""
Test Script - ALL IOS-XE Intent API Verification
ทดสอบ Intent ทั้งหมดที่อยู่ใน ios_xe drivers

Drivers Covered:
  - CiscoInterfaceDriver (11 intents)
  - CiscoRoutingDriver   (15 intents)
  - CiscoSystemDriver    (7 intents)
  - CiscoVlanDriver      (5 intents)

Usage:
    python test_intents.py
    python test_intents.py --node CSR1000vT
    python test_intents.py --base-url http://192.168.1.100:8000
    python test_intents.py --write-tests   (include write intents - CAUTION: modifies device config!)
"""

import requests
import json
import sys
import argparse
from datetime import datetime

# ========= Configuration =========
DEFAULT_BASE_URL = "http://localhost:8000"
API_PREFIX = "/api/v1/nbi"
DEFAULT_NODE_ID = "CSR1000vT"

# ========= Color Output =========
class Colors:
    GREEN  = "\033[92m"
    RED    = "\033[91m"
    YELLOW = "\033[93m"
    CYAN   = "\033[96m"
    BOLD   = "\033[1m"
    DIM    = "\033[2m"
    END    = "\033[0m"

def ok(msg):      print(f"  {Colors.GREEN}✓ PASS{Colors.END}  {msg}")
def fail(msg):    print(f"  {Colors.RED}✗ FAIL{Colors.END}  {msg}")
def info(msg):    print(f"  {Colors.CYAN}ℹ INFO{Colors.END}  {msg}")
def warn(msg):    print(f"  {Colors.YELLOW}⚠ WARN{Colors.END}  {msg}")
def skip(msg):    print(f"  {Colors.DIM}⊘ SKIP{Colors.END}  {msg}")
def header(msg):  print(f"\n{Colors.BOLD}{'='*60}\n  {msg}\n{'='*60}{Colors.END}")
def section(msg): print(f"\n{Colors.BOLD}── {msg} ──{Colors.END}")


# ========= Test Definitions =========

# --- READ-ONLY Tests (safe, always run) ---
READ_TESTS = {
    "Interface Driver (show)": [
        {
            "name": "show.interfaces",
            "intent": "show.interfaces",
            "params": {},
        },
        {
            "name": "show.interface (GigabitEthernet1)",
            "intent": "show.interface",
            "params": {"interface": "GigabitEthernet1"},
        },
        {
            "name": "show.interface (GigabitEthernet2)",
            "intent": "show.interface",
            "params": {"interface": "GigabitEthernet2"},
        },
    ],
    "Routing Driver (show)": [
        {
            "name": "show.ip_route",
            "intent": "show.ip_route",
            "params": {},
        },
        {
            "name": "show.ip_interface_brief",
            "intent": "show.ip_interface_brief",
            "params": {},
        },
        {
            "name": "show.ospf.neighbors",
            "intent": "show.ospf.neighbors",
            "params": {},
        },
        {
            "name": "show.ospf.database",
            "intent": "show.ospf.database",
            "params": {},
        },
    ],
    "System Driver (show)": [
        {
            "name": "show.running_config",
            "intent": "show.running_config",
            "params": {},
        },
        {
            "name": "show.running_config (section: interfaces)",
            "intent": "show.running_config",
            "params": {"section": "interfaces"},
        },
        {
            "name": "show.running_config (section: routing)",
            "intent": "show.running_config",
            "params": {"section": "routing"},
        },
        {
            "name": "show.running_config (section: hostname)",
            "intent": "show.running_config",
            "params": {"section": "hostname"},
        },
        {
            "name": "show.version",
            "intent": "show.version",
            "params": {},
        },
    ],
    "VLAN Driver (show)": [
        {
            "name": "show.vlans",
            "intent": "show.vlans",
            "params": {},
        },
    ],
}

# --- WRITE Tests (modifies device config! only with --write-tests) ---
WRITE_TESTS = {
    "Interface Driver (write)": [
        {
            "name": "interface.set_description",
            "intent": "interface.set_description",
            "params": {"interface": "GigabitEthernet4", "description": "TEST-by-script"},
        },
        {
            "name": "interface.set_ipv4",
            "intent": "interface.set_ipv4",
            "params": {"interface": "GigabitEthernet4", "ip": "10.99.99.1", "prefix": 24},
        },
        {
            "name": "interface.enable",
            "intent": "interface.enable",
            "params": {"interface": "GigabitEthernet4"},
        },
        {
            "name": "interface.disable",
            "intent": "interface.disable",
            "params": {"interface": "GigabitEthernet4"},
        },
        {
            "name": "interface.set_mtu",
            "intent": "interface.set_mtu",
            "params": {"interface": "GigabitEthernet4", "mtu": 1400},
        },
        {
            "name": "interface.remove_ipv4",
            "intent": "interface.remove_ipv4",
            "params": {"interface": "GigabitEthernet4"},
        },
    ],
    "Routing Driver (write)": [
        {
            "name": "routing.static.add",
            "intent": "routing.static.add",
            "params": {"prefix": "192.168.99.0/24", "next_hop": "10.0.0.1"},
        },
        {
            "name": "routing.static.delete",
            "intent": "routing.static.delete",
            "params": {"prefix": "192.168.99.0/24", "next_hop": "10.0.0.1"},
        },
    ],
    "System Driver (write)": [
        {
            "name": "system.set_banner",
            "intent": "system.set_banner",
            "params": {"banner": "TEST BANNER by test_intents.py"},
        },
    ],
}


# ========= Test Runner =========

def run_intent_test(base_url, node_id, test_case):
    """Execute a single intent test and return (passed: bool, detail: str)"""
    url = f"{base_url}{API_PREFIX}/intent"
    payload = {
        "intent": test_case["intent"],
        "node_id": node_id,
        "params": test_case["params"],
    }

    try:
        resp = requests.post(url, json=payload, timeout=15)
        status_code = resp.status_code
        body = resp.json()

        if status_code == 200:
            driver = body.get("driver_used", "?")
            data = body.get("data")
            summary = ""
            if isinstance(data, dict):
                keys = list(data.keys())[:4]
                summary = f"keys={keys}"
            elif isinstance(data, list):
                summary = f"list[{len(data)}]"
            ok(f"{test_case['name']}  →  200  driver={driver}  {summary}")
            return True

        elif status_code == 400:
            detail = body.get("detail", {})
            code = detail.get("code", "?")
            msg = detail.get("message", "?")[:100]
            if "not mounted" in msg.lower():
                warn(f"{test_case['name']}  →  400 [{code}] Device not mounted")
            else:
                fail(f"{test_case['name']}  →  400 [{code}] {msg}")
            return False

        elif status_code == 404:
            detail = body.get("detail", {})
            msg = detail.get("message", "?")[:100]
            fail(f"{test_case['name']}  →  404 {msg}")
            return False

        elif status_code == 409:
            detail = body.get("detail", {})
            msg = detail.get("message", "?")[:100]
            warn(f"{test_case['name']}  →  409 {msg}")
            return False

        elif status_code == 502:
            detail = body.get("detail", {})
            msg = detail.get("message", "?")[:100]
            warn(f"{test_case['name']}  →  502 ODL error: {msg}")
            return False

        else:
            fail(f"{test_case['name']}  →  {status_code}")
            return False

    except requests.exceptions.ConnectionError:
        fail(f"{test_case['name']}  →  Cannot connect to {base_url}")
        return False
    except requests.exceptions.Timeout:
        fail(f"{test_case['name']}  →  Timeout (>15s)")
        return False
    except Exception as e:
        fail(f"{test_case['name']}  →  Error: {e}")
        return False


def test_health(base_url):
    """Test health endpoint"""
    section("Health Check")
    try:
        resp = requests.get(f"{base_url}/health", timeout=5)
        if resp.status_code == 200:
            ok("GET /health → 200")
            return True
        else:
            fail(f"GET /health → {resp.status_code}")
            return False
    except Exception as e:
        fail(f"GET /health → Connection error: {e}")
        return False


def test_intent_list(base_url):
    """Test intent list endpoint"""
    section("Intent Registry")
    url = f"{base_url}{API_PREFIX}/intents"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            intents = data.get("intents", {})
            total = sum(len(v) for v in intents.values())
            ok(f"GET /intents → 200 ({total} intents registered)")
            return True
        else:
            fail(f"GET /intents → {resp.status_code}")
            return False
    except Exception as e:
        fail(f"GET /intents → Error: {e}")
        return False


# ========= Main =========
def main():
    parser = argparse.ArgumentParser(description="Test ALL IOS-XE Intents")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="API base URL")
    parser.add_argument("--node", default=DEFAULT_NODE_ID, help="Device node_id")
    parser.add_argument("--write-tests", action="store_true",
                        help="Include WRITE intents (modifies device config!)")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    node_id = args.node

    header(f"IOS-XE Intent Test Suite — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    info(f"Base URL    : {base_url}")
    info(f"Node ID     : {node_id}")
    info(f"Write tests : {'YES ⚠️' if args.write_tests else 'NO (use --write-tests to enable)'}")

    passed = 0
    failed = 0
    skipped = 0

    def track(result):
        nonlocal passed, failed
        if result:
            passed += 1
        else:
            failed += 1

    # 1) Health + Intent list
    track(test_health(base_url))
    track(test_intent_list(base_url))

    # 2) Read-only tests
    for group_name, tests in READ_TESTS.items():
        section(f"📖 {group_name}")
        for t in tests:
            track(run_intent_test(base_url, node_id, t))

    # 3) Write tests (optional)
    if args.write_tests:
        for group_name, tests in WRITE_TESTS.items():
            section(f"✏️  {group_name}")
            for t in tests:
                track(run_intent_test(base_url, node_id, t))
    else:
        for group_name, tests in WRITE_TESTS.items():
            section(f"✏️  {group_name} (SKIPPED)")
            for t in tests:
                skip(f"{t['name']}  (use --write-tests)")
                skipped += 1

    # ========= Summary =========
    total = passed + failed
    header("Results Summary")
    print(f"""
  {Colors.GREEN}Passed  : {passed}{Colors.END}
  {Colors.RED}Failed  : {failed}{Colors.END}
  {Colors.DIM}Skipped : {skipped}{Colors.END}
  Total   : {total} tested, {skipped} skipped
""")

    if failed == 0:
        print(f"  {Colors.GREEN}{Colors.BOLD}ALL {total} TESTS PASSED ✓{Colors.END}\n")
    else:
        print(f"  {Colors.RED}{Colors.BOLD}{failed} TEST(S) FAILED ✗{Colors.END}\n")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
