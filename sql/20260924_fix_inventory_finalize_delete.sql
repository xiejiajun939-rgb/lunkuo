create or replace function public.finalize_inventory_batch(p_batch_id uuid)
returns void
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_date date;
begin
  select inventory_date into v_date
  from public.inventory_import_batches
  where id = p_batch_id and status = 'importing'
  for update;

  if v_date is null then
    raise exception 'Inventory batch is missing or is not importing';
  end if;

  delete from public.inventory_stock_current where id is not null;

  insert into public.inventory_stock_current (
    batch_id, inventory_date, style_code, sku,
    warehouse_code, warehouse_name,
    color_code, color_name, size_code, size_name, available_qty
  )
  select
    batch_id, inventory_date, style_code, sku,
    warehouse_code, warehouse_name,
    color_code, color_name, size_code, size_name, available_qty
  from public.inventory_stock_staging
  where batch_id = p_batch_id;

  delete from public.inventory_stock_staging where batch_id = p_batch_id;
  update public.inventory_import_batches
  set status = 'completed', completed_at = now()
  where id = p_batch_id;
end;
$$;

revoke execute on function public.finalize_inventory_batch(uuid) from public;
grant execute on function public.finalize_inventory_batch(uuid) to anon;
