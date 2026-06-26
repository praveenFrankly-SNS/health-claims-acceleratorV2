"""
Supabase Population Script for Health Claims Accelerator v2.
Reads locally generated synthetic data (CSVs + documents) and pushes:
  1. Structured data -> Supabase PostgreSQL (8 tables)
  2. Unstructured documents -> Supabase Storage (3 buckets)

Prerequisites:
  pip install supabase psycopg2-binary python-dotenv
  
  Set environment variables in .env:
    SUPABASE_URL=https://nerwqbauracfinfvunul.supabase.co
    SUPABASE_SERVICE_KEY=your_service_role_key_here

Usage:
    python data/populate_supabase.py [--data-dir data/raw/structured]
                                     [--discharge-dir data/raw/unstructured]
                                     [--bills-dir data/raw/bills]
                                     [--policy-forms-dir data/policy_forms]

Author: SNS Square | Version: 2.0
"""

import os
import sys
import io

# Force stdout and stderr to UTF-8 on Windows to avoid UnicodeEncodeErrors
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
import csv
import json
import argparse
from pathlib import Path
from typing import Optional


# =========================================================================
# Dependency check
# =========================================================================
def _ensure_deps():
    missing = []
    try:
        from supabase import create_client
    except ImportError:
        missing.append("supabase")
    try:
        import psycopg2
    except ImportError:
        missing.append("psycopg2-binary")
    try:
        from dotenv import load_dotenv
    except ImportError:
        missing.append("python-dotenv")
    if missing:
        print(f"Missing dependencies: {', '.join(missing)}")
        print("Install with: pip install " + " ".join(missing))
        sys.exit(1)


_ensure_deps()

import psycopg2
from psycopg2.extras import execute_values
from supabase import create_client, Client
from dotenv import load_dotenv

# Load .env from project root
dotenv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
load_dotenv(dotenv_path)


# =========================================================================
# DDL statements — matching 00_setup.py Delta schemas
# =========================================================================

CREATE_TABLE_SQL = {
    "network_hospitals": """
        CREATE TABLE IF NOT EXISTS network_hospitals (
            hospital_id TEXT PRIMARY KEY,
            hospital_name TEXT,
            tier TEXT,
            network_status TEXT
        );
    """,
    "provider_registry": """
        CREATE TABLE IF NOT EXISTS provider_registry (
            physician_registration_number TEXT PRIMARY KEY,
            physician_name TEXT,
            hospital_id TEXT,
            blacklist_status BOOLEAN,
            historical_claim_count INTEGER DEFAULT 0,
            historical_fraud_flag_ratio DOUBLE PRECISION DEFAULT 0.0
        );
    """,
    "policy_master": """
        CREATE TABLE IF NOT EXISTS policy_master (
            policy_number TEXT PRIMARY KEY,
            policy_type TEXT,
            total_sum_insured INTEGER,
            inception_date TEXT,
            premium_paid INTEGER,
            status TEXT,
            policy_form_version TEXT,
            plan_tier TEXT
        );
    """,
    "policy_members": """
        CREATE TABLE IF NOT EXISTS policy_members (
            policy_number TEXT,
            member_id TEXT,
            member_name TEXT,
            relationship_to_primary TEXT,
            date_of_birth TEXT,
            coverage_start_date TEXT,
            coverage_end_date TEXT,
            PRIMARY KEY (policy_number, member_id)
        );
    """,
    "claim_submissions": """
        CREATE TABLE IF NOT EXISTS claim_submissions (
            claim_id TEXT PRIMARY KEY,
            policy_number TEXT,
            claimant_id TEXT,
            date_of_loss TEXT,
            claimed_amount INTEGER,
            submission_date TEXT,
            status TEXT,
            is_fraud INTEGER,
            claim_form_metadata TEXT
        );
    """,
    # Training table — full historical claims (never capped).
    # Databricks reads this for fraud model training via JDBC.
    "claim_submissions_training": """
        CREATE TABLE IF NOT EXISTS claim_submissions_training (
            claim_id TEXT PRIMARY KEY,
            policy_number TEXT,
            claimant_id TEXT,
            date_of_loss TEXT,
            claimed_amount INTEGER,
            submission_date TEXT,
            status TEXT,
            is_fraud INTEGER,
            claim_form_metadata TEXT
        );
    """,
    "pre_auth_requests": """
        CREATE TABLE IF NOT EXISTS pre_auth_requests (
            pre_auth_id TEXT PRIMARY KEY,
            claim_id TEXT,
            requested_amount INTEGER,
            approved_amount INTEGER,
            status TEXT,
            request_date TEXT
        );
    """,
    "clinical_records": """
        CREATE TABLE IF NOT EXISTS clinical_records (
            claim_id TEXT,
            record_seq INTEGER,
            admission_date TEXT,
            discharge_date TEXT,
            hospital_id TEXT,
            diagnosis_icd TEXT,
            attending_physician_registration_number TEXT,
            PRIMARY KEY (claim_id, record_seq)
        );
    """,
    "claim_bills": """
        CREATE TABLE IF NOT EXISTS claim_bills (
            claim_id TEXT,
            bill_no TEXT,
            bill_date TEXT,
            raw_expense_label TEXT,
            normalized_expense_type TEXT,
            amount INTEGER,
            PRIMARY KEY (claim_id, bill_no)
        );
    """,
}


