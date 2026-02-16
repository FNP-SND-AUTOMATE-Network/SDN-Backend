"""
Cisco Intent Tester - Full Coverage
Tests ALL Cisco intents and reports which ones work/fail

Usage:
    python test_cisco_intents.py --node CSR1000vT --host localhost --port 8000
    python test_cisco_intents.py --node CSR1000vT --host localhost --port 8000 --write
"""
import httpx
import asyncio
import argparse
from typing import Dict, Any, List
from dataclasses import dataclass
from datetime import datetime


@dataclass
class TestResult:
    intent: str
    success: bool
    status_code: int
    response: Dict[str, Any]
    error: str = ""


# ===== ALL Cisco intents =====
CISCO_INTENTS = {
    # ==================== SHOW (Read-only) ====================
    "show.interface": {
        "params": {"interface": "GigabitEthernet1"}
    },
    "show.interfaces": {
        "params": {}
    },
    "show.version": {
        "params": {}
    },
    "show.ip_route": {
        "params": {}
    },
    "show.ip_interface_brief": {
        "params": {}
    },
    
    # ==================== INTERFACE ====================
    "interface.set_ipv4": {
        "params": {"interface": "GigabitEthernet3", "ip": "10.99.99.1", "prefix": "24"},
    },
    "interface.remove_ipv4": {
        "params": {"interface": "GigabitEthernet3"},
    },
    "interface.set_ipv6": {
        "params": {"interface": "GigabitEthernet3", "ip": "2001:db8::1", "prefix": "64"},
    },
    "interface.remove_ipv6": {
        "params": {"interface": "GigabitEthernet3"},
    },
    "interface.disable": {
        "params": {"interface": "GigabitEthernet3"},
    },
    "interface.enable": {
        "params": {"interface": "GigabitEthernet3"},
    },
    "interface.set_description": {
        "params": {"interface": "GigabitEthernet3", "description": "Test from API"},
    },
    "interface.set_mtu": {
        "params": {"interface": "GigabitEthernet3", "mtu": 1500},
    },
    
    # ==================== ROUTING - Static ====================
    "routing.static.add": {
        "params": {"prefix": "192.168.100.0", "mask": "255.255.255.0", "next_hop": "10.0.0.254"},
    },
    "routing.static.delete": {
        "params": {"prefix": "192.168.100.0", "mask": "255.255.255.0", "next_hop": "10.0.0.254"},
    },
    "routing.default.add": {
        "params": {"next_hop": "10.0.0.254"},
    },
    "routing.default.delete": {
        "params": {},
    },
    
    # ==================== ROUTING - OSPF ====================
    "routing.ospf.enable": {
        "params": {"process_id": "99"},
    },
    "routing.ospf.set_router_id": {
        "params": {"process_id": "99", "router_id": "9.9.9.9"},
    },
    "routing.ospf.add_network_interface": {
        "params": {"process_id": "99", "network": "10.0.0.0", "wildcard": "0.0.0.255", "area": "0"},
    },
    # Show OSPF data after enabling OSPF
    "show.ospf.neighbors": {
        "params": {}
    },
    "show.ospf.database": {
        "params": {}
    },
    "routing.ospf.set_passive_interface": {
        "params": {"process_id": "99", "interface": "GigabitEthernet1"},
    },
    "routing.ospf.remove_passive_interface": {
        "params": {"process_id": "99", "interface": "GigabitEthernet1"},
    },
    "routing.ospf.remove_network_interface": {
        "params": {"process_id": "99", "network": "10.0.0.0", "wildcard": "0.0.0.255", "area": "0"},
    },
    "routing.ospf.disable": {
        "params": {"process_id": "99"},
    },
    
    # ==================== SYSTEM ====================
    "system.set_hostname": {
        "params": {"hostname": "CSR1-TEST"},
        "cleanup": "system.set_hostname",
        "cleanup_params": {"hostname": "CSR1000vT"}
    },
    "system.set_banner": {
        "params": {"banner": "Authorized Access Only"},
    },
    "system.set_ntp": {
        "params": {"server": "8.8.8.8"},
    },
    "system.set_dns": {
        "params": {"server": "8.8.8.8"},
    },
    "system.save_config": {
        "params": {},
    },
    
    # ==================== VLAN ====================
    "vlan.create": {
        "params": {"vlan_id": 999, "name": "TEST_VLAN"},
    },
    # Show VLANs after creating one
    "show.vlans": {
        "params": {}
    },
    "vlan.update": {
        "params": {"vlan_id": 999, "name": "TEST_VLAN_UPDATED", "description": "Test VLAN"},
    },
    "vlan.delete": {
        "params": {"vlan_id": 999},
    },
}


