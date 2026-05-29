# Model Card: Health Claims Accelerator ML Models

This model card details the two machine learning models integrated within the **Health Claims Multi-Agent Accelerator**: the **Fraud Detection Classifier (XGBoost)** and the **Reserve Estimation Quantile Regression Models (Gradient Boosting Regressors)**.

---

## 1. Fraud Detection Model

### 1.1 Model Overview
- **Model Type**: XGBoost Classifier (`XGBClassifier`)
- **Version**: 1.0.0
- **Governing Layer**: Unity Catalog registered under `health_claims_dev.claims.fraud_detection_xgboost`
- **Framework**: `xgboost` v1.7+, logged using `mlflow.xgboost`

### 1.2 Intended Use
- **Primary Function**: To analyze structured features of incoming health claims and provide a predicted probability of the claim being fraudulent or anomalous.
- **Target Users**: Health claims adjusters, special investigation units (SIU), and clinical auditors.
- **Safety Warning & Guardrails**: 
  > [!IMPORTANT]
  > **Decision Support Only — Human-in-the-Loop Required.** 
  > Under health insurance regulations (e.g., IRDAI in India, NAIC in the US, FCA in the UK), automated claim denials solely based on machine learning scoring are strictly prohibited. The fraud score is an advisory recommendation only. Claims with elevated fraud scores must be routed to human adjusters/SIU for investigation.

### 1.3 Model Features
The model is trained on a set of 4 structured operational features:
1. `claimed_amount` (numeric): The total currency amount claimed for the medical event.
2. `amount_to_premium_ratio` (numeric): The ratio of the claimed amount to the annual premium paid. High ratios can indicate inflated claim sizes.
3. `days_since_inception` (numeric): The duration in days between the policy active start date and the date of loss. Early claims (under 30 days) are high-risk indicators.
4. `claim_velocity` (numeric): The number of prior claims filed by the same policyholder within the past 90 days. High velocity is a classic health fraud pattern (e.g., duplicate billing, multi-hospital claims).

### 1.4 Training Data Details
- **Source**: Synthetically generated claims dataset using ACORD health insurance industry schemas.
- **Size**: 500 rows of structured claims.
- **Class Balance**: 15% fraud rate (deliberate injection of high-velocity, early-claim, and inflated-amount fraud patterns).
- **Validation**: 80/20 train-test split.

### 1.5 Evaluation Metrics (Test Set Results)
- **Accuracy**: ~0.90+ (Standard classification accuracy on test split)
- **Precision**: ~0.85+ (High precision to avoid unnecessary false-positive fraud reviews)
- **Recall**: ~0.80+ (Captures the majority of injected fraud patterns)
- **F1-Score**: ~0.82+

---

## 2. Reserve Estimation Model

### 2.1 Model Overview
- **Model Type**: Quantile Gradient Boosting Regressor (`GradientBoostingRegressor`)
- **Version**: 1.0.0
- **Governing Layer**: Unity Catalog registered under `health_claims_dev.claims.reserve_estimation_gbm`
- **Framework**: `scikit-learn` v1.2+, logged using `mlflow.sklearn`

### 2.2 Intended Use
- **Primary Function**: To predict the required financial reserve amount to allocate for a newly admitted claim.
- **Target Users**: Actuaries, financial controllers, and claim operations managers.
- **Key Outcome**: Automates initial reserve provisioning (within minutes of FNOL) with statistical confidence bands, reducing capital lockup compared to slow, manual actuarial estimates.

### 2.3 Model Features & Architecture
Rather than a single point estimate, the reserve agent runs a multi-model quantile ensemble:
- **Features Used**: `diagnosis_icd` (categorical ICD-10 codes).
- **Quantiles Modeled**:
  - **P10 (Low-band)**: 10% chance the actual settlement is below this estimate. Trained using `loss='quantile', alpha=0.1`.
  - **P50 (Median Point Estimate)**: The standard expected reserve amount. Trained using `loss='quantile', alpha=0.5`.
  - **P90 (High-band)**: 90% chance the actual settlement is below this estimate. Trained using `loss='quantile', alpha=0.9`.

### 2.4 Training Data Details
- **Source**: Historical claims history CSV (`claims_history.csv`) representing past settled claims.
- **Categorical Mappings**: Handled dynamically using `sklearn`'s `OneHotEncoder(handle_unknown='ignore')` wrapped inside a pipeline preprocessor.

### 2.5 Evaluation Metrics
- **Mean Absolute Error (MAE)**: Logged as a primary evaluation metric to track reserve estimation deviation from historical settlement baselines.
- **Out-of-Distribution Handling**: Graceful fallback to the claimed amount is integrated at runtime if the category is completely unseen.

---

## 3. Known Limitations and Bias
- **Synthetic Data Limitations**: The models are currently trained on synthetic data representing simulated health claim fields. While ideal for demonstrating UC integration and pipeline workflows, the models **MUST** be retrained on real historical carrier datasets before production deployment.
- **Sparsity of Diagnosis Codes**: The reserve estimation model currently relies primarily on ICD diagnosis codes (`diagnosis_icd`) to determine severity. In real production, this feature set must be enriched with age, gender, hospital tier, and pre-existing condition indicators to reduce estimation variance.
