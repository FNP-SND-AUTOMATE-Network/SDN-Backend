"""
Cisco Intent Test Script
ทดสอบทุก Cisco intents กับ OpenDaylight

Usage:
    python test_cisco_intents.py --device CSR1000v --base-url http://localhost:8000
"""
import httpx
import asyncio
import argparse
from typing import Dict, Any, List
from dataclasses import dataclass
from enum import Enum

# ==============================================================================
# Configuration
# ==============================================================================
DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_DEVICE_ID = "CSR1000v"
API_ENDPOINT = "/api/v1/nbi/intent"

# ==============================================================================
# Test Cases - ทุก Intent ที่ Cisco Driver รองรับ
# ==============================================================================

class TestCategory(str, Enum):
    INTERFACE = "Interface"
    ROUTING = "Routing"
    OSPF = "OSPF"
    SYSTEM = "System"
    VLAN = "VLAN"

@dataclass
class TestCase:
    name: str
    intent: str
    params: Dict[str, Any]
    category: TestCategory
    is_read_only: bool = False
    cleanup_intent: str = None  # Intent to cleanup after test
    cleanup_params: Dict[str, Any] = None

# ==============================================================================
# Interface Tests (8 intents)
# ==============================================================================
INTERFACE_TESTS = [
    # GET Operations
    TestCase(
        name="Show All Interfaces",
        intent="show.interfaces",
        params={},
        category=TestCategory.INTERFACE,
        is_read_only=True
    ),
    TestCase(
        name="Show Single Interface",
        intent="show.interface",
        params={"interface": "GigabitEthernet2"},
        category=TestCategory.INTERFACE,
        is_read_only=True
    ),
    # Config Operations
    TestCase(
        name="Set Interface IPv4",
        intent="interface.set_ipv4",
        params={"interface": "GigabitEthernet3", "ip": "192.168.100.1", "prefix": 24},
        category=TestCategory.INTERFACE,
    ),
    TestCase(
        name="Set Interface IPv6",
        intent="interface.set_ipv6",
        params={"interface": "GigabitEthernet3", "ip": "2001:db8::1", "prefix": 64},
        category=TestCategory.INTERFACE,
    ),
    TestCase(
        name="Enable Interface",
        intent="interface.enable",
        params={"interface": "GigabitEthernet3"},
        category=TestCategory.INTERFACE,
    ),
    TestCase(
        name="Disable Interface",
        intent="interface.disable",
        params={"interface": "GigabitEthernet3"},
        category=TestCategory.INTERFACE,
    ),
    TestCase(
        name="Set Interface Description",
        intent="interface.set_description",
        params={"interface": "GigabitEthernet3", "description": "Test Interface"},
        category=TestCategory.INTERFACE,
    ),
    TestCase(
        name="Set Interface MTU",
        intent="interface.set_mtu",
        params={"interface": "GigabitEthernet3", "mtu": 1400},
        category=TestCategory.INTERFACE,
    ),
]

# ==============================================================================
# Routing Tests (4 intents)
# ==============================================================================
ROUTING_TESTS = [
    # GET Operations
    TestCase(
        name="Show IP Route",
        intent="show.ip_route",
        params={},
        category=TestCategory.ROUTING,
        is_read_only=True
    ),
    TestCase(
        name="Show IP Interface Brief",
        intent="show.ip_interface_brief",
        params={},
        category=TestCategory.ROUTING,
        is_read_only=True
    ),
    # Config Operations
    TestCase(
        name="Add Static Route",
        intent="routing.static.add",
        params={"prefix": "10.99.99.0/24", "next_hop": "192.168.1.1"},
        category=TestCategory.ROUTING,
        cleanup_intent="routing.static.delete",
        cleanup_params={"prefix": "10.99.99.0/24"}
    ),
    TestCase(
        name="Add Default Route",
        intent="routing.default.add",
        params={"next_hop": "192.168.1.254"},
        category=TestCategory.ROUTING,
        cleanup_intent="routing.default.delete",
        cleanup_params={}
    ),
]

