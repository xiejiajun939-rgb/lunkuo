-- 商品自定义标签：一个商品可拥有多个标签。
alter table public.product_master
add column if not exists tags text[] not null default '{}';

-- 兼容迁移：原“首单礼金”商品自动获得同名标签。
update public.product_master
set tags = array_append(tags, '首单礼金')
where coalesce(has_newbie_coupon, false) = true
  and not ('首单礼金' = any(tags));

create index if not exists idx_product_master_tags
on public.product_master using gin (tags);

comment on column public.product_master.tags is
'自定义商品标签，例如：秋季新品、主推品、渠道专属款。一个商品可包含多个标签。';
