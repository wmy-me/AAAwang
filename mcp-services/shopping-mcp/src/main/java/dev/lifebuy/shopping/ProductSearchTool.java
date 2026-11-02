package dev.lifebuy.shopping;

import java.math.BigDecimal;
import java.util.List;
import java.util.Locale;

import org.springframework.ai.mcp.annotation.McpTool;
import org.springframework.ai.mcp.annotation.McpToolParam;
import org.springframework.stereotype.Component;

@Component
public class ProductSearchTool {

    private static final int DEFAULT_LIMIT = 5;
    private static final int MAX_LIMIT = 10;
    private static final int MAX_KEYWORD_LENGTH = 50;

    private static final List<Product> PRODUCTS = List.of(
            new Product("mock-pencil-set", "彩色铅笔套装", new BigDecimal("12.80"), "CNY", "12支/盒"),
            new Product("mock-notebook", "线圈笔记本", new BigDecimal("8.50"), "CNY", "A5/本"),
            new Product("mock-sticker-pack", "奖励贴纸包", new BigDecimal("6.90"), "CNY", "100枚/包"),
            new Product("mock-water-bottle", "儿童水杯", new BigDecimal("29.90"), "CNY", "500ml/个"));

    @McpTool(
            name = "search_products",
            description = "只读查询 shopping-mcp 内存中的模拟商品目录；结果不是任何真实平台的价格或库存。",
            generateOutputSchema = true)
    public SearchProductsResult searchProducts(
            @McpToolParam(description = "必填非空关键词，最长50个字符") String keyword,
            @McpToolParam(required = false, description = "可选非负单价上限，货币为CNY") BigDecimal max_price,
            @McpToolParam(required = false, description = "可选结果数量，默认5，范围1至10") Integer limit) {
        String normalizedKeyword = validateKeyword(keyword);
        if (max_price != null && max_price.signum() < 0) {
            throw new IllegalArgumentException("max_price must be non-negative");
        }
        int effectiveLimit = limit == null ? DEFAULT_LIMIT : limit;
        if (effectiveLimit < 1 || effectiveLimit > MAX_LIMIT) {
            throw new IllegalArgumentException("limit must be between 1 and 10");
        }

        List<Product> matches = PRODUCTS.stream()
                .filter(product -> product.name().toLowerCase(Locale.ROOT).contains(normalizedKeyword))
            .filter(product -> max_price == null || product.unit_price().compareTo(max_price) <= 0)
                .limit(effectiveLimit)
                .toList();
        return new SearchProductsResult(matches, "mock", "shopping-mcp");
    }

    private String validateKeyword(String keyword) {
        if (keyword == null || keyword.isBlank()) {
            throw new IllegalArgumentException("keyword must not be blank");
        }
        String normalized = keyword.strip().toLowerCase(Locale.ROOT);
        if (normalized.length() > MAX_KEYWORD_LENGTH) {
            throw new IllegalArgumentException("keyword must not exceed 50 characters");
        }
        return normalized;
    }

    public record SearchProductsResult(
            List<Product> products,
            String source_type,
            String source_service) {
    }

    public record Product(
            String product_id,
            String name,
            BigDecimal unit_price,
            String currency,
            String unit) {
    }
}