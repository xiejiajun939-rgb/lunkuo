-- 2026-10-21: user explicitly requested compatibility with existing public-key uploads.
-- Elevated exposure accepted temporarily. No business rows are inserted or deleted here.
begin;
alter table public.douyin_platform_product_daily enable row level security;
grant select,insert,update,delete on public.douyin_platform_product_daily to anon,authenticated;
drop policy if exists platform_legacy_read on public.douyin_platform_product_daily;
create policy platform_legacy_read on public.douyin_platform_product_daily for select to anon,authenticated using (true);
drop policy if exists platform_legacy_insert on public.douyin_platform_product_daily;
create policy platform_legacy_insert on public.douyin_platform_product_daily for insert to anon,authenticated with check (true);
drop policy if exists platform_legacy_update on public.douyin_platform_product_daily;
create policy platform_legacy_update on public.douyin_platform_product_daily for update to anon,authenticated using (true) with check (true);
-- Required by the SECURITY INVOKER atomic single-file replacement function.
drop policy if exists platform_legacy_delete on public.douyin_platform_product_daily;
create policy platform_legacy_delete on public.douyin_platform_product_daily for delete to anon,authenticated using (true);
grant execute on function public.replace_douyin_platform_file(jsonb) to anon,authenticated;
commit;
