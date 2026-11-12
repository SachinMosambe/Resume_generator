from app.core.config import Settings


def test_integrity_recovery_settings_defaults():
    assert Settings.model_fields["RESUME_INTEGRITY_RECOVERY"].default is True
    assert Settings.model_fields["RESUME_INTEGRITY_RECOVERY_MAX_CALLS"].default == 4
    assert Settings.model_fields["RESUME_INTEGRITY_RECOVERY_TIMEOUT_SECONDS"].default == 45.0
