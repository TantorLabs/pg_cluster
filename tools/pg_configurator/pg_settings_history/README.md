# How to export settings for specific PostgreSQL version

```
docker pull postgres:10
docker run --name pg_10 -v /tmp:/tmp -e POSTGRES_PASSWORD=mysecretpassword -d postgres:10
docker exec -it pg_10 bash

su - postgres
psql -c "COPY
    (
    SELECT
        name,
        setting AS value,
        (
            CASE
            WHEN unit = '8kB' THEN 
                pg_size_pretty(setting::bigint * 1024 * 8)
            WHEN unit = 'kB' AND setting <> '-1' THEN 
                pg_size_pretty(setting::bigint * 1024)
            ELSE ''
            END
        ) AS pretty_value,
        boot_val,
        unit
    FROM pg_settings
    ORDER BY name ASC
    )
    TO '/tmp/settings_pg10.csv' DELIMITER ',' CSV HEADER;"

exit
docker stop pg_10
docker rm -f pg_10
```