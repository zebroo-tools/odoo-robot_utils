import inspect
from datetime import date
import arrow
from pathlib import Path
import json
import shutil
import os
import time
import uuid
import xmlrpc.client
from urllib.parse import urlsplit
from robot.utils.dotdict import DotDict
from robot.libraries.BuiltIn import BuiltIn
import inspect
import os
import requests
from pathlib import Path
import logging

TIMEFORMAT = {
    "default": "%m/%d/%Y %H:%M:%S",
    "system": "%Y-%m-%d %H:%M:%S",
    "english": "%m/%d/%Y %H:%M:%S",
    "german": "%d.%m.%Y %H:%M:%S",
}

logger = logging.getLogger()
current_dir = Path(
    os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
)

def _make_robot_key(k):
    return f"${{{k}}}"

def get_variable(name):
    res = BuiltIn().get_variable_value(_make_robot_key(name))
    if not res:
        res = os.getenv(name)
    return res


def _exec_get_result(code, globals_dict):
    if not code:
        raise Exception("Code missing")

    dict2 = {k: v for (k, v) in globals_dict.items()}
    del globals_dict

    code = (code or "").strip()
    code = code.splitlines()
    if code and code[-1].startswith(" ") or code[-1].startswith("\t"):
        code.append("True")
    if " = " in code[-1]:
        code.append("return None")
    code[-1] = "return " + code[-1] if not code[-1].startswith("return ") else code[-1]
    code = "\n".join(["  " + x for x in code])
    keys = ",".join(list(dict2.keys()))
    wrapper = (
        f"def __wrap({keys}):\n" f"{code}\n\n" f"result_dict['result'] = __wrap({keys})"
    )
    result_dict = {}
    dict2["result_dict"] = result_dict
    exec(wrapper, dict2)
    return result_dict.get("result")


def load_default_environment():
    path = Path(".robot-vars")
    if not path.exists():
        return
    data = json.loads(path.read_text())
    for k, v in data.items():
        if k not in os.environ:
            os.environ[k] = v

    # TODO lost test filename


def interpret_equals(string):
    """
    minutes=1,seconds=2 --> {'minutes': 1, 'seconds': 2}

    """
    res = {}
    for line in string.splitlines():
        key, value = list(map(lambda x: x.strip(), line.split("=")))
        try:
            value = float(value)
        except ValueError:
            try:
                value = int(value)
            except:
                pass
        res[key] = value
    return res


class Encoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, DotDict):
            return dict(obj)
        return super().default(obj)


def rpc_root(server):
    """Return scheme://host[:port] of server, dropping any URL path.

    Odoo may serve its web routes under a path prefix (e.g. "/cicd"), but
    /xmlrpc/2/* stays at the server root - same reasoning as in
    odoo.get_conn. Values without a scheme are returned unchanged.
    """
    parts = urlsplit(server)
    if not parts.scheme or not parts.netloc:
        return server
    return f"{parts.scheme}://{parts.netloc}"


