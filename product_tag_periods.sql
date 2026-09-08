-- 商品标签活动周期。商品与标签的关联仍保存在 product_master.tags。
create table if not exists public.product_tag_periods (
    tag_name text primary key,
    start_date date not null,
    end_date date not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint product_tag_periods_name_not_blank check (btrim(tag_name) <> ''),
    constraint product_tag_periods_valid_range check (end_date >= start_date)
);

alter table public.product_tag_periods enable row level security;

grant select, insert, update, delete on public.product_tag_periods to anon, authenticated;

drop policy if exists "product_tag_periods_read" on public.product_tag_periods;
create policy "product_tag_periods_read"
on public.product_tag_periods for select
to anon, authenticated
using (true);

drop policy if exists "product_tag_periods_insert" on public.product_tag_periods;
create policy "product_tag_periods_insert"
on public.product_tag_periods for insert
to anon, authenticated
with check (true);

drop policy if exists "product_tag_periods_update" on public.product_tag_periods;
create policy "product_tag_periods_update"
on public.product_tag_periods for update
to anon, authenticated
using (true)
with check (true);

drop policy if exists "product_tag_periods_delete" on public.product_tag_periods;
create policy "product_tag_periods_delete"
on public.product_tag_periods for delete
to anon, authenticated
using (true);
