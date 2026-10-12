package com.sandeep.incidentplatform;

import com.sandeep.incidentplatform.security.Role;
import org.springframework.security.core.GrantedAuthority;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.JwtRequestPostProcessor;

import java.util.Arrays;
import java.util.List;

import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.jwt;

/**
 * MockMvc helper: attaches an already-authenticated JWT to a request, skipping signature
 * checks. Used by tests that are about API behaviour, not about token validation
 * (token validation itself is covered by JwtAuthenticationTest).
 * jwt() does not run our roles converter, so the matching ROLE_ authorities are set explicitly.
 */
final class TestJwt {

    static final String TENANT = "acme";

    private TestJwt() {
    }

    // Default caller: a RESPONDER in tenant "acme" (allowed to call every incident endpoint).
    static JwtRequestPostProcessor asUser() {
        return as(TENANT, Role.RESPONDER);
    }

    static JwtRequestPostProcessor asTenant(String tenantId) {
        return as(tenantId, Role.RESPONDER);
    }

    static JwtRequestPostProcessor as(String tenantId, Role... roles) {
        List<String> roleNames = Arrays.stream(roles).map(Role::name).toList();
        return jwt()
                .jwt(token -> token.subject("alice").claim("tenant_id", tenantId).claim("roles", roleNames))
                .authorities(roleNames.stream()
                        .<GrantedAuthority>map(name -> new SimpleGrantedAuthority("ROLE_" + name))
                        .toList());
    }
}
