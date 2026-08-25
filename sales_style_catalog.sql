-- 商品信息管理：销售货号目录视图
-- 作用：在数据库中完成去重，页面无需下载全部销售明细。

CREATE OR REPLACE VIEW public.sales_style_catalog
WITH (security_invoker = true)
AS
SELECT DISTINCT
    UPPER(TRIM(COALESCE(NULLIF(style_code, ''), LEFT(product_code, 8)))) AS style_code
FROM public.product_sales_all
WHERE COALESCE(NULLIF(style_code, ''), LEFT(product_code, 8)) IS NOT NULL
  AND TRIM(COALESCE(NULLIF(style_code, ''), LEFT(product_code, 8))) <> '';

GRANT SELECT ON public.sales_style_catalog TO anon, authenticated, service_role;

SELECT COUNT(*) AS distinct_style_count
FROM public.sales_style_catalog;
