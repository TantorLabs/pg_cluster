DROP TABLE IF EXISTS public.order_items_1 CASCADE;
DROP TABLE IF EXISTS public.order_items_2 CASCADE;
DROP TABLE IF EXISTS public.s_items CASCADE;

CREATE TABLE public.order_items_1
(
    id serial,
    name character varying(32),
    CONSTRAINT order_items_1_pkey UNIQUE (id)
);

CREATE TABLE public.order_items_2
(
    id serial,
    name character varying(32),
    CONSTRAINT order_items_2_pkey UNIQUE (id)
);

CREATE TABLE public.s_items (
    id serial,
    order_items_1_id integer NOT NULL,
    order_items_2_id integer NOT NULL,
    amount numeric(16,4) DEFAULT 0 NOT NULL,
    cnt smallint DEFAULT 0 NOT NULL,
    descr text,
	CONSTRAINT stock_items_pk UNIQUE (id)
);

-- prepare data
INSERT INTO order_items_1 (id) SELECT generate_series(0,1500) as order_items_1_id;

INSERT INTO order_items_2 (id) SELECT generate_series(0,1500) as order_items_2_id;

INSERT INTO s_items (order_items_1_id, cnt, amount, order_items_2_id)
	select
		floor(random() * 1500)::integer as order_items_1_id,
		floor(random() * 20000)::integer as cnt,
		floor(random() * 500)::integer as amount,
		generate_series(0,1500) as order_items_2_id;

CREATE INDEX ON public.s_items USING hash (descr);

CREATE INDEX stock_items_idx01 ON public.s_items USING btree (order_items_2_id);
CREATE INDEX stock_items_idx02 ON public.s_items USING btree (order_items_1_id);

ALTER TABLE ONLY public.s_items
    ADD CONSTRAINT stock_items_fk01 FOREIGN KEY (order_items_1_id) REFERENCES public.order_items_1(id);
ALTER TABLE ONLY public.s_items
    ADD CONSTRAINT stock_items_fk02 FOREIGN KEY (order_items_2_id) REFERENCES public.order_items_2(id);