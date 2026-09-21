alter table public.mapping
    add column if not exists platform_shop_name text;

update public.mapping
set platform_shop_name = case shop_name
    when '抖音幸心轮廓女装旗舰店' then '轮廓女装旗舰店'
    when '抖音信刻吉丘古儿旗舰店' then '吉丘古儿旗舰店'
    when '抖音引美25.7转愉燃轮廓轻奢旗舰店' then '轮廓官方旗舰店'
    when '抖音江轮轮廓服饰专营店' then '吉丘古儿官方旗舰店'
    when '抖音轮廓平跃女装专卖店' then '轮廓平跃女装专卖店'
    when '抖音轮廓飞聚女装专卖店' then '轮廓飞聚女装专卖店'
    else platform_shop_name
end
where shop_name in (
    '抖音幸心轮廓女装旗舰店',
    '抖音信刻吉丘古儿旗舰店',
    '抖音引美25.7转愉燃轮廓轻奢旗舰店',
    '抖音江轮轮廓服饰专营店',
    '抖音轮廓平跃女装专卖店',
    '抖音轮廓飞聚女装专卖店'
);

update public.live_sessions
set shop_name = case
    when regexp_replace(upper(trim(anchor_name)), '直播间$', '') like '轮廓女装旗舰店%' then '抖音幸心轮廓女装旗舰店'
    when regexp_replace(upper(trim(anchor_name)), '直播间$', '') like '吉丘古儿旗舰店%' then '抖音信刻吉丘古儿旗舰店'
    when regexp_replace(upper(trim(anchor_name)), '直播间$', '') like '轮廓官方旗舰店%' then '抖音引美25.7转愉燃轮廓轻奢旗舰店'
    when regexp_replace(upper(trim(anchor_name)), '直播间$', '') like '吉丘古儿官方旗舰店%' then '抖音江轮轮廓服饰专营店'
    when regexp_replace(upper(trim(anchor_name)), '直播间$', '') like '轮廓平跃女装专卖店%' then '抖音轮廓平跃女装专卖店'
    when regexp_replace(upper(trim(anchor_name)), '直播间$', '') like '轮廓飞聚女装专卖店%' then '抖音轮廓飞聚女装专卖店'
    else shop_name
end
where shop_name = '待维护店铺';
