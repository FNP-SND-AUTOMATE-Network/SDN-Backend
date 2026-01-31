def odl_mount_base(node_id: str) -> str:
    """
    Build RFC-8040 compliant mount path for NETCONF device
    
    RFC-8040 uses '=' for list keys instead of '/'
    Example: /network-topology:network-topology/topology=topology-netconf/node=CSR1/yang-ext:mount
    """
    return f"/network-topology:network-topology/topology=topology-netconf/node={node_id}/yang-ext:mount"
