package com.sandeep.incidentplatform.security;

import com.nimbusds.jose.jwk.source.ImmutableSecret;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import org.springframework.context.annotation.Profile;
import org.springframework.security.oauth2.jose.jws.MacAlgorithm;
import org.springframework.security.oauth2.jwt.JwsHeader;
import org.springframework.security.oauth2.jwt.JwtClaimsSet;
import org.springframework.security.oauth2.jwt.JwtEncoder;
import org.springframework.security.oauth2.jwt.JwtEncoderParameters;
import org.springframework.security.oauth2.jwt.NimbusJwtEncoder;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.time.Instant;

/**
 * LOCAL DEVELOPMENT ONLY. Issues signed tokens so the API can be tried in Postman without an
 * identity provider. The bean only exists when the "dev" profile is active
 * (SPRING_PROFILES_ACTIVE=dev); in any other profile the endpoint returns 404.
 */
@Profile("dev")
@RestController
@RequestMapping("/api/v1/dev/token")
public class DevTokenController {

    private final JwtProperties properties;
    private final JwtEncoder encoder;

    public DevTokenController(JwtProperties properties) {
        this.properties = properties;
        this.encoder = new NimbusJwtEncoder(new ImmutableSecret<>(properties.secretKey()));
    }

    @PostMapping
    public TokenResponse issue(@Valid @RequestBody TokenRequest request) {
        Instant now = Instant.now();
        JwtClaimsSet claims = JwtClaimsSet.builder()
                .issuer(properties.issuer())
                .subject(request.subject())
                .claim(TenantResolver.TENANT_CLAIM, request.tenantId())
                .issuedAt(now)
                .expiresAt(now.plus(properties.tokenTtl()))
                .build();
        JwsHeader header = JwsHeader.with(MacAlgorithm.HS256).build();
        String token = encoder.encode(JwtEncoderParameters.from(header, claims)).getTokenValue();
        return new TokenResponse(token, "Bearer", properties.tokenTtl().toSeconds());
    }

    public record TokenRequest(@NotBlank String subject, @NotBlank String tenantId) {
    }

    public record TokenResponse(String accessToken, String tokenType, long expiresIn) {
    }
}
