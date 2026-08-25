-- 轮播图持久化：在 Supabase SQL Editor 中执行一次

CREATE TABLE IF NOT EXISTS public.carousel_settings (
    id smallint PRIMARY KEY CHECK (id = 1),
    interval_seconds integer NOT NULL DEFAULT 5 CHECK (interval_seconds BETWEEN 2 AND 20),
    slides jsonb NOT NULL DEFAULT '[]'::jsonb,
    updated_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.carousel_settings ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "carousel settings are publicly readable" ON public.carousel_settings;
CREATE POLICY "carousel settings are publicly readable"
ON public.carousel_settings FOR SELECT TO anon, authenticated USING (true);

GRANT SELECT ON public.carousel_settings TO anon, authenticated;
GRANT ALL ON public.carousel_settings TO service_role;

INSERT INTO public.carousel_settings (id, interval_seconds, slides)
VALUES (1, 5, '[{"image_url":"","title":"欢迎使用数据罗盘","subtitle":"经营数据与运营决策工作台","link_url":""}]'::jsonb)
ON CONFLICT (id) DO NOTHING;

INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES ('carousel', 'carousel', true, 10485760, ARRAY['image/png', 'image/jpeg', 'image/webp'])
ON CONFLICT (id) DO UPDATE SET
    public = EXCLUDED.public,
    file_size_limit = EXCLUDED.file_size_limit,
    allowed_mime_types = EXCLUDED.allowed_mime_types;

SELECT id, name, public, file_size_limit FROM storage.buckets WHERE id = 'carousel';
