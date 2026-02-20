"""
Huawei Drivers Package

Re-exports all VRP8 drivers from the vrp8 subpackage for backward compatibility.
"""
from app.drivers.huawei.vrp8.interface import HuaweiInterfaceDriver
from app.drivers.huawei.vrp8.routing import HuaweiRoutingDriver
from app.drivers.huawei.vrp8.system import HuaweiSystemDriver
from app.drivers.huawei.vrp8.dhcp import HuaweiDhcpDriver

__all__ = [
    "HuaweiInterfaceDriver",
    "HuaweiRoutingDriver",
    "HuaweiSystemDriver",
    "HuaweiDhcpDriver",
]
