#!/usr/bin/python3
import csv
import os
import datetime
import copy
import argparse
import json
import psutil
import socket
from conf_perf import *
from conf_common import *
from common import *
from conf_profiles import *


PGC_VERSION = '22.10.17'


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


class OutputFormat(BasicEnum, Enum):
    JSON = 'json'
    PATRONI_JSON = 'patroni-json'
    CONF = 'conf'


class PGConfigurator:
    known_versions = {
        "9.6": "settings_pg_9_6.csv",
        "10": "settings_pg_10.csv",
        "11": "settings_pg_11.csv",
        "12": "settings_pg_12.csv",
        "13": "settings_pg_13.csv",
        "14": "settings_pg_14.csv",
        "15": "settings_pg_15.csv"
    }

    conf_profiles = {
        "profile_1c": "alg_set_1c",       # filename : dict name in file
        "ext_perf": "ext_alg_set"
    }

    current_dir = os.path.dirname(os.path.realpath(__file__))
    output_dir = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'output')
    args = {}
    ext_params = {}

    @exception_handler
    def __init__(self, args, ext_params):
        self.args = args
        self.ext_params = ext_params
        if not(args.output_file_name.find("""/""") != -1 or args.output_file_name.find("""\\""") != -1):
            args.output_file_name = os.path.join(self.output_dir, args.output_file_name)

        dir_exists = os.path.exists(self.output_dir)
        if not dir_exists:
            os.makedirs(self.output_dir)

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
    def iterate_alg_set(tune_alg) -> [str, dict]:
        for alg_set_v in sorted(
                [(ver, alg_set_v) for ver, alg_set_v in tune_alg.items()],
                key=lambda x: float(x[0])
        ):
            yield alg_set_v[0], alg_set_v[1]

    @staticmethod
    def prepare_alg_set(tune_alg, source_name):
        print("Called prepare_alg_set for '%s'" % source_name)
        prepared_tune_alg = copy.deepcopy(tune_alg)

        for ver, perf_alg_set in PGConfigurator.iterate_alg_set(tune_alg):
            # inheritance, redefinition, deprecation

            current_ver_deprecated_params = [
                alg["name"] for alg in perf_alg_set if "alg" in alg and alg["alg"] == "deprecated"
            ]

            prepared_tune_alg[ver] = [
                p for p in prepared_tune_alg[ver] if 'name' in p and p['name'] not in current_ver_deprecated_params
            ]

            prepared_tune_alg[ver] = [
                alg for alg in perf_alg_set \
                if not("alg" in alg and alg["alg"] == "deprecated") and "__parent" not in alg
            ]

            alg_set_current_version = prepared_tune_alg[ver]

            alg_set_from_parent = []
            if len([alg for alg in perf_alg_set if "__parent" in alg]) > 0:
                alg_set_from_parent = prepared_tune_alg[
                        [alg for alg in perf_alg_set if "__parent" in alg][0]["__parent"]
                ]

            prepared_tune_alg[ver].extend([
                    alg for alg in alg_set_from_parent
                    if "name" in alg and alg["name"] not in [
                        alg["name"] for alg in alg_set_current_version
                    ] and alg["name"] not in current_ver_deprecated_params
                ]
            )

        return prepared_tune_alg

    def make_conf(
                self,
                cpu_cores,
                ram_value,
                disk_type=DiskType.SAS,
                duty_db=DutyDB.MIXED,
                replication_enabled=True,
                pg_version="15",
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
                common_conf=False,
                conf_profiles=None
        ):
        # =======================================================================================================
        # checks
        if round(shared_buffers_part + client_mem_part + maintenance_mem_part, 1) != 1.0:
            raise NameError("Invalid memory parts size")
        if round(autovacuum_workers_mem_part + maintenance_conns_mem_part, 1) != 1.0:
            raise NameError("Invalid memory parts size for maintenance tasks")
        # =======================================================================================================
        # consts
        page_size = 8192
        max_cpu_cores = 96      # maximum of CPU cores in system, 4 CPU with 12 cores=>24 threads = 96
        min_cpu_cores = 4
        max_ram = '768Gi'
        max_ram_in_bytes = UnitConverter.size_from(max_ram, system=UnitConverter.sys_iec) * \
            ((100 - reserved_ram_percent) / 100) - \
            UnitConverter.size_from(reserved_system_ram, system=UnitConverter.sys_iec)
        # =======================================================================================================
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
        # =======================================================================================================
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
        # =======================================================================================================

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

        # Apply profiles to perf_alg_set
        if conf_profiles is not None and len(conf_profiles) > 0:
            for profile in conf_profiles.split(','):
                if profile not in self.conf_profiles:
                    raise NameError("Profile %s not found! See directory 'conf_profiles'" % profile)
                for k, v in perf_alg_set.items():
                    if k in globals()[self.conf_profiles[profile]]:
                        perf_alg_set[k].extend(
                            globals()[self.conf_profiles[profile]][k]
                        )

        d1 = {}
        # Merge params in versions to avoid duplicates
        for ver, params in perf_alg_set.items():
            d1[ver] = {
                d["name"]: {
                    k: v for k, v in d.items() if k != 'name'
                } for d in perf_alg_set[ver] if "name" in d
            }

        d2 = {}
        for ver, params in perf_alg_set.items():
            d2[ver] = {"__parent": d["__parent"] for d in perf_alg_set[ver] if "__parent" in d}

        perf_alg_set_res = {}
        for ver, param in d2.items():
            perf_alg_set_res[ver] = [
                {k: v for k, v in param.items() if isinstance(v, str)}
            ]

        for ver, param in d1.items():
            perf_alg_set_res[ver].extend([{**{"name": k}, **v} for k, v in param.items() if isinstance(v, dict)])

        prepared_alg_set = PGConfigurator.prepare_alg_set(perf_alg_set_res, 'conf_perf')[pg_version]

        if common_conf:
            prepared_alg_set.extend(
                PGConfigurator.prepare_alg_set(common_alg_set, 'conf_common')[pg_version]
            )

        if self.ext_params is not None and len(self.ext_params) > 0:    # ext_params initialized in unit tests
            prepared_alg_set.extend(self.ext_params)

        config_res = {}
        for param in prepared_alg_set:
            if "name" not in param:
                continue
            param_name = param["name"]
            value = param["alg"].rstrip().lstrip() if "alg" in param else param["const"]

            if ('debug_mode' in vars() or 'debug_mode' in globals()) and self.args.debug_mode:
                print("Processing: %s = %s" % (param_name, value))
            if "const" in param:
                config_res[param_name] = value

            if "alg" in param:
                try:
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
                except:
                    print("Exception on processing: %s\n%s" % (param, exception_helper()))
                    raise NameError("Invalid alg value")

        return dict(sorted(config_res.items()))

    def settings_history(self, list_versions) -> PGConfiguratorResult:
        res = PGConfiguratorResult
        configs = []
        for v in sorted([ver for ver in list_versions], key=lambda x: get_major_version(x)):
            with open(
                    os.path.join(self.current_dir, 'pg_settings_history', self.known_versions[v]),
                    'r',
                    encoding="utf-8"
            ) as f:
                reader = csv.reader(f)
                next(reader, None)  # skip header
                conf = {}
                for row in reader:
                    conf[row[0]] = {
                        "value": row[1],
                        "boot_val": row[3],
                        "unit": row[4]
                    }
                configs.append(conf)

        print_header("Deprecated parameters")
        for v in [k for k, _ in configs[0].items() if k not in configs[1]]:
            print("%s = %s" % (v, str(configs[0][v])))

        print_header("New parameters")
        for v in [k for k, _ in configs[1].items() if k not in configs[0]]:
            print("%s = %s" % (v, str(configs[1][v])))

        print_header("Changed boot_val")
        for k, v in configs[1].items():
            if k in configs[0] and v["boot_val"] != configs[0][k]["boot_val"]:
                print('%s = %s -> %s    # %s -> %s' % (
                    k,
                    configs[0][k]["boot_val"],
                    v["boot_val"],
                    str(configs[0][k]),
                    str(v)
                ))

        print_header("Changed unit")
        for k, v in configs[1].items():
            if k in configs[0] and v["unit"] != configs[0][k]["unit"]:
                print('%s = %s -> %s    # %s -> %s' % (
                    k,
                    configs[0][k]["unit"],
                    v["unit"],
                    str(configs[0][k]),
                    str(v)
                ))
        res.result_code = ResultCode.DONE
        res.result_data = {
            "Deprecated parameters": {
                v: configs[0][v] for v in [k for k, _ in configs[0].items() if k not in configs[1]]
            },
            "New parameters": {
                v: configs[1][v] for v in [k for k, _ in configs[1].items() if k not in configs[0]]
            },
            "Changed boot_val": {
                k: {
                    "old": configs[0][k]["boot_val"],
                    "new": v["boot_val"]
                } for k, v in configs[1].items()
                if k in configs[0] and v["boot_val"] != configs[0][k]["boot_val"]
            },
            "Changed unit": {
                k: {
                    "old": configs[0][k]["unit"],
                    "new": v["unit"]
                } for k, v in configs[1].items()
                if k in configs[0] and v["unit"] != configs[0][k]["unit"]
            }
        }
        return res

    def specific_setting_history(self, setting_name) -> PGConfiguratorResult:
        res = PGConfiguratorResult
        configs = []
        for v in sorted([ver for ver in self.known_versions], key=lambda x: get_major_version(x)):
            with open(
                    os.path.join(self.current_dir, 'pg_settings_history', self.known_versions[v]),
                    'r',
                    encoding="utf-8"
            ) as f:
                reader = csv.reader(f)
                next(reader, None)  # skip header
                conf = {}
                for row in reader:
                    if row[0] == setting_name:
                        conf[v] = {
                            "setting": row[0],
                            "value": row[1],
                            "boot_val": row[3],
                            "unit": row[4]
                        }
                        continue
                if len(conf) == 0:
                    conf[v] = {
                        "setting": "not exists",
                        "value": "",
                        "boot_val": "",
                        "unit": ""
                    }
                configs.append(conf)

        res.result_code = ResultCode.DONE
        res.result_data = configs
        print(str(json.dumps(configs, indent=4)))
        return res

    @staticmethod
    def get_arg_parser():
        parser = argparse.ArgumentParser()
        mca = get_default_args(PGConfigurator.make_conf)

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
            type=str,
            default=''
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
            default=UnitConverter.size_to(psutil.virtual_memory().total, system=UnitConverter.sys_iec)
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
            choices=list(["9.6", "10", "11", "12", "13", "14", "15"]),
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
        parser.add_argument(
            "--settings-history",
            help="Show differences in pg_settings for specific versions: for example --settings-history=9.6,15",
            type=str,
            default=""
        )
        parser.add_argument(
            "--conf-profiles",
            help="Select settings profile from \"conf_profiles\" directory. Multiple values also supported",
            type=str,
            default=""
        )
        parser.add_argument(
            "--specific-setting-history",
            help="Show specific specific: for example --specific-setting-history=max_parallel_maintenance_workers",
            type=str,
            default=""
        )

        return parser


