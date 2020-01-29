#!/usr/bin/python3
import os
import sys
import datetime
import re
import copy
from enum import Enum
import argparse
import inspect
import json
import psutil
import socket

PGC_VERSION = '1.1'

class UnitConverter:
    #            kilobytes         megabytes        gigabytes       terabytes
    # PG         kB                MB               GB              TB
    # ISO        K                 M                G               T

    #            kibibytes         mebibytes        gibibytes       tebibytes
    # IEC        Ki                Mi               Gi              Ti

    #            milliseconds    seconds     minutes     hours       days
    # PG         ms              s           min         h           d

    # https://en.wikipedia.org/wiki/Binary_prefix
    # Specific units of IEC 60027-2 A.2 and ISO/IEC 80000

    sys_std = [
        (1024 ** 4, 'T'),
        (1024 ** 3, 'G'),
        (1024 ** 2, 'M'),
        (1024 ** 1, 'K'),
        (1024 ** 0, 'B')
    ]

    sys_iec = [
        (1024 ** 4, 'Ti'),
        (1024 ** 3, 'Gi'),
        (1024 ** 2, 'Mi'),
        (1024 ** 1, 'Ki'),
        (1024 ** 0, '')
    ]

    sys_iso = [
        (1000 ** 4, 'T'),
        (1000 ** 3, 'G'),
        (1000 ** 2, 'M'),
        (1000 ** 1, 'K'),
        (1000 ** 0, 'B')
    ]

    sys_pg = [
        (1024 ** 4, 'TB'),
        (1024 ** 3, 'GB'),
        (1024 ** 2, 'MB'),
        (1024 ** 1, 'kB'),      #   <---------------- PG specific
        (1024 ** 0, '')
    ]

    @staticmethod
    def size_to(bytes, system=sys_iso, unit=None):
        for factor, postfix in system:
            if (unit is None and bytes/10 >= factor) or unit == postfix:
                break
        amount = int(bytes/factor)
        return str(amount) + postfix

    @staticmethod
    def size_from(sys_bytes, system=sys_iso):
        unit = ''.join(re.findall(r'[A-z]', sys_bytes))
        for factor, suffix in system:
            if suffix == unit:
                return int(int(''.join(re.findall(r'[0-9]', sys_bytes))) * factor)
        return int(sys_bytes)

    @staticmethod
    def size_cpu_to_ncores(cpu_val):
        val = ''.join(re.findall(r'[0-9][.][0-9]|[0-9]', str(cpu_val)))
        if ''.join(re.findall(r'[A-z]', str(cpu_val))) == 'm':
            return round(int(val)/1000, 1)
        else:
            return round(float(val), 1)


class BasicEnum():
    def __str__(self):
        return self.value


class DutyDB(BasicEnum, Enum):
    STATISTIC = 'statistic'           # Low reliability, fast speed, long recovery
                                          # Purely analytical and large aggregations
                                          # Transactions may be lost in case of a crash
    MIXED = 'mixed'                   # Medium reliability, medium speed, medium recovery
                                          # Mostly complicated real time SQL queries
    FINANCIAL = 'financial'           # High reliability, low speed, fast recovery
                                          # Billing tasks. Can't lose transactions in case of a crash


class DiskType(BasicEnum, Enum):
    # We assume that we have minimum 2 disk in hardware RAID1 (or 4 in RAID10) with BBU
    SATA = 'SATA'
    SAS = 'SAS'
    SSD = 'SSD'


class Platform(BasicEnum, Enum):
    WINDOWS = 'WINDOWS'
    LINUX = 'LINUX'


