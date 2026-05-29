import os
import json
import csv
import random
from datetime import datetime, timedelta

# Dynamically find the repo root
if os.path.exists("../notebooks") and os.path.exists("../data"):
    repo_root = ".."
elif os.path.exists("./notebooks") and os.path.exists("./data"):
    repo_root = "."
else:
    repo_root = "."

def create_directories():
    os.makedirs(f"{repo_root}/data/raw/structured", exist_ok=True)
    os.makedirs(f"{repo_root}/data/raw/unstructured", exist_ok=True)

def generate_network_hospitals():
    hospitals = [
        {"hospital_id": "HOSP-001", "hospital_name": "Apollo Hospital Coimbatore", "tier": "TIER_1", "network_status": "IN-NETWORK"},
        {"hospital_id": "HOSP-002", "hospital_name": "Fortis Healthcare Mumbai", "tier": "TIER_1", "network_status": "IN-NETWORK"},
        {"hospital_id": "HOSP-003", "hospital_name": "Max Super Speciality Delhi", "tier": "TIER_1", "network_status": "OUT-OF-NETWORK"},
        {"hospital_id": "HOSP-004", "hospital_name": "AIIMS New Delhi", "tier": "GOVT", "network_status": "IN-NETWORK"},
        {"hospital_id": "HOSP-005", "hospital_name": "Manipal Hospital Bangalore", "tier": "TIER_1", "network_status": "IN-NETWORK"},
        {"hospital_id": "HOSP-006", "hospital_name": "City Clinic Chennai", "tier": "TIER_2", "network_status": "OUT-OF-NETWORK"}
    ]
    csv_file = f"{repo_root}/data/raw/structured/network_hospitals.csv"
    with open(csv_file, mode='w', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=hospitals[0].keys())
        writer.writeheader()
        writer.writerows(hospitals)
    return hospitals

def generate_policy_master(num_policies=200):
    policies = []
    tiers = ["SILVER", "GOLD", "PREMIUM"]
    base_date = datetime.today()
    for i in range(num_policies):
        tier = random.choice(tiers)
        sum_insured = {"SILVER": 300000, "GOLD": 500000, "PREMIUM": 1000000}[tier]
        premium_paid = {"SILVER": 8000, "GOLD": 12000, "PREMIUM": 25000}[tier]
        
        # Some are new (last 30 days), most are old
        if random.random() < 0.1:
            inception_date = base_date - timedelta(days=random.randint(1, 30))
        else:
            inception_date = base_date - timedelta(days=random.randint(300, 1500))
            
        policies.append({
            "policy_number": f"POL-HLT-{20000+i}",
            "claimant_name": f"Patient {i}",
            "plan_tier": tier,
            "sum_insured": sum_insured,
            "inception_date": inception_date.strftime("%Y-%m-%d"),
            "premium_paid": premium_paid,
            "status": "ACTIVE" if random.random() < 0.95 else "LAPSED"
        })
        
    csv_file = f"{repo_root}/data/raw/structured/policy_master.csv"
    with open(csv_file, mode='w', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=policies[0].keys())
        writer.writeheader()
        writer.writerows(policies)
    return policies

def generate_claims_history(policies, base_date):
    history = []
    for policy in policies:
        # Generate some past claims for a subset of policies
        if random.random() < 0.3:
            num_past_claims = random.randint(1, 3)
            for j in range(num_past_claims):
                claim_date = base_date - timedelta(days=random.randint(30, 800))
                if claim_date > datetime.strptime(policy["inception_date"], "%Y-%m-%d"):
                    history.append({
                        "historical_claim_id": f"HIST-{policy['policy_number']}-{j}",
                        "policy_number": policy["policy_number"],
                        "claim_date": claim_date.strftime("%Y-%m-%d"),
                        "settled_amount": random.randint(10000, 80000),
                        "diagnosis_icd": random.choice(["K35.80", "A90", "Z96.65", "H25.9", "J12.9"]),
                        "fraud_flag": "YES" if random.random() < 0.05 else "NO"
                    })
    
    # ensure file is written even if empty (but it won't be empty)
    csv_file = f"{repo_root}/data/raw/structured/claims_history.csv"
    if not history:
        history.append({"historical_claim_id": "dummy", "policy_number": "dummy", "claim_date": "2000-01-01", "settled_amount": 0, "diagnosis_icd": "none", "fraud_flag": "NO"})
    
    with open(csv_file, mode='w', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=history[0].keys())
        writer.writeheader()
        writer.writerows(history)
    return history

