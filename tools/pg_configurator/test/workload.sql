INSERT INTO s_items (order_items_1_id, cnt, amount, order_items_2_id)
	select
		floor(random() * 1500)::integer as order_items_1_id,
		floor(random() * 20000)::integer as cnt,
		floor(random() * 500)::integer as amount,
		generate_series(0,10) as order_items_2_id;

UPDATE s_items SET descr = 'updated at ' || now(), amount = amount + 1
WHERE order_items_1_id in (
    SELECT T.order_items_1_id from(
        SELECT floor(random() * 1500)::integer as order_items_1_id, generate_series(1,10)
    ) T
);

DELETE FROM s_items
WHERE order_items_1_id in (
    SELECT T.order_items_1_id from(
        SELECT floor(random() * 1500)::integer as order_items_1_id, generate_series(1,5)
	) T
);

\set v1 random(1300, 1350)
\set v2 random(1450, 1500)

select order_items_1_id, order_items_2_id, max(amount) as max_amount
from s_items t1
join order_items_1 oi1 on t1.order_items_1_id = oi1.id
join order_items_2 oi2 on t1.order_items_2_id = oi2.id
where cnt > :v1 and cnt < :v2
group by order_items_1_id, order_items_2_id;