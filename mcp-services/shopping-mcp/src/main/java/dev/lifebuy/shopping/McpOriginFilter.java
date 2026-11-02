package dev.lifebuy.shopping;

import java.io.IOException;
import java.net.URI;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

@Component
public class McpOriginFilter extends OncePerRequestFilter {

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        return !request.getRequestURI().equals("/mcp");
    }

    @Override
    protected void doFilterInternal(
            HttpServletRequest request,
            HttpServletResponse response,
            FilterChain filterChain) throws ServletException, IOException {
        String origin = request.getHeader("Origin");
        if (origin != null && !isLocalOrigin(origin)) {
            response.sendError(HttpServletResponse.SC_FORBIDDEN);
            return;
        }
        filterChain.doFilter(request, response);
    }

    private boolean isLocalOrigin(String origin) {
        try {
            String host = URI.create(origin).getHost();
            return "127.0.0.1".equals(host) || "localhost".equalsIgnoreCase(host);
        }
        catch (IllegalArgumentException exception) {
            return false;
        }
    }
}