"""
Enhanced Document Generator for Health Claims Accelerator v2.
Generates realistic discharge summaries (PDF) and hospital bills (PDF/JPG)
that replicate real hospital documents for the Document Intelligence Agent.

Run AFTER generate_synthetic_data.py — it reads the generated CSVs to
produce matching realistic PDF documents in:
  data/raw/unstructured/  — discharge summary PDFs
  data/raw/bills/         — hospital bill PDFs/JPGs

Usage:
    python data/generate_enhanced_documents.py [--num-discharges 50] [--num-bills 50]

Author: SNS Square | Version: 2.1
"""

import os
import csv
import random
import argparse
from datetime import datetime, timedelta
from typing import Optional


# =========================================================================
# Helper: ensure required libs are installed
# =========================================================================
def _ensure_deps():
    missing = []
    try:
        import fpdf
    except ImportError:
        missing.append("fpdf2")
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        missing.append("Pillow")
    if missing:
        print(f"Missing dependencies: {', '.join(missing)}")
        print("Install with: pip install " + " ".join(missing))
        exit(1)


_ensure_deps()

from fpdf import FPDF
from fpdf.enums import XPos, YPos
from PIL import Image, ImageDraw, ImageFont

# =========================================================================
# Controlled vocabularies — match generate_synthetic_data.py
# =========================================================================

HOSPITALS = [
    {"hospital_id": "HOSP-001", "hospital_name": "Apollo Hospital Coimbatore", "tier": "TIER_1", "address": "15, Hospital Road, Coimbatore - 641037"},
    {"hospital_id": "HOSP-002", "hospital_name": "Fortis Healthcare Mumbai", "tier": "TIER_1", "address": "Mulund Goregaon Link Rd, Mumbai - 400078"},
    {"hospital_id": "HOSP-003", "hospital_name": "Max Super Speciality Delhi", "tier": "TIER_1", "address": "2, Press Enclave Road, Saket, Delhi - 110017"},
    {"hospital_id": "HOSP-004", "hospital_name": "AIIMS New Delhi", "tier": "GOVT", "address": "Ansari Nagar, New Delhi - 110029"},
    {"hospital_id": "HOSP-005", "hospital_name": "Manipal Hospital Bangalore", "tier": "TIER_1", "address": "98, HAL Old Airport Rd, Bangalore - 560017"},
    {"hospital_id": "HOSP-006", "hospital_name": "City Clinic Chennai", "tier": "TIER_2", "address": "42, Mount Road, Chennai - 600002"},
    {"hospital_id": "HOSP-007", "hospital_name": "Medanta The Medicity Gurgaon", "tier": "TIER_1", "address": "Sector 38, Gurgaon - 122001"},
    {"hospital_id": "HOSP-008", "hospital_name": "Narayana Health Bangalore", "tier": "TIER_1", "address": "258/A, Hosur Road, Bangalore - 560099"},
    {"hospital_id": "HOSP-009", "hospital_name": "Ruby Hall Clinic Pune", "tier": "TIER_2", "address": "40, Sassoon Road, Pune - 411001"},
    {"hospital_id": "HOSP-010", "hospital_name": "Government General Hospital Chennai", "tier": "GOVT", "address": "Poonamallee High Road, Chennai - 600003"},
]

PHYSICIAN_NAMES = [
    "Dr. A. Kumar", "Dr. S. Reddy", "Dr. P. Singh", "Dr. H. Patel", "Dr. M. Shah",
    "Dr. R. Gupta", "Dr. N. Verma", "Dr. K. Menon", "Dr. L. Rao", "Dr. B. Iyer",
]

