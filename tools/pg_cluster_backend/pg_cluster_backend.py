import asyncio
import os
import sys
from threading import Thread
import time
import threading
import configparser
import argparse
import random

import asyncpg

import logging
import collections

from tools.pg_cluster_backend.psc.pgstatcommon.pg_stat_common import (
    read_conf_param_value,
    exception_helper,
    prepare_dirs,
    get_resultset,
    get_scalar,
    SignalHandler,
)
from tools.pg_cluster_backend.psc.pgstatlogger.pg_stat_logger import PSCLogger

VERSION = 1.0


class SysConf:
    def __init__(self):
        self.current_dir = os.path.dirname(os.path.realpath(__file__))
        self.config = configparser.RawConfigParser()
        self.config.optionxform = lambda option: option
        self.config.read(
            os.path.join(
                self.current_dir,
                "conf",
                os.path.splitext(os.path.basename(__file__))[0] + ".conf",
            )
        )

        def get_key(section, parameter, default, boolean=False):
            try:
                return read_conf_param_value(self.config[section][parameter], boolean)
            except KeyError:
                return default

        self.dbs_dict = {}
        for db in self.config["databases"]:
            self.dbs_dict[db] = read_conf_param_value(self.config["databases"][db])

        # main parameters
        self.application_name = get_key(
            "main", "application_name", "custom_soft_reindex"
        )
        self.threads_num = int(get_key("main", "threads_num", "2"))
        self.conn_exception_sleep_interval = int(
            get_key("main", "conn_exception_sleep_interval", "1")
        )
        self.reconnect_attempt = int(get_key("main", "reconnect_attempt", "3"))

        # test parameters
        self.accounts = int(get_key("test", "accounts", "100"))

        # log parameters
        self.log_level = get_key("log", "log_level", "Info")
        self.log_sql = int(get_key("log", "log_sql", "1"))
        self.file_maxmbytes = int(get_key("log", "file_maxmbytes", "50"))
        self.file_backupcount = int(get_key("log", "file_backupcount", "5"))


class CLUSTERTESTGlobal:
    db_conns = {}
    is_terminate = False
    lock = threading.Lock()
    sys_conf = None
    logger = None
    args = None
    workers_db_pid = []
    operation_num = 0

    def __init__(self):
        try:
            parser = argparse.ArgumentParser()
            parser.add_argument(
                "--version",
                help="Show the version number and exit",
                action="store_true",
                default=False,
            )
            parser.add_argument(
                "--operations",
                help="Number of billing operations",
                type=int,
                default=1000,
            )

            try:
                self.args = parser.parse_args()
            except SystemExit as e:
                sys.exit(0)
            except:
                print(exception_helper())
                sys.exit(0)

            if not len(sys.argv) > 1:
                print("No arguments. Type -h for help.")
                sys.exit(0)

            if self.args.version:
                print("Version %s" % VERSION)
                sys.exit(0)

            self.sys_conf = SysConf()

            prepare_dirs(self.sys_conf.current_dir, ["log"])
            self.logger = PSCLogger(
                self.sys_conf.application_name,
                log_level=logging._nameToLevel[self.sys_conf.log_level.upper()],
                max_bytes=1024 * 1000 * self.sys_conf.file_maxmbytes,
                backup_count=self.sys_conf.file_backupcount,
                delay=3,
            )
            self.logger.start()

        except SystemExit as e:
            print("Exiting...")
            sys.exit(0)
        except:
            print("Can't initialize application. Exiting...")
            print(exception_helper())
            sys.exit(0)


