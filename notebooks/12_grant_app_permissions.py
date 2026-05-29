# Databricks notebook source
# MAGIC %md
# MAGIC # Grant Permissions to Databricks App
# MAGIC 
# MAGIC Databricks Apps run under a dedicated "Service Principal" identity. This Service Principal does not inherit your personal permissions.
# MAGIC To allow the app to query the `health_claims_dev` database, you must explicitly grant it permission.
# MAGIC 
# MAGIC ### Instructions:
# MAGIC 1. Go to your Databricks App's dashboard (where you click Deploy).
# MAGIC 2. Look at the **Overview** tab.
# MAGIC 3. Find the **Service Principal** field and copy the long ID (it looks like a UUID, e.g., `9e1aa229-...`).
# MAGIC 4. Paste that ID over `<YOUR-SP-ID>` in the SQL commands below (Keep the backticks around it!).
# MAGIC 5. Click **Run Cell**!

# COMMAND ----------

# MAGIC %sql
# MAGIC GRANT USE CATALOG ON CATALOG health_claims_dev TO `<YOUR-SP-ID>`;
# MAGIC 
# MAGIC GRANT USE SCHEMA ON SCHEMA health_claims_dev.claims TO `<YOUR-SP-ID>`;
# MAGIC GRANT USE SCHEMA ON SCHEMA health_claims_dev.audit TO `<YOUR-SP-ID>`;
# MAGIC 
# MAGIC -- Give read access to all tables so the AI Agents can cross-validate policies
# MAGIC GRANT SELECT ON SCHEMA health_claims_dev.claims TO `<YOUR-SP-ID>`;
# MAGIC GRANT SELECT ON SCHEMA health_claims_dev.audit TO `<YOUR-SP-ID>`;
# MAGIC 
# MAGIC -- Give write access to the specific tables the app updates
# MAGIC GRANT MODIFY ON TABLE health_claims_dev.claims.gold_claim_decisions TO `<YOUR-SP-ID>`;
# MAGIC GRANT MODIFY ON TABLE health_claims_dev.audit.adjuster_decisions TO `<YOUR-SP-ID>`;
