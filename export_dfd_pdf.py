import os
import shutil
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether, HRFlowable
)
from reportlab.graphics.shapes import (
    Drawing, Rect, Circle, Line, String, Group, Polygon
)
from reportlab.pdfgen import canvas

class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#4B5563"))
        
        # Header (pages > 1)
        if self._pageNumber > 1:
            self.drawString(36, 810, "Offline UPI System Specification")
            self.drawRightString(559, 810, "Data Flow Diagrams (DFD) & ER Diagram")
            self.setStrokeColor(colors.HexColor("#CBD5E1"))
            self.setLineWidth(0.5)
            self.line(36, 804, 559, 804)
            
        # Footer
        self.setStrokeColor(colors.HexColor("#CBD5E1"))
        self.setLineWidth(0.5)
        self.line(36, 32, 559, 32)
        
        footer_left = "Offline UPI — Store & Forward BLE Mesh Payment Engine"
        footer_right = f"Page {self._pageNumber} of {page_count}"
        self.drawString(36, 22, footer_left)
        self.drawRightString(559, 22, footer_right)
        self.restoreState()


def draw_arrow(d, x1, y1, x2, y2, color=colors.HexColor("#334155"), width=1.2):
    """Draws a line with an arrowhead at (x2, y2)."""
    d.add(Line(x1, y1, x2, y2, strokeColor=color, strokeWidth=width))
    import math
    angle = math.atan2(y2 - y1, x2 - x1)
    head_len = 6
    head_angle = math.pi / 7
    ax1 = x2 - head_len * math.cos(angle - head_angle)
    ay1 = y2 - head_len * math.sin(angle - head_angle)
    ax2 = x2 - head_len * math.cos(angle + head_angle)
    ay2 = y2 - head_len * math.sin(angle + head_angle)
    d.add(Polygon([x2, y2, ax1, ay1, ax2, ay2], fillColor=color, strokeColor=color))