def init_test_tbls_and_data(db_conn):
    """
    create user test_db_user with password 'test_db_user_pw';

    CREATE DATABASE test_db
        WITH
        OWNER = test_db_user
        ENCODING = 'UTF8'
        LC_COLLATE = 'en_US.UTF-8'
        LC_CTYPE = 'en_US.UTF-8'
        TABLESPACE = pg_default
        CONNECTION LIMIT = -1;

    su - postgres -c "psql -A -t -d test_db -f /etc/pgbouncer/pgbouncer_prepare.sql"
    """
    db_conn.execute(
        """
    DO $$
        begin
        DROP TABLE IF EXISTS public.accounts CASCADE;

        CREATE TABLE public.accounts
        (
            id serial,
            user_name character varying(128),
            balance money,
            CONSTRAINT accounts_pkey PRIMARY KEY (id)
        );
        ALTER TABLE public.accounts
            OWNER to test_db_user;

        INSERT INTO public.accounts(user_name, balance)
             SELECT 'user_' || T.v, 100 from(SELECT generate_series(1, %d) as v) T;
        end$$;
    """
        % CLUSTERTEST.sys_conf.accounts
    )


async def worker_func(thread_name):
    # https://www.2ndquadrant.com/en/blog/postgresql-anti-patterns-read-modify-write-cycles/
    CLUSTERTEST.logger.log("Started %s" % thread_name, "Info", do_print=True)
    reconnect_attempt = 0

    db_hosts = collections.deque([v for _, v in CLUSTERTEST.sys_conf.dbs_dict.items()])

    db_local = None

    while CLUSTERTEST.operation_num < CLUSTERTEST.args.operations:
        if CLUSTERTEST.is_terminate:
            break
        CLUSTERTEST.operation_num += 1

        if CLUSTERTEST.operation_num % 10 == 0:
            CLUSTERTEST.logger.log(
                "Progress %s"
                % str(
                    round(
                        float(CLUSTERTEST.operation_num)
                        * 100
                        / CLUSTERTEST.args.operations,
                        2,
                    )
                )
                + "%",
                "Info",
                do_print=True,
            )

        do_work = True

        def execute_task():
            with db_local.xact():
                result = get_resultset(
                    db_local,
                    """
                    SELECT id, balance
                    FROM public.accounts
                    ORDER BY random() LIMIT 2 FOR UPDATE
                """,
                )

                from_account = result[0]
                to_account = result[1]
                amount = round(random.uniform(0.01, 100), 2)

                time.sleep(
                    random.uniform(0.1, 0.2)
                )  # emulate billing calculation delay

                db_local.execute(
                    """
                    UPDATE public.accounts
                        SET balance = balance - %s::money
                    WHERE id = %d
                    """
                    % (str(amount), from_account[0])
                )

                time.sleep(
                    random.uniform(0.1, 0.2)
                )  # emulate billing calculation delay

                db_local.execute(
                    """
                    UPDATE public.accounts
                        SET balance = balance + %s::money + 1::money
                    WHERE id = %d
                    """
                    % (str(amount), to_account[0])
                )
            # success: next task
            return True

        while do_work:
            try:
                if (
                    db_local is None
                    and reconnect_attempt < CLUSTERTEST.sys_conf.reconnect_attempt
                ):
                    CLUSTERTEST.logger.log(
                        "Thread '%s': connecting... reconnect_attempt = %d"
                        % (thread_name, reconnect_attempt),
                        "Info",
                        do_print=True,
                    )
                    db_local = await asyncpg.connect(db_hosts[0])
                    db_local.execute(
                        "SET application_name = '%s'"
                        % (CLUSTERTEST.sys_conf.application_name)
                    )
                    current_pid = get_scalar(db_local, "SELECT pg_backend_pid()")
                    CLUSTERTEST.db_conns[current_pid] = db_local
                elif (
                    db_local is None
                    and reconnect_attempt >= CLUSTERTEST.sys_conf.reconnect_attempt
                ):
                    # change connection host
                    CLUSTERTEST.logger.log(
                        "Thread '%s': connecting to another host... " % thread_name,
                        "Info",
                        do_print=True,
                    )
                    invalid_host = db_hosts.popleft()
                    db_hosts.append(invalid_host)
                    reconnect_attempt = 0
                    db_local = await asyncpg.connect(db_hosts[0])
                    db_local.execute(
                        "SET application_name = '%s'"
                        % (CLUSTERTEST.sys_conf.application_name)
                    )
                    current_pid = get_scalar(db_local, "SELECT pg_backend_pid()")
                    CLUSTERTEST.db_conns[current_pid] = db_local

                if execute_task():
                    do_work = False
            except asyncpg.exceptions.DeadlockDetectedError as exc:
                CLUSTERTEST.logger.log(
                    msg=f"Exception in '{thread_name}': {str(exc)}. DeadlockError",
                    code="Error",
                    do_print=True,
                )
                # repeat task on deadlock
                db_local.execute("ROLLBACK")

            except asyncpg.exceptions.ReadOnlySQLTransactionError as exc:
                CLUSTERTEST.logger.log(
                    "Exception in '%s': %s. ReadOnlyTransactionError"
                    % (thread_name, str(exc)),
                    "Error",
                    do_print=True,
                )
                db_local = None
                # switch connection on switchover
                invalid_host = db_hosts.popleft()
                db_hosts.append(invalid_host)
                time.sleep(CLUSTERTEST.sys_conf.conn_exception_sleep_interval)
            except (
                asyncpg.exceptions.QueryCanceledError,
                asyncpg.exceptions.AdminShutdownError,
                asyncpg.exceptions.CrashShutdownError,
            ) as exc:
                if CLUSTERTEST.is_terminate:
                    return
                CLUSTERTEST.logger.log(
                    "Exception in '%s': %s. Reconnecting after %d sec..."
                    % (
                        thread_name,
                        str(exc),
                        CLUSTERTEST.sys_conf.conn_exception_sleep_interval,
                    ),
                    "Error",
                    do_print=True,
                )
                db_local = None
                time.sleep(CLUSTERTEST.sys_conf.conn_exception_sleep_interval)
            except (
                asyncpg.exceptions.ClientCannotConnectError,
                asyncpg.exceptions.ProtocolError,
                asyncpg.exceptions.ConnectionFailureError,
                ConnectionResetError,
            ) as exc:
                reconnect_attempt += 1
                CLUSTERTEST.logger.log(
                    "Exception in '%s': %s. Reconnecting after %d sec... reconnect_attempt = %d"
                    % (
                        thread_name,
                        str(exc),
                        CLUSTERTEST.sys_conf.conn_exception_sleep_interval,
                        reconnect_attempt,
                    ),
                    "Error",
                    do_print=True,
                )
                db_local = None
                time.sleep(CLUSTERTEST.sys_conf.conn_exception_sleep_interval)

    db_local.close()
    CLUSTERTEST.logger.log("Finished %s" % thread_name, "Info", do_print=True)


