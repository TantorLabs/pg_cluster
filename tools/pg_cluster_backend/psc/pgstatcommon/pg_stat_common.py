import re
import os
import sys
import json
import decimal
import datetime
import traceback
from psc import PSC_DEBUG
import signal


def limit_memory(maxsize):
    try:
        import resource
        soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        resource.setrlimit(resource.RLIMIT_AS, (maxsize, hard))
    except ImportError:
        print("Failed: import resource")


def read_conf_param_value(raw_value, boolean=False):
    #case 1:    param = 100 #comment
    #case 2:    param = "common args" #comment
    #case 3:    param = some text #comment
    #case 4:    param = some text #"comment"
    value_res = raw_value
    if value_res.find("#") > -1:
        value_res = value_res[0:value_res.find("#")-1]

    quotes = re.findall("""\"[^"]*\"""", value_res)

    if len(quotes) > 0:
        value_res = quotes[0]
        value_res = value_res.replace("\"", "")
    else:
        value_res = value_res.strip(' \t\n\r')

    if boolean:
        return True if value_res in ['1', 't', 'true', 'True', 'TRUE'] else False

    return value_res


def prepare_dirs(current_dir, dirs=['log', 'download']):
    for v in dirs:
        if not os.path.exists(os.path.join(current_dir, v)):
            os.makedirs(os.path.join(current_dir, v))


class AppFileLock:
    do_unlock = True
    app_name = None
    __instance = None

    @staticmethod
    def instance():
        if AppFileLock.__instance is None:
            AppFileLock("AppFileLock")
        return AppFileLock.__instance

    def __init__(self, directory, application_name):
        self.app_name = application_name
        self.directory = directory
        AppFileLock.__instance = self
        self.tornado_is_exists = False
        self.threads = None
        import atexit
        import signal
        try:
            from tornado.ioloop import IOLoop
            self.tornado_is_exists = True
        except ImportError:
            if PSC_DEBUG:
                print("Failed: import IOLoop")

        from psc.pgstatlogger.pg_stat_logger import PSCLogger

        # on kill do unlock
        @atexit.register
        def unlock():
            if AppFileLock.instance().do_unlock:
                try:
                    AppFileLock.instance().do_unlock = False
                    if PSC_DEBUG:
                        print("{} stopping...".format(AppFileLock.instance().app_name))
                    fname = os.path.join(directory, AppFileLock.instance().app_name + ".lock")
                    if os.path.isfile(fname):
                        os.remove(fname)
                except IOError:
                    print("can't unlock " + AppFileLock.instance().app_name + ".lock")
                finally:
                    if PSC_DEBUG:
                        print("Stoppping all threads...")
                    if AppFileLock.instance().threads is not None:
                        for thread in AppFileLock.instance().threads:
                            if thread.is_alive():
                                try:
                                    thread.stop()
                                except SystemExit:
                                    if PSC_DEBUG:
                                        print("except SystemExit")

                    PSCLogger.instance().log("PSCLogger stopping from AppFileLock", "Info")
                    if AppFileLock.instance().tornado_is_exists: IOLoop.instance().stop()
                    PSCLogger.instance().stop()
                    if PSC_DEBUG:
                        print("{} stopped!".format(AppFileLock.instance().app_name))
                    sys.exit(0)

        def handler(signum, frame):
            unlock()

        signal.signal(signal.SIGTERM, handler)
        if os.path.isfile(os.path.join(directory, application_name + ".lock")):
            sys.stderr.write("{} already started!".format(application_name))
            self.do_unlock = False
            if AppFileLock.instance().tornado_is_exists: IOLoop.instance().stop()
            PSCLogger.instance().stop()
            sys.exit(0)
        else:
            try:
                fd = os.open(os.path.join(directory, application_name + ".lock"), os.O_CREAT | os.O_EXCL)
                os.close(fd)
            except IOError:
                print("Can't open {}.lock".format(application_name))


