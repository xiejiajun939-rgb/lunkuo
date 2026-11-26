-- Metadata-only read. SECURITY INVOKER preserves the caller's existing RLS.
create or replace function public.get_douyin_platform_uploaded_dates()
returns jsonb
language sql stable security invoker
set search_path = ''
as $$
  select coalesce(jsonb_agg(to_jsonb(d) order by d.report_date desc, d.shop_name, d.scope), '[]'::jsonb)
  from (
    select report_date, shop_name, scope, count(*) as row_count
    from public.douyin_platform_product_daily
    group by report_date, shop_name, scope
  ) d;
$$;
revoke all on function public.get_douyin_platform_uploaded_dates() from public;
grant execute on function public.get_douyin_platform_uploaded_dates() to anon, authenticated, service_role;
comment on function public.get_douyin_platform_uploaded_dates() is
  'Read uploaded-date metadata under existing caller RLS; no product payload or write access.';
