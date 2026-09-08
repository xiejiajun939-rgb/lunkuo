-- 商品档案增加上新时间；不会改动已有商品资料。
alter table public.product_master
add column if not exists launch_date date;

create index if not exists idx_product_master_launch_date
on public.product_master (launch_date);

comment on column public.product_master.launch_date is
'商品首次上新日期，可包含未来计划上新日期。';