class tools(object):
    def _odoo(self, server, db, username, password):
        """
        I'm sitting here xmlrpc.client.
        :return: None
        """
        root = rpc_root(server)
        common = xmlrpc.client.ServerProxy(f"{root}/xmlrpc/2/common")
        uid = common.authenticate(db, username, password, {})
        odoo = xmlrpc.client.ServerProxy(f"{root}/xmlrpc/2/object")
        return odoo, uid

    def execute_sql(self, server, db, user, password, sql, context=None):
        odoo, uid = self._odoo(server, db, user, password)
        return odoo.execute_kw(db, uid, password, "robot.data.loader", "execute_sql", [sql])

    def get_res_id(self, server, db, user, password, model, module, name):
        odoo, uid = self._odoo(server, db, user, password)
        ir_model_obj = odoo.execute_kw(
            db,
            uid,
            password,
            "ir.model.data",
            "search_read",
            [[["model", "=", model], ["module", "=", module], ["name", "=", name]]],
            {
                "fields": [
                    "res_id",
                ]
            },
        )
        if not ir_model_obj:
            return False
        return ir_model_obj[0]["res_id"]

    def make_same_passwords(self, server, db, user, password):
        odoo, uid = self._odoo(server, db, user, password)
        sql = (
            "update res_users set password = "
            "(select password from res_users where id = 1)"
        )
        odoo.execute_kw(db, uid, password, "robot.data.loader", "execute_sql", [sql])

    def do_get_guid(self):
        return str(uuid.uuid4()).replace("-", "")

    def get_current_date(self):
        return date.today()

    def get_now(self, shiftparams={}):
        d = arrow.get()
        if shiftparams:
            if isinstance(shiftparams, str):
                shiftparams = interpret_equals(shiftparams)
            d = d.shift(**shiftparams)
        return d.datetime

    def get_now_formatted(self, format="default", shiftparams={}):
        res = self.get_now(shiftparams=shiftparams)
        formatted_res = res.strftime(self.time_format(format))
        return formatted_res

    def time_format(self, format):
        if format in TIMEFORMAT:
            return TIMEFORMAT[format]
        return format

    def copy_file(self, source, destination):
        shutil.copy(source, destination)

    def get_json_content(self, filepath):
        return json.loads(Path(filepath).absolute().read_text())

    def set_dict_key(self, data, key, value):
        data[key] = value

    def get_menu_res_id(self, server, db, user, password, module, name):
        return self.get_res_id(
            server, db, user, password, model="ir.ui.menu", module=module, name=name
        )

    def get_button_res_id(self, server, db, user, password, model, module, name):
        return self.get_res_id(
            server, db, user, password, model=model, module=module, name=name
        )

    def internal_set_wait_marker(self, server, db, user, password, name):
        odoo, uid = self._odoo(server, db, "admin", password)
        marker_name = f"robot-marker{name}"

        exists = odoo.execute_kw(
            db,
            uid,
            password,
            "ir.config_parameter",
            "search_count",
            [[["key", "=", marker_name]]],
        )
        if not exists:
            odoo.execute_kw(
                db,
                uid,
                password,
                "ir.config_parameter",
                "create",
                [
                    {
                        "key": marker_name,
                        "value": "1",
                    },
                ],
            )

    def internal_wait_for_marker(self, server, db, user, password, name, timeout=120):
        odoo, uid = self._odoo(server, db, user, password)
        deadline = arrow.get().shift(seconds=timeout)
        marker_name = f"robot-marker{name}"
        while arrow.get() < deadline:
            if odoo.execute_kw(
                db,
                uid,
                password,
                "ir.config_parameter",
                "search",
                [[["key", "=", marker_name]]],
            ):
                break
            time.sleep(1)
        else:
            raise Exception("Timeout")

    def odoo_convert_to_dictionary(self, value):
        value = value or {}
        return json.loads(json.dumps(value, cls=Encoder))

    def json_dumps(self, dict):
        return json.dumps(dict, cls=Encoder)

    def json_loads(self, str):
        return json.loads(str, cls=Encoder)

    def list_all_variables(self):
        context = BuiltIn().get_library_instance("BuiltIn")
        variables = context.get_variables()
        return variables

    def get_function_parameters(self, keyword):
        fkeyword = BuiltIn().run_keyword(keyword)
        signature = inspect.signature(fkeyword)
        return signature.parameters

    def My_Assert(self, expr, msg=""):
        if expr is False or expr is True:
            return expr
        if isinstance(expr, (int, float)):
            return bool(expr)

        if not isinstance(expr, str):
            raise Exception(
                f"Expression must be string at assert not: {type(expr)} {expr}"
            )

        res = bool(eval(expr))
        if not res:
            msg = f"Assertion failed: {expr}\n{msg}"
            raise Exception(msg)

    def libraryDirectory(self):
        return str(current_dir)

    def Base64_Encode_File_Content(self, filepath):
        import base64

        bytes = Path(filepath).read_bytes()
        return base64.b64encode(bytes).decode("utf8")

    def Get_Var_Type(self, var):
        return str(type(var))

    def Is_Empty_String(self, var):
        # logger.error(f"Checking is empty string: var: {var} type: {type(var)} and result is {not bool(var)}")
        return not bool(var)

    def Is_Not_Empty_String(self, var):
        return not self.Is_Empty_String(var)

    def Is_List(self, var):
        return isinstance(var, (tuple, list))

    def eval(self, expr, **vars):
        """
        Usage:
        ${item}=      Eval  m[0].state  m=${modules}
        Eval  m[0].state \\= 'asd'  m=${modules}
        """
        res = _exec_get_result(expr, vars)
        return res

    def prepend_parent_in_tools(self, path, parent, css_parent):
        # Check if path is a list
        is_list = isinstance(path, (tuple, list))
        parent = parent or ""

        new_path = []
        if is_list:
            for item in path:
                for subitem in item.split(","):
                    for pparent in parent.split(","):
                        subitem = " ".join(filter(bool, [css_parent, pparent, subitem]))
                        new_path.append(subitem)
            path = new_path
        else:
            for item in path.split(","):
                for pparent in parent.split(","):
                    item = " ".join(filter(bool, [css_parent, pparent, item]))
                    new_path.append(item)
            path = ",".join(new_path)

        return path

    def Get_File_Name(self, path):
        return Path(path).name

    def get_current_time_ms(self):
        return time.time() * 1000

    def get_elapsed_time_ms(self, start_time):
        return (time.time() * 1000) - start_time

    def wait_for_200(self, url, DELAY_SECONDS=2, tries=5, TIMEOUT_SECONDS=10):
        print(f"Checking {url} until status 200 is received...\n")
        tries = int(tries)
        delay = float(DELAY_SECONDS)
        timeout = float(TIMEOUT_SECONDS)
        for i in range(tries):
            try:
                response = requests.get(url, timeout=timeout)
                print(f"Status code: {response.status_code}")
                if response.status_code == 200:
                    print("✅ Success: Received status code 200.")
                    return True
            except requests.exceptions.RequestException as e:
                print(f"⚠️ Request failed: {e}")

            print(
                f"Try {i + 1}/{tries} failed, "
                f"waiting {delay} seconds before retrying...\n"
            )
            time.sleep(delay)
        raise Exception(f"Could not call {url} in time")