async def test_intent(
    client: httpx.AsyncClient,
    base_url: str,
    node_id: str,
    intent: str,
    params: Dict[str, Any]
) -> TestResult:
    """Test a single intent"""
    url = f"{base_url}/api/v1/nbi/intent"
    payload = {
        "node_id": node_id,
        "intent": intent,
        "params": params
    }
    
    try:
        response = await client.post(url, json=payload, timeout=30.0)
        data = response.json()
        
        success = response.status_code in [200, 201, 204]
        return TestResult(
            intent=intent,
            success=success,
            status_code=response.status_code,
            response=data,
            error="" if success else str(data.get("detail", "Unknown error"))
        )
    except Exception as e:
        return TestResult(
            intent=intent,
            success=False,
            status_code=0,
            response={},
            error=str(e)
        )


async def run_tests(node_id: str, base_url: str, test_write: bool = False):
    """Run all intent tests"""
    results: List[TestResult] = []
    
    async with httpx.AsyncClient() as client:
        print(f"\n{'='*70}")
        print(f"  Cisco Intent Tester - Full Coverage")
        print(f"{'='*70}")
        print(f"  Node:  {node_id}")
        print(f"  API:   {base_url}")
        print(f"  Mode:  {'READ + WRITE' if test_write else 'READ ONLY'}")
        print(f"  Time:  {datetime.now().isoformat()}")
        print(f"{'='*70}\n")
        
        current_section = ""
        for intent, config in CISCO_INTENTS.items():
            # Print section headers
            section = intent.split(".")[0]
            if section != current_section:
                current_section = section
                print(f"\n--- {section.upper()} ---")
            
            # Skip write operations if not enabled
            is_read = intent.startswith("show.")
            if not test_write and not is_read:
                print(f"  ⏭️  SKIP  {intent}")
                continue
            
            print(f"  🧪 {intent}...", end=" ", flush=True)
            
            result = await test_intent(
                client, base_url, node_id, intent, config["params"]
            )
            results.append(result)
            
            if result.success:
                print(f"✅ OK ({result.status_code})")
            else:
                print(f"❌ FAIL ({result.status_code})")
                error_msg = result.error[:90].replace('\n', ' ')
                print(f"         └─ {error_msg}")
            
            # Cleanup if needed
            if test_write and result.success and "cleanup" in config:
                await asyncio.sleep(1)
                cleanup_result = await test_intent(
                    client, base_url, node_id,
                    config["cleanup"],
                    config["cleanup_params"]
                )
                if cleanup_result.success:
                    print(f"         └─ 🧹 Cleanup OK")
    
    # ===== Summary =====
    print(f"\n{'='*70}")
    print(f"  SUMMARY")
    print(f"{'='*70}")
    
    passed = [r for r in results if r.success]
    failed = [r for r in results if not r.success]
    total = len(results)
    pct = 100 * len(passed) // total if total else 0
    
    print(f"\n  ✅ PASSED ({len(passed)}):")
    for r in passed:
        print(f"     • {r.intent}")
    
    if failed:
        print(f"\n  ❌ FAILED ({len(failed)}):")
        for r in failed:
            print(f"     • {r.intent} ({r.status_code}): {r.error[:70]}")
    
    print(f"\n  📈 Result: {len(passed)}/{total} ({pct}%)")
    print(f"{'='*70}\n")
    
    return results


def main():
    parser = argparse.ArgumentParser(description="Test ALL Cisco Intents")
    parser.add_argument("--node", default="CSR1000vT", help="Node ID (default: CSR1000vT)")
    parser.add_argument("--host", default="localhost", help="API host (default: localhost)")
    parser.add_argument("--port", default="8000", help="API port (default: 8000)")
    parser.add_argument("--write", action="store_true", help="Include write operations (default: read-only)")
    
    args = parser.parse_args()
    base_url = f"http://{args.host}:{args.port}"
    
    asyncio.run(run_tests(args.node, base_url, args.write))


if __name__ == "__main__":
    main()
