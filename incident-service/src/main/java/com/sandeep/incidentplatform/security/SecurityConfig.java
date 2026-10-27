package com.sandeep.incidentplatform.security;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.boot.security.autoconfigure.actuate.web.servlet.EndpointRequest;
import org.springframework.core.annotation.Order;
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
import org.springframework.web.cors.CorsConfiguration;
import org.springframework.web.cors.CorsConfigurationSource;
import org.springframework.web.cors.UrlBasedCorsConfigurationSource;

import java.time.Duration;
import java.util.List;

/**
 * The service is an OAuth2 resource server: it does not log users in, it only validates the
 * JWT bearer token on each request (signature, expiry, issuer). In production the token would
 * come from an identity provider (e.g. Cognito, Keycloak); locally, DevTokenController issues one.
 */
@Configuration
@EnableConfigurationProperties(JwtProperties.class)
public class SecurityConfig {

    public static final String ROLES_CLAIM = "roles";

    /**
     * Actuator endpoints (only health and prometheus are exposed) live on the separate management port
     * (management.server.port), which compose publishes only inside the Docker network for Prometheus.
     * They carry no business data, so they need no JWT; this chain matches ONLY actuator endpoints and
     * runs first, and the API chain below is unchanged. On the API port /actuator/** does not exist (404).
     */
    @Bean
    @Order(1)
    SecurityFilterChain managementSecurityFilterChain(HttpSecurity http) throws Exception {
        http
                .securityMatcher(EndpointRequest.toAnyEndpoint())
                .csrf(AbstractHttpConfigurer::disable)
                .sessionManagement(session -> session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                .authorizeHttpRequests(auth -> auth.anyRequest().permitAll());
        return http.build();
    }

    @Bean
    @Order(2)
    SecurityFilterChain securityFilterChain(HttpSecurity http,
                                            @Value("${app.cors.allowed-origins:}") List<String> corsOrigins)
            throws Exception {
        boolean corsEnabled = corsOrigins.stream().anyMatch(origin -> !origin.isBlank());
        http
                // Stateless API authenticated by a bearer token, not a cookie, so CSRF does not apply.
                .csrf(AbstractHttpConfigurer::disable)
                // CORS (milestone 4B) only when an origin is configured (corsConfigurationSource below). Otherwise
                // it stays OFF, exactly as before: same-origin calls through a proxy (whose Host header may differ
                // from the browser's Origin) are never mistaken for cross-origin ones, and browsers still block
                // real cross-origin calls because no Access-Control-Allow-Origin header is ever sent.
                .cors(cors -> {
                    if (!corsEnabled) {
                        cors.disable();
                    }
                })
                .sessionManagement(session -> session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                // Authorization rules in one place (first match wins). No token -> 401; wrong role -> 403.
                .authorizeHttpRequests(auth -> auth
                        .requestMatchers("/api/v1/health", "/error").permitAll()
                        // Only exists when the "dev" profile is active (see DevTokenController).
                        .requestMatchers(HttpMethod.POST, "/api/v1/dev/token").permitAll()
                        .requestMatchers(HttpMethod.GET, "/api/v1/incidents", "/api/v1/incidents/*",
                                        "/api/v1/incidents/*/investigation")
                                .hasAnyRole(Role.VIEWER.name(), Role.RESPONDER.name(), Role.ADMIN.name())
                        .requestMatchers(HttpMethod.POST, "/api/v1/incidents", "/api/v1/incidents/*/investigation/retry")
                                .hasAnyRole(Role.RESPONDER.name(), Role.ADMIN.name())
                        .requestMatchers(HttpMethod.PATCH, "/api/v1/incidents/*/status")
                                .hasAnyRole(Role.RESPONDER.name(), Role.ADMIN.name())
                        .anyRequest().authenticated())
                .oauth2ResourceServer(oauth2 -> oauth2.jwt(jwt -> jwt.jwtAuthenticationConverter(rolesConverter())));
        return http.build();
    }

    /**
     * CORS (milestone 4B, web UI). The UI is normally served from the SAME origin as the API (nginx proxies /api in
     * compose/k8s; the Vite dev server proxies /api too), so no cross-origin call happens and this list stays EMPTY
     * (CORS processing off, see the API chain). Only when the UI runs on its own origin against the API directly (e.g.
     * http://localhost:5173 -> http://localhost:8080) is that one origin listed, via CORS_ALLOWED_ORIGINS.
     * Bearer tokens only, no cookies: allowCredentials stays false.
     */
    @Bean
    CorsConfigurationSource corsConfigurationSource(
            @Value("${app.cors.allowed-origins:}") List<String> allowedOrigins) {
        CorsConfiguration config = new CorsConfiguration();
        config.setAllowedOrigins(allowedOrigins.stream().filter(origin -> !origin.isBlank()).toList());
        config.setAllowedMethods(List.of("GET", "POST", "PATCH"));
        config.setAllowedHeaders(List.of("Authorization", "Content-Type", "X-Request-Id"));
        // Readable by the UI: the request id (shown on errors) and Retry-After (polling and 429/503 back-off).
        config.setExposedHeaders(List.of("X-Request-Id", "Retry-After"));
        config.setMaxAge(Duration.ofHours(1));
        UrlBasedCorsConfigurationSource source = new UrlBasedCorsConfigurationSource();
        source.registerCorsConfiguration("/api/**", config);
        return source;
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
