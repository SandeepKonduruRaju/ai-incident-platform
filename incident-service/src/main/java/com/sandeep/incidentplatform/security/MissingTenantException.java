package com.sandeep.incidentplatform.security;

public class MissingTenantException extends RuntimeException {

    public MissingTenantException() {
        super("The access token has no tenant_id claim");
    }
}