# =========================================================================
# Supabase Populator
# =========================================================================

class SupabasePopulator:
    """Pushes locally generated synthetic data into Supabase."""

    def __init__(self, supabase_url: str, service_key: str,
                 data_dir: str = "data/raw/structured",
                 discharge_dir: str = "data/raw/unstructured",
                 bills_dir: str = "data/raw/bills",
                 policy_forms_dir: str = "data/policy_forms"):
        self.supabase_url = supabase_url
        self.service_key = service_key
        self.data_dir = data_dir
        self.discharge_dir = discharge_dir
        self.bills_dir = bills_dir
        self.policy_forms_dir = policy_forms_dir

        # Initialize Supabase client (for Storage operations)
        self.supabase: Client = create_client(supabase_url, service_key)

        # Initialize direct PostgreSQL connection (for bulk inserts)
        self.conn = self._connect_db()

    def _connect_db(self):
        """Connect to Supabase PostgreSQL via direct connection string."""
        project_ref = self.supabase_url.replace("https://", "").split(".")[0]

        # Resolve DB connection details dynamically from environment variables
        db_host = os.environ.get("SUPABASE_DB_HOST") or os.environ.get("SUPABASE_HOST")
        if not db_host:
            db_host = f"db.{project_ref}.supabase.co"

        db_port = int(os.environ.get("SUPABASE_PORT", "5432"))
        db_name = os.environ.get("SUPABASE_DB", "postgres")
        db_user = os.environ.get("SUPABASE_USER", "postgres")
        
        # For Supabase connection poolers, the user must be in the format 'user.[project_ref]' to identify the tenant
        if "." not in db_user and ("pooler.supabase" in db_host or "supabase.com" in db_host):
            db_user = f"{db_user}.{project_ref}"

        db_password = os.environ.get("SUPABASE_PASSWORD") or os.environ.get("SUPABASE_DB_PASSWORD") or self.service_key

        print(f"Connecting to Supabase PostgreSQL at {db_host}:{db_port} as user '{db_user}'...")
        conn = psycopg2.connect(
            host=db_host,
            port=db_port,
            dbname=db_name,
            user=db_user,
            password=db_password,
            sslmode="require"
        )
        conn.autocommit = True
        print(f"✓ Connected to Supabase PostgreSQL: {db_host}:{db_port}/{db_name}")
        return conn

    # =====================================================================
    # Structured Data (PostgreSQL Tables)
    # =====================================================================

    def create_tables(self):
        """Create all required tables in the public schema."""
        print("\n--- Creating Tables ---")
        with self.conn.cursor() as cur:
            for table_name, ddl in CREATE_TABLE_SQL.items():
                try:
                    cur.execute(ddl)
                    print(f"  ✓ Table '{table_name}' ready")
                except Exception as e:
                    print(f"  ✗ Failed to create table '{table_name}': {e}")

    def truncate_tables(self):
        """Truncate all tables for a fresh reload."""
        print("\n--- Truncating Existing Data ---")
        with self.conn.cursor() as cur:
            for table_name in CREATE_TABLE_SQL:
                try:
                    cur.execute(f"TRUNCATE TABLE {table_name} CASCADE;")
                    print(f"  ✓ Truncated '{table_name}'")
                except Exception as e:
                    print(f"  ✗ Failed to truncate '{table_name}': {e}")

    def _csv_to_rows(self, csv_path: str) -> list:
        """Read a CSV file and return list of dicts."""
        rows = []
        if not os.path.exists(csv_path):
            print(f"    WARNING: {csv_path} not found. Skipping.")
            return rows
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
        return rows

    def _cast_value(self, value: str, col_name: str) -> any:
        """Cast string values from CSV to proper Python types."""
        if value is None or value == "":
            return None
        # Check for boolean columns
        if col_name in ("blacklist_status",):
            return value.lower() in ("true", "1", "yes")
        # Check for integer columns
        if col_name in ("historical_claim_count", "total_sum_insured", "premium_paid",
                        "claimed_amount", "requested_amount", "approved_amount",
                        "amount", "record_seq", "is_fraud"):
            try:
                return int(value)
            except (ValueError, TypeError):
                return None
        # Check for float columns
        if col_name in ("historical_fraud_flag_ratio",):
            try:
                return float(value)
            except (ValueError, TypeError):
                return None
        return value

    def _insert_table(self, table_name: str, rows: list):
        """Bulk insert rows into a PostgreSQL table."""
        if not rows:
            print(f"    ⚠ Skipping (0 rows)")
            return

        columns = list(rows[0].keys())
        # Cast values to proper types
        typed_rows = []
        for row in rows:
            typed_row = tuple(self._cast_value(row.get(col, ""), col) for col in columns)
            typed_rows.append(typed_row)

        col_names = ", ".join(columns)
        placeholders = ", ".join(["%s"] * len(columns))
        insert_sql = f"INSERT INTO {table_name} ({col_names}) VALUES %s ON CONFLICT DO NOTHING;"

        with self.conn.cursor() as cur:
            try:
                execute_values(cur, insert_sql, typed_rows, template=f"({placeholders})")
                print(f"    ✓ Inserted {len(typed_rows)} rows into '{table_name}'")
            except Exception as e:
                print(f"    ✗ Failed to insert into '{table_name}': {e}")
                # Try inserting one by one for debugging
                # for i, row in enumerate(typed_rows[:5]):
                #     try:
                #         cur.execute(f"INSERT INTO {table_name} ({col_names}) VALUES ({placeholders}) ON CONFLICT DO NOTHING;", row)
                #     except Exception as e2:
                #         print(f"      Row {i}: {e2}")

    def populate_structured_data(self, max_claims: int = None):
        """Read CSVs and insert into corresponding PostgreSQL tables.
        
        If max_claims is set, claim_submissions/pre_auth_requests/clinical_records/claim_bills
        are capped to the most recent max_claims claim rows. Reference tables (policy_master,
        policy_members, network_hospitals, provider_registry) are always fully loaded.
        
        claim_submissions_training is always loaded from data/raw/training/ (full dataset,
        never capped) — this is what the fraud model trains on in Databricks.
        """
        print("\n--- Populating Structured Data ---")

        # Always load reference/training tables in full
        reference_tables = [
            ("network_hospitals", "network_hospitals.csv"),
            ("provider_registry", "provider_registry.csv"),
            ("policy_master", "policy_master.csv"),
            ("policy_members", "policy_members.csv"),
        ]
        for table_name, csv_filename in reference_tables:
            csv_path = os.path.join(self.data_dir, csv_filename)
            print(f"  Processing {table_name} from {csv_filename}...")
            rows = self._csv_to_rows(csv_path)
            if rows:
                self._insert_table(table_name, rows)
            else:
                print(f"    ⚠ No data to insert")

        # Load claim submissions — optionally cap to max_claims (most recent)
        claims_rows = self._csv_to_rows(os.path.join(self.data_dir, "claim_submissions.csv"))
        if max_claims and len(claims_rows) > max_claims:
            claims_rows = sorted(claims_rows, key=lambda r: r.get("date_of_loss", ""), reverse=True)[:max_claims]
            print(f"  [Cap] claim_submissions limited to {max_claims} most recent rows")
        kept_claim_ids = {r["claim_id"] for r in claims_rows}

        print(f"  Processing claim_submissions ({len(claims_rows)} rows)...")
        self._insert_table("claim_submissions", claims_rows)

        # Load linked tables — only rows whose claim_id is in kept_claim_ids
        linked_tables = [
            ("pre_auth_requests", "pre_auth_requests.csv"),
            ("clinical_records", "clinical_records.csv"),
            ("claim_bills", "claim_bills.csv"),
        ]
        for table_name, csv_filename in linked_tables:
            csv_path = os.path.join(self.data_dir, csv_filename)
            print(f"  Processing {table_name} from {csv_filename}...")
            rows = self._csv_to_rows(csv_path)
            if max_claims:
                rows = [r for r in rows if r.get("claim_id") in kept_claim_ids]
                print(f"    [Cap] {table_name} filtered to {len(rows)} rows linked to {max_claims} claims")
            if rows:
                self._insert_table(table_name, rows)
            else:
                print(f"    ⚠ No data to insert")

        # ----------------------------------------------------------------
        # Load claim_submissions_training — FULL dataset, never capped.
        # Reads from data/raw/training/ if it exists (written by generator
        # when --max-inference-claims is used), otherwise falls back to the
        # standard claim_submissions.csv (same as inference batch).
        # ----------------------------------------------------------------
        print(f"\n  Processing claim_submissions_training (full training set)...")
        training_csv = os.path.join(os.path.dirname(self.data_dir), "training", "claim_submissions_training.csv")
        if os.path.exists(training_csv):
            training_rows = self._csv_to_rows(training_csv)
            # Strip the _training suffix — same schema as claim_submissions
            fraud_count = sum(1 for r in training_rows if str(r.get("is_fraud", "0")) == "1")
            print(f"    Found training CSV: {len(training_rows)} rows, {fraud_count} fraud labels")
            self._insert_table("claim_submissions_training", training_rows)
        else:
            # Fallback: copy from claim_submissions (same inference batch)
            print(f"    Training CSV not found at {training_csv}")
            print(f"    Falling back to claim_submissions.csv ({len(claims_rows)} rows)")
            print(f"    TIP: Run generate_synthetic_data.py with --max-inference-claims to get separate training data")
            self._insert_table("claim_submissions_training", claims_rows)

    # =====================================================================
    # Unstructured Data (Supabase Storage Buckets)
    # =====================================================================

    def _ensure_bucket(self, bucket_name: str, public: bool = False):
        """Create a storage bucket if it doesn't exist."""
        try:
            # Check if bucket exists
            buckets = self.supabase.storage.list_buckets()
            existing = [b.name for b in buckets]
            if bucket_name in existing:
                print(f"  ✓ Bucket '{bucket_name}' already exists")
                return
        except Exception:
            pass

        try:
            self.supabase.storage.create_bucket(id=bucket_name, name=bucket_name, options={"public": public})
            print(f"  ✓ Created bucket '{bucket_name}'")
        except Exception as e:
            print(f"  ✗ Failed to create bucket '{bucket_name}': {e}")

    def _upload_file(self, bucket_name: str, local_path: str, remote_path: str):
        """Upload a single file to Supabase Storage."""
        if not os.path.exists(local_path):
            print(f"    WARNING: {local_path} not found. Skipping.")
            return False

        try:
            with open(local_path, "rb") as f:
                self.supabase.storage.from_(bucket_name).upload(
                    path=remote_path,
                    file=f,
                    file_options={"content-type": self._get_mime_type(local_path)}
                )
            return True
        except Exception as e:
            # If file already exists, it may throw an error
            error_str = str(e).lower()
            if "already exists" in error_str or "duplicate" in error_str:
                return True
            print(f"    ✗ Failed to upload {local_path}: {e}")
            return False

    def _get_mime_type(self, filepath: str) -> str:
        ext = os.path.splitext(filepath)[1].lower()
        mime_map = {
            ".pdf": "application/pdf",
            ".txt": "text/plain",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".json": "application/json",
        }
        return mime_map.get(ext, "application/octet-stream")

    def upload_discharge_summaries(self):
        """Upload discharge summary PDFs to Storage bucket."""
        bucket_name = "claim-discharges"
        self._ensure_bucket(bucket_name, public=False)

        print(f"\n--- Uploading Discharge Summaries to '{bucket_name}' ---")
        if not os.path.exists(self.discharge_dir):
            print(f"  WARNING: Directory '{self.discharge_dir}' not found.")
            return

        files = [f for f in os.listdir(self.discharge_dir)
                 if f.endswith((".pdf", ".txt")) and "discharge" in f.lower()]
        if not files:
            files = [f for f in os.listdir(self.discharge_dir)
                     if f.endswith((".pdf", ".txt"))]

        uploaded = 0
        for filename in sorted(files)[:100]:
            local_path = os.path.join(self.discharge_dir, filename)
            # Store under "discharge-summaries/" folder inside the bucket
            remote_path = f"discharge-summaries/{filename}"
            if self._upload_file(bucket_name, local_path, remote_path):
                uploaded += 1

        print(f"  ✓ Uploaded {uploaded} discharge summary files")

    def upload_hospital_bills(self):
        """Upload hospital bill documents to Storage bucket."""
        bucket_name = "claim-bills"
        self._ensure_bucket(bucket_name, public=False)

        print(f"\n--- Uploading Hospital Bills to '{bucket_name}' ---")
        if not os.path.exists(self.bills_dir):
            print(f"  WARNING: Directory '{self.bills_dir}' not found.")
            return

        files = [f for f in os.listdir(self.bills_dir)
                 if f.endswith((".pdf", ".jpg", ".jpeg", ".png"))]

        uploaded = 0
        for filename in sorted(files):
            local_path = os.path.join(self.bills_dir, filename)
            # Store under "hospital-bills/" folder inside the bucket
            remote_path = f"hospital-bills/{filename}"
            if self._upload_file(bucket_name, local_path, remote_path):
                uploaded += 1

        print(f"  ✓ Uploaded {uploaded} hospital bill files")

    def upload_policy_forms(self):
        """Upload policy form documents to Storage bucket."""
        bucket_name = "policy-forms"
        self._ensure_bucket(bucket_name, public=False)

        print(f"\n--- Uploading Policy Forms to '{bucket_name}' ---")
        if not os.path.exists(self.policy_forms_dir):
            print(f"  WARNING: Directory '{self.policy_forms_dir}' not found.")
            return

        files = [f for f in os.listdir(self.policy_forms_dir)
                 if f.endswith((".txt", ".json"))]

        uploaded = 0
        for filename in sorted(files):
            local_path = os.path.join(self.policy_forms_dir, filename)
            # Store under "policy-forms/" folder inside the bucket
            # (matches the prefix the bronze notebook lists with)
            remote_path = f"policy-forms/{filename}"
            if self._upload_file(bucket_name, local_path, remote_path):
                uploaded += 1

        print(f"  ✓ Uploaded {uploaded} policy form files")

    # =====================================================================
    # Cleanup
    # =====================================================================

    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()
            print("\n  ✓ Database connection closed.")

    # =====================================================================
    # Main Entry Point
    # =====================================================================

    def run(self, skip_truncate: bool = False, max_claims: int = None):
        """Execute the full population pipeline."""
        print(f"\n{'='*60}")
        print(f"Supabase Population Script")
        print(f"URL: {self.supabase_url}")
        if max_claims:
            print(f"Mode: FAST RUN — claim tables capped to {max_claims} rows")
            print(f"      (policy_master, policy_members, hospitals, providers: FULL)")
        print(f"{'='*60}")

        # Step 1: Create tables (idempotent)
        self.create_tables()

        # Step 2: Optionally truncate
        if not skip_truncate:
            self.truncate_tables()

        # Step 3: Insert structured data
        self.populate_structured_data(max_claims=max_claims)

        # Step 4: Upload unstructured docs to Storage
        self.upload_discharge_summaries()
        self.upload_hospital_bills()
        self.upload_policy_forms()

        # Done
        self.close()

        print(f"\n{'='*60}")
        print(f"✓ Population Complete!")
        print(f"{'='*60}")


