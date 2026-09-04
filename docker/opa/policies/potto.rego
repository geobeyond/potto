# Potto authorization policy.
#
# This policy mirrors the logic of the LocalAuthorizationBackend and serves as a
# starting point for customisation. Potto queries five rules:
#
#   potto/authz/can_view_collection        input: {user, collection}  -> boolean
#   potto/authz/can_edit_collection        input: {user, collection}  -> boolean
#   potto/authz/accessible_collection_identifiers  input: {user}      -> [string] | null
#   potto/authz/can_set_user_scopes        input: {user, new_scopes, editable_collection_identifiers} -> boolean
#   potto/authz/can_assign_admin_scope          input: {user}              -> boolean
#   potto/authz/can_change_collection_owner     input: {user, collection}  -> boolean
#   potto/authz/can_create_collection           input: {user}              -> boolean
#
# The user object has: id, username, scopes (list of strings).
# For anonymous (unauthenticated) visitors, user is null.
# The collection object has: identifier, is_public, owner_id.
#
# accessible_collection_identifiers must return null when the user should see all
# collections (e.g. admin), an empty list for anonymous visitors (only public
# collections are shown via the query layer), or a list of identifier
# strings for authenticated users with explicit access.

package potto.authz

import rego.v1

default can_view_collection := false
default can_edit_collection := false

# --- can_view_collection ---

can_view_collection if {
    input.collection.is_public
}

can_view_collection if {
    "admin" in input.user.scopes
}

can_view_collection if {
    input.user.id == input.collection.owner_id
}

can_view_collection if {
    concat("", ["collection-", input.collection.identifier, ":editor"]) in input.user.scopes
}

can_view_collection if {
    concat("", ["collection-", input.collection.identifier, ":viewer"]) in input.user.scopes
}

# --- can_edit_collection ---

can_edit_collection if {
    "admin" in input.user.scopes
}

can_edit_collection if {
    input.user.id == input.collection.owner_id
}

can_edit_collection if {
    concat("", ["collection-", input.collection.identifier, ":editor"]) in input.user.scopes
}

# --- accessible_collection_identifiers ---
#
# Returns null for admins (unrestricted access), [] for anonymous visitors
# (the query layer will then filter by is_public=true), or the list of
# collection identifiers the user has explicit editor/viewer scope for.

accessible_collection_identifiers := [] if {
    input.user == null
}

accessible_collection_identifiers := null if {
    input.user != null
    "admin" in input.user.scopes
}

accessible_collection_identifiers := identifiers if {
    input.user != null
    not "admin" in input.user.scopes
    identifiers := [id |
        some scope in input.user.scopes
        matches := regex.find_all_string_submatch_n(`^collection-(.+):(editor|viewer)$`, scope, 1)
        count(matches) > 0
        id := matches[0][1]
    ]
}

# --- can_set_user_scopes ---
#
# Admins can assign any scope. Non-admins can only assign collection-level
# editor/viewer scopes for collections they can edit (listed in
# editable_collection_identifiers). Anonymous users are always denied.

default can_set_user_scopes := false

can_set_user_scopes if {
    input.user != null
    "admin" in input.user.scopes
}

can_set_user_scopes if {
    input.user != null
    not "admin" in input.user.scopes
    every scope in input.new_scopes {
        matches := regex.find_all_string_submatch_n(`^collection-(.+):(editor|viewer)$`, scope, 1)
        count(matches) > 0
        matches[0][1] in input.editable_collection_identifiers
    }
}

# --- can_assign_admin_scope ---

default can_assign_admin_scope := false

can_assign_admin_scope if {
    input.user != null
    "admin" in input.user.scopes
}

# --- can_change_collection_owner ---

default can_change_collection_owner := false

can_change_collection_owner if {
    input.user != null
    "admin" in input.user.scopes
}

can_change_collection_owner if {
    input.user != null
    input.user.id == input.collection.owner_id
}

# --- can_create_collection ---

default can_create_collection := false

can_create_collection if {
    input.user != null
}