def validate_test(db_conn):
    result = get_resultset(
        db_conn,
        """
        select sum(balance)::numeric from public.accounts
    """,
    )
    if (
        result[0][0]
        == CLUSTERTEST.sys_conf.accounts * 100 + CLUSTERTEST.args.operations
    ):
        CLUSTERTEST.logger.log("-------------> Test successful!", "Info", do_print=True)
    else:
        result = get_resultset(
            db_conn,
            """
            SELECT
                sum(balance)::numeric -
                ((select count(1) from public.accounts) * 100 + %d)
            FROM public.accounts
        """
            % CLUSTERTEST.args.operations,
        )
        CLUSTERTEST.logger.log(
            "-------------> Test failed! Lost transactions: %d" % result[0][0],
            "Error",
            do_print=True,
        )


async def cluster_specific_execute(func):
    reconnect_attempt = 0
    thread_name = "Main"
    db_hosts = collections.deque([v for _, v in CLUSTERTEST.sys_conf.dbs_dict.items()])

    db_local = None
    do_work = True

    while do_work:
        try:
            if (
                db_local is None
                and reconnect_attempt < CLUSTERTEST.sys_conf.reconnect_attempt
            ):
                CLUSTERTEST.logger.log(
                    "Thread '%s': connecting... reconnect_attempt = %d"
                    % (thread_name, reconnect_attempt),
                    "Info",
                    do_print=True,
                )
                db_local = await asyncpg.connect(db_hosts[0])
                await db_local.execute(
                    "SET application_name = '%s'"
                    % (CLUSTERTEST.sys_conf.application_name)
                )
            elif (
                db_local is None
                and reconnect_attempt >= CLUSTERTEST.sys_conf.reconnect_attempt
            ):
                # change connection host
                CLUSTERTEST.logger.log(
                    "Thread '%s': connecting to another host... " % thread_name,
                    "Info",
                    do_print=True,
                )
                invalid_host = db_hosts.popleft()
                db_hosts.append(invalid_host)
                reconnect_attempt = 0
                db_local = await asyncpg.connect(db_hosts[0])
                await db_local.execute(
                    "SET application_name = '%s'"
                    % (CLUSTERTEST.sys_conf.application_name)
                )

            await func(db_local)
            do_work = False
        except (
            asyncpg.exceptions.QueryCanceledError,
            asyncpg.exceptions.AdminShutdownError,
            asyncpg.exceptions.ConnectionDoesNotExistError,
        ) as e:
            CLUSTERTEST.logger.log(
                "Exception in '%s': %s. Reconnecting after %d sec..."
                % (
                    thread_name,
                    str(e),
                    CLUSTERTEST.sys_conf.conn_exception_sleep_interval,
                ),
                "Error",
                do_print=True,
            )
            db_local = None
            await asyncio.sleep(CLUSTERTEST.sys_conf.conn_exception_sleep_interval)
        except asyncpg.exceptions.CannotConnectNowError as e:
            reconnect_attempt += 1
            CLUSTERTEST.logger.log(
                "Exception in '%s': %s. Reconnecting after %d sec... reconnect_attempt = %d"
                % (
                    thread_name,
                    str(e),
                    CLUSTERTEST.sys_conf.conn_exception_sleep_interval,
                    reconnect_attempt,
                ),
                "Error",
                do_print=True,
            )
            db_local = None
            await asyncio.sleep(CLUSTERTEST.sys_conf.conn_exception_sleep_interval)

    await db_local.close()
    CLUSTERTEST.logger.log("Finished %s" % thread_name, "Info", do_print=True)


