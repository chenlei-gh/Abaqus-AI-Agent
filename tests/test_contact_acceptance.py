from abaqus_ai_agent.contact_acceptance import contact_acceptance_effect
from abaqus_ai_agent.contracts.contact import ContactDiagnostic, ContactDiagnosticReport


def test_contact_failure_blocks_acceptance():
    report = ContactDiagnosticReport((
        ContactDiagnostic("expected_contact_state", "fail"),
    ))
    failures, warnings = contact_acceptance_effect(report)
    assert failures == ("contact:expected_contact_state:fail",)
    assert warnings == ()


def test_contact_evidence_gap_blocks_acceptance():
    report = ContactDiagnosticReport((
        ContactDiagnostic("contact_evidence_sufficiency", "insufficient_evidence"),
    ))
    failures, warnings = contact_acceptance_effect(report)
    assert failures == ("contact:contact_evidence_sufficiency:insufficient_evidence",)


def test_contact_warning_does_not_block_acceptance():
    report = ContactDiagnosticReport((
        ContactDiagnostic("contact_behavior_consistency", "warning", message="mixed"),
    ))
    failures, warnings = contact_acceptance_effect(report)
    assert failures == ()
    assert warnings == ("contact:contact_behavior_consistency:warning:mixed",)


def test_contact_not_applicable_is_neutral():
    report = ContactDiagnosticReport((
        ContactDiagnostic("unexpected_opening", "not_applicable"),
    ))
    assert contact_acceptance_effect(report) == ((), ())


def test_contact_ambiguous_does_not_become_pass():
    report = ContactDiagnosticReport((
        ContactDiagnostic("contact_evidence_sufficiency", "ambiguous"),
    ))
    failures, _ = contact_acceptance_effect(report)
    assert failures == ("contact:contact_evidence_sufficiency:ambiguous",)
