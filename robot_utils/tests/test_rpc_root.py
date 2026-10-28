"""Plain unit tests for tools.rpc_root (no Odoo needed).

Run: python -m unittest discover -s robot_utils/tests -p 'test_*.py'
"""
import sys
import threading
import unittest
from xmlrpc.server import SimpleXMLRPCRequestHandler, SimpleXMLRPCServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "library"))

from tools import rpc_root, tools  # noqa: E402


class TestRpcRoot(unittest.TestCase):
    def test_strips_path_prefix(self):
        self.assertEqual(rpc_root("http://proxy:80/cicd"), "http://proxy:80")

    def test_strips_nested_path_and_trailing_slash(self):
        self.assertEqual(rpc_root("https://example.com/a/b/"), "https://example.com")

    def test_keeps_url_without_path(self):
        self.assertEqual(rpc_root("http://localhost:8069"), "http://localhost:8069")

    def test_keeps_value_without_scheme(self):
        self.assertEqual(rpc_root("proxy:80"), "proxy:80")


class RootOnlyHandler(SimpleXMLRPCRequestHandler):
    # Only the root endpoints exist, like on an Odoo with a /cicd web prefix.
    rpc_paths = ("/xmlrpc/2/common", "/xmlrpc/2/object")


class TestOdooBehindPrefix(unittest.TestCase):
    """_odoo() reaches /xmlrpc/2/* at the root even if given a prefixed URL."""

    def setUp(self):
        self.server = SimpleXMLRPCServer(
            ("127.0.0.1", 0),
            requestHandler=RootOnlyHandler,
            logRequests=False,
            allow_none=True,
        )
        self.server.register_function(lambda *args: 2, "authenticate")
        self.server.register_function(lambda *args: args[3:5], "execute_kw")
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = "http://127.0.0.1:%s" % self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def test_prefixed_url(self):
        odoo, uid = tools()._odoo(self.url + "/cicd", "db", "admin", "admin")
        self.assertEqual(uid, 2)
        self.assertEqual(
            odoo.execute_kw("db", uid, "admin", "res.users", "search"),
            ["res.users", "search"],
        )


if __name__ == "__main__":
    unittest.main()
