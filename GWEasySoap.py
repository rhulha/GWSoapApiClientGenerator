import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "generated" / "groupwise-python-client"))

from groupwise.service.groupwise_client import GroupWiseClient
from groupwise.methods.LoginRequest import LoginRequest
from groupwise.methods.LogoutRequest import LogoutRequest
from groupwise.methods.GetFolderListRequest import GetFolderListRequest
from groupwise.methods.GetItemsRequest import GetItemsRequest
from groupwise.types.Authentication import Authentication
from groupwise.soap.request_context import RequestContext
from groupwise.soap.exceptions import SoapFaultException


class GWEasySoap:
    def __init__(self):
        self.client = None
        self.session = None

    def login(self, endpoint, username, password):
        self.client = GroupWiseClient(endpoint)
        login_req = LoginRequest(
            auth=Authentication(username=f"{username}:{password}"),
            application="GWEasySoap",
            language="en",
        )
        try:
            login_resp = self.client.login(login_req)
        except SoapFaultException as e:
            print(f"Login failed: {e.fault_string}", file=sys.stderr)
            sys.exit(1)

        self.login_resp = login_resp
        self.session = login_resp.session

    def whoami(self):
        if not self.client or not self.session:
            print("Not logged in", file=sys.stderr)
            return None
        return self.login_resp.userinfo


    def logout(self):
        if self.client and self.session:
            logout_req = LogoutRequest()
            ctx = RequestContext(session_id=self.session)
            try:
                self.client.logout(logout_req, ctx)
            except SoapFaultException as e:
                print(f"Logout failed: {e.fault_string}", file=sys.stderr)
            finally:
                self.session = None
                self.login_resp = None