class PGConfigurator:
    @staticmethod
    def calc_synchronous_commit(duty_db, replication_enabled):
        if replication_enabled:
            if duty_db == DutyDB.STATISTIC:
                return "off"
            if duty_db == DutyDB.MIXED:
                return "local"
            if duty_db == DutyDB.FINANCIAL:
                return "remote_apply"
        else:
            if duty_db == DutyDB.STATISTIC:
                return "off"
            if duty_db == DutyDB.MIXED:
                return "off"
            if duty_db == DutyDB.FINANCIAL:
                return "on"

    @staticmethod
    def make_conf(cpu_cores,
                ram_value,
                disk_type=DiskType.SAS,
                duty_db=DutyDB.MIXED,
                replication_enabled=True,
                pg_version="10",
                reserved_ram_percent=10,           # for calc of total_ram_in_bytes
                reserved_system_ram='256Mi',       # for calc of total_ram_in_bytes
                shared_buffers_part=0.7,
                client_mem_part=0.2,               # for all available connections
                maintenance_mem_part=0.1,          # memory for maintenance connections + autovacuum workers
                autovacuum_workers_mem_part=0.5,   # from maintenance_mem_part
                maintenance_conns_mem_part=0.5,    # from maintenance_mem_part
                min_conns=50,
                max_conns=500,
                min_autovac_workers=4,             # autovacuum workers
                max_autovac_workers=20,
                min_maint_conns=4,                 # maintenance connections
                max_maint_conns=16,
                platform=Platform.LINUX,
                common_conf=False
        ):
        #=======================================================================================================
        # checks
        if round(shared_buffers_part + client_mem_part + maintenance_mem_part, 1) != 1.0:
            raise NameError("Invalid memory parts size")
        if round(autovacuum_workers_mem_part + maintenance_conns_mem_part, 1) != 1.0:
            raise NameError("Invalid memory parts size for maintenance tasks")
        #=======================================================================================================
        # consts
        page_size = 8192
        max_cpu_cores = 96      # maximum of CPU cores in system, 4 CPU with 12 cores=>24 threads = 96
        min_cpu_cores = 4
        max_ram = '768Gi'
        max_ram_in_bytes = UnitConverter.size_from(max_ram, system=UnitConverter.sys_iec) * \
            ((100 - reserved_ram_percent) / 100) - \
            UnitConverter.size_from(reserved_system_ram, system=UnitConverter.sys_iec)
        #=======================================================================================================
        # pre-calculated vars
        total_ram_in_bytes = UnitConverter.size_from(ram_value, system=UnitConverter.sys_iec) * \
            ((100 - reserved_ram_percent) / 100) - \
            UnitConverter.size_from(reserved_system_ram, system=UnitConverter.sys_iec)

        total_cpu_cores = UnitConverter.size_cpu_to_ncores(cpu_cores)

        maint_max_conns = max(
            ((((total_cpu_cores - min_cpu_cores) * 100) / (max_cpu_cores - min_cpu_cores)) / 100) * \
                (max_maint_conns - min_maint_conns) + min_maint_conns,
            min_maint_conns
        )
        #=======================================================================================================
        # system scores calculation in percents
        cpu_scores = (total_cpu_cores * 100) / max_cpu_cores
        ram_scores = (total_ram_in_bytes * 100) / max_ram_in_bytes
        disk_scores = 20 if disk_type == DiskType.SATA else \
                      40 if disk_type == DiskType.SAS else \
                      100     # SSD

        system_scores = \
                0.5 * cpu_scores * ram_scores * 0.866 + \
                0.5 * ram_scores * disk_scores * 0.866 + \
                0.5 * disk_scores * cpu_scores * 0.866
        # where triangle_surface = 0.5 * cpu_scores * ram_scores * sin(120)
        # sin(120) = 0.866

        system_scores_max = \
                0.5 * 100 * 100 * 0.866 + \
                0.5 * 100 * 100 * 0.866 + \
                0.5 * 100 * 100 * 0.866

        system_scores = (system_scores * 100) / system_scores_max   # 0-100
        # where 100 if system has max_cpu_cores, max_ram and SSD disk (4 disks in RAID10 for example)
        #=======================================================================================================

        def calc_cpu_scale(v_min, v_max):
            return max(
                (
                    (
                        ((total_cpu_cores - min_cpu_cores) * 100) / (max_cpu_cores - min_cpu_cores)
                    ) / 100
                ) * (v_max - v_min) + v_min,
                v_min
            )

        def calc_system_scores_scale(v_min, v_max):
            return max(
                (
                    system_scores / 100
                ) * (v_max - v_min) + v_min,
                v_min
            )

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
                    "alg": "int(calc_system_scores_scale(10000, 50000))",
                    "to_unit": "as_is"
                },
                {
                    "name": "autovacuum_analyze_threshold",
                    "alg": "int(calc_system_scores_scale(5000, 10000))",
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
                    "alg": "max(((total_ram_in_bytes * client_mem_part) / max_connections) * 0.9, 1024 * 1000)"
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
                    "name": "wal_buffers",            # http://rhaas.blogspot.ru/2012/03/tuning-sharedbuffers-and-walbuffers.html
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
                    "name": "wal_writer_delay",       # milliseconds
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
                    "alg": "'90s' if replication_enabled else '0'",
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
                        '0.9'""",       # DutyDB.STATISTIC
                    "to_unit": "as_is"
                },
                {
                    "name": "commit_delay",       # microseconds
                    "alg": """\
                        0 if duty_db == DutyDB.FINANCIAL else \
                        int(calc_system_scores_scale(100, 1000)) if duty_db == DutyDB.MIXED else \
                        int(calc_system_scores_scale(100, 5000))""",       # DutyDB.STATISTIC
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
                    "alg": "int(calc_system_scores_scale(200, 1000))",      # delay between activity rounds
                    "unit_postfix": "ms"
                },
                {
                    "name": "bgwriter_lru_maxpages",
                    "const": "1000"                                         # 8MB per each round
                },
                {
                    "name": "bgwriter_lru_multiplier",                      # some cushion against spikes in demand
                    "const": "7.0"
                },
                # ----------------------------------------------------------------------------------
                # Query Planning
                {
                    "name": "effective_cache_size",
                    "alg": "total_ram_in_bytes - shared_buffers"
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
                        '1'""",         # SSD
                    "to_unit": "as_is"
                },
                {
                    "name": "seq_page_cost",
                    "const": "1"        # default
                },
                # ----------------------------------------------------------------------------------
                # Asynchronous Behavior
                {
                    "name": "effective_io_concurrency",
                    "alg": """\
                        '2' if disk_type == DiskType.SATA else \
                        '4' if disk_type == DiskType.SAS else \
                        '128'""",       # SSD
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
                    "name": "bgwriter_delay",
                    "alg": "int(calc_system_scores_scale(200, 3000))",
                    "unit_postfix": "ms"
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
                }
            ],
            "11": [
                {
                    "__parent": "10"                        # inheritance
                },
                {
                    "name": "max_parallel_maintenance_workers",
                    "alg": "calc_cpu_scale(4, 16)"
                }
            ],
            "12": [
                {
                    "__parent": "11"                                                # inheritance
                }
            ]
        }

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
            ]
        }

        def iterate_alg_set(tune_alg) -> [str, dict]:
            for alg_set_v in sorted(
                    [(ver, alg_set_v) for ver, alg_set_v in tune_alg.items()],
                    key=lambda x: float(x[0])
            ):
                yield alg_set_v[0], alg_set_v[1]

        def prepare_alg_set(tune_alg):
            prepared_tune_alg = copy.deepcopy(tune_alg)

            for ver, perf_alg_set in iterate_alg_set(tune_alg):
                # inheritance, redefinition, deprecation
                if len([alg for alg in perf_alg_set if "__parent" in alg]) > 0:
                    current_ver_deprecated_params = [
                        alg["name"] for alg in perf_alg_set if "alg" in alg and alg["alg"] == "deprecated"
                    ]
                    prepared_tune_alg[ver] = [
                        alg for alg in perf_alg_set \
                            if not("alg" in alg and alg["alg"] == "deprecated") and "__parent" not in alg
                    ]

                    alg_set_current_version = prepared_tune_alg[ver]
                    alg_set_from_parent = prepared_tune_alg[
                            [alg for alg in perf_alg_set if "__parent" in alg][0]["__parent"]
                    ]

                    prepared_tune_alg[ver].extend([
                            alg for alg in alg_set_from_parent
                            if alg["name"] not in [
                                alg["name"] for alg in alg_set_current_version
                            ] and alg["name"] not in current_ver_deprecated_params
                        ]
                    )

            return prepared_tune_alg

        config_res = {}

        if common_conf:
            prepared_alg_set = prepare_alg_set(perf_alg_set)[pg_version]
            prepared_alg_set.extend(
                prepare_alg_set(common_alg_set)[pg_version]
            )
        else:
            prepared_alg_set = prepare_alg_set(perf_alg_set)[pg_version]

        for param in prepared_alg_set:
            param_name = param["name"]
            value = param["alg"] if "alg" in param else param["const"]

            if ('debug_mode' in vars() or 'debug_mode' in globals()) and debug_mode:
                print("Processing: %s = %s" % (param_name, value))
            if "const" in param:
                config_res[param_name] = value

            if "alg" in param:
                if "unit_postfix" in param:
                    config_res[param_name] = str(eval(param["alg"])) + param["unit_postfix"]
                else:
                    if "to_unit" in param and param["to_unit"] == 'as_is':
                        config_res[param_name] = str(eval(param["alg"]))
                    elif "to_unit" in param and param["to_unit"] == 'quote':
                        config_res[param_name] = "'%s'" % str(eval(param["alg"]))
                    else:
                        config_res[param_name] = str(
                            UnitConverter.size_to(
                                eval(param["alg"]),
                                system=UnitConverter.sys_pg,
                                unit=param["to_unit"] if "to_unit" in param is not None else None
                            )
                        )
                        exec(param_name + '=' + str(eval(param["alg"])))

        return config_res