def create_dfd0_drawing():
    """Builds crisp vector diagram for DFD Level 0 Context Diagram."""
    d = Drawing(520, 210)
    
    # Background card
    d.add(Rect(0, 0, 520, 210, rx=8, ry=8, fillColor=colors.HexColor("#F8FAFC"), strokeColor=colors.HexColor("#E2E8F0"), strokeWidth=1))
    
    # Sender Phone (Left)
    d.add(Rect(20, 75, 110, 60, rx=4, ry=4, fillColor=colors.HexColor("#EFF6FF"), strokeColor=colors.HexColor("#3B82F6"), strokeWidth=1.5))
    d.add(String(75, 112, "SENDER PHONE", fontName="Helvetica-Bold", fontSize=9, textAnchor="middle", fillColor=colors.HexColor("#1E3A8A")))
    d.add(String(75, 98, "(Offline Payer)", fontName="Helvetica", fontSize=8, textAnchor="middle", fillColor=colors.HexColor("#475569")))
    d.add(String(75, 84, "No Internet Needed", fontName="Helvetica-Oblique", fontSize=7, textAnchor="middle", fillColor=colors.HexColor("#2563EB")))
    
    # Relays (Top Middle)
    d.add(Rect(205, 150, 130, 50, rx=4, ry=4, fillColor=colors.HexColor("#F0FDF4"), strokeColor=colors.HexColor("#10B981"), strokeWidth=1.5))
    d.add(String(270, 180, "BLE MESH RELAYS", fontName="Helvetica-Bold", fontSize=8.5, textAnchor="middle", fillColor=colors.HexColor("#065F46")))
    d.add(String(270, 168, "(Bystander Phones)", fontName="Helvetica", fontSize=8, textAnchor="middle", fillColor=colors.HexColor("#047857")))
    d.add(String(270, 156, "stranger1 -> stranger2", fontName="Helvetica-Oblique", fontSize=7, textAnchor="middle", fillColor=colors.HexColor("#059669")))

    # Central System Process 0.0 (Center)
    d.add(Circle(270, 95, 46, fillColor=colors.HexColor("#FEF3C7"), strokeColor=colors.HexColor("#D97706"), strokeWidth=2))
    d.add(String(270, 112, "0.0", fontName="Helvetica-Bold", fontSize=11, textAnchor="middle", fillColor=colors.HexColor("#92400E")))
    d.add(String(270, 98, "OFFLINE UPI", fontName="Helvetica-Bold", fontSize=8.5, textAnchor="middle", fillColor=colors.HexColor("#92400E")))
    d.add(String(270, 86, "Settlement Engine", fontName="Helvetica-Bold", fontSize=8, textAnchor="middle", fillColor=colors.HexColor("#78350F")))
    d.add(String(270, 74, "(Central Server)", fontName="Helvetica", fontSize=7.5, textAnchor="middle", fillColor=colors.HexColor("#B45309")))

    # Bridge Node (Bottom Middle)
    d.add(Rect(205, 5, 130, 48, rx=4, ry=4, fillColor=colors.HexColor("#ECFEFF"), strokeColor=colors.HexColor("#06B6D4"), strokeWidth=1.5))
    d.add(String(270, 37, "BRIDGE NODE", fontName="Helvetica-Bold", fontSize=8.5, textAnchor="middle", fillColor=colors.HexColor("#155E75")))
    d.add(String(270, 25, "(Roaming to 4G / Wi-Fi)", fontName="Helvetica", fontSize=8, textAnchor="middle", fillColor=colors.HexColor("#0E7490")))
    d.add(String(270, 13, "Ingestion Uplink", fontName="Helvetica-Oblique", fontSize=7, textAnchor="middle", fillColor=colors.HexColor("#0891B2")))

    # Receiver (Right)
    d.add(Rect(400, 75, 105, 60, rx=4, ry=4, fillColor=colors.HexColor("#FDF2F8"), strokeColor=colors.HexColor("#DB2777"), strokeWidth=1.5))
    d.add(String(452, 112, "RECEIVER / PAYEE", fontName="Helvetica-Bold", fontSize=8.5, textAnchor="middle", fillColor=colors.HexColor("#831843")))
    d.add(String(452, 98, "(Merchant / Friend)", fontName="Helvetica", fontSize=8, textAnchor="middle", fillColor=colors.HexColor("#9D174D")))
    d.add(String(452, 84, "SMS Notification", fontName="Helvetica-Oblique", fontSize=7, textAnchor="middle", fillColor=colors.HexColor("#BE185D")))

    # Arrows & Data Flows
    # 1. Sender -> Relays (BLE Gossip)
    draw_arrow(d, 80, 135, 205, 170, color=colors.HexColor("#2563EB"))
    d.add(String(120, 160, "BLE Gossip", fontName="Helvetica-Bold", fontSize=7, fillColor=colors.HexColor("#1E40AF")))

    # 2. Relays -> Bridge (Multi-hop)
    draw_arrow(d, 335, 170, 390, 140, color=colors.HexColor("#059669"))
    d.add(String(345, 172, "Multi-hop", fontName="Helvetica-Bold", fontSize=7, fillColor=colors.HexColor("#065F46")))

    # 3. Bridge -> System (HTTPS Ingest)
    draw_arrow(d, 270, 53, 270, 49, color=colors.HexColor("#0891B2"))
    draw_arrow(d, 300, 53, 290, 60, color=colors.HexColor("#0891B2"))
    d.add(String(325, 45, "HTTPS Ingest", fontName="Helvetica-Bold", fontSize=7, fillColor=colors.HexColor("#0E7490")))

    # 4. Sender -> Engine (Params/PIN offline create)
    draw_arrow(d, 130, 95, 220, 95, color=colors.HexColor("#475569"))
    d.add(String(160, 100, "1. Payment Info", fontName="Helvetica", fontSize=6.5, fillColor=colors.HexColor("#334155")))

    # 5. Engine -> Receiver (Credit notification)
    draw_arrow(d, 316, 95, 400, 95, color=colors.HexColor("#DB2777"))
    d.add(String(332, 100, "6. Credit Alert", fontName="Helvetica-Bold", fontSize=7, fillColor=colors.HexColor("#9D174D")))

    return d


