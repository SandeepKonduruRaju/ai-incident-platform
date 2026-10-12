package com.sandeep.incidentplatform.security;

import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpMethod;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configurers.AbstractHttpConfigurer;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.oauth2.core.DelegatingOAuth2TokenValidator;
import org.springframework.security.oauth2.core.OAuth2TokenValidator;
import org.springframework.security.oauth2.jose.jws.MacAlgorithm;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.security.oauth2.jwt.JwtClaimValidator;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.security.oauth2.jwt.JwtValidators;
import org.springframework.security.oauth2.jwt.NimbusJwtDecoder;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationConverter;
import org.springframework.security.oauth2.server.resource.authentication.JwtGrantedAuthoritiesConverter;
import org.springframework.security.web.SecurityFilterChain;

/**
 * The service is an OAuth2 resource server: it does not log users in, it only validates the
 * JWT bearer token on each request (signature, expiry, issuer). In production the token would
 * come from an identity provider (e.g. Cognito, Keycloak); locally, DevTokenController issues one.
 */
@Configuration
@EnableConfigurationProperties(JwtProperties.class)
public class SecurityConfig {

    public static final String ROLES_CLAIM = "roles";

    @Bean
    SecurityFilterChain securityFilterChain(HttpSecurity http) throws Exception {
        http
                // Stateless API authenticated by a bearer token, not a cookie, so CSRF does not apply.
                .csrf(AbstractHttpConfigurer::disable)
                .sessionManagement(session -> session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                // Authorization rules in one place (first match wins). No token -> 401; wrong role -> 403.
                .authorizeHttpRequests(auth -> auth
                        .requestMatchers("/api/v1/health", "/error").permitAll()
                        // Only exists when the "dev" profile is active (see DevTokenController).
                        .requestMatchers(HttpMethod.POST, "/api/v1/dev/token").permitAll()
                        .requestMatchers(HttpMethod.GET, "/api/v1/incidents", "/api/v1/incidents/*")
                                .hasAnyRole(Role.VIEWER.name(), Role.RESPONDER.name(), Role.ADMIN.name())
                        .requestMatchers(HttpMethod.POST, "/api/v1/incidents")
                                .hasAnyRole(Role.RESPONDER.name(), Role.ADMIN.name())
                        .requestMatchers(HttpMethod.PATCH, "/api/v1/incidents/*/status")
                                .hasAnyRole(Role.RESPONDER.name(), Role.ADMIN.name())
                        .anyRequest().authenticated())
                .oauth2ResourceServer(oauth2 -> oauth2.jwt(jwt -> jwt.jwtAuthenticationConverter(rolesConverter())));
        return http.build();
    }

    // Maps the JWT "roles" claim (e.g. ["VIEWER"]) to authorities (ROLE_VIEWER).
    private static JwtAuthenticationConverter rolesConverter() {
        JwtGrantedAuthoritiesConverter authorities = new JwtGrantedAuthoritiesConverter();
        authorities.setAuthoritiesClaimName(ROLES_CLAIM);
        authorities.setAuthorityPrefix("ROLE_");
        JwtAuthenticationConverter converter = new JwtAuthenticationConverter();
        converter.setJwtGrantedAuthoritiesConverter(authorities);
        return converter;
    }

    @Bean
    JwtDecoder jwtDecoder(JwtProperties properties) {
        NimbusJwtDecoder decoder = NimbusJwtDecoder.withSecretKey(properties.secretKey())
                .macAlgorithm(MacAlgorithm.HS256)
                .build();
        // Checks expiry/not-before (with clock skew), that "iss" matches our issuer, and that the
        // token names a tenant: a token without tenant_id is invalid for this API (401).
        OAuth2TokenValidator<Jwt> requireTenant = new JwtClaimValidator<String>(
                TenantResolver.TENANT_CLAIM, tenant -> tenant != null && !tenant.isBlank());
        decoder.setJwtValidator(new DelegatingOAuth2TokenValidator<>(
                JwtValidators.createDefaultWithIssuer(properties.issuer()), requireTenant));
        return decoder;
    }
}