class OutputFormat(BasicEnum, Enum):
    JSON = 'json'
    CONF = 'conf'


def get_default_args(func):
    signature = inspect.signature(func)
    return {
        k: v.default
        for k, v in signature.parameters.items()
            if v.default is not inspect.Parameter.empty
    }

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    mca = get_default_args(PGConfigurator.make_conf)		#make_conf_args

    parser.add_argument(
        "--version",
        help="Show the version number and exit",
        action='store_true',
        default=False
    )
    parser.add_argument(
        "--debug",
        help="Enable debug mode, (default: %(default)s)",
        action='store_true',
        default=False
    )
    parser.add_argument(
        "--output-format",
        help="Specify output format, (default: %(default)s)",
        type=OutputFormat,
        choices=list(OutputFormat),
        default=OutputFormat.CONF.value
    )
    parser.add_argument(
        "--output-file-name",
        help="Save to file",
        type=str
    )
    parser.add_argument(
        "--db-cpu",
        help="Available CPU cores, (default: %(default)s)",
        type=str,
        default=psutil.cpu_count()
    )
    parser.add_argument(
        "--db-ram",
        help="Available RAM memory, (default: %(default)s)",
        type=str,
        default=UnitConverter.size_to(psutil.virtual_memory().total,system=UnitConverter.sys_iec)
    )
    parser.add_argument(
        "--db-disk-type",
        help="Disks type, (default: %(default)s)",
        type=DiskType,
        choices=list(DiskType),
        default=mca["disk_type"].value
    )
    parser.add_argument(
        "--db-duty",
        help="Database duty, (default: %(default)s)",
        type=DutyDB,
        choices=list(DutyDB),
        default=mca["duty_db"].value
    )
    parser.add_argument(
        "--replication-enabled",
        help="Replication is enabled, (default: %(default)s)",
        type=bool,
        default=mca["replication_enabled"]
    )
    parser.add_argument(
        "--pg-version",
        help="PostgreSQL version, (default: %(default)s)",
        type=str,
        choices=list(["9.6", "10", "11"]),
        default=mca["pg_version"]
    )
    parser.add_argument(
        "--reserved-ram-percent",
        help="Reserved RAM memory part, (default: %(default)s)",
        type=float,
        default=mca["reserved_ram_percent"]
    )
    parser.add_argument(
        "--reserved-system-ram",
        help="Reserved system RAM memory, (default: %(default)s)",
        type=str,
        default=mca["reserved_system_ram"]
    )
    parser.add_argument(
        "--shared-buffers-part",
        help="Shared buffers part, (default: %(default)s)",
        type=float,
        default=mca["shared_buffers_part"]
    )
    parser.add_argument(
        "--client-mem-part",
        help="Memory part for all available connections, (default: %(default)s)",
        type=float,
        default=mca["client_mem_part"]
    )
    parser.add_argument(
        "--maintenance-mem-part",
        help="Memory part for maintenance connections, (default: %(default)s)",
        type=float,
        default=mca["maintenance_mem_part"]
    )
    parser.add_argument(
        "--autovacuum-workers-mem-part",
        help="Memory part of maintenance-mem, (default: %(default)s)",
        type=float,
        default=mca["autovacuum_workers_mem_part"]
    )
    parser.add_argument(
        "--maintenance-conns-mem-part",
        help="Memory part of maintenance-mem, (default: %(default)s)",
        type=float,
        default=mca["maintenance_conns_mem_part"]
    )
    parser.add_argument(
        "--min-conns",
        help="Min client connection, (default: %(default)s)",
        type=int,
        default=mca["min_conns"]
    )
    parser.add_argument(
        "--max-conns",
        help="Max client connection, (default: %(default)s)",
        type=int,
        default=mca["max_conns"]
    )
    parser.add_argument(
        "--min-autovac-workers",
        help="Min autovacuum workers, (default: %(default)s)",
        type=int,
        default=mca["min_autovac_workers"]
    )
    parser.add_argument(
        "--max-autovac-workers",
        help="Max autovacuum workers, (default: %(default)s)",
        type=int,
        default=mca["max_autovac_workers"]
    )
    parser.add_argument(
        "--min-maint-conns",
        help="Min maintenance connections, (default: %(default)s)",
        type=int,
        default=mca["min_maint_conns"]
    )
    parser.add_argument(
        "--max-maint-conns",
        help="Max maintenance connections, (default: %(default)s)",
        type=int,
        default=mca["max_maint_conns"]
    )
    parser.add_argument(
        "--common-conf",
        help="Add common part of postgresql.conf (like stats collector options, logging, etc...)",
        action='store_true',
        default=False
    )
    parser.add_argument(
        "--platform",
        help="Platform on which the DB is running, (default: %(default)s)",
        type=Platform,
        choices=list(Platform),
        default=mca["platform"].value
    )

    args = parser.parse_args()
    debug_mode = args.debug

    dt = datetime.datetime.now().isoformat(' ')
    if debug_mode:
        print('%s %s started' % (dt, os.path.basename(__file__)))

    if debug_mode:
        print("#--------------- Incoming parameters")
        for arg in vars(args):
            print("#   %s = %s" % (arg, getattr(args, arg)))
        print("#-----------------------------------")

    if args.version:
        print("Version %s" % (PGC_VERSION))
        sys.exit(0)

    conf = PGConfigurator.make_conf(
                    args.db_cpu,
                    args.db_ram,
                    disk_type=args.db_disk_type,
                    duty_db=args.db_duty,
                    replication_enabled=args.replication_enabled,
                    pg_version=args.pg_version,
                    reserved_ram_percent=args.reserved_ram_percent,
                    reserved_system_ram=args.reserved_system_ram,
                    shared_buffers_part=args.shared_buffers_part,
                    client_mem_part=args.client_mem_part,
                    maintenance_mem_part=args.maintenance_mem_part,
                    autovacuum_workers_mem_part=args.autovacuum_workers_mem_part,
                    maintenance_conns_mem_part=args.maintenance_conns_mem_part,
                    min_conns=args.min_conns,
                    max_conns=args.max_conns,
                    min_autovac_workers=args.min_autovac_workers,
                    max_autovac_workers=args.max_autovac_workers,
                    min_maint_conns=args.min_maint_conns,
                    max_maint_conns=args.max_maint_conns,
                    platform=args.platform,
                    common_conf=args.common_conf
            )

    out_conf = ''
    if args.output_format == OutputFormat.CONF:
        header = """#   pgconfigurator version %s runned on %s at %s
#   =============> Parameters\n""" % (
            PGC_VERSION, socket.gethostname(),
            datetime.datetime.today().strftime('%Y-%m-%d %H:%M:%S')
        )
        # if args.output_file_name is None: print(header)
        out_conf += header
        for arg in vars(args):
            # if args.output_file_name is None: print("#   %s = %s" % (arg, getattr(args, arg)))
            out_conf += '#   %s = %s\n' % (arg, getattr(args, arg))

        for key, val in conf.items():
            # if args.output_file_name is None: print('%s = %s\n' % (key, val))
            out_conf += '%s = %s\n' % (key, val)

    if args.output_format == OutputFormat.JSON:
        out_conf = json.dumps(conf, indent=4)

    if args.output_file_name is not None:
        if os.path.exists(args.output_file_name):
            os.rename(
                args.output_file_name,
                args.output_file_name + "_" + str(datetime.datetime.now().timestamp()).split('.')[0]
            )
        with open(args.output_file_name, "w") as output_file_name:
            output_file_name.write(out_conf)
        print("pgconfigurator finished!")
    else:
        print(out_conf)