def create_dfd1_drawing():
    """Builds crisp vector diagram for DFD Level 1 Subsystem Decomposition."""
    d = Drawing(520, 230)
    d.add(Rect(0, 0, 520, 230, rx=8, ry=8, fillColor=colors.HexColor("#F8FAFC"), strokeColor=colors.HexColor("#E2E8F0"), strokeWidth=1))
    
    # Process 1.0 (Encrypt)
    d.add(Circle(60, 170, 32, fillColor=colors.HexColor("#EFF6FF"), strokeColor=colors.HexColor("#3B82F6"), strokeWidth=1.5))
    d.add(String(60, 180, "1.0", fontName="Helvetica-Bold", fontSize=9, textAnchor="middle", fillColor=colors.HexColor("#1E3A8A")))
    d.add(String(60, 170, "Payment Create", fontName="Helvetica", fontSize=6.5, textAnchor="middle", fillColor=colors.HexColor("#1E3A8A")))
    d.add(String(60, 160, "& Encrypt", fontName="Helvetica", fontSize=6.5, textAnchor="middle", fillColor=colors.HexColor("#1E3A8A")))

    # Process 2.0 (BLE Mesh)
    d.add(Circle(170, 170, 32, fillColor=colors.HexColor("#F0FDF4"), strokeColor=colors.HexColor("#10B981"), strokeWidth=1.5))
    d.add(String(170, 180, "2.0", fontName="Helvetica-Bold", fontSize=9, textAnchor="middle", fillColor=colors.HexColor("#065F46")))
    d.add(String(170, 170, "BLE Mesh", fontName="Helvetica", fontSize=6.5, textAnchor="middle", fillColor=colors.HexColor("#065F46")))
    d.add(String(170, 160, "Gossip Relay", fontName="Helvetica", fontSize=6.5, textAnchor="middle", fillColor=colors.HexColor("#065F46")))

    # Process 3.0 (Bridge Gateway)
    d.add(Circle(280, 170, 32, fillColor=colors.HexColor("#ECFEFF"), strokeColor=colors.HexColor("#06B6D4"), strokeWidth=1.5))
    d.add(String(280, 180, "3.0", fontName="Helvetica-Bold", fontSize=9, textAnchor="middle", fillColor=colors.HexColor("#155E75")))
    d.add(String(280, 170, "Bridge Ingest", fontName="Helvetica", fontSize=6.5, textAnchor="middle", fillColor=colors.HexColor("#155E75")))
    d.add(String(280, 160, "Gateway", fontName="Helvetica", fontSize=6.5, textAnchor="middle", fillColor=colors.HexColor("#155E75")))

    # Process 4.0 (Crypto & Freshness)
    d.add(Circle(390, 170, 32, fillColor=colors.HexColor("#FEF3C7"), strokeColor=colors.HexColor("#D97706"), strokeWidth=1.5))
    d.add(String(390, 180, "4.0", fontName="Helvetica-Bold", fontSize=9, textAnchor="middle", fillColor=colors.HexColor("#92400E")))
    d.add(String(390, 170, "Crypto Verify &", fontName="Helvetica", fontSize=6.5, textAnchor="middle", fillColor=colors.HexColor("#92400E")))
    d.add(String(390, 160, "Freshness", fontName="Helvetica", fontSize=6.5, textAnchor="middle", fillColor=colors.HexColor("#92400E")))

    # Process 5.0 (Settlement)
    d.add(Circle(465, 70, 32, fillColor=colors.HexColor("#FDF2F8"), strokeColor=colors.HexColor("#DB2777"), strokeWidth=1.5))
    d.add(String(465, 80, "5.0", fontName="Helvetica-Bold", fontSize=9, textAnchor="middle", fillColor=colors.HexColor("#831843")))
    d.add(String(465, 70, "ACID Ledger", fontName="Helvetica", fontSize=6.5, textAnchor="middle", fillColor=colors.HexColor("#831843")))
    d.add(String(465, 60, "Settlement", fontName="Helvetica", fontSize=6.5, textAnchor="middle", fillColor=colors.HexColor("#831843")))

    # Connectors across Top
    draw_arrow(d, 92, 170, 138, 170, color=colors.HexColor("#3B82F6"))
    draw_arrow(d, 202, 170, 248, 170, color=colors.HexColor("#10B981"))
    draw_arrow(d, 312, 170, 358, 170, color=colors.HexColor("#06B6D4"))

    # Down to 5.0
    draw_arrow(d, 405, 140, 445, 95, color=colors.HexColor("#D97706"))

    # Data Stores (Bottom Layer)
    # D1: idempotency_claims
    d.add(Rect(30, 35, 120, 42, rx=3, ry=3, fillColor=colors.HexColor("#FFFFFF"), strokeColor=colors.HexColor("#64748B"), strokeWidth=1.2))
    d.add(Line(30, 77, 30, 35, strokeColor=colors.HexColor("#0EA5E9"), strokeWidth=4))
    d.add(String(38, 62, "D1: idempotency_claims", fontName="Helvetica-Bold", fontSize=7.5, fillColor=colors.HexColor("#0F172A")))
    d.add(String(38, 48, "Atomic SHA-256 Claim", fontName="Helvetica", fontSize=6.5, fillColor=colors.HexColor("#475569")))

    # D2: accounts
    d.add(Rect(175, 35, 115, 42, rx=3, ry=3, fillColor=colors.HexColor("#FFFFFF"), strokeColor=colors.HexColor("#64748B"), strokeWidth=1.2))
    d.add(Line(175, 77, 175, 35, strokeColor=colors.HexColor("#10B981"), strokeWidth=4))
    d.add(String(183, 62, "D2: accounts", fontName="Helvetica-Bold", fontSize=7.5, fillColor=colors.HexColor("#0F172A")))
    d.add(String(183, 48, "Balances & Version Locks", fontName="Helvetica", fontSize=6.5, fillColor=colors.HexColor("#475569")))

    # D3: transactions
    d.add(Rect(315, 35, 115, 42, rx=3, ry=3, fillColor=colors.HexColor("#FFFFFF"), strokeColor=colors.HexColor("#64748B"), strokeWidth=1.2))
    d.add(Line(315, 77, 315, 35, strokeColor=colors.HexColor("#DB2777"), strokeWidth=4))
    d.add(String(323, 62, "D3: transactions", fontName="Helvetica-Bold", fontSize=7.5, fillColor=colors.HexColor("#0F172A")))
    d.add(String(323, 48, "Permanent Audit Ledger", fontName="Helvetica", fontSize=6.5, fillColor=colors.HexColor("#475569")))

    # Arrows to Stores
    draw_arrow(d, 375, 142, 90, 80, color=colors.HexColor("#0EA5E9"))
    d.add(String(170, 115, "claim(hash)", fontName="Helvetica-Bold", fontSize=7, fillColor=colors.HexColor("#0284C7")))

    draw_arrow(d, 455, 45, 290, 52, color=colors.HexColor("#10B981"))
    d.add(String(330, 85, "debit/credit", fontName="Helvetica-Bold", fontSize=7, fillColor=colors.HexColor("#059669")))

    draw_arrow(d, 435, 65, 425, 55, color=colors.HexColor("#DB2777"))

    return d


