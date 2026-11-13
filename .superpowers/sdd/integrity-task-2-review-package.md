diff --git a/backend/.env.example b/backend/.env.example
index f001350..45716a5 100644
--- a/backend/.env.example
+++ b/backend/.env.example
@@ -2,20 +2,26 @@
 # condensed: legacy page-fit to RESUME_TARGET_PAGES plus optional LLM polish.
 RESUME_OUTPUT_MODE=faithful
 # Optional. Only used when RESUME_OUTPUT_MODE=condensed and RESUME_LLM_CONDENSE=true.
 AWS_BEARER_TOKEN_BEDROCK=
 AWS_REGION=ap-south-1
 BEDROCK_MODEL=google.gemma-3-27b-it
 LLM_MAX_TOKENS=2048
 RESUME_GENERATION_MAX_TOKENS=16384
 RESUME_TARGET_PAGES=5.0
 RESUME_LLM_CONDENSE=false
+# Post-integrity Bedrock recovery; runs only when AWS_BEARER_TOKEN_BEDROCK is set.
+RESUME_INTEGRITY_RECOVERY=true
+# Maximum Bedrock calls allowed for one integrity recovery.
+RESUME_INTEGRITY_RECOVERY_MAX_CALLS=4
+# Timeout in seconds for each integrity recovery Bedrock call.
+RESUME_INTEGRITY_RECOVERY_TIMEOUT_SECONDS=45.0
 # OCR for scanned PDF pages; needs `tesseract-ocr` installed (Dockerfile/setup-ec2.sh do this).
 RESUME_OCR_ENABLED=true
 RESUME_OCR_MAX_PAGES=10
 RESUME_OCR_DPI=200
 RESUME_OCR_LANG=eng
 APP_BUILD_ID=dev
 # Optional slow multi-pass polish. Section quality gate already repairs critical issues.
 RESUME_LLM_POLISH=false
 # Multi-agent pipeline: extract -> plan -> write -> critique -> refine (best draft ships).
 RESUME_AGENT_PIPELINE=false
diff --git a/backend/app/core/config.py b/backend/app/core/config.py
index e284f47..f5d4dd6 100644
--- a/backend/app/core/config.py
+++ b/backend/app/core/config.py
@@ -29,20 +29,24 @@ class Settings(BaseSettings):
     RESUME_OCR_LANG: str = "eng"
     # Optional deploy stamp so /api/health can prove which build is live.
     APP_BUILD_ID: str = "dev"
     # When false (default), skip slow full-document LLM polish loops.
     RESUME_LLM_POLISH: bool = False
     # Optional one-shot, source-checked LLM structure repair when the deterministic parse is
     # weak. Golden/scored CI forces it off (deterministic). Rejected output is discarded.
     # Accuracy-first: eligible weak parses may call Bedrock once (source-checked). Golden CI forces off.
     RESUME_LLM_PARSE_FALLBACK: bool = True
     RESUME_LLM_PARSE_TIMEOUT_SECONDS: float = 45.0
+    # Post-integrity Bedrock recovery is enabled only when a Bedrock token is configured.
+    RESUME_INTEGRITY_RECOVERY: bool = True
+    RESUME_INTEGRITY_RECOVERY_MAX_CALLS: int = 4
+    RESUME_INTEGRITY_RECOVERY_TIMEOUT_SECONDS: float = 45.0
 
     # Multi-agent pipeline (extract -> plan -> write -> critique -> refine).
     # Runs inside the same service; enable per-deploy to compare against classic.
     RESUME_AGENT_PIPELINE: bool = False
     AGENT_MAX_ROUNDS: int = 2
     AGENT_MAX_LLM_CALLS: int = 8
     AGENT_SCORE_THRESHOLD: float = 85.0
     AGENT_TIME_BUDGET_SECONDS: float = 90.0
     INTERVIEW_FALLBACK_MODELS: str = ""
     AWS_BEARER_TOKEN_BEDROCK: str | None = None
diff --git a/backend/tests/test_integrity_recovery.py b/backend/tests/test_integrity_recovery.py
new file mode 100644
index 0000000..192d5cc
--- /dev/null
+++ b/backend/tests/test_integrity_recovery.py
@@ -0,0 +1,7 @@
+from app.core.config import Settings
+
+
+def test_integrity_recovery_settings_defaults():
+    assert Settings.model_fields["RESUME_INTEGRITY_RECOVERY"].default is True
+    assert Settings.model_fields["RESUME_INTEGRITY_RECOVERY_MAX_CALLS"].default == 4
+    assert Settings.model_fields["RESUME_INTEGRITY_RECOVERY_TIMEOUT_SECONDS"].default == 45.0
---
db27de5 feat: add RESUME_INTEGRITY_RECOVERY settings
 backend/.env.example                     | 6 ++++++  backend/app/core/config.py               | 4 ++++  backend/tests/test_integrity_recovery.py | 7 +++++++  3 files changed, 17 insertions(+)
