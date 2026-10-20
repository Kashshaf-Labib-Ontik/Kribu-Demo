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

test_policy_version_is_guard_v2 if {
    authz.decision.policy_version == "guard-v2" with input as base_input
}

test_subject_grant_allows_internal_read if {
    resource := object.union(base_input.resource, {
        "classification": "internal",
        "department": "programs",
        "grants": [{"principal_type": "subject", "principal_id": "mike-sub", "action": "resource.read"}],
    })
    authz.decision.allow with input as object.union(base_input, {"resource": resource})
}

test_department_grant_on_other_department_resource_denied if {
    resource := object.union(base_input.resource, {
        "classification": "internal",
        "department": "programs",
        "grants": [{"principal_type": "department", "principal_id": "engineering", "action": "resource.read"}],
    })
    not authz.decision.allow with input as object.union(base_input, {"resource": resource})
}

test_empty_roles_denied if {
    subject := object.union(base_input.subject, {"roles": []})
    resource := object.union(base_input.resource, {
        "classification": "internal",
        "department": "engineering",
        "grants": [{"principal_type": "department", "principal_id": "engineering", "action": "resource.read"}],
    })
    not authz.decision.allow with input as object.union(base_input, {"subject": subject, "resource": resource})
}

test_document_read_purpose_allowed if {
    resource := object.union(base_input.resource, {
        "classification": "internal",
        "department": "engineering",
        "grants": [{"principal_type": "department", "principal_id": "engineering", "action": "resource.read"}],
    })
    authz.decision.allow with input as object.union(base_input, {
        "resource": resource,
        "environment": {"purpose": "document_read"},
    })
}

test_authorized_retrieval_purpose_uses_the_same_read_grant if {
    resource := object.union(base_input.resource, {
        "classification": "internal",
        "department": "engineering",
        "grants": [{"principal_type": "department", "principal_id": "engineering", "action": "resource.read"}],
    })
    authz.decision.allow with input as object.union(base_input, {
        "resource": resource,
        "environment": {"purpose": "authorized_retrieval"},
    })
}

test_read_with_upload_purpose_denied if {
    subject := object.union(base_input.subject, {"roles": ["hr_manager"]})
    not authz.decision.allow with input as object.union(base_input, {
        "subject": subject,
        "environment": {"purpose": "document_upload"},
    })
}

# Upload table (document.create / document.version.create, purpose document_upload).
upload_input(roles, department, classification, resource_department, action) := object.union(base_input, {
    "subject": object.union(base_input.subject, {"roles": roles, "department": department}),
    "action": action,
    "resource": object.union(base_input.resource, {
        "classification": classification,
        "department": resource_department,
        "grants": [],
    }),
    "environment": {"purpose": "document_upload"},
})

test_admin_uploads_any_mapped_classification if {
    every classification in ["internal", "restricted_hr"] {
        authz.decision.allow with input as upload_input(["administrator"], "it", classification, "finance", "document.create")
    }
}

test_admin_cannot_upload_unmapped_classification if {
    not authz.decision.allow with input as upload_input(["administrator"], "it", "top_secret", "finance", "document.create")
}

test_hr_manager_uploads_restricted_hr if {
    authz.decision.allow with input as upload_input(["hr_manager"], "human-resources", "restricted_hr", "human-resources", "document.create")
}

test_hr_manager_cannot_upload_internal_for_other_department if {
    not authz.decision.allow with input as upload_input(["hr_manager"], "human-resources", "internal", "engineering", "document.create")
}

test_employee_uploads_internal_for_own_department if {
    authz.decision.allow with input as upload_input(["employee"], "engineering", "internal", "engineering", "document.create")
}

# New versions: the upload rule plus read access to the existing document.
with_grants(upload, grants) := object.union(upload, {"resource": object.union(upload.resource, {"grants": grants})})

department_read := [{"principal_type": "department", "principal_id": "engineering", "action": "resource.read"}]

hr_read := [{"principal_type": "role", "principal_id": "hr_manager", "action": "resource.read"}]

test_version_requires_read_access if {
    version := upload_input(["employee"], "engineering", "internal", "engineering", "document.version.create")
    not authz.decision.allow with input as version
    authz.decision.allow with input as with_grants(version, department_read)
}

test_version_requires_upload_right_as_well_as_read if {
    version := upload_input(["employee"], "engineering", "internal", "programs", "document.version.create")
    readable := with_grants(version, [{"principal_type": "subject", "principal_id": base_input.subject.subject_id, "action": "resource.read"}])
    not authz.decision.allow with input as readable
}

test_hr_manager_versions_restricted_hr_only_with_read_grant if {
    version := upload_input(["hr_manager"], "human-resources", "restricted_hr", "human-resources", "document.version.create")
    not authz.decision.allow with input as version
    authz.decision.allow with input as with_grants(version, hr_read)
}

test_admin_versions_need_read_grant if {
    version := upload_input(["administrator"], "it", "restricted_hr", "human-resources", "document.version.create")
    not authz.decision.allow with input as version
    not authz.decision.allow with input as with_grants(version, hr_read) # admin is not hr_manager
    admin_read := [{"principal_type": "role", "principal_id": "administrator", "action": "resource.read"}]
    internal := upload_input(["administrator"], "it", "internal", "finance", "document.version.create")
    authz.decision.allow with input as with_grants(internal, admin_read)
}

test_non_read_grant_does_not_count if {
    version := upload_input(["employee"], "engineering", "internal", "engineering", "document.version.create")
    upload_grant := [{"principal_type": "department", "principal_id": "engineering", "action": "document.version.create"}]
    not authz.decision.allow with input as with_grants(version, upload_grant)
}

test_employee_cannot_upload_for_other_department if {
    not authz.decision.allow with input as upload_input(["employee"], "engineering", "internal", "programs", "document.create")
}

test_employee_cannot_upload_restricted_hr if {
    not authz.decision.allow with input as upload_input(["employee"], "human-resources", "restricted_hr", "human-resources", "document.create")
}

test_missing_department_cannot_self_serve if {
    not authz.decision.allow with input as upload_input(["employee"], null, "internal", "engineering", "document.create")
}

test_auditor_never_uploads if {
    not authz.decision.allow with input as upload_input(["auditor"], "engineering", "internal", "engineering", "document.create")
    not authz.decision.allow with input as upload_input(["auditor", "employee"], "engineering", "internal", "engineering", "document.create")
    not authz.decision.allow with input as upload_input(["auditor", "administrator"], "it", "internal", "it", "document.version.create")
}

test_upload_with_read_purpose_denied if {
    upload := upload_input(["administrator"], "it", "internal", "it", "document.create")
    not authz.decision.allow with input as object.union(upload, {"environment": {"purpose": "demo_resource_read"}})
}

test_upload_permission_never_grants_read if {
    upload := upload_input(["administrator"], "it", "restricted_hr", "human-resources", "document.create")
    read := object.union(upload, {"action": "resource.read", "environment": {"purpose": "document_read"}})
    not authz.decision.allow with input as read
}

test_upload_cross_tenant_denied if {
    upload := upload_input(["administrator"], "it", "internal", "it", "document.create")
    resource := object.union(upload.resource, {"tenant_id": "22222222-2222-4222-8222-222222222222"})
    not authz.decision.allow with input as object.union(upload, {"resource": resource})
}