def create_erd_drawing():
    """Builds crisp vector diagram for Entity-Relationship Diagram."""
    d = Drawing(520, 200)
    d.add(Rect(0, 0, 520, 200, rx=8, ry=8, fillColor=colors.HexColor("#F8FAFC"), strokeColor=colors.HexColor("#E2E8F0"), strokeWidth=1))

    # Entity 1: ACCOUNTS (Left)
    d.add(Rect(20, 60, 140, 120, rx=4, ry=4, fillColor=colors.HexColor("#EFF6FF"), strokeColor=colors.HexColor("#2563EB"), strokeWidth=1.5))
    d.add(Rect(20, 155, 140, 25, rx=4, ry=4, fillColor=colors.HexColor("#2563EB"), strokeColor=colors.HexColor("#2563EB"), strokeWidth=1))
    d.add(String(90, 163, "ACCOUNTS", fontName="Helvetica-Bold", fontSize=9, textAnchor="middle", fillColor=colors.white))
    d.add(String(28, 140, "PK  vpa (TEXT)", fontName="Helvetica-Bold", fontSize=7.5, fillColor=colors.HexColor("#1E3A8A")))
    d.add(String(28, 122, "      holder_name (TEXT)", fontName="Helvetica", fontSize=7.5, fillColor=colors.HexColor("#1E293B")))
    d.add(String(28, 104, "      balance (REAL)", fontName="Helvetica", fontSize=7.5, fillColor=colors.HexColor("#1E293B")))
    d.add(String(28, 86, "      version (INT >= 1)", fontName="Helvetica-Bold", fontSize=7.5, fillColor=colors.HexColor("#2563EB")))
    d.add(String(28, 68, "      *Optimistic Lock", fontName="Helvetica-Oblique", fontSize=6.5, fillColor=colors.HexColor("#64748B")))

    # Entity 2: IDEMPOTENCY_CLAIMS (Top Right)
    d.add(Rect(340, 105, 160, 80, rx=4, ry=4, fillColor=colors.HexColor("#F0FDF4"), strokeColor=colors.HexColor("#10B981"), strokeWidth=1.5))
    d.add(Rect(340, 160, 160, 25, rx=4, ry=4, fillColor=colors.HexColor("#10B981"), strokeColor=colors.HexColor("#10B981"), strokeWidth=1))
    d.add(String(420, 168, "IDEMPOTENCY_CLAIMS", fontName="Helvetica-Bold", fontSize=8.5, textAnchor="middle", fillColor=colors.white))
    d.add(String(348, 144, "PK  packet_hash (TEXT)", fontName="Helvetica-Bold", fontSize=7.5, fillColor=colors.HexColor("#065F46")))
    d.add(String(348, 128, "      claimed_at (TEXT)", fontName="Helvetica", fontSize=7.5, fillColor=colors.HexColor("#1E293B")))
    d.add(String(348, 112, "      status (TEXT)", fontName="Helvetica", fontSize=7.5, fillColor=colors.HexColor("#1E293B")))

    # Entity 3: TRANSACTIONS (Bottom Center-Right)
    d.add(Rect(200, 15, 190, 125, rx=4, ry=4, fillColor=colors.HexColor("#FDF2F8"), strokeColor=colors.HexColor("#DB2777"), strokeWidth=1.5))
    d.add(Rect(200, 115, 190, 25, rx=4, ry=4, fillColor=colors.HexColor("#DB2777"), strokeColor=colors.HexColor("#DB2777"), strokeWidth=1))
    d.add(String(295, 123, "TRANSACTIONS (Ledger)", fontName="Helvetica-Bold", fontSize=9, textAnchor="middle", fillColor=colors.white))
    d.add(String(208, 102, "PK   id (INT AUTOINC)", fontName="Helvetica-Bold", fontSize=7.5, fillColor=colors.HexColor("#831843")))
    d.add(String(208, 88, "FK   packet_hash (TEXT)", fontName="Helvetica-Bold", fontSize=7.5, fillColor=colors.HexColor("#065F46")))
    d.add(String(208, 74, "FK   sender_vpa (TEXT)", fontName="Helvetica-Bold", fontSize=7.5, fillColor=colors.HexColor("#1E3A8A")))
    d.add(String(208, 60, "FK   receiver_vpa (TEXT)", fontName="Helvetica-Bold", fontSize=7.5, fillColor=colors.HexColor("#1E3A8A")))
    d.add(String(208, 46, "       amount (REAL)", fontName="Helvetica", fontSize=7.5, fillColor=colors.HexColor("#1E293B")))
    d.add(String(208, 32, "       status, bridge_id, hops", fontName="Helvetica", fontSize=7, fillColor=colors.HexColor("#475569")))
    d.add(String(208, 20, "       settled_at (TEXT)", fontName="Helvetica", fontSize=7, fillColor=colors.HexColor("#475569")))

    # Relationships Lines
    # ACCOUNTS -> TRANSACTIONS (1 to N)
    draw_arrow(d, 160, 110, 200, 85, color=colors.HexColor("#2563EB"))
    d.add(String(165, 102, "1", fontName="Helvetica-Bold", fontSize=7, fillColor=colors.HexColor("#2563EB")))
    d.add(String(190, 75, "N", fontName="Helvetica-Bold", fontSize=7, fillColor=colors.HexColor("#2563EB")))

    # IDEMPOTENCY_CLAIMS -> TRANSACTIONS (1 to 0..1)
    draw_arrow(d, 370, 105, 350, 75, color=colors.HexColor("#10B981"))
    d.add(String(375, 95, "1", fontName="Helvetica-Bold", fontSize=7, fillColor=colors.HexColor("#10B981")))
    d.add(String(355, 65, "0..1", fontName="Helvetica-Bold", fontSize=7, fillColor=colors.HexColor("#10B981")))

    return d