def generate_synthetic_claims_and_docs(hospitals, policies, history, num_claims=500):
    claims = []
    diagnoses = [
        {"desc": "Appendectomy", "code": "K35.80", "base_amount": 60000},
        {"desc": "Dengue Fever", "code": "A90", "base_amount": 25000},
        {"desc": "Knee Replacement", "code": "Z96.65", "base_amount": 250000},
        {"desc": "Cataract Surgery", "code": "H25.9", "base_amount": 35000},
        {"desc": "Viral Pneumonia", "code": "J12.9", "base_amount": 50000}
    ]
    
    base_date = datetime.today()
    num_fraud = int(num_claims * 0.15)
    
    for i in range(num_claims):
        is_fraud = i < num_fraud
        policy = random.choice(policies)
        diagnosis = random.choice(diagnoses)
        hospital = random.choice(hospitals)
        
        # Fraud patterns
        if is_fraud:
            fraud_type = random.choice(["high_velocity", "early_claim", "inflated_amount"])
            if fraud_type == "high_velocity":
                # Ensure recent history
                admission_date = base_date - timedelta(days=random.randint(1, 10))
                claimed_amount = diagnosis["base_amount"] + random.randint(10000, 30000)
                # We'll artificially inject history records later for high velocity
            elif fraud_type == "early_claim":
                # Ensure policy is very new
                admission_date = datetime.strptime(policy["inception_date"], "%Y-%m-%d") + timedelta(days=random.randint(2, 14))
                claimed_amount = diagnosis["base_amount"] + random.randint(20000, 50000)
            elif fraud_type == "inflated_amount":
                admission_date = base_date - timedelta(days=random.randint(20, 60))
                claimed_amount = diagnosis["base_amount"] * random.uniform(2.5, 4.0)
        else:
            admission_date = base_date - timedelta(days=random.randint(15, 90))
            claimed_amount = diagnosis["base_amount"] + random.randint(-5000, 5000)
            
        discharge_date = admission_date + timedelta(days=random.randint(1, 10))
        
        # For the CSV, we need the exact features that the ML model will train on if it's joining
        # But wait, the pipeline expects 'claim_velocity' to be computed from 'claims_history'.
        # To make 'high_velocity' work, let's inject 3 claims in the last 90 days into claims_history for this policy
        if is_fraud and fraud_type == "high_velocity":
            for _ in range(3):
                hist_date = admission_date - timedelta(days=random.randint(5, 80))
                history.append({
                    "historical_claim_id": f"HIST-FRAUD-{policy['policy_number']}-{random.randint(1000,9999)}",
                    "policy_number": policy["policy_number"],
                    "claim_date": hist_date.strftime("%Y-%m-%d"),
                    "settled_amount": random.randint(20000, 50000),
                    "diagnosis_icd": "A90",
                    "fraud_flag": "NO"
                })
        
        claim_id = f"CLM-2026-{10000+i}"
        claim = {
            "claim_id": claim_id,
            "policy_number": policy["policy_number"],
            "claimant_name": policy["claimant_name"],
            "date_of_loss": admission_date.strftime("%Y-%m-%d"),
            "hospital_name": hospital["hospital_name"],
            "claimed_amount": int(claimed_amount),
            "submission_date": discharge_date.strftime("%Y-%m-%d"),
            "status": "NEW",
            "is_fraud": 1 if is_fraud else 0  # Label for ML training!
        }
        claims.append(claim)
        
        # Generate 50 TXTs only (as requested)
        if i < 50:
            generate_discharge_summary(claim, diagnosis, admission_date, discharge_date, hospital)
            
    # Rewrite history because we might have appended to it
    csv_file = f"{repo_root}/data/raw/structured/claims_history.csv"
    with open(csv_file, mode='w', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=history[0].keys())
        writer.writeheader()
        writer.writerows(history)
        
    csv_file = f"{repo_root}/data/raw/structured/claims.csv"
    with open(csv_file, mode='w', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=claims[0].keys())
        writer.writeheader()
        writer.writerows(claims)
    print(f"Generated {num_claims} structured claims at {csv_file}")

