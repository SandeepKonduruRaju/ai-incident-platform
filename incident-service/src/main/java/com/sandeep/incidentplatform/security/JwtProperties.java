package com.sandeep.incidentplatform.security;

import org.springframework.boot.context.properties.ConfigurationProperties;

import javax.crypto.SecretKey;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.time.Duration;

/**
 * JWT settings (app.security.jwt.*). The secret comes from the JWT_SECRET environment variable.
 * HS256 needs a key of at least 256 bits, so a shorter secret stops the app at startup.
 */
@ConfigurationProperties("app.security.jwt")
public record JwtProperties(String secret, String issuer, Duration tokenTtl) {

    private static final int MIN_SECRET_BYTES = 32;

    public JwtProperties {
        if (secret == null || secret.getBytes(StandardCharsets.UTF_8).length < MIN_SECRET_BYTES) {
            throw new IllegalStateException(
                    "app.security.jwt.secret (JWT_SECRET) must be at least " + MIN_SECRET_BYTES + " bytes");
        }
    }

    public SecretKey secretKey() {
        return new SecretKeySpec(secret.getBytes(StandardCharsets.UTF_8), "HmacSHA256");
    }
}
