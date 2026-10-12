package com.sandeep.incidentplatform.security;

/**
 * Roles carried in the JWT "roles" claim. Spring Security sees them as authorities with the
 * ROLE_ prefix (ROLE_VIEWER, ...), which is what hasRole/hasAnyRole check.
 * <ul>
 *   <li>VIEWER: read incidents</li>
 *   <li>RESPONDER: read, create incidents and change their status</li>
 *   <li>ADMIN: everything a responder can do; reserved for future admin-only operations</li>
 * </ul>
 */
public enum Role {
    VIEWER,
    RESPONDER,
    ADMIN
}