if __name__ == "__main__":
    CLUSTERTEST = CLUSTERTESTGlobal()
    worker_threads = []

    asyncio.run(cluster_specific_execute(init_test_tbls_and_data))

    CLUSTERTEST.logger.log("Start threads initialization", "Info", do_print=True)
    for t_num in range(1, CLUSTERTEST.sys_conf.threads_num + 1):
        worker_threads.append(
            Thread(target=worker_func, args=["manager_%s" % str(t_num)])
        )
    for thread in worker_threads:
        thread.start()

    alive_count = 1
    live_iteration = 0
    CLUSTERTEST.logger.log(
        "Threads successfully initialized for db = %s"
        % str(next(iter(CLUSTERTEST.sys_conf.dbs_dict))),
        "Info",
        do_print=True,
    )
    while alive_count > 0:
        with SignalHandler() as handler:
            alive_count = len(
                [thread for thread in worker_threads if thread.is_alive()]
            )
            if alive_count == 0:
                break
            time.sleep(0.5)
            if live_iteration % (20 * 3) == 0:
                CLUSTERTEST.logger.log("Live %s threads" % alive_count, "Info")
            live_iteration += 1
            if handler.interrupted:
                CLUSTERTEST.is_terminate = True
                CLUSTERTEST.logger.log(
                    "Received termination signal!", "Info", do_print=True
                )
                for _, conn in CLUSTERTEST.db_conns.items():
                    try:
                        conn.interrupt()
                    except:
                        pass
                CLUSTERTEST.logger.log("Stopping...", "Info", do_print=True)
                PSCLogger.instance().stop()
                sys.exit(0)

    asyncio.run(cluster_specific_execute(validate_test))
    PSCLogger.instance().stop()
