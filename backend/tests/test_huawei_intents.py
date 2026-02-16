"""
Huawei NE40E (VRP8) Intent Test Suite
=====================================

Test script for verifying Huawei-specific intents against ODL.
Uses huawei-ifm, huawei-ip, huawei-ospfv2 native YANG models.

Usage:
    python test_huawei_intents.py
    python test_huawei_intents.py --device NE40E-R1 --read-only
    python test_huawei_intents.py --category ospf
"""
import asyncio
import argparse
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional
import httpx


# ==============================================================================
# Configuration
# ==============================================================================
DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_DEVICE_ID = "NE40E-R1"  # Huawei NE40E node_id
API_ENDPOINT = "/api/v1/nbi/intent"


# ==============================================================================
# Test Categories
# ==============================================================================
class TestCategory(Enum):
    INTERFACE = "interface"
    OSPF = "ospf"
    ROUTING = "routing"
    SYSTEM = "system"
    VLAN = "vlan"
    DHCP = "dhcp"


@dataclass
class TestCase:
    """Test case definition"""
    name: str
    intent: str
    params: Dict[str, Any]
    category: TestCategory
    is_read_only: bool = False
    cleanup_intent: Optional[str] = None
    cleanup_params: Optional[Dict[str, Any]] = None


# ==============================================================================
# Interface Tests (huawei-ifm + huawei-ip)
# ==============================================================================
INTERFACE_TESTS = [
    # GET Interface (Read-Only)
    TestCase(
        name="Show Single Interface",
        intent="show.interface",
        params={"interface": "Ethernet1/0/0"},
        category=TestCategory.INTERFACE,
        is_read_only=True
    ),
    TestCase(
        name="Show All Interfaces",
        intent="show.interfaces",
        params={},
        category=TestCategory.INTERFACE,
        is_read_only=True
    ),
    
    # SET Interface IPv4 (VRP8 huawei-ip:ipv4Config)
    TestCase(
        name="Set Interface IPv4",
        intent="interface.set_ipv4",
        params={
            "interface": "Ethernet1/0/3",
            "ip": "200.168.100.1",
            "prefix": 24
        },
        category=TestCategory.INTERFACE,
        is_read_only=False
    ),
    
    # Enable/Disable Interface
    TestCase(
        name="Enable Interface",
        intent="interface.enable",
        params={"interface": "Ethernet1/0/0"},
        category=TestCategory.INTERFACE,
        is_read_only=False
    ),
    TestCase(
        name="Disable Interface",
        intent="interface.disable",
        params={"interface": "Ethernet1/0/0"},
        category=TestCategory.INTERFACE,
        is_read_only=False,
        cleanup_intent="interface.enable",
        cleanup_params={"interface": "Ethernet1/0/0"}
    ),
    
    # Set Description
    TestCase(
        name="Set Interface Description",
        intent="interface.set_description",
        params={
            "interface": "Ethernet1/0/0",
            "description": "Link_to_Core_Router"
        },
        category=TestCategory.INTERFACE,
        is_read_only=False
    ),
    
    # Set MTU
    TestCase(
        name="Set Interface MTU",
        intent="interface.set_mtu",
        params={
            "interface": "Ethernet1/0/0",
            "mtu": 1500
        },
        category=TestCategory.INTERFACE,
        is_read_only=False
    ),
]


# ==============================================================================
# OSPF Tests (huawei-ospfv2)
# ==============================================================================
OSPF_TESTS = [
    # Create OSPF Process
    TestCase(
        name="Enable OSPF Process",
        intent="routing.ospf.enable",
        params={
            "process_id": 1,
            "router_id": "192.168.1.1",
            "description": "OSPF_Process_1"
        },
        category=TestCategory.OSPF,
        is_read_only=False
    ),
    
    # Set Router ID
    TestCase(
        name="Set OSPF Router ID",
        intent="routing.ospf.set_router_id",
        params={
            "process_id": 1,
            "router_id": "10.0.0.1"
        },
        category=TestCategory.OSPF,
        is_read_only=False
    ),
    
    # Add Network to Area
    TestCase(
        name="Add OSPF Network",
        intent="routing.ospf.add_network_interface",
        params={
            "process_id": 1,
            "area": "0.0.0.0",
            "network": "192.168.1.0",
            "wildcard": "0.0.0.255"
        },
        category=TestCategory.OSPF,
        is_read_only=False,
        cleanup_intent="routing.ospf.remove_network_interface",
        cleanup_params={
            "process_id": 1,
            "area": "0.0.0.0",
            "network": "192.168.1.0"
        }
    ),
    
    # Show OSPF (Read-Only)
    TestCase(
        name="Show OSPF Neighbors",
        intent="show.ospf.neighbors",
        params={"process_id": 1},
        category=TestCategory.OSPF,
        is_read_only=True
    ),
    TestCase(
        name="Show OSPF Database",
        intent="show.ospf.database",
        params={"process_id": 1},
        category=TestCategory.OSPF,
        is_read_only=True
    ),
    
    # Disable OSPF (cleanup)
    TestCase(
        name="Disable OSPF Process",
        intent="routing.ospf.disable",
        params={"process_id": 1},
        category=TestCategory.OSPF,
        is_read_only=False
    ),
]


