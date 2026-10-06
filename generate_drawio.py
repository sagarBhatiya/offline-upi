import xml.etree.ElementTree as ET
import xml.dom.minidom
import os

def create_drawio_xml():
    mxfile = ET.Element('mxfile', {
        'host': 'app.diagrams.net',
        'modified': '2024-04-15T12:00:00.000Z',
        'agent': 'Mozilla/5.0 Offline UPI DFD Generator',
        'version': '24.0.0',
        'type': 'device'
    })

    # =========================================================================
    # TAB 1: EXACT ARCHITECTURE & DATA FLOW (Matching User's Specified Diagram)
    # =========================================================================
    d_arch = ET.SubElement(mxfile, 'diagram', {'id': 'exact_arch_flow', 'name': 'Architecture & Data Flow (Spec)'})
    model_arch = ET.SubElement(d_arch, 'mxGraphModel', {
        'dx': '1400', 'dy': '1100', 'grid': '1', 'gridSize': '10', 'guides': '1',
        'tooltips': '1', 'connect': '1', 'arrows': '1', 'fold': '1', 'page': '1',
        'pageScale': '1', 'pageWidth': '1169', 'pageHeight': '1400', 'math': '0', 'shadow': '0'
    })
    root = ET.SubElement(model_arch, 'root')
    ET.SubElement(root, 'mxCell', {'id': '0'})
    ET.SubElement(root, 'mxCell', {'id': '1', 'parent': '0'})

    # 1. TOP CONTAINER: SENDER PHONE (offline)
    sender_box = ET.SubElement(root, 'mxCell', {
        'id': 'box_sender',
        'value': '<b>SENDER PHONE (offline)</b>',
        'style': 'swimlane;whiteSpace=wrap;html=1;fillColor=#f8fafc;strokeColor=#0f172a;strokeWidth=2;fontColor=#0f172a;fontSize=14;startSize=30;rounded=1;',
        'vertex': '1', 'parent': '1'
    })
    ET.SubElement(sender_box, 'mxGeometry', {'x': '140', 'y': '40', 'width': '640', 'height': '220', 'as': 'geometry'})

    # Inside Sender: PaymentInstruction
    pi_node = ET.SubElement(root, 'mxCell', {
        'id': 'node_pi',
        'value': '<span style="font-family:monospace;font-size:12px;"><b>PaymentInstruction</b> { sender, receiver, amount, pinHash, nonce, time }</span>',
        'style': 'rounded=1;whiteSpace=wrap;html=1;fillColor=#e2e8f0;strokeColor=#475569;fontColor=#0f172a;strokeWidth=1.5;',
        'vertex': '1', 'parent': 'box_sender'
    })
    ET.SubElement(pi_node, 'mxGeometry', {'x': '40', 'y': '45', 'width': '560', 'height': '45', 'as': 'geometry'})

    # Inside Sender: MeshPacket
    mp_node = ET.SubElement(root, 'mxCell', {
        'id': 'node_mp',
        'value': '<span style="font-family:monospace;font-size:12px;"><b>MeshPacket</b> { packetId, ttl, createdAt, ciphertext }</span>',
        'style': 'rounded=1;whiteSpace=wrap;html=1;fillColor=#cbd5e1;strokeColor=#334155;fontColor=#0f172a;strokeWidth=1.5;',
        'vertex': '1', 'parent': 'box_sender'
    })
    ET.SubElement(mp_node, 'mxGeometry', {'x': '40', 'y': '145', 'width': '560', 'height': '45', 'as': 'geometry'})

    # Edge inside Sender
    e_enc = ET.SubElement(root, 'mxCell', {
        'id': 'e_enc',
        'value': '<b>encrypt with server\'s RSA public key</b>',
        'style': 'edgeStyle=straight;html=1;strokeColor=#1e293b;strokeWidth=2;fontSize=11;fontColor=#1e3a8a;align=center;',
        'edge': '1', 'parent': 'box_sender', 'source': 'node_pi', 'target': 'node_mp'
    })
    ET.SubElement(e_enc, 'mxGeometry', {'relative': '1', 'as': 'geometry'})

    # 2. MIDDLE HOP LAYER (Bluetooth Gossip)
    stranger1 = ET.SubElement(root, 'mxCell', {
        'id': 'node_stranger1',
        'value': '<b>stranger1</b><br/><span style="font-size:10px;color:#64748b;">(offline relay)</span>',
        'style': 'rounded=1;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;strokeWidth=2;fontColor=#1e293b;fontSize=12;',
        'vertex': '1', 'parent': '1'
    })
    ET.SubElement(stranger1, 'mxGeometry', {'x': '140', 'y': '340', 'width': '130', 'height': '60', 'as': 'geometry'})

    stranger2 = ET.SubElement(root, 'mxCell', {
        'id': 'node_stranger2',
        'value': '<b>stranger2</b><br/><span style="font-size:10px;color:#64748b;">(offline relay)</span>',
        'style': 'rounded=1;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;strokeWidth=2;fontColor=#1e293b;fontSize=12;',
        'vertex': '1', 'parent': '1'
    })
    ET.SubElement(stranger2, 'mxGeometry', {'x': '395', 'y': '340', 'width': '130', 'height': '60', 'as': 'geometry'})

    bridge = ET.SubElement(root, 'mxCell', {
        'id': 'node_bridge',
        'value': '<b>bridge</b><br/><span style="font-size:10px;color:#047857;font-weight:bold;">(online relay)</span>',
        'style': 'rounded=1;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;strokeWidth=2;fontColor=#064e3b;fontSize=12;',
        'vertex': '1', 'parent': '1'
    })
    ET.SubElement(bridge, 'mxGeometry', {'x': '650', 'y': '340', 'width': '130', 'height': '60', 'as': 'geometry'})

    bridge_note = ET.SubElement(root, 'mxCell', {
        'id': 'note_bridge',
        'value': '<span style="font-size:11px;color:#047857;">◀── <b>walks outside<br/>gets 4G</b></span>',
        'style': 'text;html=1;align=left;verticalAlign=middle;resizable=0;points=[];autosize=1;strokeColor=none;fillColor=none;',
        'vertex': '1', 'parent': '1'
    })
    ET.SubElement(bridge_note, 'mxGeometry', {'x': '790', 'y': '350', 'width': '120', 'height': '35', 'as': 'geometry'})

    e_gossip = ET.SubElement(root, 'mxCell', {
        'id': 'e_gossip',
        'value': '<b>Bluetooth gossip</b>',
        'style': 'edgeStyle=orthogonalEdgeStyle;html=1;strokeColor=#0f172a;strokeWidth=2;fontSize=11;fontColor=#0f172a;align=center;',
        'edge': '1', 'parent': '1', 'source': 'box_sender', 'target': 'node_stranger1'
    })
    ET.SubElement(e_gossip, 'mxGeometry', {'relative': '1', 'as': 'geometry'})

    e_hop1 = ET.SubElement(root, 'mxCell', {
        'id': 'e_hop1',
        'value': '<b>hop</b>',
        'style': 'edgeStyle=straight;html=1;strokeColor=#0f172a;strokeWidth=2;fontSize=11;fontColor=#0f172a;align=center;',
        'edge': '1', 'parent': '1', 'source': 'node_stranger1', 'target': 'node_stranger2'
    })
    ET.SubElement(e_hop1, 'mxGeometry', {'relative': '1', 'as': 'geometry'})

    e_hop2 = ET.SubElement(root, 'mxCell', {
        'id': 'e_hop2',
        'value': '<b>hop</b>',
        'style': 'edgeStyle=straight;html=1;strokeColor=#0f172a;strokeWidth=2;fontSize=11;fontColor=#0f172a;align=center;',
        'edge': '1', 'parent': '1', 'source': 'node_stranger2', 'target': 'node_bridge'
    })
    ET.SubElement(e_hop2, 'mxGeometry', {'relative': '1', 'as': 'geometry'})

    # 3. BOTTOM CONTAINER: PYTHON FLASK BACKEND & SQLITE
    backend_box = ET.SubElement(root, 'mxCell', {
        'id': 'box_backend',
        'value': '<b>PYTHON FLASK BACKEND &amp; SQLITE (this project)</b>',
        'style': 'swimlane;whiteSpace=wrap;html=1;fillColor=#f8fafc;strokeColor=#0f172a;strokeWidth=2;fontColor=#0f172a;fontSize=14;startSize=30;rounded=1;',
        'vertex': '1', 'parent': '1'
    })
    ET.SubElement(backend_box, 'mxGeometry', {'x': '140', 'y': '480', 'width': '780', 'height': '640', 'as': 'geometry'})

    api_node = ET.SubElement(root, 'mxCell', {
        'id': 'node_api',
        'value': '<span style="font-family:monospace;font-size:13px;font-weight:bold;color:#1e3a8a;">/api/bridge/ingest (Flask Endpoint)</span>',
        'style': 'text;html=1;align=left;verticalAlign=middle;strokeColor=none;fillColor=none;',
        'vertex': '1', 'parent': 'box_backend'
    })
    ET.SubElement(api_node, 'mxGeometry', {'x': '40', 'y': '40', 'width': '300', 'height': '30', 'as': 'geometry'})

    step1 = ET.SubElement(root, 'mxCell', {
        'id': 'step1',
        'value': '<b>[1] hash ciphertext (SHA-256)</b>',
        'style': 'rounded=1;whiteSpace=wrap;html=1;fillColor=#e2e8f0;strokeColor=#334155;strokeWidth=1.5;fontColor=#0f172a;fontSize=12;align=left;spacingLeft=15;',
        'vertex': '1', 'parent': 'box_backend'
    })
    ET.SubElement(step1, 'mxGeometry', {'x': '40', 'y': '90', 'width': '340', 'height': '45', 'as': 'geometry'})

    step2 = ET.SubElement(root, 'mxCell', {
        'id': 'step2',
        'value': '<b>[2] IdempotencyService.claim(hash)</b>',
        'style': 'rounded=1;whiteSpace=wrap;html=1;fillColor=#fed7aa;strokeColor=#ea580c;strokeWidth=1.5;fontColor=#7c2d12;fontSize=12;align=left;spacingLeft=15;',
        'vertex': '1', 'parent': 'box_backend'
    })
    ET.SubElement(step2, 'mxGeometry', {'x': '40', 'y': '180', 'width': '340', 'height': '45', 'as': 'geometry'})

    step2_note = ET.SubElement(root, 'mxCell', {
        'id': 'note_step2',
        'value': '<span style="font-size:11px;color:#c2410c;">◀── <b>atomic putIfAbsent (SQLite PK constraint / Redis SETNX)</b><br/>Duplicates rejected here, before any work.</span>',
        'style': 'text;html=1;align=left;verticalAlign=middle;strokeColor=none;fillColor=none;',
        'vertex': '1', 'parent': 'box_backend'
    })
    ET.SubElement(step2_note, 'mxGeometry', {'x': '395', 'y': '180', 'width': '370', 'height': '45', 'as': 'geometry'})

    step3 = ET.SubElement(root, 'mxCell', {
        'id': 'step3',
        'value': '<b>[3] HybridCryptoService.decrypt(ciphertext)</b><br/><span style="font-size:10.5px;color:#475569;">(RSA-OAEP unwraps AES key, AES-GCM decrypts payload<br/>AND verifies the auth tag — tampering = exception)</span>',
        'style': 'rounded=1;whiteSpace=wrap;html=1;fillColor=#e0e7ff;strokeColor=#4338ca;strokeWidth=1.5;fontColor=#1e1b4b;fontSize=12;align=left;spacingLeft=15;',
        'vertex': '1', 'parent': 'box_backend'
    })
    ET.SubElement(step3, 'mxGeometry', {'x': '40', 'y': '275', 'width': '520', 'height': '65', 'as': 'geometry'})

    step4 = ET.SubElement(root, 'mxCell', {
        'id': 'step4',
        'value': '<b>[4] Freshness check: signedAt within last 24h</b>',
        'style': 'rounded=1;whiteSpace=wrap;html=1;fillColor=#fef08a;strokeColor=#ca8a04;strokeWidth=1.5;fontColor=#713f12;fontSize=12;align=left;spacingLeft=15;',
        'vertex': '1', 'parent': 'box_backend'
    })
    ET.SubElement(step4, 'mxGeometry', {'x': '40', 'y': '390', 'width': '340', 'height': '45', 'as': 'geometry'})

    step5 = ET.SubElement(root, 'mxCell', {
        'id': 'step5',
        'value': '<b>[5] SettlementService.settle() in SQLite</b><br/><span style="font-size:11px;color:#065f46;">• <b>ACID Transaction:</b> debit sender, credit receiver, write ledger<br/>• <b>Optimistic Locking on Account (version):</b> defense in depth</span>',
        'style': 'rounded=1;whiteSpace=wrap;html=1;fillColor=#dcfce7;strokeColor=#15803d;strokeWidth=2;fontColor=#14532d;fontSize=12;align=left;spacingLeft=15;',
        'vertex': '1', 'parent': 'box_backend'
    })
    ET.SubElement(step5, 'mxGeometry', {'x': '40', 'y': '485', 'width': '520', 'height': '75', 'as': 'geometry'})

    backend_edges = [
        ('be_1', 'node_api', 'step1', ''),
        ('be_2', 'step1', 'step2', ''),
        ('be_3', 'step2', 'step3', ''),
        ('be_4', 'step3', 'step4', ''),
        ('be_5', 'step4', 'step5', ''),
    ]
    for bid, src, tgt, val in backend_edges:
        e = ET.SubElement(root, 'mxCell', {
            'id': bid, 'value': val,
            'style': 'edgeStyle=straight;html=1;strokeColor=#0f172a;strokeWidth=2;fontSize=11;',
            'edge': '1', 'parent': 'box_backend', 'source': src, 'target': tgt
        })
        ET.SubElement(e, 'mxGeometry', {'relative': '1', 'as': 'geometry'})

    e_https = ET.SubElement(root, 'mxCell', {
        'id': 'e_https',
        'value': '<b>HTTPS POST</b>',
        'style': 'edgeStyle=orthogonalEdgeStyle;html=1;strokeColor=#0f172a;strokeWidth=2;fontSize=12;fontColor=#0f172a;align=center;',
        'edge': '1', 'parent': '1', 'source': 'node_bridge', 'target': 'box_backend'
    })
    ET.SubElement(e_https, 'mxGeometry', {'relative': '1', 'as': 'geometry'})

    # TAB 2: DFD Level 0
    d0 = ET.SubElement(mxfile, 'diagram', {'id': 'level0_context', 'name': 'DFD Level 0 - Context'})
    model0 = ET.SubElement(d0, 'mxGraphModel', {
        'dx': '1200', 'dy': '800', 'grid': '1', 'gridSize': '10', 'guides': '1',
        'tooltips': '1', 'connect': '1', 'arrows': '1', 'fold': '1', 'page': '1',
        'pageScale': '1', 'pageWidth': '1169', 'pageHeight': '827', 'math': '0', 'shadow': '0'
    })
    root0 = ET.SubElement(model0, 'root')
    ET.SubElement(root0, 'mxCell', {'id': '0'})
    ET.SubElement(root0, 'mxCell', {'id': '1', 'parent': '0'})

    s0 = ET.SubElement(root0, 'mxCell', {
        'id': 'c_sender', 'value': '<b>Sender Phone</b><br/>(Offline Device)',
        'style': 'rounded=0;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;strokeWidth=2;fontSize=12;',
        'vertex': '1', 'parent': '1'
    })
    ET.SubElement(s0, 'mxGeometry', {'x': '80', 'y': '270', 'width': '160', 'height': '80', 'as': 'geometry'})

    p0 = ET.SubElement(root0, 'mxCell', {
        'id': 'c_proc', 'value': '<b>0.0</b><br/><br/><b>Offline UPI Payment &amp;<br/>Settlement Engine (Python)</b>',
        'style': 'ellipse;whiteSpace=wrap;html=1;aspect=fixed;fillColor=#d5e8d4;strokeColor=#82b366;strokeWidth=3;fontSize=13;',
        'vertex': '1', 'parent': '1'
    })
    ET.SubElement(p0, 'mxGeometry', {'x': '475', 'y': '230', 'width': '190', 'height': '160', 'as': 'geometry'})

    r0 = ET.SubElement(root0, 'mxCell', {
        'id': 'c_rcv', 'value': '<b>Receiver / Payee</b><br/>(Beneficiary)',
        'style': 'rounded=0;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;strokeWidth=2;fontSize=12;',
        'vertex': '1', 'parent': '1'
    })
    ET.SubElement(r0, 'mxGeometry', {'x': '880', 'y': '270', 'width': '160', 'height': '80', 'as': 'geometry'})

    rel0 = ET.SubElement(root0, 'mxCell', {
        'id': 'c_rel', 'value': '<b>BLE Mesh Relays</b><br/>(Stranger Devices)',
        'style': 'rounded=0;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;strokeWidth=2;fontSize=12;',
        'vertex': '1', 'parent': '1'
    })
    ET.SubElement(rel0, 'mxGeometry', {'x': '480', 'y': '80', 'width': '180', 'height': '70', 'as': 'geometry'})

    brg0 = ET.SubElement(root0, 'mxCell', {
        'id': 'c_brg', 'value': '<b>Bridge Node</b><br/>(4G / Wi-Fi)',
        'style': 'rounded=0;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;strokeWidth=2;fontSize=12;',
        'vertex': '1', 'parent': '1'
    })
    ET.SubElement(brg0, 'mxGeometry', {'x': '480', 'y': '520', 'width': '180', 'height': '70', 'as': 'geometry'})

    edges_c = [
        ('ec_1', 'c_sender', 'c_proc', '1. Payment Info (VPA, Amt, PIN)'),
        ('ec_2', 'c_proc', 'c_sender', '2. Encrypted MeshPacket'),
        ('ec_3', 'c_sender', 'c_rel', '3. BLE Gossip Broadcast'),
        ('ec_4', 'c_rel', 'c_brg', '4. Multi-hop Relayed Packets'),
        ('ec_5', 'c_brg', 'c_proc', '5. HTTPS Ingest (/api/bridge/ingest)'),
        ('ec_6', 'c_proc', 'c_rcv', '6. Credit SMS Notification')
    ]
    for cid, src, tgt, val in edges_c:
        e = ET.SubElement(root0, 'mxCell', {
            'id': cid, 'value': val,
            'style': 'edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;strokeColor=#1E293B;strokeWidth=1.5;fontSize=10;',
            'edge': '1', 'parent': '1', 'source': src, 'target': tgt
        })
        ET.SubElement(e, 'mxGeometry', {'relative': '1', 'as': 'geometry'})

    # Save XML out
    xml_str = ET.tostring(mxfile, encoding='utf-8')
    parsed = xml.dom.minidom.parseString(xml_str)
    pretty_xml = parsed.toprettyxml(indent="  ")

    output_path = os.path.abspath(os.path.join(os.getcwd(), 'Offline_UPI_DFD.drawio'))
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(pretty_xml)

    print(f"Updated Draw.io file successfully at: {output_path}")

if __name__ == '__main__':
    create_drawio_xml()
