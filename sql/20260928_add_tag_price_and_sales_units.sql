-- 商品吊牌价与销售件数口径。
-- 一条销售明细代表一件；金额为 0 的赠品不计入件数和件均价。

alter table public.product_master
    add column if not exists tag_price numeric;

comment on column public.product_master.tag_price is
    '商品吊牌价，来自每日全量库存表的选定单价；仅正数更新。';

drop function if exists public.get_product_sales_cube(date, date);

create function public.get_product_sales_cube(
    p_start_date date,
    p_end_date date
)
returns table (
    sale_date date,
    style_code text,
    brand text,
    dept text,
    org_name text,
    shop_name text,
    anchor text,
    anchor_display text,
    ship_amount numeric,
    return_amount numeric,
    net_amount numeric,
    ship_units bigint,
    return_units bigint,
    net_units bigint,
    order_count bigint
)
language sql
stable
security invoker
set search_path = public
as $$
with mapping_normalized as (
    select distinct on (
        upper(btrim(m.shop_name)),
        upper(btrim(coalesce(m.anchor_name, 'NONE')))
    )
        upper(btrim(m.shop_name)) as shop_key,
        upper(btrim(coalesce(m.anchor_name, 'NONE'))) as anchor_key,
        nullif(btrim(m.org_name), '') as org_name,
        nullif(btrim(m.dept), '') as dept
    from public.mapping m
    order by
        upper(btrim(m.shop_name)),
        upper(btrim(coalesce(m.anchor_name, 'NONE'))),
        m.id desc
),
shop_fallback as (
    select
        shop_key,
        case when count(distinct org_name) = 1 then min(org_name) end as org_name,
        case when count(distinct dept) = 1 then min(dept) end as dept
    from mapping_normalized
    group by shop_key
),
sales_normalized as (
    select
        ps.sale_date::date as sale_date,
        upper(btrim(coalesce(ps.style_code, left(ps.product_code, 8)))) as style_code,
        ps.brand,
        upper(btrim(ps.shop_name)) as shop_name,
        upper(btrim(coalesce(nullif(ps.anchor_name, ''), 'NONE'))) as anchor,
        coalesce(ps.ship_amount, 0)::numeric as ship_amount,
        coalesce(ps.return_amount, 0)::numeric as return_amount,
        coalesce(ps.net_amount, 0)::numeric as net_amount,
        ps.remark
    from public.product_sales_all ps
    where ps.sale_date >= p_start_date
      and ps.sale_date <= p_end_date
)
select
    s.sale_date,
    s.style_code,
    max(s.brand)::text as brand,
    coalesce(exact_map.dept, fallback.dept, '未分配部门')::text as dept,
    coalesce(exact_map.org_name, fallback.org_name, '未分配组织')::text as org_name,
    s.shop_name::text as shop_name,
    s.anchor::text as anchor,
    case
        when s.anchor in ('', 'NONE', 'NAN', '<NA>')
            then ('未识别主播｜' || s.shop_name)::text
        else s.anchor::text
    end as anchor_display,
    sum(s.ship_amount)::numeric as ship_amount,
    sum(s.return_amount)::numeric as return_amount,
    sum(s.net_amount)::numeric as net_amount,
    count(*) filter (where s.ship_amount > 0)::bigint as ship_units,
    count(*) filter (where s.return_amount > 0)::bigint as return_units,
    (
        count(*) filter (where s.ship_amount > 0)
        - count(*) filter (where s.return_amount > 0)
    )::bigint as net_units,
    count(distinct s.remark)::bigint as order_count
from sales_normalized s
left join mapping_normalized exact_map
    on exact_map.shop_key = s.shop_name
   and exact_map.anchor_key = s.anchor
left join shop_fallback fallback
    on fallback.shop_key = s.shop_name
group by
    s.sale_date,
    s.style_code,
    coalesce(exact_map.dept, fallback.dept, '未分配部门'),
    coalesce(exact_map.org_name, fallback.org_name, '未分配组织'),
    s.shop_name,
    s.anchor;
$$;

grant execute on function public.get_product_sales_cube(date, date) to anon, authenticated;

create or replace function public.update_product_tag_prices(p_items jsonb)
returns integer
language plpgsql
security invoker
set search_path = public
as $$
declare
    updated_count integer;
begin
    with prices as (
        select
            upper(btrim(item.style_code)) as style_code,
            item.tag_price
        from jsonb_to_recordset(coalesce(p_items, '[]'::jsonb))
            as item(style_code text, tag_price numeric)
        where item.tag_price > 0
    ), updated as (
        update public.product_master master
        set tag_price = prices.tag_price,
            updated_at = now()
        from prices
        where upper(btrim(master.style_code)) = prices.style_code
        returning master.id
    )
    select count(*) into updated_count from updated;
    return updated_count;
end;
$$;

grant execute on function public.update_product_tag_prices(jsonb) to anon, authenticated;
