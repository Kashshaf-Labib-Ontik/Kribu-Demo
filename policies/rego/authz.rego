package kribu.authz

policy_version := "guard-v2"

default allow := false

decision := {
    "allow": allow,
    "reason_code": reason_code,
    "policy_version": policy_version,
}

default reason_code := "access_denied"

reason_code := "allowed" if allow

# Each action is only valid for its own declared purposes.
action_purposes := {
    "resource.read": {"demo_resource_read", "document_read", "authorized_retrieval"},
    "document.create": {"document_upload"},
    "document.version.create": {"document_upload"},
}

mapped_classifications := {"internal", "restricted_hr"}

allow if {
    valid_input
    input.action == "resource.read"
    may_read
}

# Uploads never grant reads. Auditors stay read-only observers regardless of other roles.
allow if {
    valid_input
    input.action == "document.create"
    not "auditor" in input.subject.roles
    may_upload
}

# A new version changes what readers see, so only people who can already read it may add one.
allow if {
    valid_input
    input.action == "document.version.create"
    not "auditor" in input.subject.roles
    may_upload
    may_read
}

# Reads: always an explicit ACL grant; restricted HR also needs the HR manager role.
may_read if {
    input.resource.classification == "internal"
    read_grant
}

may_read if {
    input.resource.classification == "restricted_hr"
    "hr_manager" in input.subject.roles
    read_grant
}

may_upload if {
    "administrator" in input.subject.roles
    input.resource.classification in mapped_classifications
}

may_upload if {
    "hr_manager" in input.subject.roles
    input.resource.classification == "restricted_hr"
}

# Department self-service: internal documents for the subject's own (database) department.
may_upload if {
    input.resource.classification == "internal"
    is_string(input.subject.department)
    input.subject.department != ""
    input.subject.department == input.resource.department
}

valid_input if {
    is_string(input.subject.subject_id)
    input.subject.subject_id != ""
    is_string(input.subject.tenant_id)
    input.subject.tenant_id != ""
    input.subject.tenant_id == input.resource.tenant_id
    is_array(input.subject.roles)
    count(input.subject.roles) > 0
    is_string(input.resource.resource_type)
    input.resource.resource_type != ""
    is_array(input.resource.grants)
    input.environment.purpose in action_purposes[input.action]
}

read_grant if {
    some grant in input.resource.grants
    grant.action == "resource.read"
    grant.principal_type == "subject"
    grant.principal_id == input.subject.subject_id
}

read_grant if {
    some grant in input.resource.grants
    grant.action == "resource.read"
    grant.principal_type == "role"
    grant.principal_id in input.subject.roles
}

read_grant if {
    some grant in input.resource.grants
    grant.action == "resource.read"
    grant.principal_type == "department"
    is_string(input.subject.department)
    input.subject.department != ""
    grant.principal_id == input.subject.department
    grant.principal_id == input.resource.department
}