# ==============================================================================
# OSPF Tests (9 intents)
# ==============================================================================
OSPF_TESTS = [
    # GET Operations
    TestCase(
        name="Show OSPF Neighbors",
        intent="show.ospf.neighbors",
        params={"process_id": "1"},
        category=TestCategory.OSPF,
        is_read_only=True
    ),
    TestCase(
        name="Show OSPF Database",
        intent="show.ospf.database",
        params={"process_id": "1"},
        category=TestCategory.OSPF,
        is_read_only=True
    ),
    # Config Operations
    TestCase(
        name="Enable OSPF Process",
        intent="routing.ospf.enable",
        params={"process_id": "99", "router_id": "9.9.9.9"},
        category=TestCategory.OSPF,
        cleanup_intent="routing.ospf.disable",
        cleanup_params={"process_id": "99"}
    ),
    TestCase(
        name="Set OSPF Router ID",
        intent="routing.ospf.set_router_id",
        params={"process_id": "99", "router_id": "1.1.1.1"},
        category=TestCategory.OSPF,
    ),
    TestCase(
        name="Add OSPF Network",
        intent="routing.ospf.add_network",
        params={"process_id": "99", "network": "10.0.0.0", "wildcard": "0.0.0.255", "area": "0"},
        category=TestCategory.OSPF,
        cleanup_intent="routing.ospf.remove_network",
        cleanup_params={"process_id": "99", "network": "10.0.0.0", "wildcard": "0.0.0.255", "area": "0"}
    ),
    TestCase(
        name="Set OSPF Passive Interface",
        intent="routing.ospf.set_passive_interface",
        params={"process_id": "99", "interface": "Loopback0"},
        category=TestCategory.OSPF,
        cleanup_intent="routing.ospf.remove_passive_interface",
        cleanup_params={"process_id": "99", "interface": "Loopback0"}
    ),
]

# ==============================================================================
# System Tests (5 intents)
# ==============================================================================
SYSTEM_TESTS = [
    # GET Operations
    TestCase(
        name="Show Running Config",
        intent="show.running_config",
        params={},
        category=TestCategory.SYSTEM,
        is_read_only=True
    ),
    TestCase(
        name="Show Running Config - Interfaces Section",
        intent="show.running_config",
        params={"section": "interfaces"},
        category=TestCategory.SYSTEM,
        is_read_only=True
    ),
    TestCase(
        name="Show Version",
        intent="show.version",
        params={},
        category=TestCategory.SYSTEM,
        is_read_only=True
    ),
    # Config Operations
    TestCase(
        name="Set Hostname",
        intent="system.set_hostname",
        params={"hostname": "TestRouter"},
        category=TestCategory.SYSTEM,
    ),
    TestCase(
        name="Set NTP Server",
        intent="system.set_ntp",
        params={"server": "1.1.1.1"},
        category=TestCategory.SYSTEM,
    ),
]

# ==============================================================================
# VLAN Tests (3 intents)
# ==============================================================================
VLAN_TESTS = [
    TestCase(
        name="Create VLAN",
        intent="vlan.create",
        params={"vlan_id": "999", "name": "TestVLAN"},
        category=TestCategory.VLAN,
        cleanup_intent="vlan.delete",
        cleanup_params={"vlan_id": "999"}
    ),
    TestCase(
        name="Assign Port to VLAN (Access)",
        intent="vlan.assign_port",
        params={"interface": "GigabitEthernet0/1", "vlan_id": "999", "mode": "access"},
        category=TestCategory.VLAN,
    ),
    # Delete is tested via cleanup
]

# ==============================================================================
# Test Runner
# ==============================================================================
ALL_TESTS = INTERFACE_TESTS + ROUTING_TESTS + OSPF_TESTS + SYSTEM_TESTS + VLAN_TESTS


