package com.sandeep.incidentplatform;

import com.nimbusds.jose.jwk.source.ImmutableSecret;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.http.HttpHeaders;
import org.springframework.security.oauth2.jose.jws.MacAlgorithm;
import org.springframework.security.oauth2.jwt.JwsHeader;
import org.springframework.security.oauth2.jwt.JwtClaimsSet;
import org.springframework.security.oauth2.jwt.JwtEncoderParameters;
import org.springframework.security.oauth2.jwt.NimbusJwtEncoder;
import org.springframework.test.web.servlet.MockMvc;

import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.Instant;
import java.util.List;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * Token validation end to end with real signed JWTs (full context, H2): only a token signed with
 * our secret, issued by us and not expired is accepted.
 */
@SpringBootTest
@AutoConfigureMockMvc
class JwtAuthenticationTest {

    private static final String SECRET = "test-only-jwt-secret-0123456789abcdef"; // matches test properties
    private static final String ISSUER = "incident-platform";

    @Autowired
    private MockMvc mockMvc;

    @Test
    void shouldReturn401WithoutToken() throws Exception {
        mockMvc.perform(get("/api/v1/incidents"))
                .andExpect(status().isUnauthorized())
                .andExpect(header().exists(HttpHeaders.WWW_AUTHENTICATE));
    }

    @Test
    void shouldAllowHealthWithoutToken() throws Exception {
        mockMvc.perform(get("/api/v1/health"))
                .andExpect(status().isOk());
    }

    @Test
    void shouldAcceptValidToken() throws Exception {
        String token = token(SECRET, ISSUER, Instant.now().plus(Duration.ofMinutes(5)));

        mockMvc.perform(get("/api/v1/incidents").header(HttpHeaders.AUTHORIZATION, "Bearer " + token))
                .andExpect(status().isOk());
    }

    @Test
    void shouldRejectTokenSignedWithAnotherSecret() throws Exception {
        String token = token("attacker-secret-that-is-also-32-bytes!!", ISSUER, Instant.now().plus(Duration.ofMinutes(5)));

        mockMvc.perform(get("/api/v1/incidents").header(HttpHeaders.AUTHORIZATION, "Bearer " + token))
                .andExpect(status().isUnauthorized());
    }

    @Test
    void shouldRejectExpiredToken() throws Exception {
        String token = token(SECRET, ISSUER, Instant.now().minus(Duration.ofMinutes(5)));

        mockMvc.perform(get("/api/v1/incidents").header(HttpHeaders.AUTHORIZATION, "Bearer " + token))
                .andExpect(status().isUnauthorized());
    }

    @Test
    void shouldRejectTokenFromAnotherIssuer() throws Exception {
        String token = token(SECRET, "someone-else", Instant.now().plus(Duration.ofMinutes(5)));

        mockMvc.perform(get("/api/v1/incidents").header(HttpHeaders.AUTHORIZATION, "Bearer " + token))
                .andExpect(status().isUnauthorized());
    }

    @Test
    void shouldRejectTokenWithoutTenant() throws Exception {
        String token = token(SECRET, ISSUER, Instant.now().plus(Duration.ofMinutes(5)), null);

        mockMvc.perform(get("/api/v1/incidents").header(HttpHeaders.AUTHORIZATION, "Bearer " + token))
                .andExpect(status().isUnauthorized());
    }

    @Test
    void shouldNotExposeDevTokenEndpointOutsideDevProfile() throws Exception {
        mockMvc.perform(post("/api/v1/dev/token")
                        .contentType("application/json")
                        .content("{ \"subject\": \"alice\", \"tenantId\": \"acme\", \"roles\": [\"RESPONDER\"] }"))
                .andExpect(status().isNotFound());
    }

    @Test
    void shouldMapRolesClaimSoViewerCanReadButNotCreate() throws Exception {
        String viewer = token(SECRET, ISSUER, Instant.now().plus(Duration.ofMinutes(5)), "acme", List.of("VIEWER"));

        mockMvc.perform(get("/api/v1/incidents").header(HttpHeaders.AUTHORIZATION, "Bearer " + viewer))
                .andExpect(status().isOk());
        mockMvc.perform(post("/api/v1/incidents")
                        .header(HttpHeaders.AUTHORIZATION, "Bearer " + viewer)
                        .contentType("application/json")
                        .content("{ \"title\": \"t\", \"severity\": \"LOW\", \"affectedService\": \"s\" }"))
                .andExpect(status().isForbidden());
    }

    @Test
    void shouldForbidValidTokenWithoutRoles() throws Exception {
        String noRoles = token(SECRET, ISSUER, Instant.now().plus(Duration.ofMinutes(5)), "acme", List.of());

        mockMvc.perform(get("/api/v1/incidents").header(HttpHeaders.AUTHORIZATION, "Bearer " + noRoles))
                .andExpect(status().isForbidden());
    }

    private static String token(String secret, String issuer, Instant expiresAt) {
        return token(secret, issuer, expiresAt, "acme");
    }

    private static String token(String secret, String issuer, Instant expiresAt, String tenantId) {
        return token(secret, issuer, expiresAt, tenantId, List.of("RESPONDER"));
    }

    private static String token(String secret, String issuer, Instant expiresAt, String tenantId, List<String> roles) {
        var key = new SecretKeySpec(secret.getBytes(StandardCharsets.UTF_8), "HmacSHA256");
        var encoder = new NimbusJwtEncoder(new ImmutableSecret<>(key));
        JwtClaimsSet.Builder claims = JwtClaimsSet.builder()
                .issuer(issuer)
                .subject("alice")
                .claim("roles", roles)
                .issuedAt(expiresAt.minus(Duration.ofHours(1)))
                .expiresAt(expiresAt);
        if (tenantId != null) {
            claims.claim("tenant_id", tenantId);
        }
        return encoder.encode(JwtEncoderParameters.from(JwsHeader.with(MacAlgorithm.HS256).build(), claims.build()))
                .getTokenValue();
    }
}