# ==============================================================================
# Static Routing Tests (huawei-routing)
# ==============================================================================
ROUTING_TESTS = [
    TestCase(
        name="Add Static Route",
        intent="routing.static.add",
        params={
            "prefix": "10.0.0.0/24",
            "next_hop": "192.168.1.254"
        },
        category=TestCategory.ROUTING,
        is_read_only=False,
        cleanup_intent="routing.static.delete",
        cleanup_params={
            "prefix": "10.0.0.0/24",
            "next_hop": "192.168.1.254"
        }
    ),
    
    TestCase(
        name="Show IP Route",
        intent="show.ip_route",
        params={},
        category=TestCategory.ROUTING,
        is_read_only=True
    ),
]


# ==============================================================================
# System Tests (huawei-system)
# ==============================================================================
SYSTEM_TESTS = [
    TestCase(
        name="Show Version",
        intent="show.version",
        params={},
        category=TestCategory.SYSTEM,
        is_read_only=True
    ),
    
    TestCase(
        name="Set Hostname",
        intent="system.set_hostname",
        params={"hostname": "NE40E-Test"},
        category=TestCategory.SYSTEM,
        is_read_only=False
    ),
]


# ==============================================================================
# VLAN Tests (huawei-vlan)
# ==============================================================================
VLAN_TESTS = [
    TestCase(
        name="Show All VLANs",
        intent="show.vlans",
        params={},
        category=TestCategory.VLAN,
        is_read_only=True
    ),
    
    TestCase(
        name="Create VLAN",
        intent="vlan.create",
        params={
            "vlan_id": 100,
            "name": "TEST_VLAN_100",
            "description": "Test VLAN for automation"
        },
        category=TestCategory.VLAN,
        is_read_only=False,
        cleanup_intent="vlan.delete",
        cleanup_params={"vlan_id": 100}
    ),
    
    TestCase(
        name="Update VLAN",
        intent="vlan.update",
        params={
            "vlan_id": 100,
            "name": "UPDATED_VLAN",
            "description": "Updated description"
        },
        category=TestCategory.VLAN,
        is_read_only=False
    ),
]


# ==============================================================================
# DHCP Tests (huawei-ip-pool)
# ==============================================================================
DHCP_TESTS = [
    TestCase(
        name="Show DHCP Pools",
        intent="show.dhcp_pools",
        params={},
        category=TestCategory.DHCP,
        is_read_only=True
    ),
    
    TestCase(
        name="Create DHCP Pool",
        intent="dhcp.create_pool",
        params={
            "pool_name": "TEST_POOL",
            "gateway": "192.168.100.1",
            "mask": "255.255.255.0",
            "start_ip": "192.168.100.10",
            "end_ip": "192.168.100.100",
            "dns_servers": ["8.8.8.8", "8.8.4.4"],
            "lease_days": 1
        },
        category=TestCategory.DHCP,
        is_read_only=False,
        cleanup_intent="dhcp.delete_pool",
        cleanup_params={"pool_name": "TEST_POOL"}
    ),
]


# ==============================================================================
# Test Runner
# ==============================================================================
ALL_TESTS = INTERFACE_TESTS + OSPF_TESTS + ROUTING_TESTS + SYSTEM_TESTS + VLAN_TESTS + DHCP_TESTS


async def run_test(client: httpx.AsyncClient, node_id: str, test: TestCase) -> Dict[str, Any]:
    """Run a single test case"""
    payload = {
        "node_id": node_id,
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


async def run_cleanup(client: httpx.AsyncClient, node_id: str, test: TestCase):
    """Run cleanup for a test case"""
    if not test.cleanup_intent:
        return
    
    payload = {
        "node_id": node_id,
        "intent": test.cleanup_intent,
        "params": test.cleanup_params or {}
    }
    
    try:
        await client.post(API_ENDPOINT, json=payload, timeout=30.0)
    except:
        pass  # Ignore cleanup errors


async def run_all_tests(base_url: str, node_id: str, categories: List[str] = None, read_only: bool = False):
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
        print(f"Huawei NE40E (VRP8) Intent Test Suite")
        print(f"Device: {node_id}")
        print(f"Base URL: {base_url}")
        print(f"Tests to run: {len(tests_to_run)}")
        print(f"{'='*60}\n")
        
        for test in tests_to_run:
            result = await run_test(client, node_id, test)
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
            await run_cleanup(client, node_id, test)
            
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
    parser = argparse.ArgumentParser(description="Test Huawei VRP8 Intents")
    parser.add_argument("--device", "-d", default=DEFAULT_DEVICE_ID, help="Device node_id")
    parser.add_argument("--base-url", "-u", default=DEFAULT_BASE_URL, help="Backend base URL")
    parser.add_argument("--category", "-c", action="append", help="Filter by category (interface, ospf, routing, system)")
    parser.add_argument("--read-only", "-r", action="store_true", help="Only run read-only (GET) tests")
    
    args = parser.parse_args()
    
    asyncio.run(run_all_tests(
        base_url=args.base_url,
        node_id=args.device,
        categories=args.category,
        read_only=args.read_only
    ))


if __name__ == "__main__":
    main()
