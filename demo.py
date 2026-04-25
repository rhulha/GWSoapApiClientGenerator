"""
GroupWise SOAP API – demo script

Usage:
    python demo.py --host gw.example.com --user jdoe --password secret

The script:
  1. Logs in and prints the session token and server version.
  2. Lists all top-level mail folders.
  3. Reads the first 10 items from the mailbox root folder.
  4. Logs out.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "generated" / "groupwise-python-client"))

import config
from gwsoap.service.groupwise_client import GroupWiseClient
from gwsoap.methods.LoginRequest import LoginRequest
from gwsoap.methods.LogoutRequest import LogoutRequest
from gwsoap.methods.GetFolderListRequest import GetFolderListRequest
from gwsoap.methods.GetItemsRequest import GetItemsRequest
from gwsoap.types.PlainText import PlainText
from gwsoap.soap.request_context import RequestContext
from gwsoap.soap.exceptions import SoapFaultException


def main():
    endpoint = config.GW_SOAP_URL
    client = GroupWiseClient(endpoint)

    # ── 1. Login ────────────────────────────────────────────────────────────
    print(f"Connecting to {endpoint} as {config.GW_USER} …")
    login_req = LoginRequest(
        auth=PlainText(username=config.GW_USER, password=config.GW_PASSWORD),
        application="GWSoapDemo",
        language="en",
    )
    try:
        login_resp = client.login(login_req)
    except SoapFaultException as e:
        print(f"Login failed: {e.fault_string}", file=sys.stderr)
        sys.exit(1)

    session = login_resp.session
    print(f"  Session : {session}")
    print(f"  Version : {login_resp.gw_version}  build {login_resp.build}")
    if login_resp.userinfo:
        ui = login_resp.userinfo
        print(f"  User    : {getattr(ui, 'display_name', None) or getattr(ui, 'name', None) or config.GW_USER}")

    ctx = RequestContext(session_id=session)

    # ── 2. Folder list ───────────────────────────────────────────────────────
    print("\nTop-level folders:")
    folder_resp = client.get_folder_list(
        GetFolderListRequest(parent="folders", recurse=False),
        ctx,
    )
    folders = folder_resp.folders.folder if folder_resp.folders else []
    if folders:
        for f in folders:
            fid   = getattr(f, "id",   "?")
            fname = getattr(f, "name", "?") or getattr(f, "display_name", "?")
            ftype = type(f).__name__
            print(f"  [{ftype}]  {fname}  (id={fid})")
    else:
        print("  (no folders returned)")

    # ── 3. Mailbox items ─────────────────────────────────────────────────────
    print("\nFirst 10 items in mailbox:")
    items_resp = client.get_items(
        GetItemsRequest(container="mailbox", count=10),
        ctx,
    )
    items = items_resp.items.item if items_resp.items else []
    if items:
        for item in items:
            iid      = getattr(item, "id",      "?")
            subject  = getattr(item, "subject", "(no subject)")
            itype    = type(item).__name__
            print(f"  [{itype}] {subject!r}  id={iid}")
    else:
        print("  (no items returned)")

    # ── 4. Logout ────────────────────────────────────────────────────────────
    print("\nLogging out …")
    client.logout(LogoutRequest(), ctx)
    print("Done.")


if __name__ == "__main__":
    main()