DIAGNOSES = [
    {"desc": "Appendectomy", "code": "K35.80", "category": "SURGICAL", "details": "Acute appendicitis with periappendicitis. Laparoscopic appendectomy performed."},
    {"desc": "Dengue Fever", "code": "A90", "category": "MEDICAL", "details": "Dengue NS1 antigen positive. Thrombocytopenia with fever. Managed conservatively."},
    {"desc": "Knee Replacement", "code": "Z96.65", "category": "SURGICAL", "details": "Primary total knee arthroplasty for osteoarthritis. Right knee replaced."},
    {"desc": "Cataract Surgery", "code": "H25.9", "category": "SURGICAL", "details": "Age-related cataract. Phacoemulsification with IOL implantation."},
    {"desc": "Viral Pneumonia", "code": "J12.9", "category": "MEDICAL", "details": "Community-acquired viral pneumonia. Bilateral infiltrates on chest X-ray."},
    {"desc": "Coronary Angioplasty", "code": "I25.10", "category": "SURGICAL", "details": "Left anterior descending artery stenosis. PTCA with drug-eluting stent."},
    {"desc": "Hernia Repair", "code": "K40.90", "category": "SURGICAL", "details": "Right inguinal hernia. Mesh repair performed under spinal anesthesia."},
    {"desc": "Fracture Treatment", "code": "S72.009A", "category": "SURGICAL", "details": "Closed fracture neck of femur. ORIF with dynamic hip screw."},
    {"desc": "Typhoid Fever", "code": "A01.0", "category": "MEDICAL", "details": "Salmonella typhi isolated on blood culture. Treated with IV antibiotics."},
    {"desc": "Gallstone Surgery", "code": "K80.20", "category": "SURGICAL", "details": "Cholelithiasis with cholecystitis. Laparoscopic cholecystectomy performed."},
]

EXPENSE_ITEMS = [
    {"item": "Ward Charges", "expense_type": "ROOM_RENT", "unit": "Days", "rate_per_unit": 3500},
    {"item": "ICU Charges", "expense_type": "ROOM_RENT", "unit": "Days", "rate_per_unit": 12000},
    {"item": "Medicines & Consumables", "expense_type": "PHARMACY", "unit": "", "rate_per_unit": 0},
    {"item": "Injection & IV Fluids", "expense_type": "PHARMACY", "unit": "", "rate_per_unit": 0},
    {"item": "Blood & Blood Products", "expense_type": "PHARMACY", "unit": "Units", "rate_per_unit": 2500},
    {"item": "Lab Investigations", "expense_type": "DIAGNOSTICS", "unit": "", "rate_per_unit": 0},
    {"item": "Radiology / Imaging", "expense_type": "DIAGNOSTICS", "unit": "", "rate_per_unit": 0},
    {"item": "ECG & Cardiac Tests", "expense_type": "DIAGNOSTICS", "unit": "", "rate_per_unit": 0},
    {"item": "Consultation Fees", "expense_type": "CONSULTANT_FEES", "unit": "Visits", "rate_per_unit": 1500},
    {"item": "Surgeon Charges", "expense_type": "CONSULTANT_FEES", "unit": "", "rate_per_unit": 0},
    {"item": "Anesthetist Charges", "expense_type": "CONSULTANT_FEES", "unit": "", "rate_per_unit": 0},
    {"item": "Physiotherapy", "expense_type": "OTHER", "unit": "Sessions", "rate_per_unit": 800},
    {"item": "Nursing Charges", "expense_type": "OTHER", "unit": "Days", "rate_per_unit": 2000},
    {"item": "OT Charges", "expense_type": "OTHER", "unit": "", "rate_per_unit": 0},
    {"item": "Ambulance Charges", "expense_type": "AMBULANCE", "unit": "", "rate_per_unit": 0},
]

REG_NO_PREFIXES = ["MC", "MCI", "SMC", "DMC", "KMC", "GMC"]


# =========================================================================
# Enhanced Document Generator
# =========================================================================

