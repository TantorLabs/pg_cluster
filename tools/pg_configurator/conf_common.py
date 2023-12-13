common_alg_set = {
    "9.6": [
        # ----------------------------------------------------------------------------------
        # Extensions
        {
            "name": "shared_preload_libraries",
            "const": "'pg_stat_statements,auto_explain'"
        },
        {
            "name": "auto_explain.log_min_duration",
            "const": "'3s'"
        },
        {
            "name": "auto_explain.log_analyze",
            "const": "true"
        },
        {
            "name": "auto_explain.log_verbose",
            "const": "true"
        },
        {
            "name": "auto_explain.log_buffers",
            "const": "true"
        },
        {
            "name": "auto_explain.log_format",
            "const": "text"
        },
        {
            "name": "pg_stat_statements.max",
            "const": "1000"
        },
        {
            "name": "pg_stat_statements.track",
            "const": "all"
        },
        # ----------------------------------------------------------------------------------
        # Logging
        {
            "name": "logging_collector",
            "const": "on"
        },
        {
            "name": "log_destination",
            "const": "'csvlog'"
        },
        {
            "name": "log_directory",
            "const": "'pg_log'"
        },
        {
            "name": "log_filename",
            "const": "'postgresql-%Y-%m-%d_%H%M%S.log'"
        },
        {
            "name": "log_truncate_on_rotation",
            "const": "on"
        },
        {
            "name": "log_rotation_age",
            "const": "1d"
        },
        {
            "name": "log_rotation_size",
            "const": "100MB"
        },
        {
            "name": "log_min_messages",
            "const": "warning"
        },
        {
            "name": "log_min_error_statement",
            "const": "error"
        },
        {
            "name": "log_min_duration_statement",
            "const": "3000"
        },
        {
            "name": "log_duration",
            "const": "off"
        },
        {
            "name": "log_lock_waits",
            "const": "on"
        },
        {
            "name": "log_statement",
            "const": "'ddl'"
        },
        {
            "name": "log_temp_files",
            "const": "0"
        },
        {
            "name": "log_checkpoints",
            "const": "on"
        },
        {
            "name": "log_autovacuum_min_duration",
            "const": "1s"
        },
        # ----------------------------------------------------------------------------------
        # Statistic collection
        {
            "name": "track_activities",
            "const": "on"
        },
        {
            "name": "track_counts",
            "const": "on"
        },
        {
            "name": "track_io_timing",
            "const": "on"
        },
        {
            "name": "track_functions",
            "const": "pl"
        },
        {
            "name": "track_activity_query_size",
            "const": "2048"
        }
    ],
    "10": [
        {
            "__parent": "9.6"
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
