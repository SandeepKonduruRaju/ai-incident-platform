package com.sandeep.incidentplatform.security;

import org.springframework.security.oauth2.jwt.Jwt;

/**
 * Reads the caller's tenant from the verified JWT. Tokens without a tenant are already rejected
 * by the JwtDecoder (see SecurityConfig); this check is a second line of defence.
 */
public final class TenantResolver {

    public static final String TENANT_CLAIM = "tenant_id";

    private TenantResolver() {
    }

    public static String tenantOf(Jwt jwt) {
        String tenantId = jwt == null ? null : jwt.getClaimAsString(TENANT_CLAIM);
        if (tenantId == null || tenantId.isBlank()) {
            throw new MissingTenantException();
        }
        return tenantId;
    }
}
