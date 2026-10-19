package kribu.authz_test

import data.kribu.authz

base_input := {
    "subject": {
        "tenant_id": "11111111-1111-4111-8111-111111111111",
        "subject_id": "mike-sub",
        "roles": ["employee"],
        "department": "engineering",
    },
    "action": "resource.read",
    "resource": {
        "tenant_id": "11111111-1111-4111-8111-111111111111",
        "resource_type": "employee_record",
        "classification": "restricted_hr",
        "department": "human-resources",
        "grants": [{"principal_type": "role", "principal_id": "hr_manager", "action": "resource.read"}],
    },
    "environment": {"purpose": "demo_resource_read"},
}

test_mike_cannot_read_salary if {
    not authz.decision.allow with input as base_input
}

test_hr_manager_can_read_salary if {
    subject := object.union(base_input.subject, {"roles": ["hr_manager"]})
    authz.decision.allow with input as object.union(base_input, {"subject": subject})
}

test_manager_cannot_read_salary if {
    subject := object.union(base_input.subject, {"roles": ["manager"]})
    not authz.decision.allow with input as object.union(base_input, {"subject": subject})
}

test_admin_cannot_read_salary if {
    subject := object.union(base_input.subject, {"roles": ["administrator"]})
    not authz.decision.allow with input as object.union(base_input, {"subject": subject})
}

test_auditor_cannot_read_salary if {
    subject := object.union(base_input.subject, {"roles": ["auditor"]})
    not authz.decision.allow with input as object.union(base_input, {"subject": subject})
}

test_cross_tenant_denied if {
    subject := object.union(base_input.subject, {"roles": ["hr_manager"]})
    resource := object.union(base_input.resource, {"tenant_id": "22222222-2222-4222-8222-222222222222"})
    not authz.decision.allow with input as object.union(base_input, {"subject": subject, "resource": resource})
}

test_missing_acl_denied if {
    subject := object.union(base_input.subject, {"roles": ["hr_manager"]})
    resource := object.union(base_input.resource, {"grants": []})
    not authz.decision.allow with input as object.union(base_input, {"subject": subject, "resource": resource})
}

test_unknown_classification_denied if {
    subject := object.union(base_input.subject, {"roles": ["hr_manager"]})
    resource := object.union(base_input.resource, {"classification": "unknown"})
    not authz.decision.allow with input as object.union(base_input, {"subject": subject, "resource": resource})
}

test_missing_subject_denied if {
    subject := object.remove(base_input.subject, {"subject_id"})
    not authz.decision.allow with input as object.union(base_input, {"subject": subject})
}

test_department_grant_for_internal if {
    resource := object.union(base_input.resource, {
        "classification": "internal",
        "department": "engineering",
        "grants": [{"principal_type": "department", "principal_id": "engineering", "action": "resource.read"}],
    })
    authz.decision.allow with input as object.union(base_input, {"resource": resource})
}

test_other_department_denied if {
    resource := object.union(base_input.resource, {
        "classification": "internal",
        "department": "programs",
        "grants": [{"principal_type": "department", "principal_id": "programs", "action": "resource.read"}],
    })
    not authz.decision.allow with input as object.union(base_input, {"resource": resource})
}

test_unknown_action_denied if {
    not authz.decision.allow with input as object.union(base_input, {"action": "resource.delete"})
}