class EnhancedDocumentGenerator:
    """Generates realistic PDF discharge summaries and hospital bills."""

    def __init__(self, num_discharges: int = 50, num_bills: int = 50,
                 repo_root: Optional[str] = None):
        self.num_discharges = num_discharges
        self.num_bills = num_bills
        self.repo_root = repo_root or self._find_repo_root()

        self.discharge_dir = os.path.join(self.repo_root, "data/raw/unstructured")
        self.bills_dir = os.path.join(self.repo_root, "data/raw/bills")
        os.makedirs(self.discharge_dir, exist_ok=True)
        os.makedirs(self.bills_dir, exist_ok=True)

        # Load generated claims data for realistic cross-referencing
        self.claims_data = self._load_claims_data()

    def _find_repo_root(self):
        if os.path.exists("../notebooks") and os.path.exists("../data"):
            return ".."
        elif os.path.exists("./notebooks") and os.path.exists("./data"):
            return "."
        return "."

    def _load_claims_data(self):
        """Load claim IDs, member names, policy numbers from generated CSVs."""
        data = []
        csv_path = os.path.join(self.repo_root, "data/raw/structured/claim_submissions.csv")
        if not os.path.exists(csv_path):
            print(f"WARNING: {csv_path} not found. Generating generic documents.")
            return self._generate_fallback_claims()

        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                data.append(row)

        # Also load policy_members for patient names
        member_path = os.path.join(self.repo_root, "data/raw/structured/policy_members.csv")
        member_map = {}
        if os.path.exists(member_path):
            with open(member_path, "r", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    member_map[row["member_id"]] = row["member_name"]

        # Attach names to claims
        for c in data:
            c["patient_name"] = member_map.get(c.get("claimant_id", ""), "Unknown Patient")

        return data

    def _generate_fallback_claims(self):
        """Generate minimal claim data if CSVs aren't available."""
        return [
            {"claim_id": f"CLM-2026-{10000 + i}", "patient_name": f"Patient_{i}",
             "policy_number": f"POL-HLT-{20000 + i}-T1", "claimed_amount": str(50000 + i * 1000)}
            for i in range(self.num_discharges)
        ]

    def _get_random_hospital(self):
        return random.choice(HOSPITALS)

    def _get_random_diagnosis(self):
        return random.choice(DIAGNOSES)

    def _get_random_physician(self):
        reg_no = f"{random.choice(REG_NO_PREFIXES)}-{random.randint(1000, 9999)}"
        return {"name": random.choice(PHYSICIAN_NAMES), "reg_no": reg_no}

    # ------------------------------------------------------------------
    # Discharge Summary PDF
    # ------------------------------------------------------------------

    def generate_discharge_summary_pdf(self, claim: dict, output_path: str):
        """Generate a realistic-looking discharge summary as a PDF."""
        hospital = self._get_random_hospital()
        diagnosis = self._get_random_diagnosis()
        physician = self._get_random_physician()

        admission_date = (datetime.now() - timedelta(days=random.randint(5, 60))).strftime("%Y-%m-%d")
        discharge_date = (datetime.strptime(admission_date, "%Y-%m-%d") + timedelta(days=random.randint(2, 10))).strftime("%Y-%m-%d")

        pdf = FPDF(orientation='P', unit='mm', format='A4')
        pdf.add_page()

        # --- Header ---
        pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 10, hospital["hospital_name"], new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
        pdf.set_font("Helvetica", "", 8)
        pdf.cell(0, 4, hospital["address"], new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
        pdf.cell(0, 4, f"Phone: +91-{random.randint(100, 999)}-{random.randint(1000000, 9999999)} | Email: info@{hospital['hospital_id'].lower()}.com", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
        pdf.line(10, pdf.get_y() + 2, 200, pdf.get_y() + 2)
        pdf.ln(5)

        # --- Title ---
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 8, "DISCHARGE SUMMARY", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
        pdf.ln(5)

        # --- Patient Information ---
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 6, "PATIENT INFORMATION", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_fill_color(240, 240, 240)

        info_lines = [
            ("Patient Name", claim.get("patient_name", "Unknown")),
            ("Date of Birth", f"{random.randint(1, 31):02d}/{random.randint(1, 12):02d}/{random.randint(1950, 2000)}"),
            ("Gender", random.choice(["Male", "Female"])),
            ("Policy Number", claim.get("policy_number", "N/A")),
            ("Claim ID", claim.get("claim_id", "N/A")),
            ("Admission Date", admission_date),
            ("Discharge Date", discharge_date),
            ("Ward", random.choice(["General Ward", "Semi-Private", "Private", "ICU"])),
        ]

        left_col_w = 50
        right_col_w = 140
        for label, value in info_lines:
            pdf.set_x(pdf.l_margin)
            pdf.cell(left_col_w, 5, f"  {label}:", border=0, fill=True)
            pdf.cell(right_col_w, 5, f"{value}", border=0, fill=True)
            pdf.ln()

        pdf.ln(4)

        # --- Diagnosis ---
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 6, "DIAGNOSIS", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(0, 5, f"  Principal Diagnosis: {diagnosis['desc']} ({diagnosis['code']})", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.cell(0, 5, f"  Diagnosis Category: {diagnosis['category']}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        pdf.ln(3)

        # --- Clinical Details ---
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 6, "CLINICAL DETAILS", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("Helvetica", "", 9)
        clinical_text = diagnosis["details"]
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(0, 5, f"  {clinical_text}")

        # Additional clinical notes
        findings = random.choice([
            "Vitals were stable throughout the admission. Post-operative recovery was uneventful.",
            "Patient responded well to conservative management. Symptoms resolved by day 3.",
            "Post-operative period was complicated by mild wound infection, managed with antibiotics.",
            "Patient required intensive monitoring for 48 hours post-procedure.",
            "Recovery was satisfactory. Patient mobilized with support from day 2.",
        ])
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(0, 5, f"  {findings}")

        pdf.ln(3)

        # --- Investigations ---
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 6, "INVESTIGATIONS & LAB RESULTS", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("Helvetica", "", 9)

        inv_count = random.randint(3, 6)
        investigations = random.sample([
            "Complete Blood Count", "Liver Function Test", "Renal Function Test",
            "Blood Glucose", "Chest X-Ray", "ECG", "USG Abdomen",
            "CT Scan", "MRI", "Blood Culture", "Urine Analysis", "Coagulation Profile"
        ], inv_count)
        for inv in investigations:
            status = random.choice(["Normal", "Elevated", "Within normal limits", "Abnormal - resolved"])
            pdf.cell(0, 5, f"  * {inv}: {status}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        pdf.ln(3)

        # --- Treatment Summary ---
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 6, "TREATMENT SUMMARY", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("Helvetica", "", 9)

        treatment_text = random.choice([
            "Patient was managed conservatively with IV fluids, antibiotics, and analgesics.",
            "Surgical intervention was performed under general anesthesia uneventfully.",
            "Patient underwent minimally invasive procedure under spinal anesthesia.",
            "Medical management with anti-hypertensives and diuretics was initiated.",
        ])
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(0, 5, f"  {treatment_text}")

        meds = random.sample([
            ("Inj. Ceftriaxone 1g IV BD", "Antibiotic"),
            ("Tab. Paracetamol 500mg SOS", "Analgesic"),
            ("Inj. Pantoprazole 40mg IV OD", "Antacid"),
            ("Tab. Atorvastatin 10mg OD", "Statin"),
            ("Inj. Enoxaparin 40mg SC OD", "Anticoagulant"),
            ("Tab. Metformin 500mg BD", "Antidiabetic"),
            ("Inj. Ondansetron 4mg IV SOS", "Antiemetic"),
            ("Tab. Amlodipine 5mg OD", "Antihypertensive"),
        ], random.randint(3, 5))

        for med, reason in meds:
            pdf.cell(0, 5, f"  * {med} ({reason})", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        pdf.ln(3)

        # --- Bill Summary ---
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 6, "BILL SUMMARY", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("Helvetica", "", 9)

        claimed_amt = int(float(claim.get("claimed_amount", 50000)))
        pdf.cell(0, 5, f"  Total Amount Claimed: INR {claimed_amt:,}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.cell(0, 5, f"  Room Rent Charges: INR {int(claimed_amt * random.uniform(0.15, 0.30)):,}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        pdf.ln(5)

        # --- Discharge Instructions ---
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 6, "DISCHARGE INSTRUCTIONS & FOLLOW-UP", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("Helvetica", "", 9)

        instructions = [
            "Follow up with treating physician in 7 days.",
            "Continue prescribed medications as directed.",
            "Wound care: Keep the surgical site clean and dry.",
            "Report immediately if fever > 100F, excessive bleeding, or severe pain.",
            "Avoid heavy lifting and strenuous activity for 2 weeks.",
            "Diet: Light, easily digestible food for next 3 days.",
        ]
        for inst in instructions:
            pdf.cell(0, 5, f"  * {inst}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        pdf.ln(8)

        # --- Footer ---
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(3)
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(0, 5, f"Attending Physician: {physician['name']}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.cell(0, 5, f"Registration No: {physician['reg_no']}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.cell(0, 5, f"Signature: ___________________________", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.cell(0, 5, f"Date: {discharge_date} | Time: {random.randint(9, 18):02d}:{random.randint(0, 59):02d}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.cell(0, 5, "", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("Helvetica", "I", 7)
        pdf.cell(0, 4, "This is a computer-generated document. No signature is required.", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")

        pdf.output(output_path)
        print(f"  Wrote discharge summary PDF: {output_path}")

    # ------------------------------------------------------------------
    # Hospital Bill PDF
    # ------------------------------------------------------------------

    def generate_hospital_bill_pdf(self, claim: dict, output_path: str):
        """Generate a realistic hospital bill as a PDF."""
        hospital = self._get_random_hospital()
        diagnosis = self._get_random_diagnosis()

        admission_date = (datetime.now() - timedelta(days=random.randint(5, 60))).strftime("%Y-%m-%d")
        discharge_date = (datetime.strptime(admission_date, "%Y-%m-%d") + timedelta(days=random.randint(2, 10))).strftime("%Y-%m-%d")
        days_stayed = (datetime.strptime(discharge_date, "%Y-%m-%d") - datetime.strptime(admission_date, "%Y-%m-%d")).days
        bill_no = f"BILL-{random.randint(100000, 999999)}"

        pdf = FPDF(orientation='L', unit='mm', format='A4')  # Landscape for bill
        pdf.add_page()

        # --- Header ---
        pdf.set_font("Helvetica", "B", 18)
        pdf.cell(0, 12, hospital["hospital_name"], new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(0, 5, hospital["address"], new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
        pdf.cell(0, 5, f"GSTIN: 33AAACH{random.randint(1000, 9999)}Z{random.choice(['1','2'])}D", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
        pdf.line(10, pdf.get_y() + 2, 287, pdf.get_y() + 2)
        pdf.ln(4)

        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 8, "DETAILED HOSPITAL BILL / FINAL ACCOUNT", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
        pdf.ln(3)

        # Bill metadata
        pdf.set_font("Helvetica", "", 9)
        half_w = 95
        pdf.cell(half_w, 5, f"Bill No: {bill_no}")
        pdf.cell(0, 5, f"Date: {discharge_date}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        pdf.cell(half_w, 5, f"Patient Name: {claim.get('patient_name', 'Unknown')}")
        pdf.cell(0, 5, f"Claim ID: {claim.get('claim_id', 'N/A')}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        pdf.cell(half_w, 5, f"Admission: {admission_date}")
        pdf.cell(0, 5, f"Discharge: {discharge_date}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        pdf.cell(half_w, 5, f"Days Stayed: {days_stayed}")
        pdf.cell(0, 5, f"Diagnosis: {diagnosis['desc']} ({diagnosis['code']})", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        pdf.line(10, pdf.get_y() + 2, 287, pdf.get_y() + 2)
        pdf.ln(4)

        # --- Bill Line Items ---
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_fill_color(230, 230, 230)

        # Table header
        col_widths = [80, 50, 30, 40, 50]  # Item, Qty, Rate, Amount
        headers = ["Particulars", "Qty / Days", "Rate (INR)", "Amount (INR)"]
        for i, h in enumerate(headers):
            pdf.cell(col_widths[i], 7, h, border=1, fill=True, align="C")
        pdf.ln()

        # Generate items
        pdf.set_font("Helvetica", "", 8)
        total_amount = 0
        bill_items = []

        # Room rent
        room_rent_per_day = random.randint(2000, 12000)
        room_amount = room_rent_per_day * days_stayed
        bill_items.append({"item": f"Room Rent ({hospital['tier']})", "qty": f"{days_stayed} Days", "rate": room_rent_per_day, "amount": room_amount})
        total_amount += room_amount

        # Select random expense items
        num_items = random.randint(5, 10)
        selected_items = random.sample(EXPENSE_ITEMS, min(num_items, len(EXPENSE_ITEMS)))

        for item in selected_items:
            if item["expense_type"] == "ROOM_RENT":
                continue
            qty = random.randint(1, 5) if "Days" in item["unit"] or "Sessions" in item["unit"] else 1
            rate = item["rate_per_unit"] if item["rate_per_unit"] > 0 else random.randint(500, 15000)
            amount = qty * rate
            amt_scaled = int(amount * random.uniform(0.8, 1.2))
            bill_items.append({
                "item": item["item"],
                "qty": f"{qty} {item['unit']}" if item["unit"] else str(qty),
                "rate": rate,
                "amount": amt_scaled
            })
            total_amount += amt_scaled

        # Surgeon charges for surgical cases
        if diagnosis["category"] == "SURGICAL":
            surgeon_fee = random.randint(15000, 60000)
            bill_items.append({"item": "Surgeon's Fees", "qty": "1", "rate": surgeon_fee, "amount": surgeon_fee})
            total_amount += surgeon_fee
            ot_charges = random.randint(10000, 40000)
            bill_items.append({"item": "Operation Theatre Charges", "qty": "1", "rate": ot_charges, "amount": ot_charges})
            total_amount += ot_charges
            anesthetist_fee = random.randint(5000, 15000)
            bill_items.append({"item": "Anesthetist Charges", "qty": "1", "rate": anesthetist_fee, "amount": anesthetist_fee})
            total_amount += anesthetist_fee

        # Consumables (add a lump sum)
        consumables = random.randint(3000, 15000)
        bill_items.append({"item": "Consumables & Implants", "qty": "LS", "rate": consumables, "amount": consumables})
        total_amount += consumables

        # Write bill items
        for item in bill_items:
            pdf.cell(col_widths[0], 6, f"  {item['item']}", border=1)
            pdf.cell(col_widths[1], 6, str(item['qty']), border=1, align="C")
            pdf.cell(col_widths[2], 6, f"{item['rate']:,}", border=1, align="R")
            pdf.cell(col_widths[3], 6, f"{item['amount']:,}", border=1, align="R")
            pdf.ln()

        # Grand Total
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_fill_color(255, 255, 230)
        pdf.cell(col_widths[0], 8, "", border=0)
        pdf.cell(col_widths[1], 8, "", border=0)
        pdf.cell(col_widths[2], 8, "GRAND TOTAL", border=1, fill=True, align="R")
        pdf.cell(col_widths[3], 8, f"INR {total_amount:,}/-", border=1, fill=True, align="R")
        pdf.ln()

        pdf.ln(5)

        # --- Payment Section ---
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(0, 5, f"Amount in Words: Rupees {self._number_to_words(total_amount)} Only", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.cell(0, 5, f"Payment Mode: {random.choice(['Cash', 'Card', 'Insurance TPA', 'UPI', 'Cheque'])}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.cell(0, 5, f"Settlement Status: {random.choice(['Paid in Full', 'Pending Insurance Approval', 'Partial Payment'])}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        pdf.ln(8)

        # Terms and conditions
        pdf.line(10, pdf.get_y(), 287, pdf.get_y())
        pdf.ln(2)
        pdf.set_font("Helvetica", "I", 7)
        terms = [
            "1. This is a computer-generated bill and does not require a physical signature.",
            "2. In case of any discrepancy, please report within 7 days.",
            "3. Insurance claims are subject to policy terms and conditions.",
            "4. Original bill to be produced for insurance claim processing.",
        ]
        for t in terms:
            pdf.cell(0, 4, t, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        pdf.output(output_path)
        print(f"  Wrote hospital bill PDF: {output_path}")

    def _number_to_words(self, n):
        """Convert number to Indian Rupee words (simple implementation)."""
        if n < 1000:
            return str(n)
        if n < 100000:
            return f"{n // 1000} Thousand {n % 1000}"
        return f"{n // 100000} Lakh {n % 100000}"

    # ------------------------------------------------------------------
    # Payment Receipt Image (JPG) — for OCR testing
    # ------------------------------------------------------------------

    def generate_payment_receipt_jpg(self, claim: dict, output_path: str):
        """Generate a simple payment receipt as a JPG image."""
        hospital = self._get_random_hospital()
        claimed_amt = int(float(claim.get("claimed_amount", 50000)))
        receipt_no = f"RCPT-{random.randint(10000, 99999)}"

        img = Image.new('RGB', (800, 600), color=(255, 255, 255))
        draw = ImageDraw.Draw(img)

        try:
            font_large = ImageFont.truetype("arial.ttf", 28)
            font_med = ImageFont.truetype("arial.ttf", 20)
            font_small = ImageFont.truetype("arial.ttf", 16)
        except Exception:
            font_large = ImageFont.load_default()
            font_med = ImageFont.load_default()
            font_small = ImageFont.load_default()

        # Header
        draw.text((200, 20), hospital["hospital_name"], fill=(0, 51, 102), font=font_large)
        draw.text((200, 55), hospital["address"], fill=(100, 100, 100), font=font_small)
        draw.rectangle([(40, 90), (760, 95)], fill=(0, 51, 102))

        # Receipt title
        draw.text((300, 100), "PAYMENT RECEIPT", fill=(0, 0, 0), font=font_med)
        draw.text((550, 100), f"No: {receipt_no}", fill=(100, 100, 100), font=font_small)

        # Details
        y = 140
        details = [
            ("Received from:", claim.get("patient_name", "Unknown")),
            ("Claim ID:", claim.get("claim_id", "N/A")),
            ("Policy No:", claim.get("policy_number", "N/A")),
            ("Date of Payment:", (datetime.now() - timedelta(days=random.randint(0, 30))).strftime("%Y-%m-%d")),
            ("Payment Mode:", random.choice(["Cash", "Bank Transfer", "Card", "UPI"])),
        ]
        for label, value in details:
            draw.text((60, y), label, fill=(80, 80, 80), font=font_small)
            draw.text((220, y), value, fill=(0, 0, 0), font=font_small)
            y += 28

        # Amount
        y += 10
        draw.rectangle([(60, y), (740, y + 45)], fill=(230, 255, 230))
        draw.text((80, y + 8), f"Amount Received: INR {claimed_amt:,}/-", fill=(0, 100, 0), font=font_med)

        y += 70
        draw.text((60, y), f"In Words: Rupees {self._number_to_words(claimed_amt)} Only", fill=(80, 80, 80), font=font_small)

        y += 40
        draw.rectangle([(40, y), (760, y + 2)], fill=(200, 200, 200))
        y += 15
        draw.text((500, y), "Authorized Signatory", fill=(80, 80, 80), font=font_small)
        draw.text((500, y + 25), "_________________________", fill=(80, 80, 80), font=font_small)
        y += 60
        draw.text((60, y), "Note: This is a computer-generated receipt.", fill=(150, 150, 150), font=font_small)

        img.save(output_path, "JPEG", quality=85)
        print(f"  Wrote payment receipt JPG: {output_path}")

    # ------------------------------------------------------------------
    # Main Generation
    # ------------------------------------------------------------------

    def generate_all(self):
        print(f"\n{'='*60}")
        print("Enhanced Document Generation")
        print(f"{'='*60}")

        # Generate discharge summaries
        print(f"\nGenerating {self.num_discharges} Discharge Summary PDFs...")
        for i, claim in enumerate(self.claims_data[:self.num_discharges]):
            claim_id = claim.get("claim_id", f"CLM-2026-{10000 + i}")
            output_path = os.path.join(self.discharge_dir, f"{claim_id}_discharge_summary.pdf")
            self.generate_discharge_summary_pdf(claim, output_path)

        # Generate hospital bills
        print(f"\nGenerating {self.num_bills} Hospital Bill PDFs...")
        for i, claim in enumerate(self.claims_data[:self.num_bills]):
            claim_id = claim.get("claim_id", f"CLM-2026-{10000 + i}")
            pdf_path = os.path.join(self.bills_dir, f"{claim_id}_hospital_bill.pdf")
            self.generate_hospital_bill_pdf(claim, pdf_path)
            if i % 3 == 0:
                jpg_path = os.path.join(self.bills_dir, f"{claim_id}_payment_receipt.jpg")
                self.generate_payment_receipt_jpg(claim, jpg_path)

        discharge_count = len([f for f in os.listdir(self.discharge_dir) if f.endswith(".pdf")])
        bill_count = len([f for f in os.listdir(self.bills_dir) if f.endswith((".pdf", ".jpg", ".jpeg", ".png"))])
        print(f"\n{'='*60}")
        print(f"Generation Complete!")
        print(f"  Discharge Summaries:  {discharge_count} PDF files")
        print(f"  Hospital Bills:       {bill_count} files (PDF + JPG)")
        print(f"  Discharge dir:        {self.discharge_dir}")
        print(f"  Bills dir:            {self.bills_dir}")
        print(f"{'='*60}")


# =========================================================================
# Main
# =========================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate enhanced hospital documents (PDF/JPG)")
    parser.add_argument("--num-discharges", type=int, default=50, help="Number of discharge summaries to generate")
    parser.add_argument("--num-bills", type=int, default=50, help="Number of hospital bills to generate")
    args = parser.parse_args()

    gen = EnhancedDocumentGenerator(
        num_discharges=args.num_discharges,
        num_bills=args.num_bills
    )
    gen.generate_all()