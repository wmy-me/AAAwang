package dev.lifebuy.shopping;

import static org.assertj.core.api.Assertions.assertThat;

import jakarta.servlet.FilterChain;

import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

class McpOriginFilterTests {

    private final McpOriginFilter filter = new McpOriginFilter();

    @Test
    void allowsBackendRequestsWithoutOrigin() throws Exception {
        var response = filterRequest(null);

        assertThat(response.getStatus()).isEqualTo(204);
    }

    @Test
    void allowsLocalBrowserOrigin() throws Exception {
        var response = filterRequest("http://127.0.0.1:5173");

        assertThat(response.getStatus()).isEqualTo(204);
    }

    @Test
    void rejectsNonLocalOrigin() throws Exception {
        var response = filterRequest("https://evil.example");

        assertThat(response.getStatus()).isEqualTo(403);
    }

    private MockHttpServletResponse filterRequest(String origin) throws Exception {
        var request = new MockHttpServletRequest("POST", "/mcp");
        if (origin != null) {
            request.addHeader("Origin", origin);
        }
        var response = new MockHttpServletResponse();
        FilterChain chain = (_request, chainResponse) ->
                ((MockHttpServletResponse) chainResponse).setStatus(204);
        filter.doFilter(request, response, chain);
        return response;
    }
}