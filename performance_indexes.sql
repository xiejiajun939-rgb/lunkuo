-- 数据罗盘：第一阶段数据库性能优化
-- 安全性：只创建索引并更新统计信息，不修改、不删除业务数据。
-- 可重复执行：所有索引均使用 IF NOT EXISTS。

-- 1. 本月/日期区间查询
CREATE INDEX IF NOT EXISTS idx_product_sales_all_sale_date
ON public.product_sales_all (sale_date);

-- 2. 日期过滤后稳定分页
CREATE INDEX IF NOT EXISTS idx_product_sales_all_sale_date_id
ON public.product_sales_all (sale_date, id);

-- 3. 商品分析：日期 + 商品货号
CREATE INDEX IF NOT EXISTS idx_product_sales_all_sale_date_style
ON public.product_sales_all (sale_date, style_code);

-- 4. 店铺分析：日期 + 店铺
CREATE INDEX IF NOT EXISTS idx_product_sales_all_sale_date_shop
ON public.product_sales_all (sale_date, shop_name);

-- 5. 主播分析：仅在 anchor_name 字段存在时创建
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'product_sales_all'
          AND column_name = 'anchor_name'
    ) THEN
        EXECUTE '
            CREATE INDEX IF NOT EXISTS idx_product_sales_all_sale_date_anchor
            ON public.product_sales_all (sale_date, anchor_name)
        ';
    END IF;
END $$;

-- 6. 线下销售日期与店铺查询
CREATE INDEX IF NOT EXISTS idx_offline_sales_all_sale_date_id
ON public.offline_sales_all (sale_date, id);

CREATE INDEX IF NOT EXISTS idx_offline_sales_all_sale_date_shop
ON public.offline_sales_all (sale_date, shop_name);

-- 7. 映射表关联
CREATE INDEX IF NOT EXISTS idx_mapping_shop_anchor
ON public.mapping (shop_name, anchor_name);

-- 8. 更新 PostgreSQL 查询规划统计
ANALYZE public.product_sales_all;
ANALYZE public.offline_sales_all;
ANALYZE public.mapping;

-- 执行结果检查：应返回上面创建的索引
SELECT
    schemaname,
    tablename,
    indexname
FROM pg_indexes
WHERE schemaname = 'public'
  AND tablename IN ('product_sales_all', 'offline_sales_all', 'mapping')
  AND indexname LIKE 'idx_%'
ORDER BY tablename, indexname;
