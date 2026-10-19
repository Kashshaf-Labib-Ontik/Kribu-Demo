package kribu.authz

policy_version := "guard-v1"

default allow := false

decision := {
    "allow": allow,
    "reason_code": reason_code,
    "policy_version": policy_version,
}

default reason_code := "access_denied"

reason_code := "allowed" if allow

allow if {
    valid_input
    input.resource.classification == "internal"
    matching_grant
}

allow if {
    valid_input
    input.resource.classification == "restricted_hr"
    "hr_manager" in input.subject.roles
    matching_grant
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
    input.action == "resource.read"
    input.environment.purpose == "demo_resource_read"
}

matching_grant if {
    some grant in input.resource.grants
    grant.action == input.action
    grant.principal_type == "subject"
    grant.principal_id == input.subject.subject_id
}

matching_grant if {
    some grant in input.resource.grants
    grant.action == input.action
    grant.principal_type == "role"
    grant.principal_id in input.subject.roles
}

matching_grant if {
    some grant in input.resource.grants
    grant.action == input.action
    grant.principal_type == "department"
    is_string(input.subject.department)
    input.subject.department != ""
    grant.principal_id == input.subject.department
    grant.principal_id == input.resource.department
}