async def run_test(client: httpx.AsyncClient, device_id: str, test: TestCase) -> Dict[str, Any]:
    """Run a single test case"""
    payload = {
        "node_id": device_id,
        "intent": test.intent,
        "params": test.params
    }
    
    try:
        response = await client.post(API_ENDPOINT, json=payload, timeout=30.0)
        data = response.json()
        
        return {
            "name": test.name,
            "intent": test.intent,
            "category": test.category.value,
            "is_read_only": test.is_read_only,
            "status": "PASS" if response.status_code in [200, 201, 204] else "FAIL",
            "http_status": response.status_code,
            "strategy_used": data.get("strategy_used"),
            "driver_used": data.get("driver_used"),
            "response": data if response.status_code in [200, 201, 204] else None,
            "error": data.get("detail") if response.status_code >= 400 else None
        }
    except Exception as e:
        return {
            "name": test.name,
            "intent": test.intent,
            "category": test.category.value,
            "status": "ERROR",
            "error": str(e)
        }


async def run_cleanup(client: httpx.AsyncClient, device_id: str, test: TestCase):
    """Run cleanup for a test case"""
    if not test.cleanup_intent:
        return
    
    payload = {
        "node_id": device_id,
        "intent": test.cleanup_intent,
        "params": test.cleanup_params or {}
    }
    
    try:
        await client.post(API_ENDPOINT, json=payload, timeout=30.0)
    except:
        pass  # Ignore cleanup errors


async def run_all_tests(base_url: str, device_id: str, categories: List[str] = None, read_only: bool = False):
    """Run all test cases"""
    async with httpx.AsyncClient(base_url=base_url) as client:
        results = []
        passed = 0
        failed = 0
        errors = 0
        
        tests_to_run = ALL_TESTS
        
        # Filter by category
        if categories:
            tests_to_run = [t for t in tests_to_run if t.category.value.lower() in [c.lower() for c in categories]]
        
        # Filter by read_only
        if read_only:
            tests_to_run = [t for t in tests_to_run if t.is_read_only]
        
        print(f"\n{'='*60}")
        print(f"Cisco Intent Test Suite")
        print(f"Device: {device_id}")
        print(f"Base URL: {base_url}")
        print(f"Tests to run: {len(tests_to_run)}")
        print(f"{'='*60}\n")
        
        for test in tests_to_run:
            result = await run_test(client, device_id, test)
            results.append(result)
            
            # Print result
            icon = "✅" if result["status"] == "PASS" else "❌" if result["status"] == "FAIL" else "⚠️"
            driver_info = f"[{result.get('driver_used', 'N/A')}]" if result.get("driver_used") else ""
            print(f"{icon} [{result['category']}] {result['name']} {driver_info}")
            
            if result["status"] == "PASS":
                passed += 1
            elif result["status"] == "FAIL":
                failed += 1
                print(f"   Error: {result.get('error', 'Unknown error')}")
            else:
                errors += 1
                print(f"   Error: {result.get('error', 'Unknown error')}")
            
            # Run cleanup
            await run_cleanup(client, device_id, test)
            
            # Small delay between tests
            await asyncio.sleep(0.5)
        
        # Summary
        print(f"\n{'='*60}")
        print(f"Test Results Summary")
        print(f"{'='*60}")
        print(f"✅ Passed: {passed}")
        print(f"❌ Failed: {failed}")
        print(f"⚠️  Errors: {errors}")
        print(f"Total: {len(results)}")
        print(f"{'='*60}\n")
        
        return results


def main():
    parser = argparse.ArgumentParser(description="Test Cisco Intents")
    parser.add_argument("--device", "-d", default=DEFAULT_DEVICE_ID, help="Device ID")
    parser.add_argument("--base-url", "-u", default=DEFAULT_BASE_URL, help="Backend base URL")
    parser.add_argument("--category", "-c", action="append", help="Filter by category (interface, routing, ospf, system, vlan)")
    parser.add_argument("--read-only", "-r", action="store_true", help="Only run read-only (GET) tests")
    
    args = parser.parse_args()
    
    asyncio.run(run_all_tests(
        base_url=args.base_url,
        device_id=args.device,
        categories=args.category,
        read_only=args.read_only
    ))


if __name__ == "__main__":
    main()
