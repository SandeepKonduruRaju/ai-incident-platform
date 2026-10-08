package com.sandeep.incidentplatform;

import org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.JwtRequestPostProcessor;

import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.jwt;

/**
 * MockMvc helper: attaches an already-authenticated JWT to a request, skipping signature
 * checks. Used by tests that are about API behaviour, not about token validation
 * (token validation itself is covered by JwtAuthenticationTest).
 */
final class TestJwt {

    private TestJwt() {
    }

    static JwtRequestPostProcessor asUser() {
        return jwt().jwt(token -> token.subject("alice"));
    }
}