def generate_discharge_summary(claim, diagnosis, admin_date, discharge_date, hospital):
    physician_name = random.choice(['A. Kumar', 'S. Reddy', 'P. Singh', 'H. Patel', 'M. Shah', 'R. Gupta', 'N. Verma', 'K. Menon', 'L. Rao', 'B. Iyer'])
    physician_reg = f"MC-{random.randint(1000, 9999)}"

    templates = [
        # Template 1: Standard
        """
        DISCHARGE SUMMARY
        -----------------
        Patient Name: {name}
        Policy Number: {policy}
        Admission Date: {admit}
        Discharge Date: {discharge}
        Hospital: {hospital}
        
        Diagnosis: {diag_desc}
        ICD-10 Code: {icd}
        
        Course in the Hospital:
        The patient presented with symptoms relating to {diag_desc}. 
        Routine investigations were carried out. The patient was managed conservatively/surgically 
        and responded well to the treatment.
        
        Final Bill Amount: INR {amount}
        
        Attending Physician: Dr. {physician_name} (Reg No: {physician_reg})
        """,
        # Template 2: Minimal
        """
        HOSPITAL DISCHARGE RECORD
        Hospital: {hospital}
        Patient: {name} | Policy: {policy}
        Admitted: {admit} | Discharged: {discharge}
        
        Principal Diagnosis: {diag_desc} ({icd})
        Total Charges: {amount}
        
        Physician: Dr. {physician_name}, {physician_reg}
        """,
        # Template 3: Verbose
        """
        ========================================
        CLINICAL DISCHARGE REPORT
        ========================================
        Facility: {hospital}
        
        PATIENT INFORMATION
        Name: {name}
        Insurance ID: {policy}
        
        ENCOUNTER DETAILS
        Date of Admission: {admit}
        Date of Discharge: {discharge}
        
        CLINICAL FINDINGS
        Diagnosis: {diag_desc}
        ICD Reference: {icd}
        The patient was admitted and treated for the above condition.
        
        FINANCIAL
        Total Incurred Amount: {amount} INR
        
        Signed: Dr. {physician_name} ({physician_reg})
        """,
        # Template 4: Minimal with Physician
        """
        SUMMARY OF DISCHARGE
        Location: {hospital}
        Name: {name} - {policy}
        From {admit} to {discharge}
        Condition: {diag_desc} [{icd}]
        Bill: {amount}
        Physician: Dr. {physician_name} (Reg No: {physician_reg})
        """,
        # Template 5: Tabular
        """
        | Hospital       | {hospital} |
        | Patient        | {name} |
        | Policy         | {policy} |
        | Admitted       | {admit} |
        | Discharged     | {discharge} |
        | Diagnosis      | {diag_desc} |
        | ICD-10         | {icd} |
        | Total Bill     | {amount} |
        | Doctor         | Dr. {physician_name} (Reg: {physician_reg}) |
        """
    ]
    
    template = random.choice(templates)
    summary = template.format(
        name=claim['claimant_name'],
        policy=claim['policy_number'],
        admit=admin_date.strftime("%Y-%m-%d"),
        discharge=discharge_date.strftime("%Y-%m-%d"),
        hospital=hospital['hospital_name'],
        diag_desc=diagnosis['desc'],
        icd=diagnosis['code'],
        amount=claim['claimed_amount'],
        physician_name=physician_name,
        physician_reg=physician_reg
    )
    
    filename = f"{repo_root}/data/raw/unstructured/{claim['claim_id']}_discharge_summary.txt"
    with open(filename, "w") as f:
        f.write(summary.strip())

if __name__ == "__main__":
    create_directories()
    hospitals = generate_network_hospitals()
    policies = generate_policy_master()
    base_date = datetime.today()
    history = generate_claims_history(policies, base_date)
    generate_synthetic_claims_and_docs(hospitals, policies, history, 500)
    print("Synthetic data generation complete.")
