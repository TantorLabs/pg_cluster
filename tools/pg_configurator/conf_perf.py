perf_alg_set = {
    # external pre-calculated vars for algs:
    #    total_ram_in_bytes
    #    total_cpu_cores
    #    maint_max_conns
    "9.6": [
        # ----------------------------------------------------------------------------------
        # Autovacuum
        {
            "name": "autovacuum",
            "const": "on"
        },
        {
            "name": "autovacuum_max_workers",
            "alg": "calc_cpu_scale(min_autovac_workers, max_autovac_workers)"
            # where:     min_autovac_workers if CPU_CORES <= 4
            #            max_autovac_workers if CPU_CORES = max_cpu_cores
        },
        {
            "name": "autovacuum_work_mem",
            "alg": "(total_ram_in_bytes * maintenance_mem_part * autovacuum_workers_mem_part) / autovacuum_max_workers"
        },
        {
            "name": "autovacuum_naptime",
            "const": "15s"
        },
        {
            "name": "autovacuum_vacuum_threshold",
            "alg": "int(calc_system_scores_scale(1000, 20000))",
            "to_unit": "as_is"
        },
        {
            "name": "autovacuum_analyze_threshold",
            "alg": "int(calc_system_scores_scale(500, 10000))",
            "to_unit": "as_is"
        },
        {
            "name": "autovacuum_vacuum_scale_factor",
            "const": "0.1",
        },
        {
            "name": "autovacuum_analyze_scale_factor",
            "const": "0.05"
        },
        {
            "name": "autovacuum_vacuum_cost_limit",
            "alg": "int(calc_system_scores_scale(4000, 8000))",
            "unit": "as_is"
        },
        {
            "name": "vacuum_cost_limit",
            "alg": "autovacuum_vacuum_cost_limit"
        },
        {
            "name": "autovacuum_vacuum_cost_delay",
            "const": "10ms"
        },
        {
            "name": "vacuum_cost_delay",
            "const": "10ms"
        },
        {
            "name": "autovacuum_freeze_max_age",
            "const": "1200000000"
        },
        {
            "name": "autovacuum_multixact_freeze_max_age",
            "const": "1400000000"
        },
        # ----------------------------------------------------------------------------------
        # Resource Consumption
        {
            "name": "shared_buffers",
            "alg": "total_ram_in_bytes * shared_buffers_part"
        },
        {
            "name": "max_connections",
            "alg": """\
                max(
                    calc_cpu_scale(min_conns, max_conns),
                    min_conns
                )"""
            # where:     min_conns if CPU_CORES <= 4
            #            max_conns if CPU_CORES = max_cpu_cores
        },
        {
            "name": "max_files_per_process",
            "alg": "calc_cpu_scale(1000, 10000)"
        },
        {
            "name": "superuser_reserved_connections",
            "const": "4"
        },
        {
            "name": "work_mem",
            "alg": "max(((total_ram_in_bytes * client_mem_part) / max_connections) * 0.9, 1024 * 10000)"
        },
        {
            "name": "temp_buffers",
            "alg": "max(((total_ram_in_bytes * client_mem_part) / max_connections) * 0.1, 1024 * 1000)"
            # where: temp_buffers per session, 10% of work_mem
        },
        {
            "name": "maintenance_work_mem",
            "alg": "(total_ram_in_bytes * maintenance_mem_part * maintenance_conns_mem_part) / maint_max_conns"
        },
        {
            "name": "old_snapshot_threshold",
            "alg": "4320",      # [minutes], 3 days
            "to_unit": "as_is"
        },
        # ----------------------------------------------------------------------------------
        # Write Ahead Log
        {
            "name": "wal_level",
            "alg": "'logical' if replication_enabled else 'minimal'",
            "to_unit": "as_is"
        },
        {
            "name": "wal_keep_segments",
            "alg": "int(calc_system_scores_scale(500, 10000)) if replication_enabled else 0"
        },
        {
            "name": "synchronous_commit",
            "alg": "PGConfigurator.calc_synchronous_commit(duty_db, replication_enabled)",
            "to_unit": "as_is"
            # NOTE: If no "synchronous_standby_names" are specified, then synchronous replication
            # is not enabled and transaction commits will not wait for replication
            # If synchronous_standby_names is empty, the settings on, remote_apply, remote_write and local all
            # provide the same synchronization level: transaction commits only wait for local flush to disk
        },
        {
            "name": "full_page_writes",
            "alg": "'on' if duty_db == DutyDB.FINANCIAL or replication_enabled else 'off'",
            "to_unit": "as_is"
        },
        {
            "name": "wal_compression",
            "alg": "'on' if replication_enabled else 'off'",
            "to_unit": "as_is"
        },
        {
            "name": "wal_buffers",  # http://rhaas.blogspot.ru/2012/03/tuning-sharedbuffers-and-walbuffers.html
            "alg": """\
                int(
                    calc_system_scores_scale(
                        UnitConverter.size_from('16MB', system=UnitConverter.sys_pg), 
                        UnitConverter.size_from('256MB', system=UnitConverter.sys_pg)
                    )
                )""",
            "to_unit": "MB"
        },
        {
            # if synchronous_commit = off
            "name": "wal_writer_delay",  # milliseconds
            "alg": """\
                100 if duty_db == DutyDB.FINANCIAL else \
                int(calc_system_scores_scale(200, 1000)) if duty_db == DutyDB.MIXED else \
                int(calc_system_scores_scale(200, 5000))""",
            "unit_postfix": "ms"
        },
        {
            "name": "wal_writer_flush_after",
            "alg": """\
                calc_system_scores_scale(
                    UnitConverter.size_from('1MB', system=UnitConverter.sys_pg),
                    UnitConverter.size_from('64MB', system=UnitConverter.sys_pg)
                )"""
        },
        {
            "name": "min_wal_size",
            "alg": """\
                calc_system_scores_scale(
                    UnitConverter.size_from('512MB', system=UnitConverter.sys_pg), 
                    UnitConverter.size_from('16GB', system=UnitConverter.sys_pg)
                )"""
        },
        {
            "name": "max_wal_size",
            # CHECKPOINT every checkpoint_timeout or when the WAL grows to about max_wal_size on disk
            "alg": """\
                calc_system_scores_scale(
                    UnitConverter.size_from('1GB', system=UnitConverter.sys_pg), 
                    UnitConverter.size_from(
                        '32GB' if duty_db == DutyDB.FINANCIAL else '64GB',
                        system=UnitConverter.sys_pg
                    )
                )"""
        },
        # ----------------------------------------------------------------------------------
        # Replication
        # Primary
        {
            "name": "max_replication_slots",
            "alg": "10 if replication_enabled else 0",
            "to_unit": "as_is"
        },
        {
            "name": "max_wal_senders",
            "alg": "10 if replication_enabled else 0",
            "to_unit": "as_is"
        },
        {
            "name": "wal_sender_timeout",
            "alg": "'180s' if replication_enabled else '0'",
            "to_unit": "as_is"
        },
        {
            "name": "wal_log_hints",
            "alg": "'on' if replication_enabled else 'off'",
            "to_unit": "as_is"
        },
        # Standby
        {
            "name": "hot_standby",
            "alg": "'on' if replication_enabled else 'off'",
            "to_unit": "as_is"
        },
        {
            "name": "wal_receiver_timeout",
            "alg": "'180s' if replication_enabled else '0'",
            "to_unit": "as_is"
        },
        {
            "name": "max_standby_streaming_delay",
            "alg": """\
                '90s' if duty_db == DutyDB.FINANCIAL and replication_enabled else \
                '1800s' if duty_db == DutyDB.MIXED else \
                '-1' \
            """,
            "to_unit": "as_is"
        },
        {
            "name": "wal_receiver_status_interval",
            "alg": "'10s' if replication_enabled else '0'",
            "to_unit": "as_is"
        },
        {
            "name": "hot_standby_feedback",
            "alg": "'on' if replication_enabled else 'off'",
            "to_unit": "as_is"
        },
        # ----------------------------------------------------------------------------------
        # Checkpointer
        {
            "name": "checkpoint_timeout",
            "alg": """\
                '5min' if duty_db == DutyDB.FINANCIAL else \
                '30min' if duty_db == DutyDB.MIXED else \
                '1h'""",
            "to_unit": "as_is"
        },
        {
            "name": "checkpoint_completion_target",
            "alg": """\
                '0.5' if duty_db == DutyDB.FINANCIAL else \
                '0.7' if duty_db == DutyDB.MIXED else \
                '0.9'""",  # DutyDB.STATISTIC
            "to_unit": "as_is"
        },
        {
            "name": "commit_delay",  # microseconds
            "alg": """\
                0 if duty_db == DutyDB.FINANCIAL else \
                int(calc_system_scores_scale(100, 1000)) if duty_db == DutyDB.MIXED else \
                int(calc_system_scores_scale(100, 5000))""",  # DutyDB.STATISTIC
            "to_unit": "as_is"
        },
        {
            "name": "commit_siblings",
            "alg": """\
                0 if duty_db == DutyDB.FINANCIAL else \
                int(calc_system_scores_scale(10, 100))""",
            "to_unit": "as_is"
        },
        # ----------------------------------------------------------------------------------
        # Background Writer
        {
            "name": "bgwriter_delay",
            "alg": "int(calc_system_scores_scale(200, 1000))",  # delay between activity rounds
            "unit_postfix": "ms"
        },
        {
            "name": "bgwriter_lru_maxpages",
            "const": "1000"  # 8MB per each round
        },
        {
            "name": "bgwriter_lru_multiplier",  # some cushion against spikes in demand
            "const": "7.0"
        },
        # ----------------------------------------------------------------------------------
        # Query Planning
        {
            "name": "effective_cache_size",
            "alg": """total_ram_in_bytes - shared_buffers - \
                UnitConverter.size_from(reserved_system_ram, system=UnitConverter.sys_iec)"""
        },
        {
            "name": "default_statistics_target",
            "const": "1000"
        },
        {
            "name": "random_page_cost",
            "alg": """\
                '6' if disk_type == DiskType.SATA else \
                '4' if disk_type == DiskType.SAS else \
                '1'""",  # SSD
            "to_unit": "as_is"
        },
        {
            "name": "seq_page_cost",
            "const": "1"  # default
        },
        # ----------------------------------------------------------------------------------
        # Asynchronous Behavior
        {
            "name": "effective_io_concurrency",
            "alg": """\
                '2' if disk_type == DiskType.SATA else \
                '4' if disk_type == DiskType.SAS else \
                '128'""",  # SSD
            "to_unit": "as_is"
        },
        {
            "name": "max_worker_processes",
            "alg": """calc_cpu_scale(4, 32)"""
        },
        {
            "name": "max_parallel_workers_per_gather",
            "alg": "calc_cpu_scale(2, 16)"
        },
        # ----------------------------------------------------------------------------------
        # Lock Management
        {
            "name": "max_locks_per_transaction",
            "alg": "calc_system_scores_scale(64, 4096)"
        },
        {
            "name": "max_pred_locks_per_transaction",
            "alg": "calc_system_scores_scale(64, 4096)"
        },
        {
            "name": "statement_timeout",
            "alg": "86400000",
            "to_unit": "as_is"
        },
        {
            "name": "idle_in_transaction_session_timeout",
            "alg": "86400000",
            "to_unit": "as_is"
        },
        # ----------------------------------------------------------------------------------
        # Statistics Collector
        {
            "name": "stats_temp_directory",
            "alg": "'/run/postgresql' if platform == Platform.LINUX else 'pg_stat_tmp'",
            "to_unit": "quote"
        }
    ],
    "10": [
        {
            "__parent": "9.6"
        },
        {
            "name": "max_parallel_workers",
            "alg": "calc_cpu_scale(4, 32)"
        },
        {
            "name": "bgwriter_lru_maxpages",
            "alg": """\
                int(
                    calc_system_scores_scale(
                        UnitConverter.size_from('8MB', system=UnitConverter.sys_pg) / page_size,
                        UnitConverter.size_from('256MB', system=UnitConverter.sys_pg) / page_size
                    )
                )""",
            "to_unit": "as_is"
        },
        {
            "name": "max_logical_replication_workers",
            "alg": """\
                calc_cpu_scale(4, 12) if duty_db == DutyDB.FINANCIAL else \
                calc_cpu_scale(4, 16) if duty_db == DutyDB.MIXED else \
                calc_cpu_scale(6, 24) \
            """
        },
        {
            "name": "max_sync_workers_per_subscription",
            "alg": """\
                calc_cpu_scale(2, 8) if duty_db == DutyDB.FINANCIAL else \
                calc_cpu_scale(2, 12) if duty_db == DutyDB.MIXED else \
                calc_cpu_scale(4, 16) \
            """
        }
    ],
    "11": [
        {
            "__parent": "10"  # inheritance
        },
        {
            "name": "max_parallel_maintenance_workers",
            "alg": "calc_cpu_scale(4, 16)"
        }
    ],
    "12": [
        {
            "__parent": "11"  # inheritance
        }
    ],
    "13": [
        {
            "__parent": "12"  # inheritance
        },
        {
            "name": "wal_keep_segments",
            "alg": "deprecated"
        },
        {
            "__parent": "12"  # inheritance
        },
        {
            "name": "autovacuum_vacuum_insert_threshold",
            "alg": "int(calc_system_scores_scale(1000, 20000))",
            "to_unit": "as_is"
        },
        {
            "name": "autovacuum_vacuum_insert_scale_factor",
            "alg": "round(float(calc_system_scores_scale(0.01, 0.2)), 2)",
            "to_unit": "as_is"
        },
        {
            "name": "logical_decoding_work_mem",
            "alg": """\
                int(
                    calc_system_scores_scale(
                        UnitConverter.size_from('64MB', system=UnitConverter.sys_pg),
                        UnitConverter.size_from('8096MB', system=UnitConverter.sys_pg)
                    )
                )\
            """,
            "to_unit": "MB"
        },
        {
            "name": "maintenance_io_concurrency",
            "alg": """\
                '2' if disk_type == DiskType.SATA else \
                '4' if disk_type == DiskType.SAS else \
                '128' \
            """,
            "to_unit": "as_is"
        },
        {
            "name": "wal_keep_size",
            "alg": """\
                int(
                    calc_system_scores_scale(
                        UnitConverter.size_from('1024MB', system=UnitConverter.sys_pg),
                        UnitConverter.size_from('16384MB', system=UnitConverter.sys_pg)
                    )
                ) \
            """,
            "to_unit": "MB"
        },
        {
            "name": "hash_mem_multiplier",
            "alg": """\
                '1.2' if duty_db == DutyDB.FINANCIAL else \
                '2.0' if duty_db == DutyDB.MIXED else \
                '8.0' \
            """,
            "to_unit": "as_is"
        }
    ],
    "14": [
        {
            "__parent": "13"  # inheritance
        },
        {
            "name": "client_connection_check_interval",
            "alg": """\
                '3s' if duty_db == DutyDB.FINANCIAL else \
                '10s' if duty_db == DutyDB.MIXED else \
                '30s'""",
            "to_unit": "as_is"
        },
        {
            "name": "default_toast_compression",
            "alg": """\
                'pglz' if duty_db in (DutyDB.FINANCIAL, DutyDB.MIXED) else 'lz4'""",
            "to_unit": "as_is"
        }
    ],
    "15": [
        {
            "__parent": "14"  # inheritance
        },
        {
            "name": "stats_temp_directory",
            "alg": "deprecated"
        }
    ]
}
