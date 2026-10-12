package com.sandeep.incidentplatform;

import com.sandeep.incidentplatform.observability.RequestIdFilter;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import org.junit.jupiter.api.Test;
import org.slf4j.MDC;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

import java.util.UUID;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;

// Plain unit test of the filter: no Spring context, Spring's mock servlet request/response.
class RequestIdFilterTest {

    private final RequestIdFilter filter = new RequestIdFilter();

    @Test
    void shouldGenerateIdWhenHeaderIsMissing() throws Exception {
        MockHttpServletRequest request = new MockHttpServletRequest();
        MockHttpServletResponse response = new MockHttpServletResponse();
        AtomicReference<String> idSeenDuringRequest = new AtomicReference<>();

        filter.doFilter(request, response, (req, res) -> idSeenDuringRequest.set(MDC.get(RequestIdFilter.MDC_KEY)));

        String returned = response.getHeader(RequestIdFilter.HEADER);
        assertDoesNotThrow(() -> UUID.fromString(returned));
        assertEquals(returned, idSeenDuringRequest.get(), "log lines during the request carry the same id");
        assertNull(MDC.get(RequestIdFilter.MDC_KEY), "id is removed after the request");
    }

    @Test
    void shouldReuseSafeIncomingId() throws Exception {
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.addHeader(RequestIdFilter.HEADER, "gateway-abc_123.7");
        MockHttpServletResponse response = new MockHttpServletResponse();

        filter.doFilter(request, response, (req, res) -> { });

        assertEquals("gateway-abc_123.7", response.getHeader(RequestIdFilter.HEADER));
    }

    @Test
    void shouldReplaceUnsafeIncomingIdToPreventLogInjection() throws Exception {
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.addHeader(RequestIdFilter.HEADER, "abc\n2026-01-01 ERROR fake log line");
        MockHttpServletResponse response = new MockHttpServletResponse();

        filter.doFilter(request, response, (req, res) -> { });

        String returned = response.getHeader(RequestIdFilter.HEADER);
        assertNotEquals("abc\n2026-01-01 ERROR fake log line", returned);
        assertDoesNotThrow(() -> UUID.fromString(returned));
    }

    @Test
    void shouldReplaceTooLongIncomingId() throws Exception {
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.addHeader(RequestIdFilter.HEADER, "x".repeat(65));
        MockHttpServletResponse response = new MockHttpServletResponse();

        filter.doFilter(request, response, (req, res) -> { });

        assertDoesNotThrow(() -> UUID.fromString(response.getHeader(RequestIdFilter.HEADER)));
    }

    @Test
    void shouldClearIdEvenWhenRequestFails() {
        FilterChain failing = (req, res) -> {
            throw new ServletException("boom");
        };

        assertThrows(ServletException.class,
                () -> filter.doFilter(new MockHttpServletRequest(), new MockHttpServletResponse(), failing));
        assertNull(MDC.get(RequestIdFilter.MDC_KEY));
    }
}