class SignalHandler(object):
    tornado_is_exists = False

    def __init__(self):
        self.sigterm = signal.SIGTERM
        self.sigint = signal.SIGINT

    def __enter__(self):
        self.interrupted = False
        self.released = False
        self.handler_sigterm = signal.getsignal(self.sigterm)
        self.handler_sigint = signal.getsignal(self.sigint)

        def handler(signum, frame):
            self.release()
            self.interrupted = True

        signal.signal(self.sigterm, handler)
        signal.signal(self.sigint, handler)

        return self

    def __exit__(self, type, value, tb):
        self.release()

    def release(self):
        if self.released:
            return False

        signal.signal(self.sigterm, self.handler_sigterm)
        signal.signal(self.sigint, self.handler_sigint)
        self.released = True
        return True

    # This method should be used if AppFileLock is created
    def unlock(self):
        from psc.pgstatlogger.pg_stat_logger import PSCLogger
        try:
            from tornado.ioloop import IOLoop
            self.tornado_is_exists = True
        except ImportError:
            if PSC_DEBUG:
                print("Failed: import IOLoop")

        afli = AppFileLock.instance()
        cn = self.__class__.__name__
        try:
            if PSC_DEBUG:
                print("%s: %s stopping..." % (cn, afli.app_name))
            fname = os.path.join(afli.directory, afli.app_name + ".lock")
            if os.path.isfile(fname):
                os.remove(fname)
        except IOError:
            print("%s: can't unlock %s.lock" % (cn, afli.app_name))
        finally:
            if PSC_DEBUG:
                print("%s: Stoppping all threads..." % cn)
            if afli.threads is not None:
                for thread in afli.threads:
                    if thread.is_alive():
                        try:
                            thread.stop()
                        except SystemExit:
                            if PSC_DEBUG:
                                print("except SystemExit")

            PSCLogger.instance().log("%s: PSCLogger stopping..." % cn, "Info", do_print=True)
            if afli.tornado_is_exists: IOLoop.instance().stop()
            PSCLogger.instance().stop()
            if PSC_DEBUG:
                print("%s: %s stopped!" % (cn, afli.app_name))
            sys.exit(0)


def to_json(obj, formatted=False):
    def type_adapter(o):
        if isinstance(o, datetime.datetime):
            return o.__str__()
        if isinstance(o, decimal.Decimal):
            return float(o)
    if formatted:
        return json.dumps(obj, default=type_adapter, ensure_ascii=False, indent=4, sort_keys=True)
    else:
        return json.dumps(obj, default=type_adapter, ensure_ascii=False).encode('utf8')


def get_scalar(conn, query):
    p_query = conn.prepare(query)
    res = p_query()
    return None if len(res) == 0 else next(row[0] for row in res)


def get_resultset(conn, query):
    p_query = conn.prepare(query)
    return p_query()


def exception_helper(show_traceback=True):
    exc_type, exc_value, exc_traceback = sys.exc_info()
    return "\n".join(
        [
            v for v in traceback.format_exception(exc_type, exc_value, exc_traceback if show_traceback else None)
        ]
    )


def match(mask, text):
    # If we reach at the end of both strings, we are done
    if len(mask) == 0 and len(text) == 0:
        return True

    # Make sure that the characters after '*' are present
    # in text string. This function assumes that the mask
    # string will not contain two consecutive '*'
    if len(mask) > 1 and mask[0] == '*' and len(text) == 0:
        return False

    # If the mask string contains '?', or current characters
    # of both strings match
    if (len(mask) > 1 and mask[0] == '?') or (len(mask) != 0
        and len(text) != 0 and mask[0] == text[0]):
        return match(mask[1:],text[1:]);

    # If there is *, then there are two possibilities
    # a) We consider current character of text string
    # b) We ignore current character of text string.
    if len(mask) != 0 and mask[0] == '*':
        return match(mask[1:], text) or match(mask, text[1:])

    return False
