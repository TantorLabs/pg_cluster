ext_alg_set = {
    "9.6": [
        # ----------------------------------------------------------------------------------
        # Autovacuum
        {
            "name": "autovacuum_vacuum_scale_factor",
            "alg": "round(float(calc_system_scores_scale(0.001, 0.2)),4)",
            "to_unit": "as_is"
        },
        {
            "name": "autovacuum_analyze_scale_factor",
            "alg": "round(float(calc_system_scores_scale(0.0007, 0.1)),4)",
            "to_unit": "as_is"
        },
        {
            "name": "autovacuum_vacuum_cost_limit",
            "alg": "int(calc_system_scores_scale(2000, 8000))",
            "unit": "as_is"
        },
        {
            "name": "vacuum_cost_limit",
            "const": "8000"
        },
        {
            "name": "autovacuum_freeze_max_age",
            "const": "500000000"
        },
        {
            "name": "autovacuum_multixact_freeze_max_age",
            "const": "800000000"
        },
        # ----------------------------------------------------------------------------------
        # Write Ahead Log
        {
            "name": "wal_keep_segments",
            "alg": "int(calc_system_scores_scale(128, 1024)) if replication_enabled else 0"
        },
        # ----------------------------------------------------------------------------------
        # Background Writer
        {
            "name": "bgwriter_delay",
            "alg": "int(calc_system_scores_scale(50, 200))",  # delay between activity rounds
            "unit_postfix": "ms"
        },
        {
            "name": "bgwriter_lru_maxpages",
            "alg": "int(calc_system_scores_scale(500, 1000))",
            "to_unit": "as_is"  # 4-8MB per each round
        },
        {
            "name": "bgwriter_lru_multiplier",  # some cushion against spikes in demand
            "const": "7.0"
        },
        {
            "name": "random_page_cost",
            "alg": """\
                '4' if disk_type == DiskType.SATA else \
                '2.5' if disk_type == DiskType.SAS else \
                '1.1'\
            """,
            "to_unit": "as_is"
        },
        # ----------------------------------------------------------------------------------
        # Asynchronous Behavior
        {
            "name": "max_parallel_workers_per_gather",
            "alg": """\
                calc_cpu_scale(2, 4) if duty_db == DutyDB.FINANCIAL else \
                calc_cpu_scale(2, 8) if duty_db == DutyDB.MIXED else \
                calc_cpu_scale(2, 16)"""
        },
        {
            "name": "stats_temp_directory",
            "alg": "deprecated"
        }
    ],
    "10": [
        {
            "__parent": "9.6"
        },
        {
            "name": "max_parallel_workers",
            "alg": """\
                calc_cpu_scale(4, 12) if duty_db == DutyDB.FINANCIAL else \
                calc_cpu_scale(4, 24) if duty_db == DutyDB.MIXED else \
                calc_cpu_scale(4, 32)\
            """
        }
    ],
    "11": [
        {
            "__parent": "10"
        }
    ],
    "12": [
        {
            "__parent": "11"
        }
    ],
    "13": [
        {
            "__parent": "12"
        }
    ],
    "14": [
        {
            "__parent": "13"
        }
    ],
    "15": [
        {
            "__parent": "14"
        }
    ]
}
