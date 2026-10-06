import os
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether, HRFlowable
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
            self.drawString(36, 810, "Project Proposal / Synopsis 2023-24")
            self.drawRightString(559, 810, "Offline UPI (Python & SQLite)")
            self.setStrokeColor(colors.HexColor("#CBD5E1"))
            self.setLineWidth(0.5)
            self.line(36, 804, 559, 804)
            
        # Footer
        self.setStrokeColor(colors.HexColor("#CBD5E1"))
        self.setLineWidth(0.5)
        self.line(36, 32, 559, 32)
        
        footer_left = "Department of Computer Science & Engineering"
        footer_right = f"Page {self._pageNumber} of {page_count}"
        self.drawString(36, 22, footer_left)
        self.drawRightString(559, 22, footer_right)
        self.restoreState()

def build_pdf(filename):
    doc = SimpleDocTemplate(
        filename,
        pagesize=A4,
        leftMargin=36,
        rightMargin=36,
        topMargin=40,
        bottomMargin=40
    )
    
    styles = getSampleStyleSheet()
    
    primary_color = colors.HexColor("#0F172A")    # Deep Navy
    accent_color = colors.HexColor("#1E3A8A")     # Royal Blue
    dark_neutral = colors.HexColor("#1E293B")     # Charcoal body text
    light_bg = colors.HexColor("#F8FAFC")         # Zebra row
    header_bg = colors.HexColor("#1E293B")        # Table Header
    border_color = colors.HexColor("#94A3B8")      # Crisp table border
    
    title_style = ParagraphStyle(
        'DocTitle', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=17, leading=21,
        textColor=primary_color, alignment=1, spaceAfter=3
    )
    
    session_style = ParagraphStyle(
        'DocSession', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=12, leading=15,
        textColor=accent_color, alignment=1, spaceAfter=10
    )
    
    section_heading = ParagraphStyle(
        'SectionHeading', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=11, leading=14,
        textColor=primary_color, spaceBefore=8, spaceAfter=5, keepWithNext=True
    )
    
    body_style = ParagraphStyle(
        'BodyTextCustom', parent=styles['Normal'],
        fontName='Helvetica', fontSize=8.5, leading=12,
        textColor=dark_neutral, spaceAfter=3
    )
    
    bullet_style = ParagraphStyle(
        'BulletCustom', parent=body_style,
        leftIndent=14, firstLineIndent=-9, spaceAfter=2.5
    )
    
    table_cell = ParagraphStyle(
        'TableCell', parent=styles['Normal'],
        fontName='Helvetica', fontSize=8, leading=10.5,
        textColor=dark_neutral
    )
    
    table_cell_bold = ParagraphStyle('TableCellBold', parent=table_cell, fontName='Helvetica-Bold')
    
    table_header = ParagraphStyle(
        'TableHeader', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=8, leading=10.5,
        textColor=colors.white, alignment=1
    )
    
    story = []
    
    # -------------------------------------------------------------
    # Title & Academic Session
    # -------------------------------------------------------------
    story.append(Paragraph("Project Proposal/Synopsis", title_style))
    story.append(Paragraph("2023-24", session_style))
    story.append(HRFlowable(width="100%", thickness=1.2, color=accent_color, spaceBefore=0, spaceAfter=8))
    
    # -------------------------------------------------------------
    # 1. Team Details
    # -------------------------------------------------------------
    story.append(Paragraph("Team Details", section_heading))
    
    team_data = [
        [
            Paragraph("<b>S.No</b>", table_header),
            Paragraph("<b>Roll Number</b>", table_header),
            Paragraph("<b>Name</b>", table_header),
            Paragraph("<b>Email</b>", table_header),
            Paragraph("<b>Contact number</b>", table_header)
        ],
        [
            Paragraph("1", table_cell),
            Paragraph("[Roll No 1]", table_cell),
            Paragraph("<b>Sagar [Full Name] (TL)</b>", table_cell),
            Paragraph("sagar[email]@domain.com", table_cell),
            Paragraph("+91-XXXXXXXXXX", table_cell)
        ],
        [
            Paragraph("2", table_cell),
            Paragraph("[Roll No 2]", table_cell),
            Paragraph("[Team Member 2 Name]", table_cell),
            Paragraph("member2[email]@domain.com", table_cell),
            Paragraph("+91-XXXXXXXXXX", table_cell)
        ],
        [
            Paragraph("3", table_cell),
            Paragraph("[Roll No 3]", table_cell),
            Paragraph("[Team Member 3 Name]", table_cell),
            Paragraph("member3[email]@domain.com", table_cell),
            Paragraph("+91-XXXXXXXXXX", table_cell)
        ]
    ]
    
    team_table = Table(team_data, colWidths=[32, 90, 160, 145, 96])
    team_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), header_bg),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3.5),
        ('TOPPADDING', (0, 0), (-1, -1), 3.5),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('GRID', (0, 0), (-1, -1), 0.5, border_color),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, light_bg])
    ]))
    story.append(team_table)
    story.append(Spacer(1, 8))
    
    # -------------------------------------------------------------
    # 2. Project Details
    # -------------------------------------------------------------
    story.append(Paragraph("Project Details", section_heading))
    
    story.append(Paragraph("<b>Title:</b> Offline UPI: Secure Multi-Hop BLE Mesh Routed Payment and Settlement Engine", body_style))
    story.append(Spacer(1, 2))
    
    tech_str = (
        "<b>Technologies to be used:</b><br/>"
        "• <b>Backend Framework & APIs:</b> Python 3, Flask Web Framework, RESTful API architecture.<br/>"
        "• <b>Database & Ledger:</b> SQLite3 (<code>upi.db</code>) with ACID Transactions and Optimistic Version Locking.<br/>"
        "• <b>Frontend & Dashboard:</b> HTML5, Modern CSS3 (Dark Theme UI), Vanilla JavaScript (Fetch API).<br/>"
        "• <b>Cryptography & Security:</b> Python <code>cryptography</code> library (RSA-2048-OAEP, AES-256-GCM, SHA-256 Hashing).<br/>"
        "• <b>Distributed Mesh Simulation:</b> Python Store-and-Forward Gossip Engine, Hop Decrement, Opportunistic Bridge Ingestion.<br/>"
        "• <b>Testing & Quality Assurance:</b> Python standard <code>unittest</code> suite (Crypto roundtrip, Tamper rejection, Exact-once settlement races)."
    )
    story.append(Paragraph(tech_str, body_style))
    story.append(Spacer(1, 4))
    
    story.append(Paragraph("<b>Brief Description of the Project (Point-wise):</b>", body_style))
    
    points = [
        "<b>Problem Statement:</b> Standard UPI payments fail completely when users are in offline dead-zones (underground basements, parking lots, transits, remote rural locations, or disaster relief zones) due to absence of active mobile data or Wi-Fi.",
        "<b>Multi-Hop Mesh Gossip Architecture:</b> This project implements an offline peer-to-peer store-and-forward mesh protocol. An offline sender creates an encrypted payment packet and broadcasts it over simulated Bluetooth Low Energy (BLE) gossip. Intermediate bystander phones act as passive relay nodes, passing the packet hop-by-hop without requiring internet until an opportunistic Bridge Node with 4G/Wi-Fi uploads it to the backend.",
        "<b>Zero-Trust Hybrid Cryptography:</b> Intermediary phones are untrusted and cannot read or tamper with transaction details. The payment instruction is encrypted using <b>AES-256-GCM</b>, and the session AES key is enveloped using the Server's <b>RSA-2048-OAEP</b> public key. Any alteration in ciphertext invalidates the 128-bit authentication tag, causing immediate cryptographic rejection at the server.",
        "<b>Idempotency & Deduplication Engine:</b> If multiple bridge nodes upload the same broadcasted packet concurrently, SQLite's primary key constraint on SHA-256 ciphertext hash acts as an atomic <code>putIfAbsent</code> claim. The first upload settles (<code>SETTLED</code>); subsequent duplicate uploads are safely discarded (<code>DUPLICATE_DROPPED</code>) preventing double-spending.",
        "<b>Freshness & Nonce Verification:</b> Each packet includes a cryptographically generated UUIDv4 nonce and timestamp. A strict 24-hour freshness sliding window prevents replay attacks.",
        "<b>ACID Ledger Settlement in SQLite:</b> Upon successful decryption and validation, an atomic SQLite transaction debits the sender's account, credits the receiver, increments version locks, and logs an immutable audit trail.",
        "<b>Interactive Web Dashboard:</b> A clean Flask-powered web dashboard enables examiners to live-test the 4-step workflow: creating offline payments, stepping through BLE gossip hops, uploading through the 4G bridge, injecting tamper attacks, and inspecting live SQLite tables."
    ]
    for pt in points:
        story.append(Paragraph(f"• {pt}", bullet_style))
    story.append(Spacer(1, 5))
    
    # Questions and Clarifications
    q_data = [
        ("Whether compared with any existing system: (Give URL /link or citation)",
         "<b>Yes.</b> Compared with:<br/>"
         "1. <b>NPCI UPI 123PAY (*99# USSD/IVR):</b> Requires active telecom cellular carrier service for voice/SMS; fails in RF-shielded basements and zero-signal deadzones (https://www.npci.org.in/what-we-do/upi-123pay/product-overview).<br/>"
         "2. <b>RBI Offline Payment Framework for Small Value Transactions:</b> Limited to proximity NFC / hardware-secure-element proximity wallets (https://www.rbi.org.in/Scripts/NotificationUser.aspx?Id=12215&Mode=0).<br/>"
         "3. <b>Delay-Tolerant Networking (DTN / RFC 4838):</b> Multi-hop store-and-forward gossip protocols across challenged networks (Fall, K., RFC 4838)."),
        ("Whether discussed with any Faculty Member (NAME):",
         "<b>Yes.</b> Discussed with <b>[Prof. / Dr. Faculty Mentor Name]</b>, Department of Computer Science & Engineering."),
        ("Whether proposed work is extension of internship work:",
         "<b>No.</b> It is an original, self-initiated Capstone Research & Engineering Project."),
        ("Any previous work with proposed technologies:",
         "<b>Yes.</b> Team members have completed coursework and practical lab projects in Python programming, Flask web frameworks, SQLite relational databases, and Applied Cryptography."),
        ("Whether crude DFD/ ERD are prepared:",
         "<b>Yes.</b> Level 0, Level 1, and Level 2 Data Flow Diagrams (DFDs) along with comprehensive Entity-Relationship Diagrams (ERDs) detailing Account, MeshPacket, IdempotencyClaim, and Transaction models are prepared.")
    ]
    for q, ans in q_data:
        story.append(Paragraph(f"<b>{q}</b>", body_style))
        story.append(Paragraph(ans, ParagraphStyle('Ans', parent=body_style, leftIndent=12, spaceAfter=4)))
        
    story.append(Spacer(1, 6))
    
    # -------------------------------------------------------------
    # 3. Planning Details Table
    # -------------------------------------------------------------
    story.append(Paragraph("Planning Details (July-23 to Apr-24)", section_heading))
    
    plan_data = [
        [Paragraph("<b>Phase</b>", table_header), Paragraph("<b>From</b>", table_header), Paragraph("<b>To</b>", table_header)],
        [Paragraph("Literature Survey", table_cell_bold), Paragraph("17 July 2023", table_cell), Paragraph("31 August 2023", table_cell)],
        [Paragraph("Design (Architecture, DFD, Crypto Schemas)", table_cell_bold), Paragraph("01 September 2023", table_cell), Paragraph("15 October 2023", table_cell)],
        [Paragraph("Implementation-1 (Python Cryptography & SQLite DB Setup)", table_cell_bold), Paragraph("16 October 2023", table_cell), Paragraph("30 November 2023", table_cell)],
        [Paragraph("Implementation-2 (Mesh Simulation Engine & Flask Ingestion API)", table_cell_bold), Paragraph("01 December 2023", table_cell), Paragraph("20 January 2024", table_cell)],
        [Paragraph("Implementation-3 (Idempotency Claim Engine & Web Dashboard)", table_cell_bold), Paragraph("21 January 2024", table_cell), Paragraph("10 March 2024", table_cell)],
        [Paragraph("Testing (Concurrency, Tamper Injection & Unittest Suite)", table_cell_bold), Paragraph("11 March 2024", table_cell), Paragraph("10 April 2024", table_cell)],
        [Paragraph("<b>Submission</b>", table_cell_bold), Paragraph("<b>15 April 2024</b>", table_cell), Paragraph("<b>15 April 2024</b>", table_cell)]
    ]
    
    plan_table = Table(plan_data, colWidths=[243, 140, 140])
    plan_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), header_bg),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3.5),
        ('TOPPADDING', (0, 0), (-1, -1), 3.5),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('GRID', (0, 0), (-1, -1), 0.5, border_color),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, light_bg]),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor("#E2E8F0"))
    ]))
    story.append(plan_table)
    story.append(Spacer(1, 14))
    
    # -------------------------------------------------------------
    # 4. Work Distribution Plan
    # -------------------------------------------------------------
    story.append(KeepTogether([
        Paragraph("WORK DISTRIBUTION PLAN", section_heading),
        Spacer(1, 2)
    ]))
    
    hdr_info = (
        "<b>PROJECT ID: -</b> [Pending Acceptance]&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;"
        "<b>TEAM LEADER: -</b> Sagar [Full Name]&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;"
        "<b>PROJECT TITLE: -</b> Offline UPI: Secure Multi-Hop BLE Mesh Routed Payment & Settlement Engine"
    )
    story.append(Paragraph(hdr_info, body_style))
    story.append(Spacer(1, 5))
    
    work_data = [
        [
            Paragraph("<b>S.No</b>", table_header),
            Paragraph("<b>MODULE NAME(S)</b>", table_header),
            Paragraph("<b>FUNCTIONALITIES</b>", table_header),
            Paragraph("<b>TECHNOLOGIES USED</b>", table_header),
            Paragraph("<b>TEAM MEMBER</b>", table_header)
        ],
        [
            Paragraph("1.", table_cell),
            Paragraph("<b>Hybrid Cryptographic & Key Management Engine</b>", table_cell),
            Paragraph("• Server RSA-2048 keypair generation and management.<br/>"
                      "• Hybrid RSA-2048-OAEP key wrapping & AES-256-GCM cipher engine.<br/>"
                      "• 128-bit authentication tag verification & tampering rejection.<br/>"
                      "• SHA-256 packet hashing and nonce generation.", table_cell),
            Paragraph("Python 3, <code>cryptography</code>, RSA-2048, AES-256-GCM, SHA-256", table_cell),
            Paragraph("<b>Sagar (TL)</b>", table_cell)
        ],
        [
            Paragraph("2.", table_cell),
            Paragraph("<b>Bridge Ingestion & Idempotent Settlement Service</b>", table_cell),
            Paragraph("• Flask Bridge ingestion API (<code>/api/bridge/ingest</code>).<br/>"
                      "• Atomic SQLite primary key claim cache for deduplication.<br/>"
                      "• Settlement resolver ensuring exact-once balance debit/credit.<br/>"
                      "• Account balance manager with optimistic version locks.", table_cell),
            Paragraph("Python 3, Flask, SQLite3, ACID Transactions", table_cell),
            Paragraph("<b>Sagar (TL)</b>", table_cell)
        ],
        [
            Paragraph("3.", table_cell),
            Paragraph("<b>P2P BLE Mesh Simulation & Gossip Routing Engine</b>", table_cell),
            Paragraph("• Virtual device topology state modeling (offline phones vs. bridge node).<br/>"
                      "• Store-and-forward Delay Tolerant Gossip algorithm.<br/>"
                      "• Packet Time-To-Live (TTL) decrement & multi-hop counter.<br/>"
                      "• Opportunistic bridge synchronization and flush endpoints.", table_cell),
            Paragraph("Python 3, Distributed Systems Simulation Logic", table_cell),
            Paragraph("<b>[Team Member 2]</b>", table_cell)
        ],
        [
            Paragraph("4.", table_cell),
            Paragraph("<b>Client-Side Packet Injection & Demo Workflow</b>", table_cell),
            Paragraph("• Offline simulated sender device packet assembler.<br/>"
                      "• PIN hashing and client payment instruction validation.<br/>"
                      "• Interactive 4-step execution flow controller (Create → Gossip → Connect → Flush).<br/>"
                      "• Mesh topology state reset and test-run initialization.", table_cell),
            Paragraph("Python 3, Flask Endpoints, JavaScript", table_cell),
            Paragraph("<b>[Team Member 2]</b>", table_cell)
        ],
        [
            Paragraph("5.", table_cell),
            Paragraph("<b>Interactive Dashboard & Mesh Visualizer UI</b>", table_cell),
            Paragraph("• Real-time graphical mesh topology component.<br/>"
                      "• Visual device status cards with held packet counters and live connection badges.<br/>"
                      "• Interactive simulation control panel.<br/>"
                      "• Dark-mode responsive UI and navigation bar with live telemetry logs.", table_cell),
            Paragraph("HTML5, Modern CSS3, Vanilla JavaScript (Fetch API)", table_cell),
            Paragraph("<b>[Team Member 3]</b>", table_cell)
        ],
        [
            Paragraph("6.", table_cell),
            Paragraph("<b>Ledger Audit Interface & Automated Test Suite</b>", table_cell),
            Paragraph("• Live double-entry Bank Accounts and Transaction Ledger tables.<br/>"
                      "• Real-time settlement status badges (<code>SETTLED</code>, <code>DUPLICATE_DROPPED</code>, <code>INVALID</code>).<br/>"
                      "• Automated Python <code>unittest</code> suite covering crypto symmetry, tampering, and concurrent bridge upload races.", table_cell),
            Paragraph("Python <code>unittest</code>, SQLite3, HTML5/JS", table_cell),
            Paragraph("<b>[Team Member 3]</b>", table_cell)
        ]
    ]
    
    work_table = Table(work_data, colWidths=[24, 110, 205, 104, 80])
    work_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), header_bg),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3.5),
        ('TOPPADDING', (0, 0), (-1, -1), 3.5),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('GRID', (0, 0), (-1, -1), 0.5, border_color),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, light_bg])
    ]))
    story.append(work_table)
    story.append(Spacer(1, 8))
    
    reminders = (
        "<b>Remember:</b><br/>"
        "• Permanent PROJECT ID would be provided only after acceptance of proposal.<br/>"
        "• If more than one person is allocated on a module, it should be mentioned who is dealing with which functionalities of the module.<br/>"
        "• Create this distribution PLAN in detail.<br/>"
        "• Distribution of workload should be balanced among team members."
    )
    story.append(Paragraph(reminders, ParagraphStyle('Reminders', parent=body_style, fontSize=8, leading=11, textColor=colors.HexColor("#475569"))))
    
    doc.build(story, canvasmaker=NumberedCanvas)
    print(f"Successfully generated: {filename}")

if __name__ == '__main__':
    target_path = os.path.abspath(os.path.join(os.getcwd(), 'UPI_Offline_Project_Synopsis_2023-24.pdf'))
    build_pdf(target_path)
