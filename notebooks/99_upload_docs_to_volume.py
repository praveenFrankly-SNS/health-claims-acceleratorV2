# Databricks notebook source
# MAGIC %md
# MAGIC # 99 — Upload Proof Documents to UC Volume
# MAGIC
# MAGIC Copies discharge summaries and hospital bills from the deployed workspace
# MAGIC bundle files into the UC Volume so Agent 1 can read them.
# MAGIC
# MAGIC **Run this once after deploying the bundle.**

# COMMAND ----------

catalog = "health_claims_dev"
schema  = "claims"

# Source: the deployed bundle workspace files
bundle_root = "/Workspace/Users/praveen.v.ihub@snsgroups.com/.bundle/health-claims-accelerator/default/files"

# Destination UC Volumes
discharge_vol = f"/Volumes/{catalog}/{schema}/raw_documents/discharge-summaries"
bills_vol     = f"/Volumes/{catalog}/{schema}/raw_documents/hospital-bills"

# COMMAND ----------

# DBTITLE 1,Create volume directories
import os

dbutils.fs.mkdirs(discharge_vol)
dbutils.fs.mkdirs(bills_vol)
print(f"✓ Volume directories ready")

# COMMAND ----------

# DBTITLE 1,Copy discharge summaries (.txt and .pdf)
src_unstructured = f"{bundle_root}/data/raw/unstructured"

copied = 0
skipped = 0
errors = []

for fname in os.listdir(src_unstructured):
    if "discharge_summary" not in fname:
        continue
    src = os.path.join(src_unstructured, fname)
    dst = os.path.join(discharge_vol, fname)
    try:
        dbutils.fs.cp(f"file:{src}", dst)
        copied += 1
    except Exception as e:
        errors.append(f"{fname}: {e}")
        skipped += 1

print(f"✓ Discharge summaries: {copied} copied, {skipped} skipped")
if errors:
    for err in errors[:5]:
        print(f"  ⚠ {err}")

# COMMAND ----------

# DBTITLE 1,Copy hospital bills (.pdf and .jpg)
src_bills = f"{bundle_root}/data/raw/bills"

copied_bills = 0
skipped_bills = 0

if os.path.exists(src_bills):
    for fname in os.listdir(src_bills):
        src = os.path.join(src_bills, fname)
        dst = os.path.join(bills_vol, fname)
        try:
            dbutils.fs.cp(f"file:{src}", dst)
            copied_bills += 1
        except Exception as e:
            skipped_bills += 1
    print(f"✓ Hospital bills: {copied_bills} copied, {skipped_bills} skipped")
else:
    print(f"Notice: Bills source directory not found at {src_bills}")

# COMMAND ----------

# DBTITLE 1,Verify — list discharge summaries in volume
files = dbutils.fs.ls(discharge_vol)
print(f"\n✓ {len(files)} files now in {discharge_vol}")
for f in files[:10]:
    print(f"  {f.name} ({f.size} bytes)")
if len(files) > 10:
    print(f"  ... and {len(files)-10} more")
