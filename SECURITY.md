# Security Policy

## Data Classification
This accelerator processes and handles **Protected Health Information (PHI)** and **Personally Identifiable Information (PII)** including:
- Claimant Names
- ICD-10 Diagnosis Codes
- Claimed Amounts and Reserve Calculations
- Hospital and Treatment information

All tables handling this data (Bronze, Silver, Gold) are tagged with `TBLPROPERTIES ('sensitivity'='PHI', 'classification'='restricted')`. 
At the Silver layer, `claimant_name` is irreversibly hashed using SHA-256 and the plaintext is dropped.

## Unity Catalog Permissions
Deploying this accelerator requires the following privileges in Databricks Unity Catalog:
- `CREATE CATALOG` or `USE CATALOG` on the target catalog
- `CREATE SCHEMA`, `CREATE TABLE`, `CREATE VOLUME`, `CREATE MODEL` on the target schema
- Appropriate privileges to read from Secrets if using a Databricks Secret Scope.

## Secrets Management
**DO NOT hardcode credentials in this repository.** 
The LLM Client (`config/llm_client.py`) requires Databricks or OpenAI tokens.
You must inject these via environment variables or secret scopes:
- `DATABRICKS_HOST`: Your Databricks workspace URL.
- `DATABRICKS_TOKEN`: Your Personal Access Token or Service Principal Token.
- `OPENAI_API_KEY`: Fallback if not using Databricks FMAPI.

In a Databricks Job, set these securely using task parameters or use `dbutils.secrets.get("scope", "key")` directly in the code.

## Vulnerability Reporting
If you discover any security vulnerability in this accelerator, please do not report it in public issues. Contact the security team at `security@example.com` or through the appropriate private channel.