def build_dfd_pdf(destination_path):
    doc = SimpleDocTemplate(
        destination_path,
        pagesize=A4,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36
    )

    styles = getSampleStyleSheet()
    
    primary_color = colors.HexColor("#0F172A")
    accent_color = colors.HexColor("#1E3A8A")
    body_color = colors.HexColor("#1E293B")
    table_header_bg = colors.HexColor("#1E293B")
    border_color = colors.HexColor("#CBD5E1")
    light_row = colors.HexColor("#F8FAFC")

    title_style = ParagraphStyle(
        'MainTitle',
        fontName='Helvetica-Bold',
        fontSize=18,
        leading=22,
        textColor=primary_color,
        spaceAfter=3
    )

    subtitle_style = ParagraphStyle(
        'Subtitle',
        fontName='Helvetica',
        fontSize=10,
        leading=13,
        textColor=colors.HexColor("#64748B"),
        spaceAfter=12
    )

    section_heading = ParagraphStyle(
        'SecHeading',
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=15,
        textColor=accent_color,
        spaceBefore=8,
        spaceAfter=5
    )

    body_style = ParagraphStyle(
        'BodyText',
        fontName='Helvetica',
        fontSize=8.5,
        leading=11.5,
        textColor=body_color,
        spaceAfter=4
    )

    th_style = ParagraphStyle(
        'TH',
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=10,
        textColor=colors.white
    )

    td_style = ParagraphStyle(
        'TD',
        fontName='Helvetica',
        fontSize=7.5,
        leading=9.5,
        textColor=body_color
    )

    td_bold = ParagraphStyle(
        'TDBold',
        fontName='Helvetica-Bold',
        fontSize=7.5,
        leading=9.5,
        textColor=body_color
    )

    story = []

    # ================= PAGE 1: COVER & DFD LEVEL 0 =================
    story.append(Paragraph("Offline UPI Payment & Settlement System", title_style))
    story.append(Paragraph("System Architecture, Data Flow Diagrams (Level 0, 1, 2) and Entity-Relationship (ER) Specifications", subtitle_style))
    story.append(HRFlowable(width="100%", thickness=1, color=border_color, spaceAfter=8))

    story.append(Paragraph("1. DFD Level 0 — Context Diagram", section_heading))
    story.append(Paragraph("The Level 0 Context Diagram depicts the primary system boundary, showing external entities interacting with the central offline UPI engine without exposing internal storage mechanisms.", body_style))
    story.append(Spacer(1, 4))
    
    # Add Vector Drawing of DFD Level 0
    story.append(create_dfd0_drawing())
    story.append(Spacer(1, 8))

    # Flow Table for DFD Level 0
    dfd0_data = [
        [Paragraph("Flow ID", th_style), Paragraph("Source Entity", th_style), Paragraph("Destination", th_style), Paragraph("Data Carried", th_style), Paragraph("Security / Mechanism", th_style)],
        [Paragraph("1", td_bold), Paragraph("Sender Phone", td_style), Paragraph("0.0 Client Module", td_style), Paragraph("VPA, Amount, PIN, Nonce", td_style), Paragraph("Entered 100% offline", td_style)],
        [Paragraph("2", td_bold), Paragraph("0.0 Client Module", td_style), Paragraph("Sender Storage", td_style), Paragraph("Encrypted MeshPacket", td_style), Paragraph("RSA-2048-OAEP + AES-GCM", td_style)],
        [Paragraph("3", td_bold), Paragraph("Sender Phone", td_style), Paragraph("BLE Relays", td_style), Paragraph("Ciphertext broadcast", td_style), Paragraph("BLE Advertising / GATT", td_style)],
        [Paragraph("4", td_bold), Paragraph("BLE Relays", td_style), Paragraph("Bridge Node", td_style), Paragraph("Relayed MeshPacket", td_style), Paragraph("Store-and-forward (hop count)", td_style)],
        [Paragraph("5", td_bold), Paragraph("Bridge Node", td_style), Paragraph("0.0 Central Server", td_style), Paragraph("Ciphertext + Bridge ID", td_style), Paragraph("HTTPS POST /api/bridge/ingest", td_style)],
        [Paragraph("6", td_bold), Paragraph("0.0 Central Server", td_style), Paragraph("Receiver / Payee", td_style), Paragraph("Credit SMS / Push Alert", td_style), Paragraph("Telecom SMS / Bank Push", td_style)],
        [Paragraph("7", td_bold), Paragraph("0.0 Central Server", td_style), Paragraph("Bridge Node", td_style), Paragraph("Status (SETTLED/DUP)", td_style), Paragraph("HTTP 200 / 400 response", td_style)],
    ]
    t0 = Table(dfd0_data, colWidths=[35, 80, 85, 140, 183])
    t0.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), table_header_bg),
        ('GRID', (0, 0), (-1, -1), 0.5, border_color),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, light_row]),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    story.append(t0)

    story.append(PageBreak())

    # ================= PAGE 2: DFD LEVEL 1 =================
    story.append(Paragraph("2. DFD Level 1 — Subsystem Data Flow Decomposition", section_heading))
    story.append(Paragraph("Decomposes the system into 5 modular processes across client cryptography, distributed mesh gossip routing, bridge ingestion, and central bank ACID ledger updates.", body_style))
    story.append(Spacer(1, 4))

    story.append(create_dfd1_drawing())
    story.append(Spacer(1, 8))

    dfd1_data = [
        [Paragraph("Process", th_style), Paragraph("Process Name", th_style), Paragraph("Input Data", th_style), Paragraph("Output Data", th_style), Paragraph("Primary Function", th_style)],
        [Paragraph("1.0", td_bold), Paragraph("Payment Creation & Encrypt", td_style), Paragraph("User input (Amt, PIN)", td_style), Paragraph("Signed MeshPacket", td_style), Paragraph("Hybrid encryption with Server's RSA Public Key.", td_style)],
        [Paragraph("2.0", td_bold), Paragraph("BLE Gossip Routing", td_style), Paragraph("MeshPacket (TTL=5)", td_style), Paragraph("Relayed packet (TTL--)", td_style), Paragraph("Store-and-forward hopping across bystander devices.", td_style)],
        [Paragraph("3.0", td_bold), Paragraph("Bridge Ingest Gateway", td_style), Paragraph("Cached mesh packets", td_style), Paragraph("HTTPS Ingest Request", td_style), Paragraph("Uploads ciphertext when device connects to 4G/Wi-Fi.", td_style)],
        [Paragraph("4.0", td_bold), Paragraph("Crypto Verification & Deduplication", td_style), Paragraph("Ingest payload", td_style), Paragraph("Decrypted instruction", td_style), Paragraph("Enforces atomic SHA-256 claim, RSA decrypt, GCM tag, and freshness.", td_style)],
        [Paragraph("5.0", td_bold), Paragraph("ACID Ledger Settlement", td_style), Paragraph("Valid instruction", td_style), Paragraph("Ledger record & SMS", td_style), Paragraph("Executes atomic debit, credit, optimistic lock and logs audit trail.", td_style)],
    ]
    t1 = Table(dfd1_data, colWidths=[40, 110, 100, 105, 168])
    t1.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), table_header_bg),
        ('GRID', (0, 0), (-1, -1), 0.5, border_color),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, light_row]),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    story.append(t1)

    story.append(PageBreak())

    # ================= PAGE 3: DFD LEVEL 2 & ER DIAGRAM =================
    story.append(Paragraph("3. DFD Level 2 — Ingestion & Settlement Pipeline", section_heading))
    story.append(Paragraph("Details the exact atomic execution path inside <code>/api/bridge/ingest</code> on the central server:", body_style))
    story.append(Spacer(1, 2))

    p2_points = [
        "<b>Step 4.1 (SHA-256 Digest):</b> Central engine hashes incoming ciphertext to produce a 64-char hex digest.",
        "<b>Step 4.2 (Atomic Deduplication Gate):</b> Executes atomic <code>INSERT INTO idempotency_claims</code>. If hash exists, returns <code>DUPLICATE_DROPPED</code> immediately without expensive cryptographic compute.",
        "<b>Step 4.3 (Hybrid Decryption & Authentication):</b> Server unwraps AES key using RSA-2048-OAEP Private Key. Decrypts with AES-256-GCM. 128-bit authentication tag guarantees 0-bit tampering.",
        "<b>Step 4.4 (Sliding Freshness Window):</b> Rejects payments with <code>signedAt</code> older than 24 hours (prevents long-term replay).",
        "<b>Step 5.1 & 5.2 (Optimistic Concurrency Balance Updates):</b> Atomically updates sender balance with <code>WHERE vpa=? AND version=?</code>.",
        "<b>Step 5.3 (Ledger Commit):</b> Appends immutable audit entry to <code>transactions</code>."
    ]
    for p in p2_points:
        story.append(Paragraph(f"• {p}", td_style))
    story.append(Spacer(1, 6))

    story.append(Paragraph("4. Entity-Relationship (ER) Diagram & Schema", section_heading))
    story.append(Paragraph("Relational model enforced in SQLite (<code>upi.db</code>) with primary keys, foreign keys, and version locks.", body_style))
    story.append(Spacer(1, 4))

    story.append(create_erd_drawing())
    story.append(Spacer(1, 8))

    # ER Table
    erd_data = [
        [Paragraph("Table Name", th_style), Paragraph("Primary Key", th_style), Paragraph("Foreign Keys", th_style), Paragraph("Attributes & Concurrency Role", th_style)],
        [Paragraph("accounts", td_bold), Paragraph("vpa (TEXT)", td_style), Paragraph("None", td_style), Paragraph("holder_name, balance (REAL), version (INT). Version provides optimistic locking against balance races.", td_style)],
        [Paragraph("idempotency_claims", td_bold), Paragraph("packet_hash (TEXT)", td_style), Paragraph("None", td_style), Paragraph("claimed_at (TEXT), status (TEXT). Acts as atomic putIfAbsent deduplication gate.", td_style)],
        [Paragraph("transactions", td_bold), Paragraph("id (INTEGER AUTOINC)", td_style), Paragraph("packet_hash, sender_vpa, receiver_vpa", td_style), Paragraph("amount (REAL), status, bridge_id, hop_count, settled_at. Permanent audit trail.", td_style)],
    ]
    ter = Table(erd_data, colWidths=[95, 80, 110, 238])
    ter.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), table_header_bg),
        ('GRID', (0, 0), (-1, -1), 0.5, border_color),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, light_row]),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    story.append(ter)

    doc.build(story, canvasmaker=NumberedCanvas)
    print(f"PDF built successfully at: {destination_path}")

if __name__ == '__main__':
    downloads_dir = os.path.join(os.environ.get('USERPROFILE', 'C:\\Users\\Sagar'), 'Downloads')
    target_pdf = os.path.join(downloads_dir, 'Offline_UPI_DFD_and_ER_Diagrams.pdf')
    local_pdf = os.path.abspath('Offline_UPI_DFD_and_ER_Diagrams.pdf')
    
    build_dfd_pdf(local_pdf)
    shutil.copy(local_pdf, target_pdf)
    print(f"Copied to Downloads folder: {target_pdf}")