def run_pgc(external_args=None, ext_params=None) -> PGConfiguratorResult:
    res = PGConfiguratorResult

    if external_args is not None:
        args = external_args
        pgc = PGConfigurator(external_args, ext_params)
    else:
        args = PGConfigurator.get_arg_parser().parse_args()
        pgc = PGConfigurator(args, ext_params)

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
        return True

    if args.settings_history != '':
        list_versions = args.settings_history.split(',')

        if len(list_versions) != 2:
            print("Wrong input value! Example: --settings-history=9.6,15")
        for v in list_versions:
            if v not in pgc.known_versions:
                print("Unknown version: %s" % v)
                sys.exit(0)
        return pgc.settings_history(list_versions)

    if args.specific_setting_history != '':
        return pgc.specific_setting_history(args.specific_setting_history)

    conf = pgc.make_conf(
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
        common_conf=args.common_conf,
        conf_profiles=args.conf_profiles
    )

    out_conf = ''
    if args.output_format == OutputFormat.CONF:
        header = """#   pgconfigurator version %s started on %s at %s
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

    if args.output_format == OutputFormat.PATRONI_JSON:
        for key, val in conf.items():
            conf[key] = val.strip("'")
        patroni_conf = {
            "postgresql": {
                "parameters": conf
            }
        }
        out_conf = json.dumps(patroni_conf, indent=4)

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

    res.result_data = conf
    res.result_code = ResultCode.DONE

    return res


if __name__ == "__main__":
    run_pgc()
