from typing import Dict, Any, List

def normalize_topology(raw_topology: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalizes a hybrid topology structure (OpenFlow + NETCONF-LLDP)
    into a format suitable for generic frontend graph visualization libraries
    (e.g., React Flow, D3, Vis.js, etc.).

    Input format:
    {
        "nodes": [ "openflow:1", "CSR1000vT", ... ],
        "links": [
            {"source": "openflow:1:1", "target": "openflow:2:2", "type": "OpenFlow-L2"},
            {"source": "CSR1000vT:GigabitEthernet1", "target": "openflow:1:3", "type": "NETCONF-LLDP (OpenConfig)"}
        ]
    }

    Output format:
    {
        "nodes": [
            {"id": "openflow:1", "label": "openflow:1", "type": "switch"},
            {"id": "CSR1000vT", "label": "CSR1000vT", "type": "router"}
        ],
        "links": [
            {
                "id": "openflow:1:1-openflow:2:2",
                "source": "openflow:1",
                "target": "openflow:2",
                "sourceHandle": "1",
                "targetHandle": "2",
                "type": "OpenFlow-L2"
            }
        ]
    }
    """
    normalized_nodes: List[Dict[str, Any]] = []
    normalized_links: List[Dict[str, Any]] = []
    
    # 1. Normalize Nodes
    for node in raw_topology.get("nodes", []):
        if isinstance(node, dict):
            # Already a dictionary structure
            normalized_nodes.append({
                "id": node.get("id"),
                "label": node.get("label", node.get("id")),
                "type": node.get("type", "switch"),
                "parent": node.get("parent")
            })
        else:
            # String parsing legacy structure
            node_id = str(node)
            node_type = "switch"
            if "CSR" in node_id or "Router" in node_id or "R" in node_id:
                node_type = "router"
                
            normalized_nodes.append({
                "id": node_id,
                "label": node_id,
                "type": node_type
            })
        
    # 2. Normalize Links
    for link in raw_topology.get("links", []):
        raw_source = link.get("source", "")
        raw_target = link.get("target", "")
        link_type = link.get("type", "unknown")
        
        # Parse source node and port
        # Example: "openflow:1:1" -> Node "openflow:1", Port "1"
        # Example: "CSR1000vT:GigabitEthernet1" -> Node "CSR1000vT", Port "GigabitEthernet1"
        source_parts = raw_source.rsplit(":", 1)
        target_parts = raw_target.rsplit(":", 1)
        
        source_node = source_parts[0] if len(source_parts) > 1 else raw_source
        source_port = source_parts[1] if len(source_parts) > 1 else ""
        
        target_node = target_parts[0] if len(target_parts) > 1 else raw_target
        target_port = target_parts[1] if len(target_parts) > 1 else ""
        
        # Construct standard link object
        link_id = f"{raw_source}-{raw_target}"
        normalized_links.append({
            "id": link_id,
            "source": source_node,
            "target": target_node,
            "sourceHandle": source_port,
            "targetHandle": target_port,
            "type": link_type,
            "raw_source": raw_source,
            "raw_target": raw_target
        })

    return {
        "nodes": normalized_nodes,
        "links": normalized_links
    }