# =========================================================================
# Main
# =========================================================================

def find_repo_root():
    """Find the repo root directory."""
    if os.path.exists("../notebooks") and os.path.exists("../data"):
        return ".."
    elif os.path.exists("./notebooks") and os.path.exists("./data"):
        return "."
    return "."


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Populate Supabase with synthetic health claims data")
    parser.add_argument("--data-dir", type=str, default=None,
                        help="Path to structured CSV directory (relative to repo root)")
    parser.add_argument("--discharge-dir", type=str, default=None,
                        help="Path to discharge summary files directory")
    parser.add_argument("--bills-dir", type=str, default=None,
                        help="Path to hospital bills directory")
    parser.add_argument("--policy-forms-dir", type=str, default=None,
                        help="Path to policy form documents directory")
    parser.add_argument("--skip-truncate", action="store_true",
                        help="Skip truncating existing data before insert")
    parser.add_argument("--url", type=str, default=None,
                        help="Supabase URL (overrides env var)")
    parser.add_argument("--key", type=str, default=None,
                        help="Supabase service role key (overrides env var)")
    parser.add_argument(
        "--max-claims",
        type=int,
        default=None,
        help=(
            "Cap claim_submissions/pre_auth/clinical_records/claim_bills to this many rows "
            "(most recent by date_of_loss). policy_master, policy_members, network_hospitals, "
            "provider_registry are always fully loaded. Example: --max-claims 25"
        )
    )
    args = parser.parse_args()

    # Get credentials
    supabase_url = args.url or os.environ.get("SUPABASE_URL")
    service_key = args.key or os.environ.get("SUPABASE_SERVICE_KEY")

    if not supabase_url or not service_key:
        print("ERROR: Supabase URL and Service Key are required.")
        print("Set SUPABASE_URL and SUPABASE_SERVICE_KEY in .env file or pass --url and --key.")
        sys.exit(1)

    # Resolve directories relative to repo root
    repo_root = find_repo_root()
    data_dir = args.data_dir or os.path.join(repo_root, "data/raw/structured")
    discharge_dir = args.discharge_dir or os.path.join(repo_root, "data/raw/unstructured")
    bills_dir = args.bills_dir or os.path.join(repo_root, "data/raw/bills")
    policy_forms_dir = args.policy_forms_dir or os.path.join(repo_root, "data/policy_forms")

    # Verify directories exist
    for name, d in [("Data", data_dir), ("Discharge", discharge_dir),
                    ("Bills", bills_dir), ("Policy Forms", policy_forms_dir)]:
        if not os.path.exists(d):
            print(f"WARNING: {name} directory '{d}' does not exist. Some uploads may be skipped.")

    populator = SupabasePopulator(
        supabase_url=supabase_url,
        service_key=service_key,
        data_dir=data_dir,
        discharge_dir=discharge_dir,
        bills_dir=bills_dir,
        policy_forms_dir=policy_forms_dir,
    )

    populator.run(skip_truncate=args.skip_truncate, max_claims=args.max_claims)