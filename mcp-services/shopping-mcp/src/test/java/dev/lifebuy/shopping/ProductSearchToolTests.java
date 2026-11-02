package dev.lifebuy.shopping;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.math.BigDecimal;

import org.junit.jupiter.api.Test;

class ProductSearchToolTests {

    private final ProductSearchTool tool = new ProductSearchTool();

    @Test
    void filtersByKeywordPriceAndLimit() {
        var result = tool.searchProducts("笔", new BigDecimal("15.00"), 1);

        assertThat(result.products()).hasSize(1);
        assertThat(result.products().getFirst().unit_price())
            .isLessThanOrEqualTo(new BigDecimal("15.00"));
        assertThat(result.source_type()).isEqualTo("mock");
        assertThat(result.source_service()).isEqualTo("shopping-mcp");
    }

    @Test
    void noMatchIsAnEmptySuccessfulResult() {
        var result = tool.searchProducts("不存在的商品", null, null);

        assertThat(result.products()).isEmpty();
        assertThat(result.source_type()).isEqualTo("mock");
    }

    @Test
    void rejectsInvalidArguments() {
        assertThatThrownBy(() -> tool.searchProducts(" ", null, 1))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("keyword");
        assertThatThrownBy(() -> tool.searchProducts("笔", new BigDecimal("-0.01"), 1))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("max_price");
        assertThatThrownBy(() -> tool.searchProducts("笔", null, 11))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("limit");
    }
}